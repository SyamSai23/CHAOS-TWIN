from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import DATABASE_URL
from app.db.base import Base
from app.models.graph_edge import GraphEdge  # noqa: F401
from app.models.graph_node import GraphNode  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.project_model_snapshot import ProjectModelSnapshot  # noqa: F401
from app.models.route_analysis import RouteAnalysis  # noqa: F401
from app.models.scan import Scan  # noqa: F401
from app.models.sequence_diagram import SequenceDiagram  # noqa: F401
from app.models.simulation_run import SimulationRun  # noqa: F401
from app.models.upload import Upload  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()