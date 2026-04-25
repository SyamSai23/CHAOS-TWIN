"""Router for AST-based route analysis endpoints."""

from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import WORKSPACE_DIR
from app.db.session import get_db
from app.models.project import Project
from app.models.scan import Scan
from app.models.sequence_diagram import SequenceDiagram
from app.models.upload import Upload
from app.models.route_analysis import RouteAnalysis
from app.services.ast_analyzer import RouteAnalyzer, infer_request_response
from app.services.phrase_generator import PhraseGenerator
from app.services.identity import make_route_id
from app.services.route_analysis_utils import build_route_analysis_from_route, ensure_route_analysis_signature
from app.services.scanner_v3 import unwrap_root_dir

logger = logging.getLogger(__name__)

_EXCLUDED_CALLER_TYPES = {"test", "style", "config", "migration", "seed"}
HTTP_CLIENT_PATTERNS = [
    "fetch(", "axios", ".get(", ".post(", ".put(", ".patch(", ".delete(",
    "XMLHttpRequest", "superagent", "got(", "ky.", "wretch",
    "requests.", "httpx.", "urllib", "aiohttp", "session.get", "session.post",
    "Net::HTTP", "HTTParty", "Faraday", "RestClient",
    "RestTemplate", "WebClient", "HttpClient", "OkHttpClient",
    "http.Get", "http.Post", "client.Do", "http.NewRequest",
    "curl_exec", "file_get_contents", "Guzzle", "$client->",
    "apiClient", "httpClient", "api_client", "http_client",
    "baseURL", "base_url", "API_URL", "API_BASE",
]
LAYER_LABELS = {
    "page": "UI Pages",
    "component": "UI Components",
    "hook": "React Hooks",
    "store": "State Management",
    "service": "Service Layer",
    "util": "Utilities",
    "route": "Route Handlers",
    "controller": "Controllers",
    "middleware": "Middleware",
    "model": "Data Models",
}
LAYER_ICONS = {
    "page": "🖥️",
    "component": "🧩",
    "hook": "🪝",
    "store": "🗄️",
    "service": "📡",
    "util": "🔧",
    "route": "🌐",
    "controller": "⚙️",
    "middleware": "🔀",
    "model": "🗃️",
}
DEFAULT_CALLER_TRAVERSAL_DEPTH = 2

router = APIRouter(
    prefix="/projects/{project_id}/analyze",
    tags=["analyze"],
)


# ── Request / Response schemas ──────────────────────────────────────

class SingleRouteBody(BaseModel):
    method: str
    path: str
    file: str
    component: str


class BatchResult(BaseModel):
    analyzed: int
    failed: int
    route_ids: list[str]


# ── Helpers ─────────────────────────────────────────────────────────

