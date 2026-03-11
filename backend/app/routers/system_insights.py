import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.project import Project
from app.schemas import ProjectInsightsResponse
from app.services.system_insights import build_system_insights

router = APIRouter(prefix="/projects/{project_id}/insights", tags=["system-insights"])
logger = logging.getLogger(__name__)


@router.get("", response_model=ProjectInsightsResponse)
def get_system_insights(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        insights = build_system_insights(project_id=project_id, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception:
        logger.exception("Failed to build system insights for project %s", project_id)
        raise HTTPException(status_code=500, detail="Failed to build system insights")

    logger.info(
        "System insights served for project %s scan %s insight_count %s graph_provenance %s",
        project_id,
        insights["scan_id"],
        insights["insight_count"],
        insights["graph_provenance"],
    )
    return insights