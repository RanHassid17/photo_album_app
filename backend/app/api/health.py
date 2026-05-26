from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    service: str
    version: str


@router.get("/healthz", response_model=Health)
def healthz() -> Health:
    return Health(status="ok", service="album-backend", version="0.1.0")
