"""Upload size limits: an early check on the request header and an exact one on the file."""

from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse

from app.core.config import Settings

MULTIPART_OVERHEAD_BYTES = 64 * 1024  # boundaries and part headers around the file


def too_large_detail(max_bytes: int) -> str:
    return f"File is larger than {max_bytes} bytes"


async def reject_oversized_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Refuse a body announced as too large before Starlette spools it to disk."""
    settings: Settings = request.app.state.settings
    content_length = request.headers.get("content-length", "")
    limit = settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES
    if content_length.isdigit() and int(content_length) > limit:
        return JSONResponse(
            {"detail": too_large_detail(settings.max_upload_bytes)},
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )
    return await call_next(request)


async def read_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Exact check on the file itself; also covers bodies sent without Content-Length."""
    data = await file.read(max_bytes + 1)  # one byte more than allowed is enough to know
    if len(data) > max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail=too_large_detail(max_bytes))
    return data
