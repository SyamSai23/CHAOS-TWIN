import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base

class ProjectUnderstanding(Base):
    __tablename__ = "project_understanding"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), unique=True)
    project_story: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    system_map: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    data_journey: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    key_decisions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    gotchas: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    glossary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String, server_default="pending")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project: Mapped["Project"] = relationship("Project", back_populates="understanding")
