"""Router for AST-based route analysis endpoints."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import WORKSPACE_DIR
from app.db.session import get_db
from app.models.project import Project
from app.models.scan import Scan
from app.models.sequence_diagram import SequenceDiagram
from app.models.upload import Upload
from app.models.route_analysis import RouteAnalysis
from app.services.ast_analyzer import RouteAnalyzer
from app.services.phrase_generator import PhraseGenerator
from app.services.route_analysis_utils import ensure_route_analysis_signature
from app.services.scanner_v3 import unwrap_root_dir

logger = logging.getLogger(__name__)

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
    _upsert_analysis(db, project_id, scan.id, result)
    db.commit()
    return result


@router.get("/routes")
def get_all_analyses(project_id: str, db: Session = Depends(get_db)):
    """Return all stored route analyses for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = (
        db.query(RouteAnalysis)
        .filter(RouteAnalysis.project_id == project_id)
        .order_by(RouteAnalysis.method, RouteAnalysis.path)
        .all()
    )
    return {
        "total": len(rows),
        "routes": [r.analysis_data for r in rows],
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
    row = (
        db.query(RouteAnalysis)
        .filter(
            RouteAnalysis.project_id == project_id,
            RouteAnalysis.route_id == route_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Route analysis not found")
    return ensure_route_analysis_signature(row.analysis_data)
