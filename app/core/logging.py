"""Logging setup and per-request access log."""

import logging
import logging.config
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

logger = logging.getLogger("app.request")


def configure_logging(level: str) -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"default": {"format": LOG_FORMAT}},
            "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "default"}},
            "root": {"handlers": ["console"], "level": level},
            "loggers": {"uvicorn.access": {"level": "WARNING"}},
        }
    )


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Log method, path, status and duration; never query strings or bodies."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    level = logging.INFO
    if response.status_code >= 500:
        level = logging.ERROR
    elif response.status_code >= 400:
        level = logging.WARNING
    logger.log(
        level,
        "%s %s -> %d (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response
