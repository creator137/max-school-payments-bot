from __future__ import annotations

import argparse
import asyncio

from app.config import get_settings
from app.db import SessionFactory, engine
from app.handlers import BotHandler
from app.max_api import MaxClient, poll_forever
from app.models import Base
from app.reminders import PaymentReminderService
from app.seed import seed_mock_data
from app.services.cursor import SQLAlchemyCursorStore
from app.storage import LocalReceiptStorage


async def main_async(command: str) -> None:
    settings = get_settings()
    client = None
    try:
        if command == "init-db":
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with SessionFactory() as session:
                await seed_mock_data(session)
        elif command == "remind-now":
            client = MaxClient(settings.max_token, settings.max_api_base_url, settings.max_verify)
            service = PaymentReminderService(SessionFactory, client, settings)
            print(f"Sent reminders: {await service.run(force=True)}")
        elif command == "poll":
            client = MaxClient(settings.max_token, settings.max_api_base_url, settings.max_verify)
            handler = BotHandler(
                SessionFactory, client, LocalReceiptStorage(settings.receipts_root), settings
            )
            await poll_forever(handler, client, SQLAlchemyCursorStore(SessionFactory))
        elif command == "check-max":
            client = MaxClient(settings.max_token, settings.max_api_base_url, settings.max_verify)
            me = await client.get_me()
            print(f"MAX connection OK: bot_id={me.get('user_id')}, username={me.get('username')}")
        elif command == "subscribe":
            client = MaxClient(settings.max_token, settings.max_api_base_url, settings.max_verify)
            if not settings.max_webhook_url or not settings.max_webhook_secret:
                raise SystemExit("MAX_WEBHOOK_URL and MAX_WEBHOOK_SECRET are required")
            result = await client.subscribe(settings.max_webhook_url, settings.max_webhook_secret)
            print(
                "Webhook subscription:",
                "OK" if result.get("success") else result.get("message", "failed"),
            )
    finally:
        if client:
            await client.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["init-db", "remind-now", "poll", "check-max", "subscribe"]
    )
    args = parser.parse_args()
    asyncio.run(main_async(args.command))


if __name__ == "__main__":
    main()
