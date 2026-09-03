from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.schemas.job import JobRead
from app.services import job_service
from app.services.job_service import JobValidationError

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", response_model=JobRead, status_code=201)
def create_job(
    file: UploadFile = File(...),
    worker_count: int = Form(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobRead:
    try:
        job = job_service.create_job(db, settings, file, worker_count)
    except JobValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return job


@router.get("", response_model=list[JobRead])
def list_jobs(db: Session = Depends(get_db)) -> list[JobRead]:
    return job_service.list_jobs(db)


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobRead:
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/run", response_model=JobRead)
def run_job(
    job_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobRead:
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        job = job_service.run_job(db, settings, job)
    except JobValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job
