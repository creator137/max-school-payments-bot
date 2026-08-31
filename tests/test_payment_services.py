from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Child, PaymentStatus, Receipt
from app.services.payments import (
    DomainError,
    add_receipt,
    child_total,
    confirm_payment,
    debtors,
    get_or_create_payment,
    link_parent,
    payment_report,
    reject_payment,
)


async def first_child(session):
    return await session.scalar(select(Child).order_by(Child.id))


async def test_link_parent_by_code(sessions):
    async with sessions() as session:
        parent = await link_parent(session, "7l1-4827", 101)
        assert parent.max_user_id == 101
        assert parent.children[0].full_name == "Алиса Иванова"


async def test_link_code_cannot_be_claimed_twice(sessions):
    async with sessions() as session:
        await link_parent(session, "7L1-4827", 101)
        with pytest.raises(DomainError):
            await link_parent(session, "7L1-4827", 102)


async def test_child_total_and_monthly_payment(sessions):
    async with sessions() as session:
        child = await first_child(session)
        assert await child_total(session, child.id) == Decimal("5500")
        payment = await get_or_create_payment(session, child.id, "2026-09")
        duplicate = await get_or_create_payment(session, child.id, "2026-09")
        assert payment.id == duplicate.id
        assert payment.expected_amount == Decimal("5500")
        assert payment.status == PaymentStatus.pending


async def test_receipt_history_and_status(sessions):
    async with sessions() as session:
        child = await first_child(session)
        payment = await get_or_create_payment(session, child.id, "2026-09")
        await add_receipt(
            session,
            payment,
            storage_key="2026/09/one.jpg",
            original_name="one.jpg",
            content_type="image/jpeg",
            size_bytes=4,
        )
        await add_receipt(
            session,
            payment,
            storage_key="2026/09/two.jpg",
            original_name="two.jpg",
            content_type="image/jpeg",
            size_bytes=5,
        )
        assert payment.status == PaymentStatus.receipt_received
        receipts = (
            await session.scalars(select(Receipt).where(Receipt.payment_id == payment.id))
        ).all()
        assert [item.storage_key for item in receipts] == ["2026/09/one.jpg", "2026/09/two.jpg"]


async def test_confirm_and_reject(sessions):
    async with sessions() as session:
        child = await first_child(session)
        payment = await get_or_create_payment(session, child.id, "2026-09")
        await reject_payment(session, payment.id, "чек не читается")
        assert payment.status == PaymentStatus.rejected
        assert payment.rejection_reason == "чек не читается"
        await confirm_payment(session, payment.id)
        assert payment.status == PaymentStatus.paid
        assert payment.paid_at is not None
        assert payment.rejection_reason is None


async def test_debtors_exclude_paid_and_manual_payment(sessions):
    async with sessions() as session:
        rows = await debtors(session, "2026-09")
        assert len(rows) == 3
        target = rows[0][2]
        await confirm_payment(session, target.id, manual=True)
        rows = await debtors(session, "2026-09")
        assert len(rows) == 2
        assert target.id not in {payment.id for _, _, payment in rows}
        assert target.manual is True


async def test_report(sessions):
    async with sessions() as session:
        rows = await debtors(session, "2026-09")
        await confirm_payment(session, rows[0][2].id)
        await add_receipt(
            session,
            rows[1][2],
            storage_key="2026/09/check.jpg",
            original_name="check.jpg",
            content_type="image/jpeg",
            size_bytes=1,
        )
        report = await payment_report(session, "2026-09")
        assert (report.total, report.paid, report.review, report.pending) == (3, 1, 1, 1)
        assert report.paid_amount == Decimal("5500")
