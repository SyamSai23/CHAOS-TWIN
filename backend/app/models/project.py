import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    uploads: Mapped[list["Upload"]] = relationship(back_populates="project")
    scans: Mapped[list["Scan"]] = relationship(back_populates="project")
    graph_nodes: Mapped[list["GraphNode"]] = relationship(back_populates="project")
    graph_edges: Mapped[list["GraphEdge"]] = relationship(back_populates="project")
    simulation_runs: Mapped[list["SimulationRun"]] = relationship(back_populates="project")
    project_model_snapshots: Mapped[list["ProjectModelSnapshot"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


from app.models.upload import Upload  # noqa: E402, F401 — resolve circular import
from app.models.scan import Scan  # noqa: E402, F401
from app.models.graph_node import GraphNode  # noqa: E402, F401
from app.models.graph_edge import GraphEdge  # noqa: E402, F401
from app.models.simulation_run import SimulationRun  # noqa: E402, F401
from app.models.project_model_snapshot import ProjectModelSnapshot  # noqa: E402, F401
