from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.graph_edge import GraphEdge
from app.models.graph_node import GraphNode
from app.models.project import Project
from app.models.scan import Scan
from app.models.simulation_run import SimulationRun
from app.schemas import RepoBriefResponse
from app.services.brief_builder import generate_brief

router = APIRouter(prefix="/projects/{project_id}/brief", tags=["briefs"])


@router.post("", response_model=RepoBriefResponse, status_code=200)
def create_brief(project_id: str, db: Session = Depends(get_db)):
    """Generate an AI repo brief from the project's scan, graph, and simulation data."""

    # --- Validate project exists ---
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # --- Gather latest scan ---
    latest_scan = (
        db.query(Scan)
        .filter(Scan.project_id == project_id)
        .order_by(Scan.created_at.desc())
        .first()
    )
    if not latest_scan:
        raise HTTPException(status_code=404, detail="No scan found — run a scan first")

    scan_dict = {
        "project_type": latest_scan.project_type,
        "file_count": latest_scan.file_count,
        "languages": latest_scan.languages,
        "frameworks": latest_scan.frameworks,
        "top_level_dirs": latest_scan.top_level_dirs,
        "entry_points": latest_scan.entry_points,
        "extension_counts": latest_scan.extension_counts,
        "components": latest_scan.components,
        "key_files": latest_scan.key_files,
    }

    # --- Gather graph ---
    nodes_db = (
        db.query(GraphNode)
        .filter(GraphNode.project_id == project_id)
        .all()
    )
    edges_db = (
        db.query(GraphEdge)
        .filter(GraphEdge.project_id == project_id)
        .all()
    )
    nodes = [
        {"id": n.id, "node_type": n.node_type, "label": n.label, "data": n.data}
        for n in nodes_db
    ]
    edges = [
        {
            "source_node_id": e.source_node_id,
            "target_node_id": e.target_node_id,
            "edge_type": e.edge_type,
        }
        for e in edges_db
    ]

    if not nodes:
        raise HTTPException(
            status_code=404, detail="No graph found — generate a graph first"
        )

    # --- Gather latest simulation (optional) ---
    sim_run = (
        db.query(SimulationRun)
        .filter(SimulationRun.project_id == project_id)
        .order_by(SimulationRun.created_at.desc())
        .first()
    )
    simulation: Optional[dict] = None
    if sim_run:
        failed_node = (
            db.query(GraphNode).filter(GraphNode.id == sim_run.failed_node_id).first()
        )
        simulation = {
            "failed_node_label": failed_node.label if failed_node else "unknown",
            "failed_node_type": failed_node.node_type if failed_node else "unknown",
            "severity": sim_run.severity,
            "summary": sim_run.summary,
            "impacted_nodes": sim_run.impacted_nodes,
        }

    # --- Generate brief ---
    try:
        brief = generate_brief(
            project_name=project.name,
            project_id=project.id,
            scan=scan_dict,
            nodes=nodes,
            edges=edges,
            simulation=simulation,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return brief
