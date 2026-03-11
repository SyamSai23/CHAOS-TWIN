import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.graph_edge import GraphEdge
from app.models.graph_node import GraphNode
from app.models.project import Project
from app.models.scan import Scan
from app.models.sequence_diagram import SequenceDiagram
from app.models.simulation_run import SimulationRun
from app.schemas import GraphEdgeResponse, GraphNodeResponse, ProjectGraphResponse
from app.services.canonical_graph_builder import build_graph_from_project_model, validate_projected_graph
from app.services.graph_builder import build_graph_from_scan
from app.services.graph_state import get_current_graph_state
from app.services.project_model_loader import load_valid_project_model_snapshot

router = APIRouter(prefix="/projects/{project_id}/graph", tags=["graphs"])
logger = logging.getLogger(__name__)


@router.post("", response_model=ProjectGraphResponse, status_code=201)
def generate_project_graph(project_id: str, db: Session = Depends(get_db)):
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
        raise HTTPException(status_code=404, detail="No scans found for this project")

    # Delete old derived graph state so the rebuilt graph fully represents this scan.
    db.query(SimulationRun).filter(SimulationRun.project_id == project_id).delete()
    db.query(SequenceDiagram).filter(SequenceDiagram.project_id == project_id).delete()
    db.query(GraphEdge).filter(GraphEdge.project_id == project_id).delete()
    db.query(GraphNode).filter(GraphNode.project_id == project_id).delete()
    db.commit()

    node_specs = []
    edge_specs = []
    graph_build_path = "raw_scan_fallback"
    snapshot_id = None

    snapshot_with_model = load_valid_project_model_snapshot(
        db,
        project_id=project_id,
        scan_id=latest_scan.id,
    )
    if snapshot_with_model is not None:
        snapshot, model = snapshot_with_model
        snapshot_id = snapshot.id
        try:
            candidate_nodes, candidate_edges = build_graph_from_project_model(model)
            projection_errors = validate_projected_graph(candidate_nodes, candidate_edges)
            if projection_errors:
                raise ValueError("; ".join(projection_errors))

            node_specs = candidate_nodes
            edge_specs = candidate_edges
            graph_build_path = "canonical_snapshot"
        except Exception as exc:
            logger.warning(
                "Graph generation fell back to raw scan builder for project %s scan %s snapshot %s: %s",
                project_id,
                latest_scan.id,
                snapshot_id,
                exc,
            )

    if not node_specs:
        node_specs, edge_specs = build_graph_from_scan(latest_scan)
        graph_build_path = "raw_scan_fallback"

    _annotate_graph_specs(
        node_specs=node_specs,
        edge_specs=edge_specs,
        graph_build_path=graph_build_path,
        snapshot_id=snapshot_id,
    )

    graph_nodes: list[GraphNode] = []
    key_to_id: dict[str, str] = {}

    for spec in node_specs:
        node = GraphNode(
            project_id=project_id,
            scan_id=latest_scan.id,
            canonical_entity_id=spec.canonical_entity_id,
            canonical_entity_kind=spec.canonical_entity_kind,
            confidence_score=spec.confidence_score,
            confidence_label=spec.confidence_label,
            node_type=spec.node_type,
            label=spec.label,
            data=spec.data,
        )
        db.add(node)
        graph_nodes.append(node)

    db.flush()

    for spec, node in zip(node_specs, graph_nodes):
        key_to_id[spec.key] = node.id

    graph_edges: list[GraphEdge] = []
    for spec in edge_specs:
        source_id = key_to_id.get(spec.source_key)
        target_id = key_to_id.get(spec.target_key)
        if not source_id or not target_id:
            continue

        edge = GraphEdge(
            project_id=project_id,
            scan_id=latest_scan.id,
            source_node_id=source_id,
            target_node_id=target_id,
            canonical_relation_id=spec.canonical_relation_id,
            canonical_relation_type=spec.canonical_relation_type,
            confidence_score=spec.confidence_score,
            confidence_label=spec.confidence_label,
            inference_stage=spec.inference_stage,
            edge_type=spec.edge_type,
            data=spec.data,
        )
        db.add(edge)
        graph_edges.append(edge)

    db.commit()

    logger.info(
        "Graph generated for project %s scan %s via %s snapshot %s nodes %s edges %s canonical_nodes %s canonical_edges %s",
        project_id,
        latest_scan.id,
        graph_build_path,
        snapshot_id,
        len(graph_nodes),
        len(graph_edges),
        sum(1 for node in graph_nodes if node.canonical_entity_id),
        sum(1 for edge in graph_edges if edge.canonical_relation_id),
    )

    return _to_graph_response(project_id=project_id, scan_id=latest_scan.id, nodes=graph_nodes, edges=graph_edges)


def _annotate_graph_specs(
    node_specs,
    edge_specs,
    graph_build_path: str,
    snapshot_id,
) -> None:
    for node_spec in node_specs:
        node_spec.data = {
            **node_spec.data,
            "graph_source": graph_build_path,
        }
        if snapshot_id is not None:
            node_spec.data.setdefault("snapshot_id", snapshot_id)

    for edge_spec in edge_specs:
        edge_spec.data = {
            **edge_spec.data,
            "graph_source": graph_build_path,
        }
        if snapshot_id is not None:
            edge_spec.data.setdefault("snapshot_id", snapshot_id)

        if graph_build_path != "canonical_snapshot":
            edge_spec.canonical_relation_id = None
            edge_spec.canonical_relation_type = None
            edge_spec.confidence_score = None
            edge_spec.confidence_label = None
            edge_spec.inference_stage = None

    for node_spec in node_specs:
        if graph_build_path != "canonical_snapshot":
            node_spec.canonical_entity_id = None
            node_spec.canonical_entity_kind = None
            node_spec.confidence_score = None
            node_spec.confidence_label = None


@router.get("", response_model=ProjectGraphResponse)
def fetch_project_graph(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    graph_scan, nodes, edges = get_current_graph_state(project_id, db)
    return _to_graph_response(project_id=project_id, scan_id=graph_scan.id, nodes=nodes, edges=edges)


def _to_graph_response(
    project_id: str,
    scan_id: str,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
) -> ProjectGraphResponse:
    return ProjectGraphResponse(
        project_id=project_id,
        scan_id=scan_id,
        node_count=len(nodes),
        edge_count=len(edges),
        nodes=[
            GraphNodeResponse(
                id=node.id,
                project_id=node.project_id,
                scan_id=node.scan_id,
                node_type=node.node_type,
                label=node.label,
                data=node.data,
                created_at=node.created_at,
            )
            for node in nodes
        ],
        edges=[
            GraphEdgeResponse(
                id=edge.id,
                project_id=edge.project_id,
                scan_id=edge.scan_id,
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                edge_type=edge.edge_type,
                created_at=edge.created_at,
            )
            for edge in edges
        ],
    )
