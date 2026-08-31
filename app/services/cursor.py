from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AppSetting


class SQLAlchemyCursorStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], key: str = "max_updates_marker"):
        self.sessions = sessions
        self.key = key

    async def load(self) -> int | None:
        async with self.sessions() as session:
            item = await session.get(AppSetting, self.key)
            return int(item.value) if item and item.value else None

    async def save(self, marker: int) -> None:
        async with self.sessions() as session:
            item = await session.get(AppSetting, self.key)
            if item:
                item.value = str(marker)
            else:
                session.add(AppSetting(key=self.key, value=str(marker)))
            await session.commit()
