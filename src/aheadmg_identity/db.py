from urllib.parse import quote_plus

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker


class Base(DeclarativeBase):
    """SQLAlchemy declarative base shared by every model in the platform.

    The identity models live in this package and are bound to this Base;
    consuming apps declare their own app-specific models against the same
    Base, so `Base.metadata.create_all` creates the union — identity
    tables plus the app's own."""

    pass


class _DB:
    """Tiny container so other modules can do `from aheadmg_identity import db`
    and reach a process-wide scoped session set up by `init_db(app)`."""

    engine = None
    Session: scoped_session | None = None


db = _DB()


# Logical schemas the platform DB is partitioned into. `identity` holds the
# shared tenant/user/role tables; `hub` and `flow` hold each app's own
# data. All apps connect to the same DB; the split makes the boundaries
# clear and a future per-app DB split straightforward.
PLATFORM_SCHEMAS = ("identity", "hub", "flow")


def _ensure_schemas(engine) -> None:
    """Create any missing platform schemas. SQLAlchemy's
    `metadata.create_all` only qualifies table names — it doesn't create
    the schemas themselves, so we do so explicitly."""
    with engine.begin() as conn:
        for schema in PLATFORM_SCHEMAS:
            conn.exec_driver_sql(
                f"IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = '{schema}') "
                f"EXEC('CREATE SCHEMA [{schema}]')"
            )


def init_db(app: Flask) -> None:
    """Wire SQLAlchemy to this Flask app's SQL connection, ensure platform
    schemas exist, and run create_all so any models registered against the
    shared Base (identity + app-specific) are created."""
    conn = app.config["SQL_CONNECTION_STRING"]
    url = f"mssql+pyodbc:///?odbc_connect={quote_plus(conn)}"
    db.engine = create_engine(url, pool_pre_ping=True, future=True)
    db.Session = scoped_session(sessionmaker(bind=db.engine, future=True))

    # Importing models registers them on Base.metadata.
    from . import models  # noqa: F401

    _ensure_schemas(db.engine)
    Base.metadata.create_all(db.engine)

    @app.teardown_appcontext
    def _remove_session(exc):  # noqa: ANN001
        if db.Session is not None:
            db.Session.remove()
