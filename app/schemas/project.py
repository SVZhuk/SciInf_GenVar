from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ShortText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
    ),
]


class ProjectCreate(BaseModel):
    name: ShortText
    lead_scientist: ShortText
    description: Annotated[str | None, Field(max_length=2000)] = None


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    created_at: datetime
    completed_at: datetime | None
