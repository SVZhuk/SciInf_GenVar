"""Domain errors: raised by services and repositories, mapped to HTTP in app/api/errors.py."""

from uuid import UUID


class DomainError(Exception):
    """Base of every error a client can cause; its message is safe to return."""


class NotFoundError(DomainError):
    kind = "Item"

    def __init__(self, item_id: UUID) -> None:
        super().__init__(f"{self.kind} {item_id} not found")
        self.item_id = item_id


class ConflictError(DomainError):
    pass


class InvalidInputError(DomainError):
    pass


class ProjectNotFoundError(NotFoundError):
    kind = "Project"


class VcfFileNotFoundError(NotFoundError):
    kind = "VCF file"


class AnnotationFileNotFoundError(NotFoundError):
    kind = "Annotation file"


class ProjectNameConflictError(ConflictError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Project name {name!r} already exists")


class InvalidFilenameError(InvalidInputError):
    def __init__(self, allowed: tuple[str, ...], max_length: int) -> None:
        super().__init__(
            f"Filename must end with one of {', '.join(allowed)} "
            f"and be at most {max_length} characters"
        )


class InvalidFileFormatError(InvalidInputError):
    """File content is invalid; the message names the line and the rule, never the content."""

    def __init__(self, reason: str, line_no: int | None = None) -> None:
        where = f"line {line_no}: " if line_no is not None else ""
        super().__init__(f"Invalid file: {where}{reason}")
        self.reason = reason
        self.line_no = line_no


class FileStorageError(Exception):
    """The file store refused an operation; not a client error, so it becomes a 500."""
