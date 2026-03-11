import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GraphNode(Base):
    __tablename__ = "graph_nodes"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id"), nullable=False, index=True
    )
    scan_id: Mapped[str] = mapped_column(
        String, ForeignKey("scans.id"), nullable=False, index=True
    )
    canonical_entity_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    canonical_entity_kind: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence_label: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    node_type: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    project: Mapped["Project"] = relationship(back_populates="graph_nodes")
    scan: Mapped["Scan"] = relationship(back_populates="graph_nodes")
    outgoing_edges: Mapped[list["GraphEdge"]] = relationship(
        back_populates="source_node",
        foreign_keys="GraphEdge.source_node_id",
    )
    incoming_edges: Mapped[list["GraphEdge"]] = relationship(
        back_populates="target_node",
        foreign_keys="GraphEdge.target_node_id",
    )


from app.models.project import Project  # noqa: E402, F401
from app.models.scan import Scan  # noqa: E402, F401
from app.models.graph_edge import GraphEdge  # noqa: E402, F401
