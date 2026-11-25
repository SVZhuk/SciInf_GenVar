"""VCF use cases: validate, parse, store the file and its variants, list, read, delete."""

import logging
from uuid import UUID, uuid4

from app.core.exceptions import VcfFileNotFoundError
from app.models import VariantModel, VcfFileModel
from app.parsers.vcf import parse_vcf
from app.repositories.project import ProjectRepository
from app.repositories.vcf_file import VcfFileRepository
from app.services.project_files import parse_upload, require_project
from app.storage.files import FileStorage, object_key

logger = logging.getLogger(__name__)

VCF_EXTENSIONS = (".vcf.gz", ".vcf")


class VcfFileService:
    def __init__(
        self,
        projects: ProjectRepository,
        vcf_files: VcfFileRepository,
        storage: FileStorage,
        max_bytes: int,
    ) -> None:
        self._projects = projects
        self._vcf_files = vcf_files
        self._storage = storage
        self._max_bytes = max_bytes

    async def upload(self, project_id: UUID, filename: str, data: bytes) -> VcfFileModel:
        """Rows are flushed before the file is written, so an S3 failure rolls the rows back.

        A failed commit after a successful write leaves an orphaned object; it is harmless (no row
        points to it) and cheaper to accept than a two-phase commit.
        """
        await require_project(self._projects, project_id)
        extension, parsed = await parse_upload(
            project_id, filename, data, VCF_EXTENSIONS, parse_vcf, self._max_bytes
        )
        vcf_file_id = uuid4()
        vcf_file = VcfFileModel(
            vcf_file_id=vcf_file_id,
            project_id=project_id,
            filename=filename,
            s3_key=object_key(project_id, "vcf", vcf_file_id, extension),
            sample_count=parsed.sample_count,
            variant_count=len(parsed.variants),
        )
        await self._vcf_files.add(vcf_file, parsed.variants)
        await self._storage.put(vcf_file.s3_key, data)
        logger.info(
            "VCF file uploaded vcf_file_id=%s project_id=%s variants=%d samples=%d bytes=%d",
            vcf_file_id,
            project_id,
            vcf_file.variant_count,
            vcf_file.sample_count,
            len(data),
        )
        return vcf_file

    async def list_vcf_files(self, project_id: UUID) -> list[VcfFileModel]:
        await require_project(self._projects, project_id)
        return await self._vcf_files.list_for_project(project_id)

    async def get_vcf_file(
        self, project_id: UUID, vcf_file_id: UUID, limit: int, offset: int
    ) -> tuple[VcfFileModel, list[VariantModel]]:
        vcf_file = await self._require_vcf_file(project_id, vcf_file_id)
        variants = await self._vcf_files.list_variants(vcf_file_id, limit, offset)
        return vcf_file, variants

    async def delete_vcf_file(self, project_id: UUID, vcf_file_id: UUID) -> None:
        vcf_file = await self._require_vcf_file(project_id, vcf_file_id)
        await self._vcf_files.delete(vcf_file)
        await self._storage.delete(vcf_file.s3_key)
        logger.info("VCF file deleted vcf_file_id=%s project_id=%s", vcf_file_id, project_id)

    async def _require_vcf_file(self, project_id: UUID, vcf_file_id: UUID) -> VcfFileModel:
        await require_project(self._projects, project_id)
        vcf_file = await self._vcf_files.get(project_id, vcf_file_id)
        if vcf_file is None:
            logger.warning(
                "VCF file not found vcf_file_id=%s project_id=%s", vcf_file_id, project_id
            )
            raise VcfFileNotFoundError(vcf_file_id)
        return vcf_file
