"""Import every model here, so importing Base from this package registers all tables."""

from app.db.base import Base
from app.models.project import ProjectModel

__all__ = ["Base", "ProjectModel"]
