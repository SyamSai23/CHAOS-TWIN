import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.project import Project
from app.models.scan import Scan
from app.models.sequence_diagram import SequenceDiagram
from app.services.identity import make_route_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/routes", tags=["routes"])


# ── Response schemas ──


class RouteItem(BaseModel):
    id: str
    method: str
    path: str
    file: str
    component: str
    has_sequence: bool


class ComponentGroup(BaseModel):
    component: str
    component_type: str
    routes: list[RouteItem]


class RoutesResponse(BaseModel):
    total: int
    by_component: list[ComponentGroup]
    methods_summary: dict[str, int]


# ── Helpers ──


def _component_type_from_scan(component_name: str, components: list[dict]) -> str:
    """Look up component type from the scan's components list."""
    for comp in components:
        if comp.get("name") == component_name:
            return comp.get("type", "unknown")
    return "unknown"


# ── Endpoint ──


@router.get("", response_model=RoutesResponse)
def get_routes(project_id: str, db: Session = Depends(get_db)):
    """Return all detected API routes from the latest scan, grouped by component."""

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    latest_scan = (
        db.query(Scan)
        .filter(Scan.project_id == project_id)
        .order_by(Scan.created_at.desc())
        .first()
    )
    if not latest_scan:
        return RoutesResponse(total=0, by_component=[], methods_summary={})

    try:
        raw_routes: list[dict] = latest_scan.routes or []
        components: list[dict] = latest_scan.components or []
    except Exception:
        logger.exception("Failed to read routes/components from scan %s", latest_scan.id)
        return RoutesResponse(total=0, by_component=[], methods_summary={})

    if not raw_routes:
        return RoutesResponse(total=0, by_component=[], methods_summary={})

    # Look up which routes already have generated sequence diagrams
    existing_seq = (
        db.query(SequenceDiagram.route_id)
        .filter(
            SequenceDiagram.project_id == project_id,
            SequenceDiagram.route_id.isnot(None),
        )
        .all()
    )
    seq_route_ids: set[str] = {r[0] for r in existing_seq}

    try:
        methods_summary: dict[str, int] = {}
        for r in raw_routes:
            method = r.get("method", "ANY").upper()
            methods_summary[method] = methods_summary.get(method, 0) + 1

        groups: dict[str, list[RouteItem]] = {}
        for r in raw_routes:
            comp_name = r.get("component", "") or "unknown"
            method = r.get("method", "ANY").upper()
            path = r.get("path", "")
            file_path = r.get("file", "")
            rid = make_route_id(method, path, file_path)
            item = RouteItem(
                id=rid,
                method=method,
                path=path,
                file=file_path,
                component=comp_name,
                has_sequence=rid in seq_route_ids,
            )
            groups.setdefault(comp_name, []).append(item)

        by_component = [
            ComponentGroup(
                component=comp_name,
                component_type=_component_type_from_scan(comp_name, components),
                routes=items,
            )
            for comp_name, items in groups.items()
        ]

        return RoutesResponse(
            total=len(raw_routes),
            by_component=by_component,
            methods_summary=methods_summary,
        )
    except Exception:
        logger.exception("Error building routes response for project %s", project_id)
        raise HTTPException(status_code=500, detail="Failed to build routes response")
