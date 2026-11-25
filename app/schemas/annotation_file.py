from uuid import UUID

from app.parsers.clinvar import ClinVarFormat
from app.schemas.project_file import ProjectFileRead


class AnnotationFileRead(ProjectFileRead):
    annotation_file_id: UUID
    column_format: ClinVarFormat
    entry_count: int
