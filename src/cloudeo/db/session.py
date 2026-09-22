from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from cloudeo.config import Settings


class Database:
    def __init__(self, settings: Settings):
        self.engine: AsyncEngine = create_async_engine(settings.database_url, echo=False)

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    def session(self) -> AsyncSession:
        return AsyncSession(self.engine)
