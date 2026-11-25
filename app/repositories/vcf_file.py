"""Data access for VCF files and their variants (Repository pattern)."""

import logging
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from itertools import batched, count
from typing import Protocol
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import VariantModel, VcfFileModel
from app.parsers.vcf import ParsedVariant

logger = logging.getLogger(__name__)

INSERT_BATCH_SIZE = 5000


class VcfFileRepository(Protocol):
    async def add(
        self, vcf_file: VcfFileModel, variants: Sequence[ParsedVariant]
    ) -> VcfFileModel: ...
    async def list_for_project(self, project_id: UUID) -> list[VcfFileModel]: ...
    async def get(self, project_id: UUID, vcf_file_id: UUID) -> VcfFileModel | None: ...
    async def list_variants(
        self, vcf_file_id: UUID, limit: int, offset: int
    ) -> list[VariantModel]: ...
    async def delete(self, vcf_file: VcfFileModel) -> None: ...


class SqlAlchemyVcfFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, vcf_file: VcfFileModel, variants: Sequence[ParsedVariant]) -> VcfFileModel:
        self._session.add(vcf_file)
        await self._session.flush()
        for batch in batched(variants, INSERT_BATCH_SIZE, strict=False):
            rows = [{"vcf_file_id": vcf_file.vcf_file_id, **asdict(v)} for v in batch]
            await self._session.execute(insert(VariantModel), rows)
            logger.debug("Inserted %d variant rows vcf_file_id=%s", len(rows), vcf_file.vcf_file_id)
        return vcf_file

    async def list_for_project(self, project_id: UUID) -> list[VcfFileModel]:
        result = await self._session.scalars(
            select(VcfFileModel)
            .where(VcfFileModel.project_id == project_id)
            .order_by(VcfFileModel.uploaded_at, VcfFileModel.vcf_file_id)
        )
        return list(result)

    async def get(self, project_id: UUID, vcf_file_id: UUID) -> VcfFileModel | None:
        return await self._session.scalar(
            select(VcfFileModel).where(
                VcfFileModel.vcf_file_id == vcf_file_id, VcfFileModel.project_id == project_id
            )
        )

    async def list_variants(self, vcf_file_id: UUID, limit: int, offset: int) -> list[VariantModel]:
        result = await self._session.scalars(
            select(VariantModel)
            .where(VariantModel.vcf_file_id == vcf_file_id)
            .order_by(VariantModel.variant_id)
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def delete(self, vcf_file: VcfFileModel) -> None:
        await self._session.delete(vcf_file)  # variants go with it: ON DELETE CASCADE
        await self._session.flush()
        logger.debug("Deleted vcf_file row vcf_file_id=%s", vcf_file.vcf_file_id)


class InMemoryVcfFileRepository:
    """Files indexed by project then id, variants by file id: lookups and deletes are O(1)."""

    def __init__(self) -> None:
        self._files: dict[UUID, dict[UUID, VcfFileModel]] = {}
        self._variants: dict[UUID, list[VariantModel]] = {}
        self._variant_ids = count(1)

    async def add(self, vcf_file: VcfFileModel, variants: Sequence[ParsedVariant]) -> VcfFileModel:
        vcf_file.uploaded_at = datetime.now(UTC)
        self._files.setdefault(vcf_file.project_id, {})[vcf_file.vcf_file_id] = vcf_file
        self._variants[vcf_file.vcf_file_id] = [
            VariantModel(
                variant_id=next(self._variant_ids), vcf_file_id=vcf_file.vcf_file_id, **asdict(v)
            )
            for v in variants
        ]
        return vcf_file

    async def list_for_project(self, project_id: UUID) -> list[VcfFileModel]:
        return list(self._files.get(project_id, {}).values())

    async def get(self, project_id: UUID, vcf_file_id: UUID) -> VcfFileModel | None:
        return self._files.get(project_id, {}).get(vcf_file_id)

    async def list_variants(self, vcf_file_id: UUID, limit: int, offset: int) -> list[VariantModel]:
        return self._variants.get(vcf_file_id, [])[offset : offset + limit]

    async def delete(self, vcf_file: VcfFileModel) -> None:
        del self._files[vcf_file.project_id][vcf_file.vcf_file_id]
        del self._variants[vcf_file.vcf_file_id]
