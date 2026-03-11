import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ProjectModelSnapshot(Base):
    """Persisted canonical ProjectModel artifact for internal backend use.

    Rollout strategy:
    - Additive only. Existing scan responses and downstream pipelines do not read this yet.
    - One snapshot row per scan so future consumers can opt into canonical reads by scan_id
      or fetch the latest successful snapshot for a project.
    """

    __tablename__ = "project_model_snapshots"
    __table_args__ = (
        Index("uq_project_model_snapshot_scan", "scan_id", unique=True),
        Index("ix_project_model_snapshot_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scan_id: Mapped[str] = mapped_column(
        String, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    model_data: Mapped[Optional[dict]] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    validation_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    build_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    project: Mapped["Project"] = relationship(back_populates="project_model_snapshots")
    scan: Mapped["Scan"] = relationship(back_populates="project_model_snapshot")


from app.models.project import Project  # noqa: E402, F401
from app.models.scan import Scan  # noqa: E402, F401