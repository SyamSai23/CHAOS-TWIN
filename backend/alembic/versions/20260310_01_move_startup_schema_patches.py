"""Move startup schema patches into Alembic.

Revision ID: 20260310_01
Revises:
Create Date: 2026-03-10 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260310_01"
down_revision = None
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "scans"):
        if not _has_column(inspector, "scans", "key_files"):
            op.add_column(
                "scans",
                sa.Column(
                    "key_files",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'::json"),
                ),
            )
        if not _has_column(inspector, "scans", "top_level_dirs"):
            op.add_column(
                "scans",
                sa.Column(
                    "top_level_dirs",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'::json"),
                ),
            )
        if not _has_column(inspector, "scans", "extension_counts"):
            op.add_column(
                "scans",
                sa.Column(
                    "extension_counts",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'{}'::json"),
                ),
            )
        if not _has_column(inspector, "scans", "project_type"):
            op.add_column(
                "scans",
                sa.Column(
                    "project_type",
                    sa.String(),
                    nullable=False,
                    server_default=sa.text("'script/data project'"),
                ),
            )
        if not _has_column(inspector, "scans", "entry_points"):
            op.add_column(
                "scans",
                sa.Column(
                    "entry_points",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'::json"),
                ),
            )

    inspector = sa.inspect(bind)

    if _has_table(inspector, "sequence_diagrams"):
        if not _has_column(inspector, "sequence_diagrams", "route_id"):
            op.add_column(
                "sequence_diagrams",
                sa.Column("route_id", sa.String(), nullable=True),
            )
            op.create_index(
                op.f("ix_sequence_diagrams_route_id"),
                "sequence_diagrams",
                ["route_id"],
                unique=False,
            )

        inspector = sa.inspect(bind)
        if not _has_index(inspector, "sequence_diagrams", "uq_project_route"):
            op.create_index(
                "uq_project_route",
                "sequence_diagrams",
                ["project_id", "route_id"],
                unique=True,
                postgresql_where=sa.text("route_id IS NOT NULL"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "sequence_diagrams"):
        if _has_index(inspector, "sequence_diagrams", "uq_project_route"):
            op.drop_index("uq_project_route", table_name="sequence_diagrams")

        inspector = sa.inspect(bind)
        if _has_column(inspector, "sequence_diagrams", "route_id"):
            if _has_index(inspector, "sequence_diagrams", op.f("ix_sequence_diagrams_route_id")):
                op.drop_index(op.f("ix_sequence_diagrams_route_id"), table_name="sequence_diagrams")
            op.drop_column("sequence_diagrams", "route_id")

    inspector = sa.inspect(bind)

    if _has_table(inspector, "scans"):
        scan_columns = {column["name"] for column in inspector.get_columns("scans")}
        for column_name in [
            "entry_points",
            "project_type",
            "extension_counts",
            "top_level_dirs",
            "key_files",
        ]:
            if column_name in scan_columns:
                op.drop_column("scans", column_name)