import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.project import Project
from app.models.sequence_diagram import SequenceDiagram
from app.services.graph_state import get_current_graph_state
from app.services.identity import make_route_id
from app.services.sequence_generator import generate_sequence, generate_sequence_for_route

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/sequence", tags=["sequence"])


# ── Schemas ──

class RouteSequenceRequest(BaseModel):
    method: str
    path: str
    file: str
    component: str


# ── Helpers ──

def _get_project_scan_graph(project_id: str, db: Session):
    """Common lookup: project and the current persisted graph state."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    graph_scan, graph_nodes, graph_edges = get_current_graph_state(project_id, db)
    return project, graph_scan, graph_nodes, graph_edges


# ── System-level sequence (existing) ──

@router.post("", status_code=201)
def generate_sequence_diagram(project_id: str, db: Session = Depends(get_db)):
    _project, graph_scan, graph_nodes, graph_edges = _get_project_scan_graph(project_id, db)

    # Delete old system-level diagrams (route_id IS NULL) for this project
    db.query(SequenceDiagram).filter(
        SequenceDiagram.project_id == project_id,
        SequenceDiagram.route_id.is_(None),
    ).delete()
    db.flush()

    diagram_data = generate_sequence(graph_scan, graph_nodes, graph_edges)

    record = SequenceDiagram(
        project_id=project_id,
        scan_id=graph_scan.id,
        route_id=None,
        diagram_data=diagram_data,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return diagram_data


@router.get("")
def fetch_sequence_diagram(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    record = (
        db.query(SequenceDiagram)
        .filter(
            SequenceDiagram.project_id == project_id,
            SequenceDiagram.route_id.is_(None),
        )
        .order_by(SequenceDiagram.created_at.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Sequence diagram not generated")

    return record.diagram_data


# ── Per-route sequence endpoints ──

@router.post("/route", status_code=201)
def generate_route_sequence(
    project_id: str,
    body: RouteSequenceRequest,
    db: Session = Depends(get_db),
):
    """Generate and store a sequence diagram for a single route."""
    _project, graph_scan, graph_nodes, graph_edges = _get_project_scan_graph(project_id, db)

    route = {
        "method": body.method,
        "path": body.path,
        "file": body.file,
        "component": body.component,
    }

    diagram_data = generate_sequence_for_route(graph_scan, graph_nodes, graph_edges, route, db=db)
    rid = make_route_id(body.method, body.path, body.file)

    # Upsert: delete old row for this (project, route) then insert
    db.query(SequenceDiagram).filter(
        SequenceDiagram.project_id == project_id,
        SequenceDiagram.route_id == rid,
    ).delete()
    db.flush()

    record = SequenceDiagram(
        project_id=project_id,
        scan_id=graph_scan.id,
        route_id=rid,
        diagram_data=diagram_data,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return diagram_data


@router.get("/route/{route_id}")
def fetch_route_sequence(project_id: str, route_id: str, db: Session = Depends(get_db)):
    """Return a stored per-route sequence diagram."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    record = (
        db.query(SequenceDiagram)
        .filter(
            SequenceDiagram.project_id == project_id,
            SequenceDiagram.route_id == route_id,
        )
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Route sequence diagram not generated")

    return record.diagram_data


@router.post("/all")
def generate_all_route_sequences(project_id: str, db: Session = Depends(get_db)):
    """Generate sequence diagrams for ALL routes in the latest scan."""
    _project, graph_scan, graph_nodes, graph_edges = _get_project_scan_graph(project_id, db)

    raw_routes: list[dict] = graph_scan.routes or []
    if not raw_routes:
        return {"generated": 0, "failed": 0, "route_ids": []}

    generated = 0
    failed = 0
    route_ids: list[str] = []

    for route in raw_routes:
        rid = make_route_id(
            route.get("method", "GET"),
            route.get("path", "/"),
            route.get("file", ""),
        )
        try:
            diagram_data = generate_sequence_for_route(graph_scan, graph_nodes, graph_edges, route, db=db)

            # Upsert
            db.query(SequenceDiagram).filter(
                SequenceDiagram.project_id == project_id,
                SequenceDiagram.route_id == rid,
            ).delete()
            db.flush()

            record = SequenceDiagram(
                project_id=project_id,
                scan_id=graph_scan.id,
                route_id=rid,
                diagram_data=diagram_data,
            )
            db.add(record)
            generated += 1
            route_ids.append(rid)
        except Exception:
            logger.exception("Failed to generate sequence for route %s %s",
                             route.get("method"), route.get("path"))
            failed += 1

    db.commit()
    return {"generated": generated, "failed": failed, "route_ids": route_ids}


@router.get("/routes")
def list_route_sequences(project_id: str, db: Session = Depends(get_db)):
    """List all per-route sequence diagrams for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    records = (
        db.query(SequenceDiagram)
        .filter(
            SequenceDiagram.project_id == project_id,
            SequenceDiagram.route_id.isnot(None),
        )
        .order_by(SequenceDiagram.created_at.desc())
        .all()
    )

    return [
        {
            "route_id": r.route_id,
            "diagram_data": r.diagram_data,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]
