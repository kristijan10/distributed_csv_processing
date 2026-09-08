import asyncio
import threading
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.jobs import router as jobs_router
from app.api.metrics import router as metrics_router
from app.core.config import get_settings
from app.core.db import Base, engine, sync_sqlite_schema
from app.k8s.watcher import run_job_watcher
from app.models import job as job_model  # noqa: F401  (registers the table with Base.metadata)

settings = get_settings()

Base.metadata.create_all(bind=engine)
sync_sqlite_schema(engine, Base.metadata)


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = threading.Event()
    watcher_task = asyncio.create_task(run_job_watcher(settings, stop_event))
    try:
        yield
    finally:
        stop_event.set()
        watcher_task.cancel()
        with suppress(asyncio.CancelledError):
            await watcher_task


app = FastAPI(title=settings.app_name, lifespan=lifespan)

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
app.include_router(metrics_router)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
