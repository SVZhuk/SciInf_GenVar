"""Domain errors: raised by services and repositories, mapped to HTTP status codes in routes."""

from uuid import UUID


class ProjectNotFoundError(Exception):
    def __init__(self, project_id: UUID) -> None:
        super().__init__(f"Project {project_id} not found")
        self.project_id = project_id


class ProjectNameConflictError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Project name {name!r} already exists")
        self.name = name
