from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.jobs import router as jobs_router
from app.core.config import get_settings
from app.core.db import Base, engine
from app.models import job as job_model  # noqa: F401  (registers the table with Base.metadata)

settings = get_settings()

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    # Vite picks the next free port when its default is taken, so match any
    # localhost port rather than hardcoding 5173.
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
