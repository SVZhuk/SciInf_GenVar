import gzip
import logging
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import (
    AnnotationFileNotFoundError,
    InvalidFileFormatError,
    InvalidFilenameError,
    ProjectNotFoundError,
)
from app.parsers.clinvar import ClinVarFormat
from app.services.annotation_file import AnnotationFileService
from app.storage.files import InMemoryFileStorage
from tests.samples import SIMPLIFIED_HEADER, SIMPLIFIED_ROW, clinvar_text, sample_clinvar


async def test_upload_stores_metadata_and_file(
    annotation_service: AnnotationFileService, storage: InMemoryFileStorage, project_id: UUID
) -> None:
    annotation_file = await annotation_service.upload(project_id, "clinvar.txt", sample_clinvar())

    assert annotation_file.column_format == ClinVarFormat.SIMPLIFIED
    assert annotation_file.entry_count == 1
    assert storage.objects == {annotation_file.s3_key: sample_clinvar()}


async def test_upload_gzip(annotation_service: AnnotationFileService, project_id: UUID) -> None:
    data = gzip.compress(sample_clinvar())

    annotation_file = await annotation_service.upload(project_id, "variant_summary.txt.gz", data)

    assert annotation_file.s3_key.endswith(
        f"/annotation/{annotation_file.annotation_file_id}.txt.gz"
    )


async def test_upload_warns_about_invalid_entries(
    annotation_service: AnnotationFileService,
    project_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    data = clinvar_text(SIMPLIFIED_HEADER, SIMPLIFIED_ROW, "broken row")

    annotation_file = await annotation_service.upload(project_id, "clinvar.tsv", data)

    assert annotation_file.entry_count == 1
    assert "1 invalid entries" in caplog.text


async def test_upload_unknown_project_raises(annotation_service: AnnotationFileService) -> None:
    with pytest.raises(ProjectNotFoundError):
        await annotation_service.upload(uuid4(), "clinvar.txt", sample_clinvar())


async def test_upload_bad_extension_raises(
    annotation_service: AnnotationFileService, project_id: UUID
) -> None:
    with pytest.raises(InvalidFilenameError):
        await annotation_service.upload(project_id, "clinvar.vcf", sample_clinvar())


async def test_upload_invalid_content_stores_nothing(
    annotation_service: AnnotationFileService,
    storage: InMemoryFileStorage,
    project_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(InvalidFileFormatError):
        await annotation_service.upload(project_id, "clinvar.txt", b"a\tb\n")

    assert storage.objects == {}
    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_list_annotation_files(
    annotation_service: AnnotationFileService, project_id: UUID
) -> None:
    annotation_file = await annotation_service.upload(project_id, "clinvar.txt", sample_clinvar())

    assert await annotation_service.list_annotation_files(project_id) == [annotation_file]


async def test_list_unknown_project_raises(annotation_service: AnnotationFileService) -> None:
    with pytest.raises(ProjectNotFoundError):
        await annotation_service.list_annotation_files(uuid4())


async def test_delete_removes_row_and_file(
    annotation_service: AnnotationFileService, storage: InMemoryFileStorage, project_id: UUID
) -> None:
    annotation_file = await annotation_service.upload(project_id, "clinvar.txt", sample_clinvar())

    await annotation_service.delete_annotation_file(project_id, annotation_file.annotation_file_id)

    assert await annotation_service.list_annotation_files(project_id) == []
    assert storage.objects == {}


async def test_delete_unknown_file_raises_and_warns(
    annotation_service: AnnotationFileService,
    project_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(AnnotationFileNotFoundError):
        await annotation_service.delete_annotation_file(project_id, uuid4())

    assert any(record.levelno == logging.WARNING for record in caplog.records)
