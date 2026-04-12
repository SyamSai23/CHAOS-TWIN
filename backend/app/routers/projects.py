import shutil
import json
from fastapi import APIRouter, Depends, HTTPException
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
from app.schemas import ProjectCreate, ProjectResponse, ProjectDashboardResponse, DashboardChatRequest, DashboardChatResponse, RoutePreview, LanguageStat

from openai import AsyncOpenAI, OpenAI
from app.config import OPENAI_API_KEY, OPENAI_MODEL

router = APIRouter(prefix="/projects", tags=["projects"])


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


@router.get("", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@router.get("/{project_id}/search")
async def search_project(project_id: str, q: str, limit: int = 8, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    return await semantic_search(project_id, q.strip(), max(1, min(limit, 20)), db)


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

    # Delete related DB rows (order matters due to FK constraints)
    # 1. sequence_diagrams (FK → projects, scans)
    db.query(SequenceDiagram).filter(SequenceDiagram.project_id == project_id).delete()
    # 2. route_analyses (FK → projects, scans)
    db.query(RouteAnalysis).filter(RouteAnalysis.project_id == project_id).delete()
    # 3. simulation_runs (FK → projects, scans, graph_nodes)
    db.query(SimulationRun).filter(SimulationRun.project_id == project_id).delete()
    # 4. graph_edges (FK → graph_nodes)
    db.query(GraphEdge).filter(GraphEdge.project_id == project_id).delete()
    # 5. graph_nodes (FK → scans)
    db.query(GraphNode).filter(GraphNode.project_id == project_id).delete()
    # 6. scans (FK → uploads)
    db.query(Scan).filter(Scan.project_id == project_id).delete()

    # 7. uploads
    db.query(Upload).filter(Upload.project_id == project_id).delete()

    # 8. Delete the project itself
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
