import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id"), nullable=False
    )
    upload_id: Mapped[str] = mapped_column(
        String, ForeignKey("uploads.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="completed"
    )
    file_count: Mapped[int] = mapped_column(nullable=False)
    files: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    languages: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    frameworks: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    key_files: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    top_level_dirs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    extension_counts: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    project_type: Mapped[str] = mapped_column(String, nullable=False)
    entry_points: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    components: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # ── Scanner V3 fields ──
    confidence_scores: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    dependencies: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    service_graph: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    routes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    import_graph: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    execution_flow: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    env_variables: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    docker_services: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    project: Mapped["Project"] = relationship(back_populates="scans")
    upload: Mapped["Upload"] = relationship()
    graph_nodes: Mapped[list["GraphNode"]] = relationship(back_populates="scan")
    graph_edges: Mapped[list["GraphEdge"]] = relationship(back_populates="scan")


from app.models.project import Project  # noqa: E402, F401
from app.models.upload import Upload  # noqa: E402, F401
from app.models.graph_node import GraphNode  # noqa: E402, F401
from app.models.graph_edge import GraphEdge  # noqa: E402, F401
