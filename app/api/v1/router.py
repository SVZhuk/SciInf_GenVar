"""Version prefix: every v1 resource router is mounted here."""

from fastapi import APIRouter

from app.api.v1.routes import annotation_files, projects, vcf_files

router = APIRouter(prefix="/api/v1")
router.include_router(projects.router)
router.include_router(vcf_files.router)
router.include_router(annotation_files.router)
