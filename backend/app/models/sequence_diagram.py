import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SequenceDiagram(Base):
    __tablename__ = "sequence_diagrams"
    __table_args__ = (
        UniqueConstraint("project_id", "route_id", name="uq_project_route"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id"), nullable=False, index=True
    )
    scan_id: Mapped[str] = mapped_column(
        String, ForeignKey("scans.id"), nullable=False
    )
    route_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, index=True
    )
    diagram_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    project: Mapped["Project"] = relationship()
    scan: Mapped["Scan"] = relationship()


from app.models.project import Project  # noqa: E402, F401
from app.models.scan import Scan  # noqa: E402, F401
