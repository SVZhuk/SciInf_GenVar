from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.parsers.clinvar import ClinVarFormat


class AnnotationFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    annotation_file_id: UUID
    project_id: UUID
    filename: str
    column_format: ClinVarFormat
    entry_count: int
    uploaded_at: datetime
