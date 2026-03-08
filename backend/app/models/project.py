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


from app.models.upload import Upload  # noqa: E402, F401 — resolve circular import
from app.models.scan import Scan  # noqa: E402, F401
