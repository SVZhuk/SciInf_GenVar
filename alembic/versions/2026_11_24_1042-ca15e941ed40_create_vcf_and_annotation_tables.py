"""create vcf and annotation tables

Revision ID: ca15e941ed40
Revises: 79befec44259
Create Date: 2026-11-24 10:42:54.522774

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ca15e941ed40"
down_revision: str | Sequence[str] | None = "79befec44259"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "annotation_files",
        sa.Column("annotation_file_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("s3_key", sa.String(length=1024), nullable=False),
        sa.Column("column_format", sa.String(length=20), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
            name=op.f("fk_annotation_files_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("annotation_file_id", name=op.f("pk_annotation_files")),
        sa.UniqueConstraint("s3_key", name=op.f("uq_annotation_files_s3_key")),
    )
    op.create_index(
        op.f("ix_annotation_files_project_id"), "annotation_files", ["project_id"], unique=False
    )
    op.create_table(
        "vcf_files",
        sa.Column("vcf_file_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("s3_key", sa.String(length=1024), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("variant_count", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
            name=op.f("fk_vcf_files_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("vcf_file_id", name=op.f("pk_vcf_files")),
        sa.UniqueConstraint("s3_key", name=op.f("uq_vcf_files_s3_key")),
    )
    op.create_index(op.f("ix_vcf_files_project_id"), "vcf_files", ["project_id"], unique=False)
    op.create_table(
        "variants",
        sa.Column("variant_id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("vcf_file_id", sa.Uuid(), nullable=False),
        sa.Column("chrom", sa.Text(), nullable=False),
        sa.Column("pos", sa.BigInteger(), nullable=False),
        sa.Column("vcf_id", sa.Text(), nullable=True),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("alt", sa.Text(), nullable=False),
        sa.Column("qual", sa.Double(), nullable=True),
        sa.Column("filter", sa.Text(), nullable=True),
        sa.Column("af", sa.Double(), nullable=True),
        sa.Column("info", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["vcf_file_id"],
            ["vcf_files.vcf_file_id"],
            name=op.f("fk_variants_vcf_file_id_vcf_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("variant_id", name=op.f("pk_variants")),
    )
    op.create_index("ix_variants_chrom_pos", "variants", ["chrom", "pos"], unique=False)
    op.create_index(
        "ix_variants_vcf_file_id_variant_id",
        "variants",
        ["vcf_file_id", "variant_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_variants_vcf_file_id_variant_id", table_name="variants")
    op.drop_index("ix_variants_chrom_pos", table_name="variants")
    op.drop_table("variants")
    op.drop_index(op.f("ix_vcf_files_project_id"), table_name="vcf_files")
    op.drop_table("vcf_files")
    op.drop_index(op.f("ix_annotation_files_project_id"), table_name="annotation_files")
    op.drop_table("annotation_files")