def _get_scan_and_workspace(project_id: str, db: Session):
    """Return (scan, workspace_root) or raise 404."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    scan = (
        db.query(Scan)
        .filter(Scan.project_id == project_id)
        .order_by(Scan.created_at.desc())
        .first()
    )
    if not scan:
        raise HTTPException(status_code=404, detail="No scan found")

    upload = db.query(Upload).filter(Upload.id == scan.upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")

    workspace_path = os.path.join(str(WORKSPACE_DIR), project_id, upload.id)
    effective_root = unwrap_root_dir(workspace_path)
    return scan, effective_root


def _upsert_analysis(
    db: Session,
    project_id: str,
    scan_id: str,
    analysis: dict,
) -> RouteAnalysis:
    """Insert or update a route analysis row."""
    ensure_route_analysis_signature(analysis)

    existing = (
        db.query(RouteAnalysis)
        .filter(
            RouteAnalysis.project_id == project_id,
            RouteAnalysis.route_id == analysis["route_id"],
        )
        .first()
    )
    if existing:
        existing.scan_id = scan_id
        existing.method = analysis["method"]
        existing.path = analysis["path"]
        existing.file = analysis["file"]
        existing.component = analysis["component"]
        existing.analysis_data = analysis
        db.query(SequenceDiagram).filter(
            SequenceDiagram.project_id == project_id,
            SequenceDiagram.route_id == analysis["route_id"],
        ).delete()
        db.flush()
        return existing

    row = RouteAnalysis(
        project_id=project_id,
        scan_id=scan_id,
        route_id=analysis["route_id"],
        method=analysis["method"],
        path=analysis["path"],
        file=analysis["file"],
        component=analysis["component"],
        analysis_data=analysis,
    )
    db.add(row)
    db.query(SequenceDiagram).filter(
        SequenceDiagram.project_id == project_id,
        SequenceDiagram.route_id == analysis["route_id"],
    ).delete()
    db.flush()
    return row


def _enrich_with_phrases(analysis: dict, phrase_gen: PhraseGenerator) -> dict:
    """Generate AI phrases and inject into phase descriptions."""
    phrases = phrase_gen.generate_phrases(analysis)
    for phase in analysis.get("phases", []):
        pid = phase["phase_id"]
        if pid in phrases and phrases[pid]:
            phase["description"] = phrases[pid]
    return ensure_route_analysis_signature(analysis)


def _attach_request_response(analysis: dict, project_id: str, db: Session) -> dict:
    file_summary_row = db.execute(
        text(
            """
            SELECT summary
            FROM file_index
            WHERE project_id = :project_id
              AND file_path = :file_path
            LIMIT 1
            """
        ),
        {"project_id": project_id, "file_path": analysis.get("file", "")},
    ).mappings().first()
    file_summary = str((file_summary_row or {}).get("summary") or "").strip()

    try:
        analysis["request_response"] = asyncio.run(
            infer_request_response(analysis, file_summary)
        )
    except Exception:
        analysis["request_response"] = None
    return ensure_route_analysis_signature(analysis)


def _find_scan_route(scan: Scan, route_id: str) -> dict | None:
    for route in scan.routes or []:
        if not isinstance(route, dict):
            continue
        method = str(route.get("method") or "ANY").upper()
        path = str(route.get("path") or "")
        file_path = str(route.get("file") or "")
        if make_route_id(method, path, file_path) == route_id:
            return route
    return None


def extract_search_terms(path: str) -> list[str]:
    segments = str(path or "").strip("/").split("/")
    return [
        segment
        for segment in segments
        if segment
        and not segment.startswith(":")
        and not segment.startswith("{")
        and len(segment) > 2
        and segment.lower() not in {"api", "v1", "v2", "v3", "auth", "admin", "index"}
    ]

def _file_type_rank(file_type: str) -> int:
    return {
        "page": 0,
        "component": 1,
        "service": 2,
        "hook": 3,
        "store": 4,
        "route": 5,
        "util": 6,
    }.get(file_type.lower(), 9)


def _normalize_file_type(file_type: str | None) -> str:
    return str(file_type or "unknown").strip().lower() or "unknown"


def _layer_label(file_type: str) -> str:
    normalized = _normalize_file_type(file_type)
    return LAYER_LABELS.get(normalized, normalized.replace("_", " ").title())


def _layer_icon(file_type: str) -> str:
    return LAYER_ICONS.get(_normalize_file_type(file_type), "📄")


def _dominant_file_type(files: list[dict]) -> str:
    counts: dict[str, int] = {}
    for file in files:
        normalized = _normalize_file_type(file.get("file_type"))
        counts[normalized] = counts.get(normalized, 0) + 1
    if not counts:
        return "unknown"
    return sorted(counts.items(), key=lambda item: (-item[1], _file_type_rank(item[0])))[0][0]


# ── Endpoints ───────────────────────────────────────────────────────

@router.post("/routes", response_model=BatchResult, status_code=201)
def analyze_all_routes(project_id: str, db: Session = Depends(get_db)):
    """Analyze ALL routes detected in the latest scan."""
    scan, workspace_root = _get_scan_and_workspace(project_id, db)

    routes = scan.routes or []
    if not routes:
        raise HTTPException(status_code=404, detail="No routes in scan")

    analyzer = RouteAnalyzer(str(workspace_root))
    phrase_gen = PhraseGenerator()
    analyzed = 0
    failed = 0
    route_ids: list[str] = []

    for route in routes:
        try:
            result = analyzer.analyze_route(route)
            if result is None:
                failed += 1
                continue
            _enrich_with_phrases(result, phrase_gen)
            _attach_request_response(result, project_id, db)
            _upsert_analysis(db, project_id, scan.id, result)
            route_ids.append(result["route_id"])
            analyzed += 1
        except Exception:
            logger.exception("Failed to analyze route %s", route)
            failed += 1

    db.commit()
    return BatchResult(analyzed=analyzed, failed=failed, route_ids=route_ids)


@router.post("/route", status_code=201)
def analyze_single_route(
    project_id: str,
    body: SingleRouteBody,
    db: Session = Depends(get_db),
):
    """Analyze a single route and upsert result."""
    scan, workspace_root = _get_scan_and_workspace(project_id, db)

    route = body.model_dump()
    analyzer = RouteAnalyzer(str(workspace_root))
    result = analyzer.analyze_route(route)
    if result is None:
        raise HTTPException(status_code=422, detail="Could not analyze route")

    phrase_gen = PhraseGenerator()
    _enrich_with_phrases(result, phrase_gen)
    _attach_request_response(result, project_id, db)
    _upsert_analysis(db, project_id, scan.id, result)
    db.commit()
    return result


@router.get("/routes")
def get_all_analyses(project_id: str, db: Session = Depends(get_db)):
    """Return all stored route analyses for a project."""
    scan, _ = _get_scan_and_workspace(project_id, db)
    rows = (
        db.query(RouteAnalysis)
        .filter(RouteAnalysis.project_id == project_id)
        .order_by(RouteAnalysis.method, RouteAnalysis.path)
        .all()
    )
    stored_by_route_id = {
        str(row.route_id): ensure_route_analysis_signature(dict(row.analysis_data or {}))
        for row in rows
        if isinstance(row.analysis_data, dict)
    }
    combined_routes: list[dict] = []
    for route in scan.routes or []:
        if not isinstance(route, dict):
            continue
        route_id = make_route_id(
            str(route.get("method") or "ANY").upper(),
            str(route.get("path") or ""),
            str(route.get("file") or ""),
        )
        if route_id in stored_by_route_id:
            combined_routes.append(stored_by_route_id[route_id])
            continue
        if route.get("request_flow"):
            combined_routes.append(build_route_analysis_from_route(route))
    return {
        "total": len(combined_routes),
        "routes": combined_routes,
    }


@router.post("/refresh", response_model=BatchResult, status_code=201)
def refresh_analyses(project_id: str, db: Session = Depends(get_db)):
    """Re-run analysis for ALL routes, replacing stale stored results."""
    scan, workspace_root = _get_scan_and_workspace(project_id, db)

    routes = scan.routes or []
    if not routes:
        raise HTTPException(status_code=404, detail="No routes in scan")

    analyzer = RouteAnalyzer(str(workspace_root))
    phrase_gen = PhraseGenerator()
    analyzed = 0
    failed = 0
    route_ids: list[str] = []

    for route in routes:
        try:
            result = analyzer.analyze_route(route)
            if result is None:
                failed += 1
                continue
            _enrich_with_phrases(result, phrase_gen)
            _attach_request_response(result, project_id, db)
            _upsert_analysis(db, project_id, scan.id, result)
            route_ids.append(result["route_id"])
            analyzed += 1
        except Exception:
            logger.exception("Failed to analyze route %s", route)
            failed += 1

    db.commit()
    return BatchResult(analyzed=analyzed, failed=failed, route_ids=route_ids)


@router.get("/route/{route_id}")
def get_single_analysis(
    project_id: str, route_id: str, db: Session = Depends(get_db)
):
    """Return a single stored route analysis."""
    scan, _ = _get_scan_and_workspace(project_id, db)
    row = (
        db.query(RouteAnalysis)
        .filter(
            RouteAnalysis.project_id == project_id,
            RouteAnalysis.route_id == route_id,
        )
        .first()
    )
    if row and isinstance(row.analysis_data, dict):
        return ensure_route_analysis_signature(dict(row.analysis_data))

    route = _find_scan_route(scan, route_id)
    if route and route.get("request_flow"):
        return build_route_analysis_from_route(route)

    raise HTTPException(status_code=404, detail="Route analysis not found")


@router.get("/callers")
def get_route_callers(
    project_id: str,
    method: str = Query(...),
    path: str = Query(...),
    depth: int = Query(DEFAULT_CALLER_TRAVERSAL_DEPTH, ge=1, le=5),
    db: Session = Depends(get_db),
):
    route_id = make_route_id(method.upper(), path, "")
    try:
        scan, _ = _get_scan_and_workspace(project_id, db)

        route_row = (
            db.query(RouteAnalysis)
            .filter(
                RouteAnalysis.project_id == project_id,
                RouteAnalysis.route_id == route_id,
            )
            .first()
        )

        handler_file = ""
        if route_row:
            handler_file = str(route_row.file or "")
        else:
            scan_route = _find_scan_route(scan, route_id)
            if scan_route:
                handler_file = str(scan_route.get("file") or "")
            else:
                synthesized_route_id = make_route_id(method.upper(), path, "")
                scan_route = _find_scan_route(scan, synthesized_route_id)
                if scan_route:
                    handler_file = str(scan_route.get("file") or "")

        indexed_rows = db.execute(
            text(
                """
                SELECT
                    file_path AS path,
                    file_type,
                    summary,
                    LEFT(COALESCE(full_content, ''), 3000) AS full_content
                FROM file_index
                WHERE project_id = :project_id
                ORDER BY
                    CASE file_type
                        WHEN 'service' THEN 0
                        WHEN 'page' THEN 1
                        WHEN 'component' THEN 2
                        WHEN 'hook' THEN 3
                        WHEN 'store' THEN 4
                        WHEN 'route' THEN 5
                        WHEN 'controller' THEN 6
                        WHEN 'middleware' THEN 7
                        WHEN 'util' THEN 5
                        ELSE 8
                    END,
                    path ASC
                """
            ),
            {"project_id": project_id},
        ).mappings().all()

        dependency_rows = db.execute(
            text(
                """
                SELECT file_path, imports, imported_by
                FROM dependency_graph
                WHERE project_id = :project_id
                """
            ),
            {"project_id": project_id},
        ).mappings().all()

        terms = extract_search_terms(path)
        files = [
            dict(row)
            for row in indexed_rows
            if str(row.get("file_type") or "").strip().lower() not in _EXCLUDED_CALLER_TYPES
        ]

        dependency_by_file: dict[str, dict] = {
            str(row["file_path"] or ""): dict(row)
            for row in dependency_rows
            if str(row["file_path"] or "")
        }
        indexed_meta = {
            str(row.get("path") or ""): dict(row)
            for row in files
            if str(row.get("path") or "")
        }

        direct_callers: dict[str, dict] = {}
        allowed_direct_types = {"page", "component", "service", "hook", "store", "util", "route"}

        for row in files:
            file_path = str(row.get("path") or "")
            file_type = _normalize_file_type(row.get("file_type"))
            if not file_path or file_path == handler_file or file_type not in allowed_direct_types:
                continue

            content = str(row.get("full_content") or "")
            content_lower = content.lower()
            if not content_lower:
                continue

            if not any(term.lower() in content_lower for term in terms):
                continue

            if not any(pattern.lower() in content_lower for pattern in HTTP_CLIENT_PATTERNS):
                continue

            matched_term = next((term for term in terms if term.lower() in content_lower), path.strip("/"))
            direct_callers[file_path] = {
                "file": file_path,
                "file_type": file_type or "util",
                "summary": str(row.get("summary") or "").strip(),
                "match_reason": f"contains {matched_term} fetch call",
            }

        indirect_callers: dict[str, dict] = {}
        frontier = set(direct_callers.keys())
        seen_upstream = set(frontier)
        for _ in range(max(depth - 1, 0)):
            next_frontier: set[str] = set()
            for source_path in frontier:
                dep_row = dependency_by_file.get(source_path)
                if not dep_row:
                    continue

                imported_by = dep_row.get("imported_by") or []
                if not isinstance(imported_by, list):
                    continue

                for upstream in imported_by:
                    upstream_path = str(upstream or "").strip()
                    if not upstream_path or upstream_path in seen_upstream or upstream_path == handler_file:
                        continue

                    meta = indexed_meta.get(upstream_path)
                    if not meta:
                        continue

                    upstream_type = _normalize_file_type(meta.get("file_type"))
                    if upstream_type in _EXCLUDED_CALLER_TYPES:
                        continue

                    seen_upstream.add(upstream_path)
                    next_frontier.add(upstream_path)
                    indirect_callers[upstream_path] = {
                        "file": upstream_path,
                        "file_type": upstream_type,
                        "summary": str(meta.get("summary") or "").strip(),
                    }
            frontier = next_frontier
            if not frontier:
                break

        chain: list[dict] = []
        if handler_file:
            handler_meta = indexed_meta.get(handler_file, {})
            entry_type = _normalize_file_type(handler_meta.get("file_type") or "route")
            chain.append(
                {
                    "layer": "entry",
                    "label": _layer_label(entry_type),
                    "icon": _layer_icon(entry_type),
                    "files": [
                        {
                            "file": handler_file,
                            "file_type": entry_type,
                            "summary": str(handler_meta.get("summary") or "").strip() or "Defines the backend entry point for this route",
                        }
                    ][:4],
                }
            )

        if direct_callers:
            direct_files = sorted(
                direct_callers.values(),
                key=lambda item: (_file_type_rank(str(item.get("file_type") or "")), str(item.get("file") or "")),
            )[:4]
            direct_type = _dominant_file_type(direct_files)
            chain.append(
                {
                    "layer": "direct",
                    "label": _layer_label(direct_type),
                    "icon": _layer_icon(direct_type),
                    "description": "These files call this route directly",
                    "files": direct_files,
                }
            )

        if indirect_callers:
            indirect_files = sorted(
                indirect_callers.values(),
                key=lambda item: (_file_type_rank(str(item.get("file_type") or "")), str(item.get("file") or "")),
            )[:4]
            indirect_type = _dominant_file_type(indirect_files)
            chain.append(
                {
                    "layer": "indirect",
                    "label": _layer_label(indirect_type),
                    "icon": _layer_icon(indirect_type),
                    "description": "These files use the service that calls this route",
                    "files": indirect_files,
                }
            )

        logger.info(
            "[callers] route=%s %s, segments=%s, files_searched=%s, found=%s",
            method,
            path,
            terms,
            len(files),
            sum(len(layer.get("files", [])) for layer in chain),
        )
        return {
            "route": f"{method.upper()} {path}",
            "chain": chain,
            "found": len(chain) > 0,
        }
    except Exception:
        logger.exception("Failed to resolve route callers for project %s route %s", project_id, route_id)
        return {"chain": [], "found": False}
