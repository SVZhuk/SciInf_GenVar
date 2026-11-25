from uuid import UUID, uuid4

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.db.base import Base
from app.models.project_file import ProjectFileMixin


class AnnotationFileModel(ProjectFileMixin, Base):
    __tablename__ = "annotation_files"

    annotation_file_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    file_id: Mapped[UUID] = synonym("annotation_file_id")
    column_format: Mapped[str] = mapped_column(String(20))
    entry_count: Mapped[int]
