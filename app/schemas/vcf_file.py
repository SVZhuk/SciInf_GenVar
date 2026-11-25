from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class VcfFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vcf_file_id: UUID
    project_id: UUID
    filename: str
    sample_count: int
    variant_count: int
    uploaded_at: datetime


class VariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variant_id: int
    chrom: str
    pos: int
    vcf_id: str | None
    ref: str
    alt: str
    qual: float | None
    filter: str | None
    af: float | None
    info: dict[str, str | bool]


class VcfFileDetail(VcfFileRead):
    variants: list[VariantRead]
