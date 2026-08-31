from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.formatting import money, month_name
from app.max_api import MaxClient
from app.models import Child, Parent, PaymentStatus, ReminderLog, Subscription
from app.services.payments import billing_month, get_or_create_payment


class PaymentReminderService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], client: MaxClient, settings: Settings
    ):
        self.sessions, self.client, self.settings = sessions, client, settings

    async def run(self, *, force: bool = False, reminder_day: int | None = None) -> int:
        now = datetime.now(ZoneInfo(self.settings.app_timezone))
        day = reminder_day or now.day
        if not force and day not in self.settings.reminder_days:
            return 0
        sent = 0
        async with self.sessions() as session:
            parents = (
                await session.scalars(
                    select(Parent)
                    .options(
                        selectinload(Parent.children)
                        .selectinload(Child.subscriptions)
                        .selectinload(Subscription.subject)
                    )
                    .where(Parent.active.is_(True), Parent.max_user_id.is_not(None))
                )
            ).all()
            for parent in parents:
                for child in parent.children:
                    payment = await get_or_create_payment(session, child.id, billing_month(now))
                    if payment.status == PaymentStatus.paid:
                        continue
                    already_sent = await session.scalar(
                        select(ReminderLog).where(
                            ReminderLog.payment_id == payment.id, ReminderLog.reminder_day == day
                        )
                    )
                    if already_sent and not force:
                        continue
                    lines = "\n".join(
                        f"📚 {item.subject.name} — {money(item.monthly_amount)}"
                        for item in child.subscriptions
                        if item.active
                    )
                    await self.client.send_message(
                        parent.max_user_id,
                        f"🔔 Напоминание об оплате\n\nОплата дополнительных занятий за "
                        f"{month_name(payment.billing_month)}.\n\n👧 {child.full_name}\n{lines}\n\n"
                        f"Итого: {money(payment.expected_amount)}\n\nПосле оплаты отправьте чек через кнопку ниже.",
                        [[("Я оплатил(а)", f"receipt:wait:{payment.id}")]],
                    )
                    if not already_sent:
                        session.add(ReminderLog(payment_id=payment.id, reminder_day=day))
                    sent += 1
            await session.commit()
        return sent
