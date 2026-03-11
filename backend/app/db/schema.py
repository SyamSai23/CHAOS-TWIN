from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.config import ENABLE_LEGACY_STARTUP_SCHEMA_PATCHES
from app.db.base import Base
from app.db.session import engine

logger = logging.getLogger(__name__)

_LEGACY_SCAN_PATCHES = {
    "key_files": "ALTER TABLE scans ADD COLUMN IF NOT EXISTS key_files JSON NOT NULL DEFAULT '[]'::json",
    "top_level_dirs": "ALTER TABLE scans ADD COLUMN IF NOT EXISTS top_level_dirs JSON NOT NULL DEFAULT '[]'::json",
    "extension_counts": "ALTER TABLE scans ADD COLUMN IF NOT EXISTS extension_counts JSON NOT NULL DEFAULT '{}'::json",
    "project_type": "ALTER TABLE scans ADD COLUMN IF NOT EXISTS project_type VARCHAR NOT NULL DEFAULT 'script/data project'",
    "entry_points": "ALTER TABLE scans ADD COLUMN IF NOT EXISTS entry_points JSON NOT NULL DEFAULT '[]'::json",
}

_LEGACY_SEQUENCE_PATCHES = {
    "route_id": "ALTER TABLE sequence_diagrams ADD COLUMN IF NOT EXISTS route_id VARCHAR",
}

_LEGACY_SEQUENCE_INDEX = """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_project_route
    ON sequence_diagrams (project_id, route_id)
    WHERE route_id IS NOT NULL
"""


def initialize_schema() -> None:
    Base.metadata.create_all(bind=engine)

    if ENABLE_LEGACY_STARTUP_SCHEMA_PATCHES:
        apply_legacy_schema_patches(engine)


def apply_legacy_schema_patches(db_engine: Engine) -> None:
    inspector = inspect(db_engine)
    statements: list[str] = []
    table_names = set(inspector.get_table_names())

    if "scans" in table_names:
        scan_columns = {column["name"] for column in inspector.get_columns("scans")}
        for column_name, statement in _LEGACY_SCAN_PATCHES.items():
            if column_name not in scan_columns:
                statements.append(statement)

    if "sequence_diagrams" in table_names:
        sequence_columns = {
            column["name"] for column in inspector.get_columns("sequence_diagrams")
        }
        for column_name, statement in _LEGACY_SEQUENCE_PATCHES.items():
            if column_name not in sequence_columns:
                statements.append(statement)

        index_names = {
            index["name"] for index in inspector.get_indexes("sequence_diagrams")
        }
        if "uq_project_route" not in index_names:
            statements.append(_LEGACY_SEQUENCE_INDEX)

    if not statements:
        return

    logger.warning(
        "Applying legacy startup schema patches. Run Alembic migrations and disable "
        "ENABLE_LEGACY_STARTUP_SCHEMA_PATCHES once the database is upgraded."
    )

    with db_engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))