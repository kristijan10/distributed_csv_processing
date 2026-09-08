import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.core.db import Base, sync_sqlite_schema
from app.models.job import Job  # noqa: F401  (registers the table with Base.metadata)


@pytest.fixture
def sqlite_engine():
    with tempfile.TemporaryDirectory(prefix="thesis_schema_sync_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "stale.db"
        yield create_engine(f"sqlite:///{db_path}")


def _table_columns(engine, table_name: str) -> set[str]:
    with engine.begin() as conn:
        return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})")}


def test_adds_missing_nullable_columns(sqlite_engine):
    # Simulate a stale on-disk table from before finished_at/worker_snapshot existed.
    with sqlite_engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE jobs (
                id VARCHAR PRIMARY KEY,
                status VARCHAR NOT NULL,
                worker_count INTEGER NOT NULL,
                row_count INTEGER NOT NULL,
                original_filename VARCHAR NOT NULL,
                input_path VARCHAR NOT NULL,
                result_path VARCHAR,
                error_message VARCHAR,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )

    assert "finished_at" not in _table_columns(sqlite_engine, "jobs")
    assert "worker_snapshot" not in _table_columns(sqlite_engine, "jobs")
    assert "started_at" not in _table_columns(sqlite_engine, "jobs")

    sync_sqlite_schema(sqlite_engine, Base.metadata)

    columns = _table_columns(sqlite_engine, "jobs")
    assert "finished_at" in columns
    assert "worker_snapshot" in columns
    assert "started_at" in columns


def test_noop_when_all_columns_present(sqlite_engine):
    Base.metadata.create_all(bind=sqlite_engine)
    before = _table_columns(sqlite_engine, "jobs")

    sync_sqlite_schema(sqlite_engine, Base.metadata)

    assert _table_columns(sqlite_engine, "jobs") == before
