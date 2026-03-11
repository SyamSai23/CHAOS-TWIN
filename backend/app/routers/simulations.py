import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.project import Project
from app.models.simulation_run import SimulationRun
from app.schemas import SimulationRunResponse
from app.services.graph_state import get_current_graph_state
from app.services.simulator import simulate_failure

router = APIRouter(
    prefix="/projects/{project_id}/simulate",
    tags=["simulations"],
)
logger = logging.getLogger(__name__)


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

    graph_scan, graph_nodes, graph_edges = get_current_graph_state(project_id, db)

    # Verify the requested node exists
    node_ids = {n.id for n in graph_nodes}
    if body.node_id not in node_ids:
        raise HTTPException(
            status_code=404,
            detail="Node not found in the current graph",
        )

    # Convert ORM objects to plain dicts for the simulator
    nodes_data = [
        {
            "id": n.id,
            "node_type": n.node_type,
            "label": n.label,
            "data": n.data,
            "canonical_entity_id": n.canonical_entity_id,
            "canonical_entity_kind": n.canonical_entity_kind,
            "confidence_score": n.confidence_score,
            "confidence_label": n.confidence_label,
        }
        for n in graph_nodes
    ]
    edges_data = [
        {
            "source_node_id": e.source_node_id,
            "target_node_id": e.target_node_id,
            "edge_type": e.edge_type,
            "data": e.data,
            "canonical_relation_id": e.canonical_relation_id,
            "canonical_relation_type": e.canonical_relation_type,
            "confidence_score": e.confidence_score,
            "confidence_label": e.confidence_label,
            "inference_stage": e.inference_stage,
        }
        for e in graph_edges
    ]

    result = simulate_failure(body.node_id, nodes_data, edges_data)

    logger.info(
        "Simulation completed for project %s scan %s mode %s canonical_nodes %s canonical_edges %s impacted %s severity %s",
        project_id,
        graph_scan.id,
        result.result_metadata.get("mode"),
        result.result_metadata.get("graph_provenance", {}).get("canonical_node_count", 0),
        result.result_metadata.get("graph_provenance", {}).get("canonical_edge_count", 0),
        len(result.impacted_nodes),
        result.severity,
    )

    # Persist the simulation run
    run = SimulationRun(
        project_id=project_id,
        scan_id=graph_scan.id,
        failed_node_id=body.node_id,
        severity=result.severity,
        summary=result.summary,
        impacted_nodes=result.impacted_nodes,
        result={
            "failed_node_label": result.failed_node_label,
            "failed_node_type": result.failed_node_type,
            "impacted_count": len(result.impacted_nodes),
            **result.result_metadata,
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
