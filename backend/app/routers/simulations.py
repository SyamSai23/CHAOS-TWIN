from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.graph_edge import GraphEdge
from app.models.graph_node import GraphNode
from app.models.project import Project
from app.models.scan import Scan
from app.models.simulation_run import SimulationRun
from app.schemas import SimulationRunResponse
from app.services.simulator import simulate_failure

router = APIRouter(
    prefix="/projects/{project_id}/simulate",
    tags=["simulations"],
)


class SimulateRequest(BaseModel):
    node_id: str


@router.post("", response_model=SimulationRunResponse, status_code=201)
def run_simulation(
    project_id: str,
    body: SimulateRequest,
    db: Session = Depends(get_db),
):
    """Simulate failure of a single graph node and return impact analysis."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Load latest scan so we can link the simulation
    latest_scan = (
        db.query(Scan)
        .filter(Scan.project_id == project_id)
        .order_by(Scan.created_at.desc())
        .first()
    )
    if not latest_scan:
        raise HTTPException(status_code=404, detail="No scans found for this project")

    # Load graph nodes and edges for this project
    graph_nodes = (
        db.query(GraphNode).filter(GraphNode.project_id == project_id).all()
    )
    graph_edges = (
        db.query(GraphEdge).filter(GraphEdge.project_id == project_id).all()
    )

    if not graph_nodes:
        raise HTTPException(
            status_code=404,
            detail="No graph found. Generate a graph first.",
        )

    # Verify the requested node exists
    node_ids = {n.id for n in graph_nodes}
    if body.node_id not in node_ids:
        raise HTTPException(
            status_code=404,
            detail="Node not found in the current graph",
        )

    # Convert ORM objects to plain dicts for the simulator
    nodes_data = [
        {"id": n.id, "node_type": n.node_type, "label": n.label}
        for n in graph_nodes
    ]
    edges_data = [
        {
            "source_node_id": e.source_node_id,
            "target_node_id": e.target_node_id,
            "edge_type": e.edge_type,
        }
        for e in graph_edges
    ]

    result = simulate_failure(body.node_id, nodes_data, edges_data)

    # Persist the simulation run
    run = SimulationRun(
        project_id=project_id,
        scan_id=latest_scan.id,
        failed_node_id=body.node_id,
        severity=result.severity,
        summary=result.summary,
        impacted_nodes=result.impacted_nodes,
        result={
            "failed_node_label": result.failed_node_label,
            "failed_node_type": result.failed_node_type,
            "impacted_count": len(result.impacted_nodes),
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    return run


@router.get("/history", response_model=list[SimulationRunResponse])
def list_simulations(
    project_id: str,
    db: Session = Depends(get_db),
):
    """List past simulation runs for a project, newest first."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    runs = (
        db.query(SimulationRun)
        .filter(SimulationRun.project_id == project_id)
        .order_by(SimulationRun.created_at.desc())
        .all()
    )
    return runs
