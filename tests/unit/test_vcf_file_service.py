import gzip
import logging
import threading
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import (
    InvalidFileFormatError,
    InvalidFilenameError,
    ProjectNotFoundError,
    VcfFileNotFoundError,
)
from app.parsers.vcf import ParsedVcf, parse_vcf
from app.repositories.project import InMemoryProjectRepository
from app.schemas.project import ProjectCreate
from app.services.vcf_file import VcfFileService
from app.storage.files import InMemoryFileStorage
from tests.samples import sample_vcf


@pytest.fixture
async def project_id(repository: InMemoryProjectRepository) -> UUID:
    project = await repository.add(ProjectCreate(name="BRCA", lead_scientist="R. Franklin"))
    return project.project_id


async def test_upload_stores_metadata_variants_and_file(
    vcf_service: VcfFileService, storage: InMemoryFileStorage, project_id: UUID
) -> None:
    vcf_file = await vcf_service.upload(project_id, "calls.vcf", sample_vcf())

    _, variants = await vcf_service.get_vcf_file(project_id, vcf_file.vcf_file_id, 100, 0)
    assert (vcf_file.filename, vcf_file.variant_count, vcf_file.sample_count) == ("calls.vcf", 3, 0)
    assert [v.af for v in variants] == [0.25, 0.1, 0.2]
    assert storage.objects == {vcf_file.s3_key: sample_vcf()}


async def test_upload_key_is_built_by_server(vcf_service: VcfFileService, project_id: UUID) -> None:
    vcf_file = await vcf_service.upload(project_id, "../../etc/calls.vcf", sample_vcf())

    assert vcf_file.s3_key == f"projects/{project_id}/vcf/{vcf_file.vcf_file_id}.vcf"


async def test_upload_gzip(vcf_service: VcfFileService, project_id: UUID) -> None:
    vcf_file = await vcf_service.upload(project_id, "calls.vcf.gz", gzip.compress(sample_vcf()))

    assert vcf_file.variant_count == 3
    assert vcf_file.s3_key.endswith(".vcf.gz")


async def test_upload_logs_ids_and_counts(
    vcf_service: VcfFileService, project_id: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        vcf_file = await vcf_service.upload(project_id, "calls.vcf", sample_vcf())

    assert f"vcf_file_id={vcf_file.vcf_file_id}" in caplog.text
    assert "variants=3" in caplog.text
    assert "calls.vcf" not in caplog.text


async def test_upload_unknown_project_raises(vcf_service: VcfFileService) -> None:
    with pytest.raises(ProjectNotFoundError):
        await vcf_service.upload(uuid4(), "calls.vcf", sample_vcf())


async def test_upload_bad_extension_raises_and_warns(
    vcf_service: VcfFileService, project_id: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(InvalidFilenameError):
        await vcf_service.upload(project_id, "calls.csv", sample_vcf())

    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_upload_invalid_content_stores_nothing(
    vcf_service: VcfFileService,
    storage: InMemoryFileStorage,
    project_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(InvalidFileFormatError):
        await vcf_service.upload(project_id, "calls.vcf", b"not a vcf")

    assert storage.objects == {}
    assert await vcf_service.list_vcf_files(project_id) == []
    assert "line=1" in caplog.text


async def test_list_vcf_files(vcf_service: VcfFileService, project_id: UUID) -> None:
    first = await vcf_service.upload(project_id, "a.vcf", sample_vcf())
    second = await vcf_service.upload(project_id, "b.vcf", sample_vcf())

    assert await vcf_service.list_vcf_files(project_id) == [first, second]


async def test_list_unknown_project_raises(vcf_service: VcfFileService) -> None:
    with pytest.raises(ProjectNotFoundError):
        await vcf_service.list_vcf_files(uuid4())


async def test_get_pages_variants(vcf_service: VcfFileService, project_id: UUID) -> None:
    vcf_file = await vcf_service.upload(project_id, "calls.vcf", sample_vcf())

    _, variants = await vcf_service.get_vcf_file(project_id, vcf_file.vcf_file_id, 1, 1)

    assert [v.alt for v in variants] == ["T"]


async def test_get_unknown_file_raises_and_warns(
    vcf_service: VcfFileService, project_id: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(VcfFileNotFoundError):
        await vcf_service.get_vcf_file(project_id, uuid4(), 100, 0)

    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_get_file_of_other_project_raises(
    vcf_service: VcfFileService, repository: InMemoryProjectRepository, project_id: UUID
) -> None:
    other = await repository.add(ProjectCreate(name="other", lead_scientist="R. Franklin"))
    vcf_file = await vcf_service.upload(project_id, "calls.vcf", sample_vcf())

    with pytest.raises(VcfFileNotFoundError):
        await vcf_service.get_vcf_file(other.project_id, vcf_file.vcf_file_id, 100, 0)


async def test_delete_removes_rows_and_file(
    vcf_service: VcfFileService, storage: InMemoryFileStorage, project_id: UUID
) -> None:
    vcf_file = await vcf_service.upload(project_id, "calls.vcf", sample_vcf())

    await vcf_service.delete_vcf_file(project_id, vcf_file.vcf_file_id)

    assert await vcf_service.list_vcf_files(project_id) == []
    assert storage.objects == {}


async def test_delete_unknown_file_raises(vcf_service: VcfFileService, project_id: UUID) -> None:
    with pytest.raises(VcfFileNotFoundError):
        await vcf_service.delete_vcf_file(project_id, uuid4())


async def test_upload_parses_in_a_worker_thread(
    vcf_service: VcfFileService, project_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    threads: list[int] = []

    def spy(lines: list[str]) -> ParsedVcf:
        threads.append(threading.get_ident())
        return parse_vcf(lines)

    monkeypatch.setattr("app.services.vcf_file.parse_vcf", spy)

    await vcf_service.upload(project_id, "calls.vcf", sample_vcf())

    assert threads != [threading.get_ident()]
