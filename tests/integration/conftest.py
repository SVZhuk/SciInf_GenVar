"""Postgres fixtures: one schema per test session, one rolled-back transaction per test."""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import Settings
from app.main import create_app
from app.models import Base
from app.storage.files import InMemoryFileStorage


@pytest_asyncio.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()


@pytest_asyncio.fixture
async def e2e_client(
    engine: AsyncEngine, settings: Settings, storage: InMemoryFileStorage
) -> AsyncIterator[AsyncClient]:
    """Real app, lifespan and Postgres (requests commit); S3 replaced by in-memory storage."""
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        app.state.file_storage = storage  # replaces S3 behind the real dependency chain
        yield client
