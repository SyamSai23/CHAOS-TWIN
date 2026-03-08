import uuid
from datetime import datetime, timezone

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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    project: Mapped["Project"] = relationship(back_populates="scans")
    upload: Mapped["Upload"] = relationship()


from app.models.project import Project  # noqa: E402, F401
