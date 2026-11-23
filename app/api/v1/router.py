"""Version prefix: every v1 resource is mounted here."""

from fastapi import APIRouter

from app.api.v1.routes import projects

router = APIRouter(prefix="/api/v1")
router.include_router(projects.router)
