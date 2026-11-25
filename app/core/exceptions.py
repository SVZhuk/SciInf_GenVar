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


class VcfFileNotFoundError(Exception):
    def __init__(self, vcf_file_id: UUID) -> None:
        super().__init__(f"VCF file {vcf_file_id} not found")
        self.vcf_file_id = vcf_file_id


class AnnotationFileNotFoundError(Exception):
    def __init__(self, annotation_file_id: UUID) -> None:
        super().__init__(f"Annotation file {annotation_file_id} not found")
        self.annotation_file_id = annotation_file_id


class InvalidFilenameError(Exception):
    def __init__(self, allowed: tuple[str, ...], max_length: int) -> None:
        super().__init__(
            f"Filename must end with one of {', '.join(allowed)} "
            f"and be at most {max_length} characters"
        )


class FileStorageError(Exception):
    """The file store refused an operation; raised by storage, never mapped to a 4xx."""


class InvalidFileFormatError(Exception):
    """File content is invalid; the message names the line and the rule, never the content."""

    def __init__(self, reason: str, line_no: int | None = None) -> None:
        where = f"line {line_no}: " if line_no is not None else ""
        super().__init__(f"Invalid file: {where}{reason}")
        self.reason = reason
        self.line_no = line_no
