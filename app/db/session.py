"""Engine lifecycle and one database session (one transaction) per request."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.unit_of_work import AfterCommit, get_after_commit

logger = logging.getLogger(__name__)


@asynccontextmanager
async def database_lifespan(app: FastAPI, settings: Settings) -> AsyncGenerator[None]:
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    logger.info("Database engine started")
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("Database engine disposed")


async def get_session(
    request: Request, after_commit: Annotated[AfterCommit, Depends(get_after_commit)]
) -> AsyncGenerator[AsyncSession]:
    """Unit of Work: commit if the request succeeds, roll back if anything raises.

    Actions in after_commit (S3 deletes) run only after a successful commit.
    """
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        async with session.begin():
            yield session
        await after_commit.run()
