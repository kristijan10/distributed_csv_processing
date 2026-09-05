import os
import shutil
import tempfile
from pathlib import Path

# Point the app at an isolated temp storage dir + SQLite DB before app.main
# (and therefore app.core.db's module-level engine) gets imported anywhere.
# pytest loads this conftest.py before collecting any test module, so this
# is guaranteed to run first.
_tmp_dir = Path(tempfile.mkdtemp(prefix="thesis_backend_tests_"))
os.environ["STORAGE_DIR"] = str(_tmp_dir / "storage")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_dir / 'test.db'}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.job import Job  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _isolate_job_state(settings):
    """The client/DB/storage dir are shared across the whole test session for
    simplicity, so a job left Running by one test would otherwise make an
    unrelated test's reconcile_status hit a real (absent) Kubernetes cluster.
    Wipe all job rows and on-disk job directories after every test.
    """
    yield
    db = SessionLocal()
    try:
        db.query(Job).delete()
        db.commit()
    finally:
        db.close()
    jobs_dir = Path(settings.storage_dir) / "jobs"
    shutil.rmtree(jobs_dir, ignore_errors=True)


def make_csv(path: Path, header: list[str], rows: list[list]) -> Path:
    import csv

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return path
