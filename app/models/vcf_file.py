from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VcfFileModel(Base):
    __tablename__ = "vcf_files"

    vcf_file_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.project_id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    s3_key: Mapped[str] = mapped_column(String(1024), unique=True)
    sample_count: Mapped[int]
    variant_count: Mapped[int]
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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
