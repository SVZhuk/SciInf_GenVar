from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.project_file import ProjectFileRead


class VcfFileRead(ProjectFileRead):
    vcf_file_id: UUID
    sample_count: int
    variant_count: int


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
