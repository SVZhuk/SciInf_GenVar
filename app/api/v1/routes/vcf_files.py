"""/projects/{project_id}/vcf resource: thin async handlers, HTTP concerns only."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from app.api.deps import UploadDep, VcfFileServiceDep
from app.schemas.vcf_file import VariantRead, VcfFileDetail, VcfFileRead

router = APIRouter(prefix="/projects/{project_id}/vcf", tags=["vcf files"])


@router.post("/", status_code=status.HTTP_201_CREATED)
async def upload_vcf_file(
    project_id: UUID,
    upload: UploadDep,
    service: VcfFileServiceDep,
    request: Request,
    response: Response,
) -> VcfFileRead:
    vcf_file = await service.upload(project_id, upload.filename, upload.data)
    response.headers["Location"] = str(
        request.url_for("get_vcf_file", project_id=project_id, vcf_id=vcf_file.vcf_file_id)
    )
    return VcfFileRead.model_validate(vcf_file)


@router.get("/")
async def list_vcf_files(project_id: UUID, service: VcfFileServiceDep) -> list[VcfFileRead]:
    return [VcfFileRead.model_validate(item) for item in await service.list_vcf_files(project_id)]


@router.get("/{vcf_id}")
async def get_vcf_file(
    project_id: UUID,
    vcf_id: UUID,
    service: VcfFileServiceDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VcfFileDetail:
    vcf_file, variants = await service.get_vcf_file(project_id, vcf_id, limit, offset)
    return VcfFileDetail(
        **VcfFileRead.model_validate(vcf_file).model_dump(),
        variants=[VariantRead.model_validate(variant) for variant in variants],
    )


@router.delete("/{vcf_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vcf_file(project_id: UUID, vcf_id: UUID, service: VcfFileServiceDep) -> None:
    await service.delete_vcf_file(project_id, vcf_id)
