from uuid import uuid4

from app.models import AnnotationFileModel, VcfFileModel
from app.parsers.clinvar import ClinVarFormat
from app.parsers.vcf import ParsedVariant
from app.repositories.annotation_file import InMemoryAnnotationFileRepository
from app.repositories.vcf_file import InMemoryVcfFileRepository


def new_vcf_file() -> VcfFileModel:
    return VcfFileModel(
        vcf_file_id=uuid4(),
        project_id=uuid4(),
        filename="calls.vcf",
        s3_key=f"{uuid4()}.vcf",
        sample_count=0,
        variant_count=1,
    )


def new_annotation_file() -> AnnotationFileModel:
    return AnnotationFileModel(
        annotation_file_id=uuid4(),
        project_id=uuid4(),
        filename="clinvar.txt",
        s3_key=f"{uuid4()}.txt",
        column_format=ClinVarFormat.FULL,
        entry_count=1,
    )


VARIANT = ParsedVariant("chr1", 100, None, "A", "G", None, None, 0.5, {"AF": "0.5"})


async def test_vcf_add_assigns_ids_and_timestamp(
    vcf_repository: InMemoryVcfFileRepository,
) -> None:
    vcf_file = await vcf_repository.add(new_vcf_file(), [VARIANT, VARIANT])

    variants = await vcf_repository.list_variants(vcf_file.vcf_file_id, 10, 0)
    assert vcf_file.uploaded_at.tzinfo is not None
    assert [v.variant_id for v in variants] == [1, 2]


async def test_vcf_get_is_scoped_to_project(vcf_repository: InMemoryVcfFileRepository) -> None:
    vcf_file = await vcf_repository.add(new_vcf_file(), [])

    assert await vcf_repository.get(uuid4(), vcf_file.vcf_file_id) is None


async def test_vcf_delete_removes_file_and_variants(
    vcf_repository: InMemoryVcfFileRepository,
) -> None:
    vcf_file = await vcf_repository.add(new_vcf_file(), [VARIANT])

    await vcf_repository.delete(vcf_file)

    assert await vcf_repository.list_for_project(vcf_file.project_id) == []
    assert await vcf_repository.list_variants(vcf_file.vcf_file_id, 10, 0) == []


async def test_annotation_get_is_scoped_to_project(
    annotation_repository: InMemoryAnnotationFileRepository,
) -> None:
    annotation_file = await annotation_repository.add(new_annotation_file())

    assert await annotation_repository.get(uuid4(), annotation_file.annotation_file_id) is None
    assert (
        await annotation_repository.get(
            annotation_file.project_id, annotation_file.annotation_file_id
        )
        is annotation_file
    )


async def test_annotation_delete(annotation_repository: InMemoryAnnotationFileRepository) -> None:
    annotation_file = await annotation_repository.add(new_annotation_file())

    await annotation_repository.delete(annotation_file)

    assert await annotation_repository.list_for_project(annotation_file.project_id) == []
