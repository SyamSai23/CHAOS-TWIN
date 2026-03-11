import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.project import Project
from app.schemas import CodePeekResponse
from app.services.code_peek import build_code_peek

router = APIRouter(prefix="/projects/{project_id}/code-peek", tags=["code-peek"])
logger = logging.getLogger(__name__)


@router.get("", response_model=CodePeekResponse)
def get_code_peek(
    project_id: str,
    evidence_id: Optional[str] = Query(default=None),
    entity_id: Optional[str] = Query(default=None),
    insight_id: Optional[str] = Query(default=None),
    graph_node_id: Optional[str] = Query(default=None),
    graph_edge_id: Optional[str] = Query(default=None),
    file_path: Optional[str] = Query(default=None),
    component_root: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        response = build_code_peek(
            project_id=project_id,
            db=db,
            evidence_id=evidence_id,
            entity_id=entity_id,
            insight_id=insight_id,
            graph_node_id=graph_node_id,
            graph_edge_id=graph_edge_id,
            file_path=file_path,
            component_root=component_root,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Failed to build code peek for project %s", project_id)
        raise HTTPException(status_code=500, detail="Failed to build code peek")

    logger.info(
        "Code peek served for project %s scan %s source_type %s source_id %s file_path %s",
        project_id,
        response["scan_id"],
        response["source_type"],
        response["source_id"],
        response["file_path"],
    )
    return response