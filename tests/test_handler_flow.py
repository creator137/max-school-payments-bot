from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.config import Settings
from app.handlers import BotHandler
from app.models import Payment, PaymentStatus, Receipt
from app.storage import LocalReceiptStorage


@dataclass
class FakeMaxClient:
    messages: list[tuple[int, str, object]] = field(default_factory=list)
    files: list[tuple[int, Path]] = field(default_factory=list)

    async def send_message(self, user_id, text, buttons=None):
        self.messages.append((user_id, text, buttons))

    async def answer_callback(self, callback_id, notification):
        return None

    async def download(self, url):
        return b"test-receipt", "image/jpeg"

    async def send_file(self, user_id, path, **kwargs):
        self.files.append((user_id, path))


def message(user_id: int, text: str = "", attachments=None):
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": user_id},
            "body": {"text": text, "attachments": attachments or []},
        },
    }


def callback(user_id: int, payload: str):
    return {
        "update_type": "message_callback",
        "callback": {
            "callback_id": f"cb-{payload}",
            "payload": payload,
            "user": {"user_id": user_id},
        },
        "message": {"sender": {"user_id": 437985824, "is_bot": True}},
    }


async def test_complete_parent_receipt_admin_flow(sessions, tmp_path):
    parent_id, admin_id = 101, 999
    client = FakeMaxClient()
    settings = Settings(_env_file=None, max_token="test", max_admin_ids={admin_id})
    handler = BotHandler(sessions, client, LocalReceiptStorage(tmp_path), settings)

    await handler.handle({"update_type": "bot_started", "user": {"user_id": parent_id}})
    await handler.handle(callback(parent_id, "link:start"))
    await handler.handle(message(parent_id, "7L1-4827"))
    await handler.handle(callback(parent_id, "payment:current"))

    async with sessions() as session:
        payment = await session.scalar(select(Payment))
        payment_id = payment.id

    await handler.handle(callback(parent_id, f"receipt:wait:{payment_id}"))
    await handler.handle(
        message(
            parent_id,
            attachments=[
                {
                    "type": "image",
                    "payload": {"url": "https://files.test/receipt.jpg", "name": "receipt.jpg"},
                }
            ],
        )
    )

    async with sessions() as session:
        payment = await session.get(Payment, payment_id)
        assert payment.status == PaymentStatus.receipt_received
        assert await session.scalar(select(Receipt).where(Receipt.payment_id == payment_id))
    assert client.files and client.files[0][0] == admin_id

    await handler.handle(callback(admin_id, f"admin:confirm:{payment_id}"))
    async with sessions() as session:
        payment = await session.get(Payment, payment_id)
        assert payment.status == PaymentStatus.paid
    assert any(
        user_id == parent_id and "Оплата подтверждена" in text
        for user_id, text, _ in client.messages
    )
