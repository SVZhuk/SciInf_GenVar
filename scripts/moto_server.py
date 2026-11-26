"""Local S3 (moto server) with access logs in the API format; runs in the s3 Compose service.

Usage (inside the motoserver/moto image): python /scripts/moto_server.py
"""

import logging
import time

from moto.moto_server.werkzeug_app import (
    DomainDispatcherApplication,
    MotoRequestHandler,
    create_backend_app,
)
from werkzeug import serving

# Same as app.core.logging.LOG_FORMAT; the moto image has no app package to import it from.
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

logger = logging.getLogger("moto.request")


class AccessLogRequestHandler(MotoRequestHandler):
    """One line per request: method, path without query string, status, duration."""

    def run_wsgi(self) -> None:
        self._start = time.perf_counter()
        super().run_wsgi()

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        duration_ms = (time.perf_counter() - self._start) * 1000
        status = int(code) if str(code).isdigit() else 0
        level = logging.INFO
        if status >= 500:
            level = logging.ERROR
        elif status >= 400:
            level = logging.WARNING
        path = self.path.split("?", 1)[0]
        logger.log(level, "%s %s -> %s (%.1f ms)", self.command, path, code, duration_ms)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    serving._log_add_style = False  # no ANSI colour codes in the startup lines
    app = DomainDispatcherApplication(create_backend_app)
    serving.run_simple("0.0.0.0", 5000, app, threaded=True, request_handler=AccessLogRequestHandler)


if __name__ == "__main__":
    main()
