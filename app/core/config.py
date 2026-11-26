"""Application settings, read from environment variables or a local .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    log_level: LogLevel = "INFO"
    s3_bucket: str = "gva-files"
    s3_endpoint_url: str | None = None
    aws_region: str = "us-east-1"
    max_upload_bytes: int = 50 * 1024 * 1024  # also caps a .gz file after decompression


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  (from the environment)
