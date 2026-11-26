import logging
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import boto3
import pytest
from moto import mock_aws
from mypy_boto3_s3 import S3Client

from app.core.config import Settings
from app.core.exceptions import FileStorageError
from app.db.unit_of_work import AfterCommit
from app.storage.files import (
    DeleteAfterCommitStorage,
    InMemoryFileStorage,
    S3FileStorage,
    build_file_storage,
    object_key,
    project_prefix,
)

BUCKET = "test-bucket"


@pytest.fixture
def s3_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[S3Client]:
    """moto fakes S3 inside the process: no network, no real AWS account."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def keys(client: S3Client) -> list[str]:
    return [obj["Key"] for obj in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])]


def test_object_key_is_under_project_prefix() -> None:
    project_id, file_id = uuid4(), uuid4()

    key = object_key(project_id, "vcf", file_id, ".vcf.gz")

    assert key == f"{project_prefix(project_id)}vcf/{file_id}.vcf.gz"


async def test_s3_put_writes_object(s3_client: S3Client) -> None:
    await S3FileStorage(s3_client, BUCKET).put("a/b.vcf", b"data")

    assert s3_client.get_object(Bucket=BUCKET, Key="a/b.vcf")["Body"].read() == b"data"


async def test_s3_delete_removes_object(s3_client: S3Client) -> None:
    storage = S3FileStorage(s3_client, BUCKET)
    await storage.put("a/b.vcf", b"data")

    await storage.delete("a/b.vcf")

    assert keys(s3_client) == []


async def test_s3_delete_prefix_keeps_other_prefixes(s3_client: S3Client) -> None:
    storage = S3FileStorage(s3_client, BUCKET)
    for key in ["p1/a", "p1/b", "p2/c"]:
        await storage.put(key, b"x")

    await storage.delete_prefix("p1/")

    assert keys(s3_client) == ["p2/c"]


async def test_s3_delete_prefix_without_objects_is_a_no_op(s3_client: S3Client) -> None:
    await S3FileStorage(s3_client, BUCKET).delete_prefix("missing/")

    assert keys(s3_client) == []


def test_build_file_storage_returns_s3_storage(settings: Settings) -> None:
    assert isinstance(build_file_storage(settings), S3FileStorage)


async def test_in_memory_delete_missing_key_is_a_no_op() -> None:
    storage = InMemoryFileStorage()

    await storage.delete("missing")

    assert storage.objects == {}


async def test_in_memory_delete_prefix() -> None:
    storage = InMemoryFileStorage()
    await storage.put("p1/a", b"x")
    await storage.put("p2/b", b"y")

    await storage.delete_prefix("p1/")

    assert storage.objects == {"p2/b": b"y"}


async def test_s3_delete_prefix_raises_on_partial_failure(
    s3_client: S3Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = S3FileStorage(s3_client, BUCKET)
    await storage.put("p1/a", b"x")

    def refuse(**_: object) -> dict[str, Any]:  # S3 reports per-key failures with HTTP 200
        return {"Errors": [{"Key": "p1/a", "Code": "AccessDenied"}]}

    monkeypatch.setattr(s3_client, "delete_objects", refuse)

    with pytest.raises(FileStorageError):
        await storage.delete_prefix("p1/")


async def test_s3_delete_prefix_client_error_becomes_storage_error(s3_client: S3Client) -> None:
    with pytest.raises(FileStorageError):
        await S3FileStorage(s3_client, "missing-bucket").delete_prefix("p1/")


async def test_s3_delete_client_error_becomes_storage_error(s3_client: S3Client) -> None:
    with pytest.raises(FileStorageError):
        await S3FileStorage(s3_client, "missing-bucket").delete("a")


class BrokenStorage(InMemoryFileStorage):
    async def delete(self, key: str) -> None:
        raise FileStorageError(f"refused key={key}")


async def test_deferred_storage_writes_at_once_and_deletes_after_commit() -> None:
    storage, after_commit = InMemoryFileStorage(), AfterCommit()
    deferred = DeleteAfterCommitStorage(storage, after_commit)
    await deferred.put("p1/a", b"x")
    await deferred.put("p2/b", b"y")

    await deferred.delete("p1/a")
    await deferred.delete_prefix("p2/")
    before_commit = dict(storage.objects)
    await after_commit.run()

    assert before_commit == {"p1/a": b"x", "p2/b": b"y"}
    assert storage.objects == {}


async def test_deferred_storage_logs_failed_delete_instead_of_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    after_commit = AfterCommit()
    await DeleteAfterCommitStorage(BrokenStorage(), after_commit).delete("p1/a")

    await after_commit.run()

    assert any(
        record.levelno == logging.ERROR and "p1/a" in record.getMessage()
        for record in caplog.records
    )
