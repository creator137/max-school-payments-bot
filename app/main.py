from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from app.config import get_settings
from app.db import SessionFactory, engine
from app.handlers import BotHandler
from app.max_api import MaxClient
from app.models import Base
from app.reminders import PaymentReminderService
from app.seed import seed_mock_data
from app.storage import LocalReceiptStorage

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

client = MaxClient(settings.max_token, settings.max_api_base_url, settings.max_verify)
storage = LocalReceiptStorage(settings.receipts_root)
handler = BotHandler(SessionFactory, client, storage, settings)
reminders = PaymentReminderService(SessionFactory, client, settings)
scheduler = AsyncIOScheduler(timezone=settings.app_timezone)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    if settings.seed_on_start:
        async with SessionFactory() as session:
            if await seed_mock_data(session):
                logger.info("Mock parent data seeded")
    if settings.scheduler_enabled:
        scheduler.add_job(
            reminders.run, "cron", hour=9, minute=0, id="payment-reminders", replace_existing=True
        )
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await client.close()
    await engine.dispose()


app = FastAPI(title="MAX School Payments Bot", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/max")
async def max_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_max_bot_api_secret: str | None = Header(default=None),
) -> dict[str, bool]:
    if settings.max_webhook_secret and x_max_bot_api_secret != settings.max_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    update = await request.json()
    background_tasks.add_task(handler.handle, update)
    return {"ok": True}
