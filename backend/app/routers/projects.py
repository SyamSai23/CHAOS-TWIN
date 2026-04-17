import shutil
import json
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.config import UPLOAD_DIR, WORKSPACE_DIR
from app.db.session import get_db
from app.models.project import Project
from app.models.upload import Upload
from app.models.scan import Scan
from app.models.graph_node import GraphNode
from app.models.graph_edge import GraphEdge
from app.models.route_analysis import RouteAnalysis
from app.models.simulation_run import SimulationRun
from app.models.sequence_diagram import SequenceDiagram
from app.models.project_understanding import ProjectUnderstanding
from app.schemas import ProjectCreate, ProjectResponse, ProjectDashboardResponse, DashboardChatRequest, DashboardChatResponse, RoutePreview, LanguageStat
from app.services.ast_analyzer import infer_request_response
from app.services.understanding_generator import generate_depth_tiers, understanding_has_depth_tiers

from openai import AsyncOpenAI, OpenAI
from app.config import OPENAI_API_KEY, OPENAI_MODEL

router = APIRouter(prefix="/projects", tags=["projects"])


class FileEnrichBody(BaseModel):
    file_path: str


def _attach_feature_file_details(project_id: str, features: list[dict], db: Session) -> list[dict]:
    file_paths: list[str] = []
    seen: set[str] = set()
    for feature in features:
        if not isinstance(feature, dict):
            continue
        for path in feature.get("files", []):
            if isinstance(path, str) and path not in seen:
                seen.add(path)
                file_paths.append(path)

    file_lookup: dict[str, dict] = {}
    if file_paths:
        rows = db.execute(
            text(
                """
                SELECT
                    file_path,
                    file_type,
                    summary,
                    importance_score
                FROM file_index
                WHERE project_id = :project_id
                  AND file_path IN :paths
                """
            ).bindparams(bindparam("paths", expanding=True)),
            {"project_id": project_id, "paths": file_paths},
        ).mappings().all()
        file_lookup = {
            str(row["file_path"]): {
                "path": str(row["file_path"]),
                "file_type": str(row["file_type"] or "other"),
                "summary": str(row["summary"] or "").strip(),
                "importance_score": float(row["importance_score"] or 0),
            }
            for row in rows
        }

    enriched: list[dict] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        files = [path for path in feature.get("files", []) if isinstance(path, str)]
        feature_copy = dict(feature)
        feature_copy["files_detail"] = [
            file_lookup.get(
                path,
                {
                    "path": path,
                    "file_type": "other",
                    "summary": "",
                    "importance_score": 0.0,
                },
            )
            for path in files
        ]
        enriched.append(feature_copy)
    return enriched


def _normalize_feature_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().rstrip("/")


def _filename_only(path: str) -> str:
    normalized = _normalize_feature_path(path)
    if not normalized:
        return ""
    return normalized.split("/")[-1]


def _route_keywords(route_path: str) -> list[str]:
    normalized = str(route_path or "").strip().lower()
    parts = [part for part in normalized.split("/") if part and not part.startswith(":")]
    keywords: list[str] = []
    seen: set[str] = set()
    for part in parts:
        tokens = [token for token in re.split(r"[^a-z0-9]+", part) if token]
        for token in tokens:
            singular = token[:-1] if token.endswith("s") and len(token) > 3 else token
            for candidate in (token, singular):
                if candidate and candidate not in seen:
                    seen.add(candidate)
                    keywords.append(candidate)
    return keywords


def _ensure_file_index_ui_analysis_column(db: Session) -> None:
    db.execute(text("ALTER TABLE file_index ADD COLUMN IF NOT EXISTS ui_analysis JSONB"))
    db.commit()


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


