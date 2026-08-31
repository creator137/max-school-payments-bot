from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.formatting import money, month_name
from app.max_api import MaxClient
from app.models import Child, Parent, Payment, Receipt, UserState
from app.services.payments import (
    DomainError,
    add_receipt,
    billing_month,
    confirm_payment,
    debtors,
    get_or_create_payment,
    link_parent,
    parent_by_max_id,
    payment_report,
    pop_state,
    reject_payment,
    set_state,
)
from app.storage import LocalReceiptStorage

REJECTION_REASONS = {
    "wrong_amount": "неправильная сумма",
    "wrong_month": "не тот месяц",
    "unreadable": "чек не читается",
    "other_payment": "другой платёж",
}


class BotHandler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        client: MaxClient,
        storage: LocalReceiptStorage,
        settings: Settings,
    ):
        self.sessions, self.client, self.storage, self.settings = (
            sessions,
            client,
            storage,
            settings,
        )

    async def handle(self, update: dict[str, Any]) -> None:
        update_type = update.get("update_type")
        if update_type == "message_callback":
            await self._callback(update)
        elif update_type in {"message_created", "bot_started"}:
            await self._message(update)

    @staticmethod
    def _user_id(update: dict[str, Any]) -> int | None:
        message = update.get("message") or {}
        if update.get("update_type") == "message_callback":
            user = update.get("callback", {}).get("user") or update.get("user") or {}
        else:
            user = message.get("sender") or update.get("user") or {}
        return user.get("user_id")

    async def _message(self, update: dict[str, Any]) -> None:
        user_id = self._user_id(update)
        if not user_id:
            return
        message = update.get("message") or {}
        body = message.get("body") or {}
        text = (body.get("text") or "").strip()
        attachments = body.get("attachments") or []
        async with self.sessions() as session:
            parent = await parent_by_max_id(session, user_id)
            state = await session.get(UserState, user_id)
            if state and state.state == "awaiting_link_code" and text:
                try:
                    parent = await link_parent(session, text, user_id)
                    child = parent.children[0]
                    await pop_state(session, user_id)
                    await self.client.send_message(
                        user_id,
                        f"Ваш аккаунт привязан.\nРебёнок: {child.full_name}.\n"
                        "Теперь все напоминания об оплате будут приходить сюда.",
                        [[("💰 Оплата за месяц", "payment:current")]],
                    )
                except DomainError as error:
                    await self.client.send_message(
                        user_id, f"⚠️ {error}\nПроверьте код и отправьте ещё раз."
                    )
                return
            if state and state.state == "awaiting_receipt" and attachments:
                await self._receive_receipt(session, user_id, parent, state, attachments)
                return
            if (
                state
                and state.state.startswith("rejection_comment:")
                and text
                and user_id in self.settings.max_admin_ids
            ):
                payment_id = int(state.state.rsplit(":", 1)[1])
                await self._reject(session, user_id, payment_id, text)
                await pop_state(session, user_id)
                return
            if update.get("update_type") == "bot_started" or text in {"/start", "начать"}:
                if parent:
                    await self._send_parent_menu(user_id, parent)
                else:
                    await self.client.send_message(
                        user_id,
                        f"Здравствуйте! Это бот для учёта оплаты дополнительных занятий "
                        f"{self.settings.class_name} класса. Для начала необходимо привязать ваш аккаунт к ребёнку.",
                        [[("Привязать ребёнка", "link:start")]],
                    )
                return
            if text == "/admin" and user_id in self.settings.max_admin_ids:
                await self._admin_menu(user_id)
                return
            if not parent:
                await self.client.send_message(
                    user_id, "Сначала привяжите ребёнка.", [[("Привязать ребёнка", "link:start")]]
                )
            else:
                await self._send_parent_menu(user_id, parent)

    async def _callback(self, update: dict[str, Any]) -> None:
        user_id = self._user_id(update)
        callback = update.get("callback") or {}
        payload, callback_id = callback.get("payload", ""), callback.get("callback_id")
        if not user_id:
            return
        async with self.sessions() as session:
            if payload == "link:start":
                await set_state(session, user_id, "awaiting_link_code")
                await self.client.send_message(
                    user_id, "Введите уникальный код привязки, например: 7L1-4827"
                )
            elif payload == "payment:current":
                parent = await parent_by_max_id(session, user_id)
                if not parent:
                    await self.client.send_message(user_id, "Сначала привяжите ребёнка.")
                else:
                    await self._send_payment_card(session, parent)
            elif payload.startswith("receipt:wait:"):
                payment_id = int(payload.rsplit(":", 1)[1])
                await set_state(session, user_id, "awaiting_receipt", str(payment_id))
                await self.client.send_message(
                    user_id,
                    "Спасибо! Пришлите чек следующим сообщением. Можно отправить фотографию или файл.",
                )
            elif payload == "admin:report" and self._admin(user_id):
                await self._send_report(session, user_id)
            elif payload == "admin:debtors" and self._admin(user_id):
                await self._send_debtors(session, user_id)
            elif payload == "admin:manual" and self._admin(user_id):
                await self._manual_list(session, user_id)
            elif payload.startswith("admin:manual:") and self._admin(user_id):
                await self._manual_paid(session, user_id, int(payload.rsplit(":", 1)[1]))
            elif payload.startswith("admin:confirm:") and self._admin(user_id):
                await self._confirm(session, user_id, int(payload.rsplit(":", 1)[1]))
            elif payload.startswith("admin:reject:") and self._admin(user_id):
                payment_id = int(payload.rsplit(":", 1)[1])
                await self.client.send_message(
                    user_id, "Выберите причину:", self._reason_buttons(payment_id)
                )
            elif payload.startswith("admin:reason:") and self._admin(user_id):
                _, _, payment_id, reason = payload.split(":", 3)
                if reason == "custom":
                    await set_state(session, user_id, f"rejection_comment:{payment_id}")
                    await self.client.send_message(
                        user_id, "Напишите причину отклонения следующим сообщением."
                    )
                else:
                    await self._reject(session, user_id, int(payment_id), REJECTION_REASONS[reason])
            elif payload == "admin:menu" and self._admin(user_id):
                await self._admin_menu(user_id)
            if callback_id:
                try:
                    await self.client.answer_callback(callback_id, "Готово")
                except Exception:
                    pass

    def _admin(self, user_id: int) -> bool:
        return user_id in self.settings.max_admin_ids

    async def _send_parent_menu(self, user_id: int, parent: Parent) -> None:
        children = ", ".join(child.full_name for child in parent.children)
        await self.client.send_message(
            user_id,
            f"Здравствуйте, {parent.full_name}!\nРебёнок: {children}",
            [[("💰 Оплата за месяц", "payment:current")]],
        )

    async def _send_payment_card(self, session: AsyncSession, parent: Parent) -> None:
        child = parent.children[0]
        payment = await get_or_create_payment(session, child.id)
        await session.commit()
        lines = [
            f"📚 {item.subject.name} — {money(item.monthly_amount)}"
            for item in child.subscriptions
            if item.active
        ]
        status = {
            "paid": "✅ Оплачено",
            "receipt_received": "⏳ Чек на проверке",
            "rejected": "⚠️ Чек отклонён",
        }.get(payment.status.value)
        text = (
            f"🔔 Оплата дополнительных занятий за {month_name(payment.billing_month)}.\n\n"
            f"👧 {child.full_name}\n"
            + "\n".join(lines)
            + f"\n\nИтого: {money(payment.expected_amount)}"
        )
        buttons = (
            None
            if payment.status.value == "paid"
            else [[("Я оплатил(а)", f"receipt:wait:{payment.id}")]]
        )
        await self.client.send_message(
            parent.max_user_id, text + (f"\n\n{status}" if status else ""), buttons
        )

    async def _receive_receipt(
        self,
        session: AsyncSession,
        user_id: int,
        parent: Parent | None,
        state: UserState,
        attachments: list[dict[str, Any]],
    ) -> None:
        if not parent:
            await self.client.send_message(user_id, "Не удалось определить привязанного родителя.")
            return
        attachment = next(
            (item for item in attachments if item.get("type") in {"image", "file"}), None
        )
        if not attachment:
            await self.client.send_message(user_id, "Нужна фотография или файл чека.")
            return
        payload = attachment.get("payload") or {}
        url = payload.get("url") or payload.get("download_url")
        if not url and payload.get("photos"):
            url = payload["photos"].get("large") or next(iter(payload["photos"].values()), None)
        if not url:
            await self.client.send_message(
                user_id, "MAX не передал ссылку на файл. Попробуйте отправить чек ещё раз."
            )
            return
        content, response_type = await self.client.download(url)
        payment = await session.get(Payment, int(state.data or 0))
        if not payment or payment.child_id != parent.children[0].id:
            await self.client.send_message(
                user_id, "Платёж не найден. Нажмите «Я оплатил(а)» ещё раз."
            )
            return
        suffix = Path(payload.get("name") or "").suffix or (
            ".jpg" if attachment["type"] == "image" else ".bin"
        )
        stored = await self.storage.save(
            content,
            month=payment.billing_month,
            parent_name=parent.full_name,
            child_name=parent.children[0].full_name,
            amount=int(payment.expected_amount),
            suffix=suffix,
        )
        receipt = await add_receipt(
            session,
            payment,
            storage_key=stored.key,
            original_name=payload.get("name"),
            content_type=payload.get("content_type") or response_type,
            size_bytes=stored.size,
            max_attachment_token=payload.get("token"),
        )
        await pop_state(session, user_id)
        await self.client.send_message(
            user_id,
            f"✅ Чек получен.\nОплата за {month_name(payment.billing_month)} записана.\n"
            f"Сумма: {money(payment.expected_amount)}.\nЧек передан ответственному.",
        )
        await self._notify_admins(parent, parent.children[0], payment, receipt)

    async def _notify_admins(
        self, parent: Parent, child: Child, payment: Payment, receipt: Receipt
    ) -> None:
        text = (
            f"💳 Новый чек\n\n👧 {child.full_name}\n👤 Родитель: {parent.full_name}\n\n"
            f"📅 {month_name(payment.billing_month).capitalize()}\n💰 Ожидаемая сумма: {money(payment.expected_amount)}"
        )
        for admin_id in self.settings.max_admin_ids:
            await self.client.send_message(
                admin_id,
                text,
                [
                    [
                        ("✅ Подтвердить", f"admin:confirm:{payment.id}"),
                        ("❌ Отклонить", f"admin:reject:{payment.id}"),
                    ]
                ],
            )
            try:
                await self.client.send_file(
                    admin_id, self.storage.path(receipt.storage_key), caption="📎 Чек"
                )
            except Exception:
                await self.client.send_message(
                    admin_id,
                    "⚠️ Чек сохранён на сервере, но повторная отправка файла в MAX не удалась.",
                )

    async def _confirm(self, session: AsyncSession, admin_id: int, payment_id: int) -> None:
        payment = await confirm_payment(session, payment_id)
        payment = await session.scalar(
            select(Payment)
            .options(selectinload(Payment.child).selectinload(Child.parent))
            .where(Payment.id == payment.id)
        )
        await self.client.send_message(admin_id, "✅ Оплата подтверждена.")
        if payment.child.parent.max_user_id:
            await self.client.send_message(
                payment.child.parent.max_user_id,
                f"✅ Оплата подтверждена\n\n{payment.child.full_name}\n{month_name(payment.billing_month).capitalize()}\n"
                f"{money(payment.expected_amount)}\n\nСпасибо!",
            )

    async def _reject(
        self, session: AsyncSession, admin_id: int, payment_id: int, reason: str
    ) -> None:
        payment = await reject_payment(session, payment_id, reason)
        payment = await session.scalar(
            select(Payment)
            .options(selectinload(Payment.child).selectinload(Child.parent))
            .where(Payment.id == payment.id)
        )
        await self.client.send_message(admin_id, "❌ Чек отклонён.")
        if payment.child.parent.max_user_id:
            await self.client.send_message(
                payment.child.parent.max_user_id,
                f"❌ Чек отклонён.\nПричина: {reason}.\nПожалуйста, нажмите «Я оплатил(а)» и пришлите новый чек.",
                [[("Я оплатил(а)", f"receipt:wait:{payment.id}")]],
            )

    @staticmethod
    def _reason_buttons(payment_id: int) -> list[list[tuple[str, str]]]:
        labels = [
            ("Неправильная сумма", "wrong_amount"),
            ("Не тот месяц", "wrong_month"),
            ("Чек не читается", "unreadable"),
            ("Другой платёж", "other_payment"),
            ("Другое", "custom"),
        ]
        return [[(label, f"admin:reason:{payment_id}:{code}")] for label, code in labels]

    async def _admin_menu(self, user_id: int) -> None:
        await self.client.send_message(
            user_id,
            "Меню ответственного:",
            [
                [("📊 Отчёт", "admin:report"), ("⏳ Должники", "admin:debtors")],
                [("Отметить оплату вручную", "admin:manual")],
            ],
        )

    async def _send_report(self, session: AsyncSession, user_id: int) -> None:
        report = await payment_report(session)
        await self.client.send_message(
            user_id,
            f"📊 Оплаты за {month_name(billing_month())}\n\n"
            f"Всего родителей: {report.total}\n✅ Оплачено: {report.paid}\n⏳ Ожидаем оплату: {report.pending}\n"
            f"⚠️ Требуют проверки: {report.review}\n\n💰 Оплачено: {money(report.paid_amount)}\n"
            f"💰 Ожидается: {money(report.expected_amount)}",
        )

    async def _send_debtors(self, session: AsyncSession, user_id: int) -> None:
        rows = await debtors(session)
        lines = [
            f"{i}. {p.full_name} — {c.full_name} — {money(pay.expected_amount)}"
            for i, (p, c, pay) in enumerate(rows, 1)
        ]
        total = sum((pay.expected_amount for _, _, pay in rows), 0)
        await self.client.send_message(
            user_id,
            f"Не оплатили за {month_name(billing_month())}:\n\n"
            + ("\n".join(lines) or "Нет должников 🎉")
            + f"\n\nВсего: {money(total)}",
        )

    async def _manual_list(self, session: AsyncSession, user_id: int) -> None:
        rows = await debtors(session)
        buttons = [
            [(f"{parent.full_name} — {child.full_name}", f"admin:manual:{payment.id}")]
            for parent, child, payment in rows
        ]
        await self.client.send_message(user_id, "Кого отметить оплатившим?", buttons or None)

    async def _manual_paid(self, session: AsyncSession, user_id: int, payment_id: int) -> None:
        await confirm_payment(session, payment_id, manual=True)
        await self.client.send_message(
            user_id, "✅ Оплата отмечена вручную.", [[("В меню", "admin:menu")]]
        )
