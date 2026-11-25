from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, Identity, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.db.base import Base
from app.models.project_file import ProjectFileMixin


class VcfFileModel(ProjectFileMixin, Base):
    __tablename__ = "vcf_files"

    vcf_file_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    file_id: Mapped[UUID] = synonym("vcf_file_id")
    sample_count: Mapped[int]
    variant_count: Mapped[int]


class VariantModel(Base):
    __tablename__ = "variants"
    # No unique (vcf_file_id, chrom, pos, ref, alt): a B-tree entry is limited to about 2.7 KB
    # and long indel alleles exceed it. The parser rejects duplicates instead.
    __table_args__ = (
        Index("ix_variants_vcf_file_id_variant_id", "vcf_file_id", "variant_id"),
        Index("ix_variants_chrom_pos", "chrom", "pos"),
    )

    variant_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    vcf_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("vcf_files.vcf_file_id", ondelete="CASCADE")
    )
    chrom: Mapped[str] = mapped_column(Text)
    pos: Mapped[int] = mapped_column(BigInteger)
    vcf_id: Mapped[str | None] = mapped_column(Text)
    ref: Mapped[str] = mapped_column(Text)
    alt: Mapped[str] = mapped_column(Text)
    qual: Mapped[float | None]
    filter: Mapped[str | None] = mapped_column(Text)
    af: Mapped[float | None]
    info: Mapped[dict[str, Any]] = mapped_column(JSONB)
