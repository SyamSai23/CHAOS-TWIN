import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id"), nullable=False, index=True
    )
    scan_id: Mapped[str] = mapped_column(
        String, ForeignKey("scans.id"), nullable=False
    )
    failed_node_id: Mapped[str] = mapped_column(
        String, ForeignKey("graph_nodes.id"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    impacted_nodes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    project: Mapped["Project"] = relationship(back_populates="simulation_runs")
    scan: Mapped["Scan"] = relationship()
    failed_node: Mapped["GraphNode"] = relationship()


from app.models.project import Project  # noqa: E402, F401
from app.models.scan import Scan  # noqa: E402, F401
from app.models.graph_node import GraphNode  # noqa: E402, F401
