from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, jobs, sources
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Photo Album Creator API",
    version="0.1.0",
    description="Backend for the AI-powered photo album builder.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(sources.router)
app.include_router(jobs.router)
