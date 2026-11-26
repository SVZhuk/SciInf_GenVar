from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProjectFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    filename: str
    uploaded_at: datetime
