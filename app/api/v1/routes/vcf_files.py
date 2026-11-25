"""/projects/{project_id}/vcf resource: thin async handlers, HTTP concerns only."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, UploadFile, status

from app.api.deps import MaxUploadBytesDep, VcfFileServiceDep
from app.api.uploads import read_upload
from app.core.exceptions import (
    InvalidFileFormatError,
    InvalidFilenameError,
    ProjectNotFoundError,
    VcfFileNotFoundError,
)
from app.schemas.vcf_file import VariantRead, VcfFileDetail, VcfFileRead

router = APIRouter(prefix="/projects/{project_id}/vcf", tags=["vcf files"])


@router.post("/", response_model=VcfFileRead, status_code=status.HTTP_201_CREATED)
async def upload_vcf_file(
    project_id: UUID,
    file: UploadFile,
    service: VcfFileServiceDep,
    max_bytes: MaxUploadBytesDep,
    request: Request,
    response: Response,
) -> VcfFileRead:
    data = await read_upload(file, max_bytes)
    try:
        vcf_file = await service.upload(project_id, file.filename or "", data)
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except (InvalidFilenameError, InvalidFileFormatError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    response.headers["Location"] = str(
        request.url_for("get_vcf_file", project_id=project_id, vcf_id=vcf_file.vcf_file_id)
    )
    return VcfFileRead.model_validate(vcf_file)


@router.get("/", response_model=list[VcfFileRead])
async def list_vcf_files(project_id: UUID, service: VcfFileServiceDep) -> list[VcfFileRead]:
    try:
        vcf_files = await service.list_vcf_files(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    return [VcfFileRead.model_validate(vcf_file) for vcf_file in vcf_files]


@router.get("/{vcf_id}", response_model=VcfFileDetail)
async def get_vcf_file(
    project_id: UUID,
    vcf_id: UUID,
    service: VcfFileServiceDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VcfFileDetail:
    try:
        vcf_file, variants = await service.get_vcf_file(project_id, vcf_id, limit, offset)
    except (ProjectNotFoundError, VcfFileNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    return VcfFileDetail(
        **VcfFileRead.model_validate(vcf_file).model_dump(),
        variants=[VariantRead.model_validate(variant) for variant in variants],
    )


@router.delete("/{vcf_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vcf_file(project_id: UUID, vcf_id: UUID, service: VcfFileServiceDep) -> None:
    try:
        await service.delete_vcf_file(project_id, vcf_id)
    except (ProjectNotFoundError, VcfFileNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
