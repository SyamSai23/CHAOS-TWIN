"""Add graph canonical provenance fields.

Revision ID: 20260311_02
Revises: 20260311_01
Create Date: 2026-03-11 00:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260311_02"
down_revision = "20260311_01"
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

    if _has_table(inspector, "graph_nodes"):
        if not _has_column(inspector, "graph_nodes", "canonical_entity_id"):
            op.add_column("graph_nodes", sa.Column("canonical_entity_id", sa.String(), nullable=True))
        if not _has_column(inspector, "graph_nodes", "canonical_entity_kind"):
            op.add_column("graph_nodes", sa.Column("canonical_entity_kind", sa.String(), nullable=True))
        if not _has_column(inspector, "graph_nodes", "confidence_score"):
            op.add_column("graph_nodes", sa.Column("confidence_score", sa.Float(), nullable=True))
        if not _has_column(inspector, "graph_nodes", "confidence_label"):
            op.add_column("graph_nodes", sa.Column("confidence_label", sa.String(), nullable=True))

    inspector = sa.inspect(bind)
    if _has_table(inspector, "graph_nodes"):
        if not _has_index(inspector, "graph_nodes", "ix_graph_nodes_canonical_entity_id"):
            op.create_index(
                "ix_graph_nodes_canonical_entity_id",
                "graph_nodes",
                ["canonical_entity_id"],
                unique=False,
            )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "graph_edges"):
        if not _has_column(inspector, "graph_edges", "canonical_relation_id"):
            op.add_column("graph_edges", sa.Column("canonical_relation_id", sa.String(), nullable=True))
        if not _has_column(inspector, "graph_edges", "canonical_relation_type"):
            op.add_column("graph_edges", sa.Column("canonical_relation_type", sa.String(), nullable=True))
        if not _has_column(inspector, "graph_edges", "confidence_score"):
            op.add_column("graph_edges", sa.Column("confidence_score", sa.Float(), nullable=True))
        if not _has_column(inspector, "graph_edges", "confidence_label"):
            op.add_column("graph_edges", sa.Column("confidence_label", sa.String(), nullable=True))
        if not _has_column(inspector, "graph_edges", "inference_stage"):
            op.add_column("graph_edges", sa.Column("inference_stage", sa.String(), nullable=True))
        if not _has_column(inspector, "graph_edges", "data"):
            op.add_column(
                "graph_edges",
                sa.Column("data", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "graph_edges"):
        if not _has_index(inspector, "graph_edges", "ix_graph_edges_canonical_relation_id"):
            op.create_index(
                "ix_graph_edges_canonical_relation_id",
                "graph_edges",
                ["canonical_relation_id"],
                unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "graph_edges"):
        if _has_index(inspector, "graph_edges", "ix_graph_edges_canonical_relation_id"):
            op.drop_index("ix_graph_edges_canonical_relation_id", table_name="graph_edges")

        inspector = sa.inspect(bind)
        for column_name in [
            "data",
            "inference_stage",
            "confidence_label",
            "confidence_score",
            "canonical_relation_type",
            "canonical_relation_id",
        ]:
            if _has_column(inspector, "graph_edges", column_name):
                op.drop_column("graph_edges", column_name)
                inspector = sa.inspect(bind)

    inspector = sa.inspect(bind)
    if _has_table(inspector, "graph_nodes"):
        if _has_index(inspector, "graph_nodes", "ix_graph_nodes_canonical_entity_id"):
            op.drop_index("ix_graph_nodes_canonical_entity_id", table_name="graph_nodes")

        inspector = sa.inspect(bind)
        for column_name in [
            "confidence_label",
            "confidence_score",
            "canonical_entity_kind",
            "canonical_entity_id",
        ]:
            if _has_column(inspector, "graph_nodes", column_name):
                op.drop_column("graph_nodes", column_name)
                inspector = sa.inspect(bind)