"""File storage behind one Protocol: S3 in the running app, a dict in tests."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings
from app.core.exceptions import FileStorageError
from app.db.unit_of_work import AfterCommit

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client  # type stubs are a dev dependency
    from mypy_boto3_s3.type_defs import ObjectIdentifierTypeDef

logger = logging.getLogger(__name__)


def project_prefix(project_id: UUID) -> str:
    return f"projects/{project_id}/"


def object_key(project_id: UUID, kind: str, file_id: UUID, extension: str) -> str:
    """Server-built key; the client filename never becomes part of it."""
    return f"{project_prefix(project_id)}{kind}/{file_id}{extension}"


class FileStorage(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def delete_prefix(self, prefix: str) -> None: ...


class S3FileStorage:
    """boto3 is blocking, so every call runs in a worker thread (boto3 clients are thread-safe)."""

    def __init__(self, client: S3Client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._client.put_object, Bucket=self._bucket, Key=key, Body=data)
        logger.debug("Stored object key=%s bytes=%d", key, len(data))

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise FileStorageError(f"S3 could not delete key={key}") from exc
        logger.debug("Deleted object key=%s", key)

    async def delete_prefix(self, prefix: str) -> None:
        try:
            count = await asyncio.to_thread(self._delete_prefix, prefix)
        except (BotoCoreError, ClientError) as exc:
            raise FileStorageError(f"S3 could not delete prefix={prefix}") from exc
        logger.debug("Deleted %d objects under prefix=%s", count, prefix)

    def _delete_prefix(self, prefix: str) -> int:
        # list_objects_v2 returns at most 1000 keys per page, the delete_objects limit.
        count = 0
        for page in self._client.get_paginator("list_objects_v2").paginate(
            Bucket=self._bucket, Prefix=prefix
        ):
            keys: list[ObjectIdentifierTypeDef] = [
                {"Key": obj["Key"]} for obj in page.get("Contents", []) if "Key" in obj
            ]
            if not keys:
                continue
            response = self._client.delete_objects(Bucket=self._bucket, Delete={"Objects": keys})
            if errors := response.get("Errors"):  # partial failure is HTTP 200, not an exception
                raise FileStorageError(f"S3 could not delete {len(errors)} objects")
            count += len(keys)
        return count


class InMemoryFileStorage:
    """Dict keyed by object key: O(1) put and delete."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def delete_prefix(self, prefix: str) -> None:
        for key in [key for key in self.objects if key.startswith(prefix)]:
            del self.objects[key]


class DeleteAfterCommitStorage:
    """Decorator: writes happen at once, deletes wait until the database commit has succeeded.

    If the commit fails, the rows come back and their files are still there. If a delete fails
    after the commit, the object is orphaned (no row points to it): logged, not raised, because
    the client's delete has already succeeded.
    """

    def __init__(self, storage: FileStorage, after_commit: AfterCommit) -> None:
        self._storage = storage
        self._after_commit = after_commit

    async def put(self, key: str, data: bytes) -> None:
        await self._storage.put(key, data)

    async def delete(self, key: str) -> None:
        self._after_commit.add(partial(self._run, self._storage.delete, key))

    async def delete_prefix(self, prefix: str) -> None:
        self._after_commit.add(partial(self._run, self._storage.delete_prefix, prefix))

    @staticmethod
    async def _run(delete: Callable[[str], Awaitable[None]], target: str) -> None:
        try:
            await delete(target)
        except FileStorageError as exc:
            logger.error("Orphaned file after commit: %s", exc)


def build_file_storage(settings: Settings) -> S3FileStorage:
    """Credentials come from the default AWS chain (env vars locally, the ECS task role on AWS)."""
    client = boto3.client(
        "s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url
    )
    return S3FileStorage(client, settings.s3_bucket)
