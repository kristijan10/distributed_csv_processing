from collections.abc import Generator

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def sync_sqlite_schema(engine: Engine, metadata: MetaData) -> None:
    """Add columns that exist on the models but not yet on disk.

    create_all() only creates missing tables, not missing columns on tables
    that already exist on disk - this covers the gap for SQLite, where a
    column added to a model after a developer's local app.db was created
    would otherwise raise sqlite3.OperationalError at request time. Not
    needed for other backends, which get real migrations instead.
    """
    if not engine.url.get_backend_name().startswith("sqlite"):
        return

    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            existing_columns = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table.name})")}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                if not column.nullable and column.server_default is None:
                    raise RuntimeError(
                        f"Cannot auto-migrate {table.name}.{column.name}: it is NOT NULL with no "
                        "server default, so SQLite can't add it to a table that may already have "
                        "rows. Write a manual migration (or delete the local database file) instead."
                    )
                type_sql = column.type.compile(dialect=engine.dialect)
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {type_sql}"
                if column.server_default is not None:
                    ddl += f" DEFAULT {column.server_default.arg}"
                conn.exec_driver_sql(ddl)
