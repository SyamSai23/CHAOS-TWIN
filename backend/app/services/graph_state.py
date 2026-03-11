from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.graph_edge import GraphEdge
from app.models.graph_node import GraphNode
from app.models.scan import Scan


def get_current_graph_state(project_id: str, db: Session) -> tuple[Scan, list[GraphNode], list[GraphEdge]]:
    latest_node = (
        db.query(GraphNode)
        .filter(GraphNode.project_id == project_id)
        .order_by(GraphNode.created_at.desc())
        .first()
    )
    if not latest_node:
        raise HTTPException(status_code=404, detail="Graph not generated for this project")

    scan = db.query(Scan).filter(Scan.id == latest_node.scan_id).first()
    if not scan:
        raise HTTPException(status_code=409, detail="Graph refers to a missing scan")

    nodes = (
        db.query(GraphNode)
        .filter(
            GraphNode.project_id == project_id,
            GraphNode.scan_id == scan.id,
        )
        .order_by(GraphNode.created_at.asc())
        .all()
    )
    edges = (
        db.query(GraphEdge)
        .filter(
            GraphEdge.project_id == project_id,
            GraphEdge.scan_id == scan.id,
        )
        .order_by(GraphEdge.created_at.asc())
        .all()
    )
    return scan, nodes, edges