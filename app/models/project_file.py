from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column


class ProjectFileMixin:
    """Columns every uploaded file shares; each model maps file_id to its own primary key."""

    if TYPE_CHECKING:
        file_id: Mapped[UUID]

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.project_id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    s3_key: Mapped[str] = mapped_column(String(1024), unique=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
