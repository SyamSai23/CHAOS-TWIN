from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.project import Project
from app.models.route_analysis import RouteAnalysis
from app.models.scan import Scan
from app.models.sequence_diagram import SequenceDiagram
from app.services.identity import make_route_id
from app.services.route_analysis_utils import build_route_analysis_from_route, ensure_route_analysis_signature

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
    handler_function: Optional[str] = None
    controller_name: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    confidence: Optional[float] = None
    best_target: Optional[dict[str, Any]] = None
    request_flow_summary: Optional[dict[str, Any]] = None


class RequestFlowStage(BaseModel):
    step: Optional[int] = None
    stage_type: str
    label: str
    file_path: Optional[str] = None
    symbol_name: Optional[str] = None
    class_name: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    confidence: Optional[float] = None
    provenance: Optional[str] = None
    is_inferred: bool = False
    anchor_kind: Optional[str] = None
    target_rank: Optional[int] = None
    selection_reason: Optional[str] = None
    code_anchor: Optional[dict[str, Any]] = None
    evidence: Optional[dict[str, Any]] = None
    hints: list[str] = []


class RequestFlowPayload(BaseModel):
    route_id: Optional[str] = None
    stage_count: int = 0
    confidence: Optional[float] = None
    summary: dict[str, Any] = {}
    stages: list[RequestFlowStage] = []


class RouteDetailResponse(RouteItem):
    component_type: str
    router_prefix: Optional[str] = None
    middleware: list[str] = []
    auth_hints: list[str] = []
    validation_hints: list[str] = []
    request_flow: Optional[RequestFlowPayload] = None
    route_analysis: Optional[dict[str, Any]] = None
    analysis_source: str = "none"


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


def _get_latest_scan(project_id: str, db: Session) -> Scan | None:
    return (
        db.query(Scan)
        .filter(Scan.project_id == project_id)
        .order_by(Scan.created_at.desc())
        .first()
    )


def _find_route_by_id(raw_routes: list[dict], route_id: str) -> dict | None:
    for route in raw_routes:
        if not isinstance(route, dict):
            continue
        method = str(route.get("method") or "ANY").upper()
        path = str(route.get("path") or "")
        file_path = str(route.get("file") or "")
        if make_route_id(method, path, file_path) == route_id:
            return route
    return None


def _request_flow_summary(request_flow: dict) -> dict[str, Any]:
    if not isinstance(request_flow, dict) or not request_flow:
        return {
            "stage_count": 0,
            "confidence": None,
            "has_request_flow": False,
            "has_service": False,
            "has_repository": False,
            "has_external": False,
        }
    summary = dict(request_flow.get("summary") or {})
    return {
        "stage_count": int(request_flow.get("stage_count") or len(request_flow.get("stages") or [])),
        "confidence": request_flow.get("confidence"),
        "has_request_flow": bool(request_flow.get("stages")),
        "has_service": bool(summary.get("has_service")),
        "has_repository": bool(summary.get("has_repository")),
        "has_external": bool(summary.get("has_external")),
        "has_data_access": bool(summary.get("has_data_access")),
    }


def _serialize_request_flow(request_flow: dict | None) -> dict[str, Any] | None:
    if not isinstance(request_flow, dict) or not request_flow:
        return None
    stages: list[dict[str, Any]] = []
    for stage in request_flow.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        provenance = str(stage.get("provenance") or "")
        is_inferred = provenance not in {
            "route_detection",
            "route_metadata",
            "direct_handler",
            "direct_code_signal",
            "route_completion",
        }
        code_anchor = dict(stage.get("evidence") or {}) or None
        stages.append(
            {
                "step": stage.get("step"),
                "stage_type": stage.get("stage_type") or "unknown",
                "label": stage.get("label") or "",
                "file_path": stage.get("file_path"),
                "symbol_name": stage.get("symbol_name"),
                "class_name": stage.get("class_name"),
                "line_start": stage.get("line_start"),
                "line_end": stage.get("line_end"),
                "confidence": stage.get("confidence"),
                "provenance": provenance or None,
                "is_inferred": is_inferred,
                "anchor_kind": stage.get("anchor_kind"),
                "target_rank": stage.get("target_rank"),
                "selection_reason": stage.get("selection_reason"),
                "code_anchor": code_anchor,
                "evidence": dict(stage.get("evidence") or {}) or None,
                "hints": list(stage.get("hints") or []),
            }
        )
    return {
        "route_id": request_flow.get("route_id"),
        "stage_count": int(request_flow.get("stage_count") or len(stages)),
        "confidence": request_flow.get("confidence"),
        "summary": dict(request_flow.get("summary") or {}),
        "stages": stages,
    }


