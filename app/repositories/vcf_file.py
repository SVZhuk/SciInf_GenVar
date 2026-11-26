"""Data access for VCF files and their variants (Repository pattern)."""

import logging
from collections.abc import Sequence
from dataclasses import asdict
from itertools import batched, count
from typing import Protocol
from uuid import UUID

from sqlalchemy import insert, select

from app.models import VariantModel, VcfFileModel
from app.parsers.vcf import ParsedVariant
from app.repositories.project_file import (
    InMemoryProjectFileRepository,
    ProjectFileRepository,
    SqlAlchemyProjectFileRepository,
)

logger = logging.getLogger(__name__)

INSERT_BATCH_SIZE = 5000


class VcfFileRepository(ProjectFileRepository[VcfFileModel], Protocol):
    async def add(
        self, vcf_file: VcfFileModel, variants: Sequence[ParsedVariant]
    ) -> VcfFileModel: ...
    async def list_variants(
        self, vcf_file_id: UUID, limit: int, offset: int
    ) -> list[VariantModel]: ...


class SqlAlchemyVcfFileRepository(SqlAlchemyProjectFileRepository[VcfFileModel]):
    """Deleting a file row deletes its variants too (ON DELETE CASCADE)."""

    model = VcfFileModel

    async def add(self, vcf_file: VcfFileModel, variants: Sequence[ParsedVariant]) -> VcfFileModel:
        await self._insert(vcf_file)
        for batch in batched(variants, INSERT_BATCH_SIZE, strict=False):
            rows = [{"vcf_file_id": vcf_file.vcf_file_id, **asdict(v)} for v in batch]
            await self._session.execute(insert(VariantModel), rows)
            logger.debug("Inserted %d variant rows vcf_file_id=%s", len(rows), vcf_file.vcf_file_id)
        return vcf_file

    async def list_variants(self, vcf_file_id: UUID, limit: int, offset: int) -> list[VariantModel]:
        result = await self._session.scalars(
            select(VariantModel)
            .where(VariantModel.vcf_file_id == vcf_file_id)
            .order_by(VariantModel.variant_id)
            .limit(limit)
            .offset(offset)
        )
        return list(result)


class InMemoryVcfFileRepository(InMemoryProjectFileRepository[VcfFileModel]):
    """Variants indexed by file id; ids come from a counter like the database identity."""

    def __init__(self) -> None:
        super().__init__()
        self._variants: dict[UUID, list[VariantModel]] = {}
        self._variant_ids = count(1)

    async def add(self, vcf_file: VcfFileModel, variants: Sequence[ParsedVariant]) -> VcfFileModel:
        self._insert(vcf_file)
        self._variants[vcf_file.vcf_file_id] = [
            VariantModel(
                variant_id=next(self._variant_ids), vcf_file_id=vcf_file.vcf_file_id, **asdict(v)
            )
            for v in variants
        ]
        return vcf_file

    async def list_variants(self, vcf_file_id: UUID, limit: int, offset: int) -> list[VariantModel]:
        return self._variants.get(vcf_file_id, [])[offset : offset + limit]

    async def delete(self, item: VcfFileModel) -> None:
        await super().delete(item)
        del self._variants[item.vcf_file_id]
