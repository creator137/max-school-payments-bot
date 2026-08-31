from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Child, Parent, Payment, PaymentStatus, Receipt, Subscription, UserState


class DomainError(ValueError):
    pass


def billing_month(value: date | datetime | None = None) -> str:
    value = value or date.today()
    return f"{value.year:04d}-{value.month:02d}"


async def child_total(session: AsyncSession, child_id: int) -> Decimal:
    amount = await session.scalar(
        select(func.coalesce(func.sum(Subscription.monthly_amount), 0)).where(
            Subscription.child_id == child_id, Subscription.active.is_(True)
        )
    )
    return Decimal(amount)


async def get_or_create_payment(
    session: AsyncSession, child_id: int, month: str | None = None
) -> Payment:
    month = month or billing_month()
    payment = await session.scalar(
        select(Payment).where(Payment.child_id == child_id, Payment.billing_month == month)
    )
    if payment:
        return payment
    payment = Payment(
        child_id=child_id,
        billing_month=month,
        expected_amount=await child_total(session, child_id),
        status=PaymentStatus.pending,
    )
    session.add(payment)
    await session.flush()
    return payment


async def link_parent(session: AsyncSession, code: str, max_user_id: int) -> Parent:
    parent = await session.scalar(
        select(Parent)
        .options(selectinload(Parent.children))
        .where(Parent.link_code == code.strip().upper())
    )
    if not parent or not parent.active:
        raise DomainError("Код привязки не найден.")
    existing = await session.scalar(select(Parent).where(Parent.max_user_id == max_user_id))
    if existing and existing.id != parent.id:
        raise DomainError("Этот MAX-аккаунт уже привязан к другому ребёнку.")
    if parent.max_user_id not in (None, max_user_id):
        raise DomainError("Этот код уже использован другим MAX-аккаунтом.")
    parent.max_user_id = max_user_id
    await session.commit()
    return parent


async def parent_by_max_id(session: AsyncSession, max_user_id: int) -> Parent | None:
    return await session.scalar(
        select(Parent)
        .options(
            selectinload(Parent.children)
            .selectinload(Child.subscriptions)
            .selectinload(Subscription.subject)
        )
        .where(Parent.max_user_id == max_user_id, Parent.active.is_(True))
    )


async def set_state(
    session: AsyncSession, max_user_id: int, state: str, data: str | None = None
) -> None:
    item = await session.get(UserState, max_user_id)
    if item:
        item.state, item.data = state, data
    else:
        session.add(UserState(max_user_id=max_user_id, state=state, data=data))
    await session.commit()


async def pop_state(session: AsyncSession, max_user_id: int) -> UserState | None:
    item = await session.get(UserState, max_user_id)
    if item:
        await session.delete(item)
        await session.commit()
    return item


async def add_receipt(
    session: AsyncSession,
    payment: Payment,
    *,
    storage_key: str,
    original_name: str | None,
    content_type: str | None,
    size_bytes: int,
    max_attachment_token: str | None = None,
) -> Receipt:
    receipt = Receipt(
        payment_id=payment.id,
        storage_key=storage_key,
        original_name=original_name,
        content_type=content_type,
        size_bytes=size_bytes,
        max_attachment_token=max_attachment_token,
    )
    session.add(receipt)
    payment.status = PaymentStatus.receipt_received
    payment.rejection_reason = None
    await session.commit()
    return receipt


async def confirm_payment(
    session: AsyncSession, payment_id: int, *, manual: bool = False
) -> Payment:
    payment = await session.get(Payment, payment_id)
    if not payment:
        raise DomainError("Платёж не найден.")
    payment.status = PaymentStatus.paid
    payment.manual = manual
    payment.paid_at = datetime.now(UTC)
    payment.rejection_reason = None
    await session.commit()
    return payment


async def reject_payment(session: AsyncSession, payment_id: int, reason: str) -> Payment:
    payment = await session.get(Payment, payment_id)
    if not payment:
        raise DomainError("Платёж не найден.")
    payment.status = PaymentStatus.rejected
    payment.rejection_reason = reason
    await session.commit()
    return payment


async def debtors(
    session: AsyncSession, month: str | None = None
) -> list[tuple[Parent, Child, Payment]]:
    month = month or billing_month()
    children = (
        await session.scalars(
            select(Child)
            .join(Parent)
            .options(selectinload(Child.parent), selectinload(Child.subscriptions))
            .where(Parent.active.is_(True), Child.active.is_(True))
        )
    ).all()
    result: list[tuple[Parent, Child, Payment]] = []
    for child in children:
        payment = await get_or_create_payment(session, child.id, month)
        if payment.status != PaymentStatus.paid:
            result.append((child.parent, child, payment))
    await session.commit()
    return result


@dataclass(slots=True)
class PaymentReport:
    total: int
    paid: int
    pending: int
    review: int
    paid_amount: Decimal
    expected_amount: Decimal


async def payment_report(session: AsyncSession, month: str | None = None) -> PaymentReport:
    month = month or billing_month()
    children = (
        await session.scalars(
            select(Child).join(Parent).where(Parent.active.is_(True), Child.active.is_(True))
        )
    ).all()
    payments = [await get_or_create_payment(session, child.id, month) for child in children]
    await session.commit()
    paid = [p for p in payments if p.status == PaymentStatus.paid]
    review = [p for p in payments if p.status == PaymentStatus.receipt_received]
    pending = [p for p in payments if p.status in (PaymentStatus.pending, PaymentStatus.rejected)]
    return PaymentReport(
        total=len(payments),
        paid=len(paid),
        pending=len(pending),
        review=len(review),
        paid_amount=sum((p.expected_amount for p in paid), Decimal()),
        expected_amount=sum((p.expected_amount for p in pending), Decimal()),
    )
