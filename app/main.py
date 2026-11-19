from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import router as v1_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_requests
from app.db.session import database_lifespan


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)
    async with database_lifespan(app, settings):
        yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Genomic Variant Analysis API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings or get_settings()
    app.middleware("http")(log_requests)
    app.include_router(v1_router)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
