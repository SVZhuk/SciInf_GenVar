"""Import every model here, so importing Base from this package registers all tables."""

from app.db.base import Base
from app.models.annotation_file import AnnotationFileModel
from app.models.project import ProjectModel
from app.models.vcf_file import VariantModel, VcfFileModel

__all__ = ["AnnotationFileModel", "Base", "ProjectModel", "VariantModel", "VcfFileModel"]
