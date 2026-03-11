import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id"), nullable=False, index=True
    )
    scan_id: Mapped[str] = mapped_column(
        String, ForeignKey("scans.id"), nullable=False, index=True
    )
    source_node_id: Mapped[str] = mapped_column(
        String, ForeignKey("graph_nodes.id"), nullable=False
    )
    target_node_id: Mapped[str] = mapped_column(
        String, ForeignKey("graph_nodes.id"), nullable=False
    )
    canonical_relation_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    canonical_relation_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence_label: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    inference_stage: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    edge_type: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    project: Mapped["Project"] = relationship(back_populates="graph_edges")
    scan: Mapped["Scan"] = relationship(back_populates="graph_edges")
    source_node: Mapped["GraphNode"] = relationship(
        back_populates="outgoing_edges",
        foreign_keys=[source_node_id],
    )
    target_node: Mapped["GraphNode"] = relationship(
        back_populates="incoming_edges",
        foreign_keys=[target_node_id],
    )


from app.models.project import Project  # noqa: E402, F401
from app.models.scan import Scan  # noqa: E402, F401
from app.models.graph_node import GraphNode  # noqa: E402, F401