async def semantic_search(project_id: str, query: str, limit: int, db: Session) -> dict:
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="Semantic search unavailable: missing OpenAI API key")

    openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    response = await openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=query,
    )
    query_embedding = response.data[0].embedding
    vector_literal = _vector_literal(query_embedding)

    results = db.execute(
        text(
            """
            SELECT
                file_path, file_type, domain_area,
                summary, exports, key_concepts,
                importance_score,
                1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM file_index
            WHERE project_id = :project_id
              AND embedding IS NOT NULL
              AND 1 - (embedding <=> CAST(:embedding AS vector)) > 0.3
            ORDER BY
                (1 - (embedding <=> CAST(:embedding AS vector))) * 0.7 +
                (importance_score / 20.0) * 0.3 DESC
            LIMIT :limit
            """
        ),
        {
            "embedding": vector_literal,
            "project_id": project_id,
            "limit": limit,
        },
    ).mappings().all()

    top_paths = [row["file_path"] for row in results[:3]]
    related_rows: list[dict] = []
    if top_paths:
        related_rows = db.execute(
            text(
                """
                SELECT file_path, imports, imported_by
                FROM dependency_graph
                WHERE project_id = :project_id
                  AND file_path IN :paths
                """
            ).bindparams(bindparam("paths", expanding=True)),
            {"project_id": project_id, "paths": top_paths},
        ).mappings().all()

    return {
        "query": query,
        "results": [dict(row) for row in results],
        "related_files": [dict(row) for row in related_rows],
    }


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(name=data.name, path=data.path)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("")
def list_projects(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            """
            SELECT
                p.id,
                p.name,
                p.path,
                p.created_at,
                COALESCE(fi.file_count, 0) AS file_count,
                COALESCE(
                    CASE ist.status
                        WHEN 'complete' THEN 'completed'
                        WHEN 'indexing' THEN 'running'
                        ELSE ist.status
                    END,
                    'unknown'
                ) AS status
            FROM projects p
            LEFT JOIN (
                SELECT project_id, COUNT(*) AS file_count
                FROM file_index
                GROUP BY project_id
            ) fi ON fi.project_id = p.id
            LEFT JOIN indexing_status ist ON ist.project_id = p.id
            ORDER BY p.created_at DESC
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/{project_id}/search")
async def search_project(project_id: str, q: str, limit: int = 8, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    return await semantic_search(project_id, q.strip(), max(1, min(limit, 20)), db)


@router.get("/{project_id}/feature-map")
async def get_project_feature_map(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    cached = db.execute(
        text(
            """
            SELECT
                features
            FROM feature_map
            WHERE project_id = :project_id
            ORDER BY generated_at DESC
            LIMIT 1
            """
        ),
        {"project_id": project_id},
    ).mappings().first()
    if cached:
        cached_features = cached["features"] if isinstance(cached["features"], list) else []
        return {"features": _attach_feature_file_details(project_id, cached_features, db)}

    file_rows = db.execute(
        text(
            """
            SELECT
                file_path,
                file_type,
                summary,
                importance_score
            FROM file_index
            WHERE project_id = :project_id
            ORDER BY importance_score DESC, file_path ASC
            """
        ),
        {"project_id": project_id},
    ).mappings().all()
    if not file_rows:
        return {"features": []}

    dep_rows = db.execute(
        text(
            """
            SELECT
                file_path,
                imports
            FROM dependency_graph
            WHERE project_id = :project_id
            """
        ),
        {"project_id": project_id},
    ).mappings().all()

    file_lines = []
    file_type_lookup: dict[str, str] = {}
    importance_lookup: dict[str, float] = {}
    for row in file_rows:
        path = str(row["file_path"])
        file_type = str(row["file_type"] or "other")
        summary = str(row["summary"] or "").strip()
        score = float(row["importance_score"] or 0)
        file_type_lookup[path] = file_type
        importance_lookup[path] = score
        file_lines.append(f"{path} | {file_type} | {summary}")

    edge_lines: list[str] = []
    for row in dep_rows:
        source = str(row["file_path"])
        imports = row["imports"] or []
        if not isinstance(imports, list):
            continue
        for target in imports:
            if isinstance(target, str) and target.strip():
                edge_lines.append(f"{source} -> {target}")

    prompt = f"""You are helping a junior developer understand a codebase they just joined.

This may be a complete full-stack app, a backend service, a frontend app, a microservice, or any partial codebase. Do not assume anything is missing — work with exactly what's here.

Here are the source files:
{chr(10).join(file_lines)}

Here are the dependencies:
{chr(10).join(edge_lines) if edge_lines else "No dependency edges found"}

Group these files into 4-6 logical capabilities this code implements.
Think: "what can this code DO?" not "what kind of app is this?"
Name each capability in plain English from a junior developer's perspective.
Every codebase — even a single microservice or frontend module — has distinct capabilities worth explaining.

Return ONLY a JSON array, no markdown:
[
  {{
    "name": "User Authentication",
    "description": "One sentence: what this capability does",
    "entry_point": "the most important file to start reading",
    "files": ["path/to/file1", "path/to/file2"],
    "importance": 0.95
  }}
]
"""

    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="Feature map generation failed: missing OpenAI API key")

    openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Return only valid JSON arrays."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        features = parsed if isinstance(parsed, list) else next(
            (value for value in parsed.values() if isinstance(value, list)),
            None,
        )
        if not isinstance(features, list):
            raise ValueError("Model returned invalid feature-map JSON")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Feature map generation failed: {str(exc) or 'unknown OpenAI error'}",
        ) from exc

    max_importance = max(importance_lookup.values(), default=0.0)
    enriched_features = []
    for item in features:
        if not isinstance(item, dict):
            continue
        files = [path for path in item.get("files", []) if isinstance(path, str)]
        normalized_importance = float(item.get("importance", 0) or 0)
        if normalized_importance > 1:
            normalized_importance = normalized_importance / 100.0
        if files and max_importance > 0:
            derived = max((importance_lookup.get(path, 0.0) for path in files), default=0.0) / max_importance
            normalized_importance = max(normalized_importance, derived)
        enriched_features.append(
            {
                "name": str(item.get("name", "Untitled Feature")).strip(),
                "description": str(item.get("description", "")).strip(),
                "entry_point": str(item.get("entry_point", "")).strip(),
                "files": files,
                "importance": max(0.0, min(1.0, normalized_importance)),
            }
        )

    db.execute(
        text(
            """
            INSERT INTO feature_map (project_id, features)
            VALUES (:project_id, CAST(:features AS jsonb))
            """
        ),
        {"project_id": project_id, "features": json.dumps(enriched_features)},
    )
    db.commit()
    return {"features": _attach_feature_file_details(project_id, enriched_features, db)}


@router.post("/{project_id}/understanding/depth-tiers")
async def generate_project_understanding_depth_tiers(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    understanding = (
        db.query(ProjectUnderstanding)
        .filter(ProjectUnderstanding.project_id == project_id)
        .first()
    )
    if not understanding:
        raise HTTPException(status_code=404, detail="Understanding not generated yet")

    if understanding_has_depth_tiers(understanding):
        return {"status": "cached"}

    status = await generate_depth_tiers(project_id, db)
    return {"status": status}


@router.get("/{project_id}/api-explorer")
def get_project_api_explorer(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    feature_row = db.execute(
        text(
            """
            SELECT features
            FROM feature_map
            WHERE project_id = :project_id
            ORDER BY generated_at DESC
            LIMIT 1
            """
        ),
        {"project_id": project_id},
    ).mappings().first()

    base_features = feature_row["features"] if feature_row and isinstance(feature_row["features"], list) else []
    feature_list = _attach_feature_file_details(project_id, base_features, db)

    feature_search_strings: dict[str, str] = {}
    grouped_routes: dict[str, list[dict]] = {
        str(feature.get("name") or "Untitled Feature"): []
        for feature in feature_list
        if isinstance(feature, dict)
    }

    for feature in feature_list:
        if not isinstance(feature, dict):
            continue
        feature_name = str(feature.get("name") or "Untitled Feature")
        searchable_parts = [
            feature_name.lower(),
            str(feature.get("description") or "").lower(),
        ]
        for file_detail in feature.get("files_detail", []):
            if not isinstance(file_detail, dict):
                continue
            file_name = _filename_only(str(file_detail.get("path") or ""))
            if file_name:
                searchable_parts.append(file_name.lower())
        feature_search_strings[feature_name] = " ".join(searchable_parts)

    route_rows = (
        db.query(RouteAnalysis)
        .filter(RouteAnalysis.project_id == project_id)
        .order_by(RouteAnalysis.method.asc(), RouteAnalysis.path.asc())
        .all()
    )

    route_payloads: list[dict] = []
    mode = "routes"
    for route_row in route_rows:
        analysis = route_row.analysis_data if isinstance(route_row.analysis_data, dict) else {}
        route_payloads.append(
            {
                "route_id": str(route_row.route_id),
                "method": str(route_row.method or analysis.get("method") or "GET").upper(),
                "path": str(route_row.path or analysis.get("path") or ""),
                "file": str(route_row.file or analysis.get("file") or ""),
                "handler": analysis.get("handler_function"),
                "complexity": str(analysis.get("complexity") or "simple"),
                "has_database": bool(analysis.get("has_database", False)),
                "has_external": bool(analysis.get("has_external", False)),
                "parameters": analysis.get("parameters", []) if isinstance(analysis.get("parameters", []), list) else [],
                "phases": analysis.get("phases", []) if isinstance(analysis.get("phases", []), list) else [],
                "participants": analysis.get("participants", []) if isinstance(analysis.get("participants", []), list) else [],
                "request_response": analysis.get("request_response") if isinstance(analysis.get("request_response"), dict) else None,
            }
        )

    if not route_payloads:
        mode = "entry_points"
        fallback_rows = db.execute(
            text(
                """
                SELECT file_path, file_type, summary, importance_score
                FROM file_index
                WHERE project_id = :project_id
                  AND file_type IN ('entry_point', 'page', 'controller', 'route')
                ORDER BY importance_score DESC, file_path ASC
                LIMIT 20
                """
            ),
            {"project_id": project_id},
        ).mappings().all()
        for row in fallback_rows:
            file_path = str(row["file_path"] or "")
            route_payloads.append(
                {
                    "route_id": file_path,
                    "method": "ENTRY",
                    "path": file_path,
                    "file": file_path,
                    "handler": _filename_only(file_path) or file_path,
                    "complexity": "unknown",
                    "has_database": False,
                    "has_external": False,
                    "parameters": [],
                    "phases": [],
                    "participants": [],
                    "request_response": None,
                    "summary": str(row["summary"] or "").strip(),
                }
            )

    other_routes: list[dict] = []
    for route_payload in route_payloads:
        route_keywords = _route_keywords(route_payload["path"])
        feature_name = None
        best_score = 0

        for candidate_feature, searchable in feature_search_strings.items():
            score = sum(1 for keyword in route_keywords if keyword and keyword in searchable)
            if score > best_score:
                best_score = score
                feature_name = candidate_feature

        if feature_name and best_score > 0 and feature_name in grouped_routes:
            grouped_routes[feature_name].append(route_payload)
        else:
            other_routes.append(route_payload)

    response_features = [
        {"name": feature_name, "routes": routes}
        for feature_name, routes in grouped_routes.items()
        if routes
    ]
    if other_routes:
        response_features.append({"name": "Other", "routes": other_routes})

    return {"mode": mode, "features": response_features}


@router.post("/{project_id}/api-explorer/routes/{route_id}/enrich")
async def enrich_api_explorer_route(project_id: str, route_id: str, db: Session = Depends(get_db)):
    route_row = (
        db.query(RouteAnalysis)
        .filter(
            RouteAnalysis.project_id == project_id,
            RouteAnalysis.route_id == route_id,
        )
        .first()
    )
    if not route_row:
        raise HTTPException(status_code=404, detail="Route analysis not found")

    analysis = dict(route_row.analysis_data or {})
    existing = analysis.get("request_response")
    if isinstance(existing, dict):
        return existing

    try:
        analysis_file = str(analysis.get("file") or route_row.file or "")
        analysis_filename = _filename_only(analysis_file)

        file_rows = db.execute(
            text(
                """
                SELECT file_path, summary
                FROM file_index
                WHERE project_id = :project_id
                """
            ),
            {"project_id": project_id},
        ).mappings().all()

        file_summary = ""
        for row in file_rows:
            file_path = str(row["file_path"] or "")
            if _filename_only(file_path) == analysis_filename:
                file_summary = str(row["summary"] or "").strip()
                break

        request_response = await infer_request_response(analysis, file_summary)
        analysis["request_response"] = request_response
        route_row.analysis_data = analysis
        db.commit()
        return request_response
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enrich request/response details: {str(exc) or 'unknown error'}",
        ) from exc


@router.post("/{project_id}/api-explorer/files/enrich")
async def enrich_api_explorer_file(project_id: str, body: FileEnrichBody, db: Session = Depends(get_db)):
    try:
        _ensure_file_index_ui_analysis_column(db)

        target_filename = _filename_only(body.file_path)
        file_rows = db.execute(
            text(
                """
                SELECT file_path, file_type, summary, ui_analysis
                FROM file_index
                WHERE project_id = :project_id
                """
            ),
            {"project_id": project_id},
        ).mappings().all()

        matched_row = next(
            (
                row
                for row in file_rows
                if _filename_only(str(row["file_path"] or "")) == target_filename
            ),
            None,
        )
        if not matched_row:
            raise HTTPException(status_code=404, detail="File index entry not found")

        existing = matched_row["ui_analysis"]
        if isinstance(existing, dict):
            return existing

        prompt = f"""You are helping a junior developer understand a UI screen/component they need to work on.

File: {str(matched_row["file_path"] or "")}
Type: {str(matched_row["file_type"] or "other")}
Summary: {str(matched_row["summary"] or "").strip()}

Based on this, infer:
1. What data/props does this screen need to display?
2. What user interactions does it handle?
3. What does it produce or navigate to?

Return ONLY a JSON object, no markdown:
{{
  "inputs": {{
    "description": "One sentence: what this screen needs to work",
    "fields": [
      {{"field": "fieldName", "type": "string", "description": "what this is"}}
    ]
  }},
  "interactions": {{
    "description": "One sentence: what the user can do here",
    "actions": [
      {{"action": "button label or gesture", "description": "what happens"}}
    ]
  }},
  "outputs": {{
    "description": "One sentence: what this screen produces or where it leads"
  }}
}}
"""

        if not OPENAI_API_KEY:
            raise HTTPException(status_code=500, detail="UI analysis unavailable: missing OpenAI API key")

        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Return only valid JSON objects."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = response.choices[0].message.content or "{}"
        ui_analysis = json.loads(content)
        if not isinstance(ui_analysis, dict):
            raise ValueError("Model returned invalid UI analysis JSON")

        db.execute(
            text(
                """
                UPDATE file_index
                SET ui_analysis = CAST(:ui_analysis AS jsonb)
                WHERE project_id = :project_id
                  AND file_path = :file_path
                """
            ),
            {
                "project_id": project_id,
                "file_path": str(matched_row["file_path"] or ""),
                "ui_analysis": json.dumps(ui_analysis),
            },
        )
        db.commit()
        return ui_analysis
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze UI file: {str(exc) or 'unknown error'}",
        ) from exc


@router.get("/{project_id}/sequence/{route_id}")
def get_project_sequence(project_id: str, route_id: str, db: Session = Depends(get_db)):
    route_row = (
        db.query(RouteAnalysis)
        .filter(
            RouteAnalysis.project_id == project_id,
            RouteAnalysis.route_id == route_id,
        )
        .first()
    )
    if not route_row:
        raise HTTPException(status_code=404, detail="Route analysis not found")

    analysis = route_row.analysis_data if isinstance(route_row.analysis_data, dict) else {}
    return {
        "method": str(analysis.get("method") or route_row.method or "GET").upper(),
        "path": str(analysis.get("path") or route_row.path or ""),
        "handler": analysis.get("handler_function"),
        "complexity": str(analysis.get("complexity") or "simple"),
        "participants": analysis.get("participants", []) if isinstance(analysis.get("participants", []), list) else [],
        "phases": analysis.get("phases", []) if isinstance(analysis.get("phases", []), list) else [],
        "has_database": bool(analysis.get("has_database", False)),
        "has_external": bool(analysis.get("has_external", False)),
    }


@router.get("/{project_id}/indexing-status")
def get_indexing_status(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    row = db.execute(
        text(
            """
            SELECT status, total_files, indexed_files, started_at, completed_at, error_message
            FROM indexing_status
            WHERE project_id = :project_id
            """
        ),
        {"project_id": project_id},
    ).mappings().first()

    if not row:
        return {
            "status": "pending",
            "total_files": 0,
            "indexed_files": 0,
            "percentage": 0,
            "started_at": None,
            "completed_at": None,
            "error_message": None,
        }

    total_files = int(row["total_files"] or 0)
    indexed_files = int(row["indexed_files"] or 0)
    percentage = int((indexed_files / total_files) * 100) if total_files > 0 else 0
    return {
        "status": row["status"],
        "total_files": total_files,
        "indexed_files": indexed_files,
        "percentage": percentage,
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "error_message": row["error_message"],
    }


@router.delete("/{project_id}", status_code=200)
def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    db.execute(text("DELETE FROM dependency_graph WHERE project_id = :project_id"), {"project_id": project_id})
    db.execute(text("DELETE FROM file_index WHERE project_id = :project_id"), {"project_id": project_id})
    db.execute(text("DELETE FROM indexing_status WHERE project_id = :project_id"), {"project_id": project_id})
    db.execute(text("DELETE FROM feature_map WHERE project_id = :project_id"), {"project_id": project_id})
    db.query(SequenceDiagram).filter(SequenceDiagram.project_id == project_id).delete()
    db.query(RouteAnalysis).filter(RouteAnalysis.project_id == project_id).delete()
    db.execute(text("DELETE FROM project_understanding WHERE project_id = :project_id"), {"project_id": project_id})
    db.query(SimulationRun).filter(SimulationRun.project_id == project_id).delete()
    db.query(GraphEdge).filter(GraphEdge.project_id == project_id).delete()
    db.query(GraphNode).filter(GraphNode.project_id == project_id).delete()
    db.query(Scan).filter(Scan.project_id == project_id).delete()
    db.query(Upload).filter(Upload.project_id == project_id).delete()
    db.delete(project)
    db.commit()

    upload_dir = UPLOAD_DIR / project_id
    if upload_dir.is_dir():
        shutil.rmtree(upload_dir, ignore_errors=True)

    # Remove workspace folder for this project
    workspace = WORKSPACE_DIR / project_id
    if workspace.is_dir():
        shutil.rmtree(workspace, ignore_errors=True)

    return {"deleted": True}


@router.get("/{project_id}/dashboard", response_model=ProjectDashboardResponse)
def get_project_dashboard(project_id: str, refresh: bool = False, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    scan = db.query(Scan).filter(Scan.project_id == project_id).order_by(Scan.created_at.desc()).first()
    if not scan:
        raise HTTPException(status_code=404, detail="No scan found for this project")

    # ── Primary programming languages only ──
    # Strip config/markup/styling languages that aren't meaningful tech stack signals
    _NON_PRIMARY_LANGS: set[str] = {
        "Shell", "Makefile", "Dockerfile", "YAML", "JSON", "JSON with Comments",
        "Markdown", "Text", "XML", "TOML", "INI", "CSV", "HTML", "CSS",
        "SCSS", "Sass", "Less", "GraphQL", "Prisma", "SQL", "Batchfile",
        "PowerShell", "HCL", "Terraform", "Smarty", "Liquid", "Handlebars",
        "Jinja", "Protocol Buffer", "Thrift", "Cap'n Proto", "Ignore List",
        "Git Attributes", "EditorConfig", "Dotenv",
    }
    raw_languages: list[str] = scan.languages or []
    primary_languages = [l for l in raw_languages if l not in _NON_PRIMARY_LANGS]

    lang_stats = [
        LanguageStat(name=lang, percentage=round(100 / max(len(primary_languages), 1), 1))
        for lang in primary_languages
    ]

    # ── Components ──
    components = [str(c.get("name", "unknown")) for c in scan.components] if scan.components else []

    # ── Dependencies — flatten and filter noise ──
    _DEP_NOISE_PREFIXES = ("@types/", "@babel/", "@eslint/", "@jest/", "@testing-library/")
    _DEP_NOISE_EXACT: set[str] = {
        # dev tooling
        "eslint", "prettier", "jest", "webpack", "vite", "babel", "typescript",
        "nodemon", "ts-node", "ts-jest", "mocha", "chai", "supertest",
        "husky", "lint-staged", "concurrently", "cross-env", "rimraf",
        # generic utilities
        "lodash", "dotenv", "chalk", "debug", "uuid", "moment", "dayjs",
        "classnames", "clsx", "underscore",
        # build / bundler
        "rollup", "esbuild", "parcel", "turbo", "nx", "tsc",
        # type stubs (handled by prefix above but cover extras)
        "type-fest",
    }

    raw_deps = scan.dependencies or {}
    all_dep_names: list[str] = []
    for ecosystem_deps in raw_deps.values():
        if isinstance(ecosystem_deps, list):
            for dep in ecosystem_deps:
                if isinstance(dep, dict) and dep.get("name"):
                    all_dep_names.append(dep["name"])

    meaningful_deps: list[str] = []
    seen_deps: set[str] = set()
    for name in all_dep_names:
        lower = name.lower()
        if lower in seen_deps:
            continue
        if lower in _DEP_NOISE_EXACT:
            continue
        if any(lower.startswith(p) for p in _DEP_NOISE_PREFIXES):
            continue
        seen_deps.add(lower)
        meaningful_deps.append(name)

    deps = meaningful_deps[:10]

    # ── Routes preview ──
    # Try RouteAnalysis table first; fall back to scan.routes[] JSON
    routes_preview = []
    route_paths: list[str] = []
    route_analyses = db.query(RouteAnalysis).filter(RouteAnalysis.project_id == project_id).limit(6).all()
    if route_analyses:
        for ra in route_analyses:
            route_paths.append(f"{ra.method} {ra.path}")
            adata = ra.analysis_data or {}
            smry = adata.get("summary", {})
            routes_preview.append(
                RoutePreview(
                    method=ra.method,
                    path=ra.path,
                    summary=smry.get("description", smry.get("title", str(ra.path)))
                )
            )
    else:
        # Fall back to routes stored directly in the scan JSON
        for r in (scan.routes or [])[:6]:
            if not isinstance(r, dict):
                continue
            method = str(r.get("method", "GET"))
            path = str(r.get("path", ""))
            if not path:
                continue
            route_paths.append(f"{method} {path}")
            routes_preview.append(
                RoutePreview(
                    method=method,
                    path=path,
                    summary=str(r.get("summary", path))
                )
            )

    # ── Executive Summary via GPT ──
    # ── Executive Summary via GPT ──
    # ?refresh=true clears the cached summary so it regenerates fresh
    summary = project.executive_summary
    if refresh and summary:
        summary = None
        project.executive_summary = None
        db.commit()

    if not summary and OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)
            prompt = f"""You are analyzing a software project. Based on the data below, write 2-3 sentences in plain English explaining what this project actually does. Be specific. Mention the main purpose, who would use it, and what it connects to. Do not use technical jargon. Do not say "this project is called X". Just explain what it does.

Project name: {project.name}
Primary languages: {', '.join(primary_languages) or 'unknown'}
Key dependencies: {', '.join(deps) or 'none detected'}
Components detected: {', '.join(components) or 'none'}
Total routes: {len(scan.routes or [])}
Route paths: {', '.join(route_paths[:10]) or 'none'}"""

            res = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You explain the purpose of software repositories in plain English."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200,
                temperature=0.3
            )
            summary = (res.choices[0].message.content or "").strip()
            project.executive_summary = summary
            db.commit()
        except Exception as e:
            summary = f"Executive summary generation failed: {e}"

    if not summary:
        summary = "No executive summary available."

    # ── AI Insights ──
    # Check if insights exist, clear if refresh is True
    insights = project.insights
    if refresh and insights:
        insights = None
        project.insights = None
        db.commit()

    if not insights and OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)
            insights_prompt = f"""Analyze this codebase and return a JSON object with exactly these 4 fields:

{{
  "complexity": "Simple | Moderate | Complex",
  "complexity_reason": "one sentence explanation why",
  "entry_points": "X routes (Y public, Z protected)",
  "entry_points_detail": "one sentence about what kinds of requests this system handles",
  "external_services": ["list", "of", "external", "services", "detected"],
  "external_services_detail": "one sentence about what these services do in this project",
  "auth_summary": "one sentence about how authentication works in this project or 'No authentication detected'"
}}

Codebase data:
- Project: {project.name}
- Languages: {', '.join(primary_languages) or 'unknown'}
- Dependencies: {', '.join(deps) or 'none detected'}
- Routes: {', '.join(route_paths[:10]) or 'none'}
- Components: {', '.join(components) or 'none'}
- Total files: {scan.file_count or 0}

Return only valid JSON. No markdown. No explanation."""

            res = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a senior technical architect analyzing a codebase. Produce exact JSON output only."},
                    {"role": "user", "content": insights_prompt}
                ],
                max_tokens=300,
                temperature=0.2,
                response_format={ "type": "json_object" }
            )
            raw_content = res.choices[0].message.content
            if raw_content:
                insights_json = json.loads(raw_content.strip())
                project.insights = insights_json
                db.commit()
                insights = insights_json
        except Exception as e:
            print(f"[dashboard] AI Insights generation failed: {e}")

    return ProjectDashboardResponse(
        project_name=project.name,
        executive_summary=summary,
        languages=lang_stats,
        dependencies=deps,
        total_routes=len(scan.routes or []),
        total_files=scan.file_count,
        components=components,
        routes_preview=routes_preview,
        insights=insights
    )



@router.post("/{project_id}/dashboard/chat", response_model=DashboardChatResponse)
def chat_project_dashboard(project_id: str, request: DashboardChatRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not OPENAI_API_KEY:
        return DashboardChatResponse(response="AI Architect is currently unavailable due to missing API key.")

    # Contextual boundary
    dashboard_data = get_project_dashboard(project_id, db).model_dump()
    
    system_prompt = f"""You are the 'AI Architect' for a project named {dashboard_data['project_name']}.
Dashboard Context:
Executive Summary: {dashboard_data['executive_summary']}
Languages: {[l['name'] for l in dashboard_data['languages']]}
Dependencies: {dashboard_data['dependencies']}
Total Routes: {dashboard_data['total_routes']}
Total Files: {dashboard_data['total_files']}
Components: {dashboard_data['components']}
Routes Preview: {dashboard_data['routes_preview']}

Answer user questions briefly, grounded precisely on this dashboard context. Do not guess."""

    messages_payload = [{"role": "system", "content": system_prompt}]
    for msg in request.messages:
        messages_payload.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        res = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages_payload,
            max_tokens=500,
            temperature=0.5
        )
        return DashboardChatResponse(response=(res.choices[0].message.content or "").strip())
    except Exception as e:
        return DashboardChatResponse(response=f"Failed to query AI: {e}")
