from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from app.config import Settings
from app.models import Child, Parent
from app.reminders import PaymentReminderService
from app.services.payments import confirm_payment, get_or_create_payment, link_parent


@dataclass
class FakeMaxClient:
    messages: list[tuple[int, str, object]] = field(default_factory=list)

    async def send_message(self, user_id, text, buttons=None):
        self.messages.append((user_id, text, buttons))


async def test_reminder_is_sent_once_and_paid_is_skipped(sessions):
    client = FakeMaxClient()
    settings = Settings(_env_file=None, reminder_days=[1, 5, 10], max_token="test")
    async with sessions() as session:
        await link_parent(session, "7L1-4827", 101)
    service = PaymentReminderService(sessions, client, settings)
    assert await service.run(force=False, reminder_day=5) == 1
    assert await service.run(force=False, reminder_day=5) == 0
    async with sessions() as session:
        parent = await session.scalar(select(Parent).where(Parent.max_user_id == 101))
        child = await session.scalar(select(Child).where(Child.parent_id == parent.id))
        payment = await get_or_create_payment(session, child.id)
        await confirm_payment(session, payment.id)
    assert await service.run(force=False, reminder_day=10) == 0
    assert len(client.messages) == 1