def _route_item_from_raw(route: dict, seq_route_ids: set[str]) -> RouteItem:
    method = str(route.get("method") or "ANY").upper()
    path = str(route.get("path") or "")
    file_path = str(route.get("file") or "")
    rid = make_route_id(method, path, file_path)
    return RouteItem(
        id=rid,
        method=method,
        path=path,
        file=file_path,
        component=str(route.get("component") or "unknown"),
        has_sequence=rid in seq_route_ids,
        handler_function=route.get("handler_function"),
        controller_name=route.get("controller_name"),
        line_start=route.get("line_start"),
        line_end=route.get("line_end"),
        confidence=route.get("confidence"),
        best_target=dict(route.get("best_target") or {}) or None,
        request_flow_summary=_request_flow_summary(route.get("request_flow") or {}),
    )


def _route_analysis_for_response(route: dict, row: RouteAnalysis | None) -> tuple[dict[str, Any] | None, str]:
    if row and isinstance(row.analysis_data, dict):
        analysis = ensure_route_analysis_signature(dict(row.analysis_data))
        if not analysis.get("request_flow") and route.get("request_flow"):
            analysis["request_flow"] = _serialize_request_flow(route.get("request_flow"))
        return analysis, "stored_route_analysis"
    if route.get("request_flow"):
        return build_route_analysis_from_route(route), "derived_from_request_flow"
    return None, "none"


# ── Endpoint ──


@router.get("", response_model=RoutesResponse)
def get_routes(project_id: str, db: Session = Depends(get_db)):
    """Return all detected API routes from the latest scan, grouped by component."""

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    latest_scan = _get_latest_scan(project_id, db)
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
            item = _route_item_from_raw(r, seq_route_ids)
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


@router.get("/{route_id}", response_model=RouteDetailResponse)
def get_route_detail(project_id: str, route_id: str, db: Session = Depends(get_db)):
    """Return detailed route metadata, including deterministic request-flow when available."""

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    latest_scan = _get_latest_scan(project_id, db)
    if not latest_scan:
        raise HTTPException(status_code=404, detail="No scan found")

    raw_routes: list[dict] = list(latest_scan.routes or [])
    if not raw_routes:
        raise HTTPException(status_code=404, detail="No routes in scan")

    raw_route = _find_route_by_id(raw_routes, route_id)
    if raw_route is None:
        raise HTTPException(status_code=404, detail="Route not found")

    seq_exists = (
        db.query(SequenceDiagram.route_id)
        .filter(
            SequenceDiagram.project_id == project_id,
            SequenceDiagram.route_id == route_id,
        )
        .first()
        is not None
    )
    analysis_row = (
        db.query(RouteAnalysis)
        .filter(
            RouteAnalysis.project_id == project_id,
            RouteAnalysis.route_id == route_id,
        )
        .first()
    )
    route_analysis, analysis_source = _route_analysis_for_response(raw_route, analysis_row)
    route_item = _route_item_from_raw(raw_route, {route_id} if seq_exists else set())
    component_type = _component_type_from_scan(str(raw_route.get("component") or ""), list(latest_scan.components or []))

    return RouteDetailResponse(
        **route_item.model_dump(),
        component_type=component_type,
        router_prefix=raw_route.get("router_prefix"),
        middleware=list(raw_route.get("middleware") or []),
        auth_hints=list(raw_route.get("auth_hints") or []),
        validation_hints=list(raw_route.get("validation_hints") or []),
        request_flow=_serialize_request_flow(raw_route.get("request_flow")),
        route_analysis=route_analysis,
        analysis_source=analysis_source,
    )
