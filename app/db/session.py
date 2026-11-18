"""Engine lifecycle and one database session (one transaction) per request."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def database_lifespan(app: FastAPI, settings: Settings) -> AsyncIterator[None]:
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    logger.info("Database engine started")
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("Database engine disposed")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Unit of Work: commit if the request succeeds, roll back if anything raises."""
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session, session.begin():
        yield session
