"""Add project model snapshots table.

Revision ID: 20260311_01
Revises: 20260310_01
Create Date: 2026-03-11 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260311_01"
down_revision = "20260310_01"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "project_model_snapshots"):
        op.create_table(
            "project_model_snapshots",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("scan_id", sa.String(), nullable=False),
            sa.Column("model_version", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("model_data", sa.JSON(), nullable=True),
            sa.Column(
                "validation_errors",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'::json"),
            ),
            sa.Column(
                "build_metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)

    if _has_table(inspector, "project_model_snapshots"):
        if not _has_index(inspector, "project_model_snapshots", "ix_project_model_snapshots_project_id"):
            op.create_index(
                "ix_project_model_snapshots_project_id",
                "project_model_snapshots",
                ["project_id"],
                unique=False,
            )
        if not _has_index(inspector, "project_model_snapshots", "ix_project_model_snapshots_scan_id"):
            op.create_index(
                "ix_project_model_snapshots_scan_id",
                "project_model_snapshots",
                ["scan_id"],
                unique=False,
            )
        if not _has_index(inspector, "project_model_snapshots", "uq_project_model_snapshot_scan"):
            op.create_index(
                "uq_project_model_snapshot_scan",
                "project_model_snapshots",
                ["scan_id"],
                unique=True,
            )
        if not _has_index(inspector, "project_model_snapshots", "ix_project_model_snapshot_project_status"):
            op.create_index(
                "ix_project_model_snapshot_project_status",
                "project_model_snapshots",
                ["project_id", "status"],
                unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "project_model_snapshots"):
        for index_name in [
            "ix_project_model_snapshot_project_status",
            "uq_project_model_snapshot_scan",
            "ix_project_model_snapshots_scan_id",
            "ix_project_model_snapshots_project_id",
        ]:
            if _has_index(inspector, "project_model_snapshots", index_name):
                op.drop_index(index_name, table_name="project_model_snapshots")
                inspector = sa.inspect(bind)

        op.drop_table("project_model_snapshots")