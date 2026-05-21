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


# Lightweight column-level migrations.
#
# `create_all` only creates tables that don't exist — it never adds new
# columns to existing tables. For each new column we add to an existing
# model, list it here and `_ensure_columns` will add it idempotently on
# startup (SQL Server's `sys.columns` lookup, then a plain ALTER TABLE).
#
# When we move to a real migration tool (Alembic) this list goes away;
# until then it lets the platform self-upgrade without manual SQL.
_NEW_COLUMNS: list[tuple[str, str, str, str]] = [
    # (schema, table, column, sql_type)
    ("identity", "app_catalog", "feature_icon", "NVARCHAR(500) NULL"),
]


def _ensure_columns(engine) -> None:
    with engine.begin() as conn:
        for schema, table, column, sql_type in _NEW_COLUMNS:
            conn.exec_driver_sql(
                f"IF NOT EXISTS ("
                f"  SELECT 1 FROM sys.columns "
                f"  WHERE Name = N'{column}' "
                f"    AND Object_ID = Object_ID(N'{schema}.{table}')"
                f") ALTER TABLE [{schema}].[{table}] ADD [{column}] {sql_type}"
            )


def _migrate_oid_to_filtered_unique(engine) -> None:
    """Replace the SQLAlchemy-generated UNIQUE constraint on
    identity.user.oid with a filtered unique index that allows multiple
    NULL rows.

    SQL Server's default UNIQUE constraint enforces "at most one NULL"
    in the column. Every invited user starts with oid=NULL until they
    first sign in, so the second pending invite fails on the constraint
    and the request 500s. A filtered unique index (UNIQUE … WHERE oid
    IS NOT NULL) gives the same "one user per oid" guarantee on real
    oids without blocking pending invites.

    Idempotent: drops any non-filtered unique index on oid (created by
    older create_all runs when the model had unique=True) and creates
    the filtered index if missing. New deployments hit the create-only
    branch.
    """
    with engine.begin() as conn:
        # Drop the legacy non-filtered unique index/constraint on oid,
        # if one exists. The name was assigned by SQLAlchemy and varies,
        # so we look it up via sys.indexes.
        conn.exec_driver_sql(
            """
            DECLARE @oid_idx sysname = (
              SELECT TOP 1 i.name
              FROM sys.indexes i
              JOIN sys.index_columns ic
                ON ic.object_id = i.object_id AND ic.index_id = i.index_id
              JOIN sys.columns c
                ON c.object_id = ic.object_id AND c.column_id = ic.column_id
              WHERE i.object_id = OBJECT_ID(N'identity.[user]')
                AND c.name = 'oid'
                AND i.is_unique = 1
                AND i.has_filter = 0
                AND i.is_primary_key = 0
            );
            IF @oid_idx IS NOT NULL
              EXEC('DROP INDEX [' + @oid_idx + '] ON identity.[user]')
            """
        )
        # Create the filtered unique index if it isn't there yet.
        conn.exec_driver_sql(
            """
            IF NOT EXISTS (
              SELECT 1 FROM sys.indexes
              WHERE object_id = OBJECT_ID(N'identity.[user]')
                AND name = 'ix_user_oid_unique_notnull'
            )
            CREATE UNIQUE NONCLUSTERED INDEX ix_user_oid_unique_notnull
              ON identity.[user](oid)
              WHERE oid IS NOT NULL
            """
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
    _ensure_columns(db.engine)
    _migrate_oid_to_filtered_unique(db.engine)

    @app.teardown_appcontext
    def _remove_session(exc):  # noqa: ANN001
        if db.Session is not None:
            db.Session.remove()
