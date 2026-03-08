from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.graph_edge import GraphEdge
from app.models.graph_node import GraphNode
from app.models.project import Project
from app.models.scan import Scan
from app.models.simulation_run import SimulationRun
from app.schemas import GraphEdgeResponse, GraphNodeResponse, ProjectGraphResponse
from app.services.graph_builder import build_graph_from_scan

router = APIRouter(prefix="/projects/{project_id}/graph", tags=["graphs"])


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

    # Delete old graph and any simulation runs that reference it
    db.query(SimulationRun).filter(SimulationRun.project_id == project_id).delete()
    db.query(GraphEdge).filter(GraphEdge.project_id == project_id).delete()
    db.query(GraphNode).filter(GraphNode.project_id == project_id).delete()
    db.commit()

    node_specs, edge_specs = build_graph_from_scan(latest_scan)

    graph_nodes: list[GraphNode] = []
    key_to_id: dict[str, str] = {}

    for spec in node_specs:
        node = GraphNode(
            project_id=project_id,
            scan_id=latest_scan.id,
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
            edge_type=spec.edge_type,
        )
        db.add(edge)
        graph_edges.append(edge)

    db.commit()

    return _to_graph_response(project_id=project_id, scan_id=latest_scan.id, nodes=graph_nodes, edges=graph_edges)


@router.get("", response_model=ProjectGraphResponse)
def fetch_project_graph(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    nodes = (
        db.query(GraphNode)
        .filter(GraphNode.project_id == project_id)
        .order_by(GraphNode.created_at.asc())
        .all()
    )
    if not nodes:
        raise HTTPException(status_code=404, detail="Graph not generated for this project")

    edges = (
        db.query(GraphEdge)
        .filter(GraphEdge.project_id == project_id)
        .order_by(GraphEdge.created_at.asc())
        .all()
    )

    scan_id = nodes[0].scan_id
    return _to_graph_response(project_id=project_id, scan_id=scan_id, nodes=nodes, edges=edges)


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
