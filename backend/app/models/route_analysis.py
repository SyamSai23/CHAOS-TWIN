"""SQLAlchemy model for route analysis results."""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.db.base import Base


def _gen_uuid() -> str:
    return str(uuid.uuid4())


class RouteAnalysis(Base):
    __tablename__ = "route_analyses"
    __table_args__ = (
        UniqueConstraint("project_id", "route_id", name="uq_route_analysis_project_route"),
    )

    id = Column(String, primary_key=True, default=_gen_uuid)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    scan_id = Column(String, ForeignKey("scans.id", ondelete="SET NULL"), nullable=True)
    route_id = Column(String, nullable=False, index=True)
    method = Column(String, nullable=False)
    path = Column(String, nullable=False)
    file = Column(String, nullable=False)
    component = Column(String, nullable=False)
    analysis_data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    project = relationship("Project", backref="route_analyses")
    scan = relationship("Scan", backref="route_analyses")
