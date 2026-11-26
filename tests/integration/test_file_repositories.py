from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnnotationFileModel, VariantModel, VcfFileModel
from app.parsers.clinvar import ClinVarFormat
from app.parsers.vcf import ParsedVariant
from app.repositories.annotation_file import SqlAlchemyAnnotationFileRepository
from app.repositories.project import SqlAlchemyProjectRepository
from app.repositories.vcf_file import INSERT_BATCH_SIZE, SqlAlchemyVcfFileRepository
from app.schemas.project import ProjectCreate

pytestmark = pytest.mark.integration


def variant(pos: int) -> ParsedVariant:
    return ParsedVariant("chr1", pos, None, "A", "G", 30.0, "PASS", 0.5, {"AF": "0.5", "DB": True})


def new_vcf_file(project_id: UUID) -> VcfFileModel:
    return VcfFileModel(
        vcf_file_id=uuid4(),
        project_id=project_id,
        filename="calls.vcf",
        s3_key=f"projects/{project_id}/vcf/{uuid4()}.vcf",
        sample_count=0,
        variant_count=0,
    )


def new_annotation_file(project_id: UUID) -> AnnotationFileModel:
    return AnnotationFileModel(
        annotation_file_id=uuid4(),
        project_id=project_id,
        filename="clinvar.txt",
        s3_key=f"projects/{project_id}/annotation/{uuid4()}.txt",
        column_format=ClinVarFormat.FULL,
        entry_count=1,
    )


@pytest.fixture
async def project_id(session: AsyncSession) -> UUID:
    projects = SqlAlchemyProjectRepository(session)
    project = await projects.add(ProjectCreate(name="BRCA", lead_scientist="R. Franklin"))
    return project.project_id


@pytest.fixture
def vcf_files(session: AsyncSession) -> SqlAlchemyVcfFileRepository:
    return SqlAlchemyVcfFileRepository(session)


@pytest.fixture
def annotation_files(session: AsyncSession) -> SqlAlchemyAnnotationFileRepository:
    return SqlAlchemyAnnotationFileRepository(session)


async def count_variants(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(VariantModel)) or 0


async def test_add_inserts_variants_in_batches(
    vcf_files: SqlAlchemyVcfFileRepository, session: AsyncSession, project_id: UUID
) -> None:
    variants = [variant(pos) for pos in range(1, INSERT_BATCH_SIZE + 2)]

    vcf_file = await vcf_files.add(new_vcf_file(project_id), variants)

    assert vcf_file.uploaded_at is not None
    assert await count_variants(session) == INSERT_BATCH_SIZE + 1


async def test_list_variants_round_trips_jsonb_and_pages(
    vcf_files: SqlAlchemyVcfFileRepository, project_id: UUID
) -> None:
    vcf_file = await vcf_files.add(new_vcf_file(project_id), [variant(1), variant(2)])

    [second] = await vcf_files.list_variants(vcf_file.vcf_file_id, limit=1, offset=1)

    assert (second.pos, second.af, second.info) == (2, 0.5, {"AF": "0.5", "DB": True})


async def test_get_is_scoped_to_project(
    vcf_files: SqlAlchemyVcfFileRepository, project_id: UUID
) -> None:
    vcf_file = await vcf_files.add(new_vcf_file(project_id), [])

    assert await vcf_files.get(project_id, vcf_file.vcf_file_id) is vcf_file
    assert await vcf_files.get(uuid4(), vcf_file.vcf_file_id) is None


async def test_list_for_project(vcf_files: SqlAlchemyVcfFileRepository, project_id: UUID) -> None:
    vcf_file = await vcf_files.add(new_vcf_file(project_id), [])

    assert await vcf_files.list_for_project(project_id) == [vcf_file]


async def test_delete_cascades_to_variants(
    vcf_files: SqlAlchemyVcfFileRepository, session: AsyncSession, project_id: UUID
) -> None:
    vcf_file = await vcf_files.add(new_vcf_file(project_id), [variant(1)])

    await vcf_files.delete(vcf_file)

    assert await count_variants(session) == 0


async def test_long_alleles_are_stored(
    vcf_files: SqlAlchemyVcfFileRepository, project_id: UUID
) -> None:
    deletion = ParsedVariant("chr1", 1, None, "A" * 10_000, "A", None, None, None, {})

    vcf_file = await vcf_files.add(new_vcf_file(project_id), [deletion])

    [stored] = await vcf_files.list_variants(vcf_file.vcf_file_id, limit=1, offset=0)
    assert len(stored.ref) == 10_000


async def test_deleting_project_cascades_to_files(
    vcf_files: SqlAlchemyVcfFileRepository,
    annotation_files: SqlAlchemyAnnotationFileRepository,
    session: AsyncSession,
    project_id: UUID,
) -> None:
    await vcf_files.add(new_vcf_file(project_id), [variant(1)])
    await annotation_files.add(new_annotation_file(project_id))
    projects = SqlAlchemyProjectRepository(session)
    project = await projects.get(project_id)
    assert project is not None

    await projects.delete(project)

    session.expunge_all()
    assert await vcf_files.list_for_project(project_id) == []
    assert await annotation_files.list_for_project(project_id) == []
    assert await count_variants(session) == 0


async def test_annotation_add_get_list_delete(
    annotation_files: SqlAlchemyAnnotationFileRepository, project_id: UUID
) -> None:
    annotation_file = await annotation_files.add(new_annotation_file(project_id))
    assert await annotation_files.get(project_id, annotation_file.annotation_file_id) is (
        annotation_file
    )
    assert await annotation_files.list_for_project(project_id) == [annotation_file]

    await annotation_files.delete(annotation_file)

    assert await annotation_files.get(project_id, annotation_file.annotation_file_id) is None
