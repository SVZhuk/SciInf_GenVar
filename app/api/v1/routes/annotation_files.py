"""/projects/{project_id}/annotation resource: thin async handlers, HTTP concerns only."""

from uuid import UUID

from fastapi import APIRouter, UploadFile, status

from app.api.deps import AnnotationFileServiceDep, MaxUploadBytesDep
from app.api.uploads import read_upload
from app.schemas.annotation_file import AnnotationFileRead

router = APIRouter(prefix="/projects/{project_id}/annotation", tags=["annotation files"])


@router.post("/", status_code=status.HTTP_201_CREATED)
async def upload_annotation_file(
    project_id: UUID,
    file: UploadFile,
    service: AnnotationFileServiceDep,
    max_bytes: MaxUploadBytesDep,
) -> AnnotationFileRead:
    data = await read_upload(file, max_bytes)
    annotation_file = await service.upload(project_id, file.filename or "", data)
    return AnnotationFileRead.model_validate(annotation_file)


@router.get("/")
async def list_annotation_files(
    project_id: UUID, service: AnnotationFileServiceDep
) -> list[AnnotationFileRead]:
    annotation_files = await service.list_annotation_files(project_id)
    return [AnnotationFileRead.model_validate(item) for item in annotation_files]


@router.delete("/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_annotation_file(
    project_id: UUID, annotation_id: UUID, service: AnnotationFileServiceDep
) -> None:
    await service.delete_annotation_file(project_id, annotation_id)
