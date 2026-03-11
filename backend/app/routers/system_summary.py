import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.project import Project
from app.schemas import SystemIntelligenceSummaryResponse
from app.services.system_intelligence_summary import build_system_intelligence_summary

router = APIRouter(prefix="/projects/{project_id}/summary", tags=["system-summary"])
logger = logging.getLogger(__name__)


@router.get("", response_model=SystemIntelligenceSummaryResponse)
def get_system_summary(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        summary = build_system_intelligence_summary(project_id=project_id, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception:
        logger.exception("Failed to build system summary for project %s", project_id)
        raise HTTPException(status_code=500, detail="Failed to build system summary")

    logger.info(
        "System summary served for project %s scan %s snapshot_used %s graph_provenance %s confidence %s",
        project_id,
        summary["scan_id"],
        bool(summary.get("snapshot_id")),
        summary["graph_provenance"],
        summary["confidence_summary"]["overall_label"],
    )
    return summary