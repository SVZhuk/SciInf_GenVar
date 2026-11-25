"""The one place where domain errors become HTTP status codes."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.exceptions import ConflictError, InvalidInputError, NotFoundError

type Handler = Callable[[Request, Exception], Awaitable[JSONResponse]]

STATUS_BY_ERROR: dict[type[Exception], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    InvalidInputError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def register_error_handlers(app: FastAPI) -> None:
    for error, status_code in STATUS_BY_ERROR.items():
        app.add_exception_handler(error, _respond_with(status_code))


def _respond_with(status_code: int) -> Handler:
    async def handle(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=status_code)

    return handle
