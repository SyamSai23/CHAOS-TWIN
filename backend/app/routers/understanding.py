import asyncio
import os
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from openai import AsyncOpenAI

from app.db.session import get_db
from app.config import OPENAI_API_KEY
from app.models.project import Project
from app.models.scan import Scan
from app.models.project_understanding import ProjectUnderstanding
from app.schemas import ProjectUnderstandingResponse, UnderstandingChatRequest, UnderstandingChatResponse
from app.services.understanding_generator import generate_understanding_backend
from app.services.scanner_v3 import unwrap_root_dir
from app.config import WORKSPACE_DIR

router = APIRouter(prefix="/projects/{project_id}/understanding", tags=["understanding"])
logger = logging.getLogger(__name__)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def _latest_scan_and_workspace(project: Project):
    latest_scan = next(iter(sorted(project.scans, key=lambda s: s.created_at, reverse=True)), None)
    upload = next(iter(sorted(project.uploads, key=lambda s: s.created_at, reverse=True)), None)
    if not latest_scan or not upload:
        return None, None, None

    project_workspace_dir = os.path.join(str(WORKSPACE_DIR), project.id)
    workspace_path = os.path.join(project_workspace_dir, upload.id)
    effective_root = unwrap_root_dir(workspace_path)

    scan_dict = {
        "files": latest_scan.files,
        "import_graph": latest_scan.import_graph,
        "dependencies": latest_scan.dependencies,
        "routes": latest_scan.routes,
        "components": latest_scan.components,
    }
    return latest_scan, scan_dict, effective_root


def _extract_top_file_paths(understanding: ProjectUnderstanding, latest_scan: Optional[Scan], max_files: int = 3) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    system_map = understanding.system_map if isinstance(understanding.system_map, list) else []
    for component in system_map:
        if not isinstance(component, dict):
            continue
        key_files = component.get("key_files", [])
        if isinstance(key_files, list):
            for path in key_files:
                if isinstance(path, str) and path.strip() and path not in seen:
                    seen.add(path)
                    candidates.append(path)
                    if len(candidates) >= max_files:
                        return candidates

    if latest_scan:
        for path in (latest_scan.key_files or []):
            if isinstance(path, str) and path.strip() and path not in seen:
                seen.add(path)
                candidates.append(path)
                if len(candidates) >= max_files:
                    return candidates

        for item in (latest_scan.files or []):
            if isinstance(item, dict):
                path = item.get("path")
            else:
                path = item
            if isinstance(path, str) and path.strip() and path not in seen:
                seen.add(path)
                candidates.append(path)
                if len(candidates) >= max_files:
                    return candidates

    return candidates[:max_files]


def _read_file_contents(effective_root: Optional[str], file_paths: list[str], max_lines: int = 220) -> dict[str, str]:
    if not effective_root:
        return {}
    contents: dict[str, str] = {}
    for rel_path in file_paths:
        full_path = os.path.join(effective_root, rel_path)
        try:
            with open(full_path, "r", errors="ignore") as f:
                lines = f.readlines()[:max_lines]
            contents[rel_path] = "".join(lines)
        except Exception:
            continue
    return contents


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


async def semantic_search(project_id: str, query: str, db: Session, top_k: int = 8) -> list[dict[str, Any]]:
    try:
        if not openai_client:
            return []

        response = await openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=query,
        )
        query_embedding = response.data[0].embedding
        vector_literal = _vector_literal(query_embedding)

        results = db.execute(
            text(
                """
                SELECT file_path, file_type, summary, importance_score,
                       1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM file_index
                WHERE project_id = :project_id
                  AND embedding IS NOT NULL
                  AND summary IS NOT NULL
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :top_k
                """
            ),
            {
                "project_id": project_id,
                "embedding": vector_literal,
                "top_k": top_k,
            },
        ).mappings().all()

        return [
            {
                "file_path": str(row.get("file_path") or ""),
                "file_type": str(row.get("file_type") or ""),
                "summary": str(row.get("summary") or "").strip(),
                "importance_score": float(row.get("importance_score") or 0),
                "similarity": float(row.get("similarity") or 0),
            }
            for row in results
            if row.get("file_path") and row.get("summary")
        ]
    except Exception as exc:
        logger.error("Semantic search failed for project %s: %s", project_id, exc)
        return []


async def find_relevant_routes(project_id: str, query: str, db: Session) -> list[dict[str, Any]]:
    try:
        query_lower = query.lower()
        route_intent = any(token in query_lower for token in ["route", "endpoint", "api", "request", "post", "get", "put", "patch", "delete", "/"])

        route_rows = db.execute(
            text(
                """
                SELECT method, path, file, analysis_data
                FROM route_analyses
                WHERE project_id = :project_id
                LIMIT 20
                """
            ),
            {"project_id": project_id},
        ).mappings().all()

        relevant: list[dict[str, Any]] = []
        for row in route_rows:
            path = str(row.get("path") or "")
            analysis = row.get("analysis_data") if isinstance(row.get("analysis_data"), dict) else {}
            phases = analysis.get("phases") if isinstance(analysis.get("phases"), list) else []
            error_paths = analysis.get("error_paths") if isinstance(analysis.get("error_paths"), list) else []
            total_steps = 0
            db_read_steps = 0
            db_write_steps = 0
            external_calls = 0
            for phase in phases:
                if not isinstance(phase, dict):
                    continue
                steps = phase.get("steps") if isinstance(phase.get("steps"), list) else []
                total_steps += len(steps)
                for step in steps:
                    if not isinstance(step, dict):
                        continue
                    step_type = str(step.get("type") or "").lower()
                    if step_type == "db_read":
                        db_read_steps += 1
                    elif step_type == "db_write":
                        db_write_steps += 1
                    elif step_type == "external":
                        external_calls += 1
            path_segments = path.replace("/", " ").replace(":", " ").replace("{", " ").replace("}", " ").lower()
            segment_match = any(segment in query_lower for segment in path_segments.split() if len(segment) > 2)
            if not segment_match and not route_intent:
                continue
            if not segment_match and route_intent and path:
                # For route-centric questions without a specific path, keep a few high-signal routes.
                if len(relevant) >= 5:
                    continue

            relevant.append(
                {
                    "method": str(row.get("method") or "GET").upper(),
                    "path": path,
                    "handler": str(analysis.get("handler_function") or row.get("file") or ""),
                    "complexity": str(analysis.get("complexity") or "unknown"),
                    "phase_count": len(phases),
                    "total_steps": total_steps,
                    "db_read_steps": db_read_steps,
                    "db_write_steps": db_write_steps,
                    "error_path_count": len(error_paths),
                    "has_external_calls": external_calls > 0,
                }
            )
            if len(relevant) >= 5:
                break

        return relevant
    except Exception as exc:
        logger.error("Relevant route lookup failed for project %s: %s", project_id, exc)
        return []


async def find_relevant_features(project_id: str, query: str, db: Session) -> list[dict[str, Any]]:
    try:
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

        feature_list = feature_row.get("features") if feature_row and isinstance(feature_row.get("features"), list) else []
        if not feature_list:
            return []

        query_lower = query.lower()
        relevant: list[dict[str, Any]] = []
        for feature in feature_list:
            if not isinstance(feature, dict):
                continue
            name = str(feature.get("name") or feature.get("feature_name") or "")
            description = str(feature.get("description") or "")
            haystack = f"{name} {description}".lower()
            if any(word in haystack for word in query_lower.split() if len(word) > 3):
                files_detail = feature.get("files_detail") if isinstance(feature.get("files_detail"), list) else []
                files = feature.get("files") if isinstance(feature.get("files"), list) else []
                relevant.append(
                    {
                        "name": name,
                        "description": description,
                        "file_count": len(files_detail) or len(files),
                    }
                )
            if len(relevant) >= 3:
                break

        return relevant
    except Exception as exc:
        logger.error("Relevant feature lookup failed for project %s: %s", project_id, exc)
        return []


def build_grounded_prompt(
    user_question: str,
    relevant_files: list[dict[str, Any]],
    relevant_routes: list[dict[str, Any]],
    relevant_features: list[dict[str, Any]],
    project_understanding: str,
    page_context: Optional[dict[str, Any]] = None,
) -> str:
    sections: list[str] = []

    if project_understanding:
        sections.append(f"PROJECT OVERVIEW:\n{project_understanding[:800]}")

    if page_context:
        page_description = str(page_context.get("description") or "").strip()
        if page_description:
            sections.append(f"USER IS CURRENTLY VIEWING:\n{page_description}")

    if relevant_files:
        file_context = "RELEVANT FILES FROM CODEBASE:\n"
        for item in relevant_files:
            file_context += f"- [{item['file_type']}] {item['file_path']}\n"
            file_context += f"  {item['summary']}\n"
        sections.append(file_context.rstrip())

    if relevant_routes:
        route_context = "RELEVANT API ROUTES:\n"
        for item in relevant_routes:
            route_context += (
                f"- {item['method']} {item['path']} "
                f"(handler: {item['handler']}, complexity: {item['complexity']}, "
                f"phases: {item['phase_count']}, total_steps: {item['total_steps']}, "
                f"db_reads: {item['db_read_steps']}, db_writes: {item['db_write_steps']}, "
                f"error_paths: {item['error_path_count']}, external_calls: {item['has_external_calls']})\n"
            )
        sections.append(route_context.rstrip())

    if relevant_features:
        feature_context = "RELEVANT FEATURES:\n"
        for item in relevant_features:
            feature_context += (
                f"- {item['name']}: {item['description']} "
                f"({item['file_count']} files)\n"
            )
        sections.append(feature_context.rstrip())

    context_block = "\n\n".join(section for section in sections if section.strip())

    return f"""You are Codebase Copilot — an expert assistant that helps developers understand a specific codebase. You have been given real data extracted from this codebase. Use it to give precise, grounded answers.

RULES:
- Every claim you make must be based on the context provided below
- When you mention a file, always include its full path in backticks
- When you mention a route, include the method and path
- If the answer is not in the provided context, say "I don't have enough information about that in the indexed data" — never guess
- When asked comparative questions like "which is most/least/riskiest", reason from the actual data provided — count steps, database calls, error paths — do not just report labels; make a concrete recommendation with reasoning
- Write for a junior developer — clear, plain English, no jargon without explanation
- Keep answers focused and under 300 words unless the question requires more detail
- Structure your answer: one paragraph explanation, then bullet points for specifics if needed

USER QUESTION:
{user_question}

CODEBASE CONTEXT:
{context_block}"""

@router.get("", response_model=ProjectUnderstandingResponse)
async def get_understanding(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    understanding = project.understanding
    if not understanding:
        raise HTTPException(status_code=404, detail="Understanding not generated yet")

    # Auto-recover stale jobs that got stuck in "generating" (e.g. process reload/interruption).
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(minutes=2)
    if understanding.status == "generating" and understanding.generated_at and understanding.generated_at < stale_cutoff:
        understanding.status = "pending"
        understanding.generated_at = now
        db.commit()
        db.refresh(understanding)

        _, scan_dict, effective_root = _latest_scan_and_workspace(project)
        if scan_dict and effective_root:
            asyncio.create_task(generate_understanding_backend(project_id, scan_dict, effective_root))
        else:
            logger.warning(
                "Could not restart stale understanding generation for project %s: missing scan or upload",
                project_id,
            )

    return understanding

@router.post("/generate")
async def generate_understanding(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    latest_scan = next(iter(sorted(project.scans, key=lambda s: s.created_at, reverse=True)), None)
    if not latest_scan:
        raise HTTPException(status_code=400, detail="Project has no completed scans")
        
    upload = next(iter(sorted(project.uploads, key=lambda s: s.created_at, reverse=True)), None)
    if not upload:
        raise HTTPException(status_code=400, detail="Project has no uploads")

    project_workspace_dir = os.path.join(str(WORKSPACE_DIR), project_id)
    workspace_path = os.path.join(project_workspace_dir, upload.id)
    effective_root = unwrap_root_dir(workspace_path)
    
    # We pass the scan schema as a dict
    scan_dict = {
        "files": latest_scan.files,
        "import_graph": latest_scan.import_graph,
        "dependencies": latest_scan.dependencies,
        "routes": latest_scan.routes,
        "components": latest_scan.components
    }

    existing = db.query(ProjectUnderstanding).filter(ProjectUnderstanding.project_id == project_id).first()
    if not existing:
        existing = ProjectUnderstanding(project_id=project_id, status="pending", generated_at=datetime.now(timezone.utc))
        db.add(existing)
    else:
        existing.status = "pending"
        existing.generated_at = datetime.now(timezone.utc)
    db.commit()

    asyncio.create_task(generate_understanding_backend(project_id, scan_dict, effective_root))

    return {"status": "Generating in background"}

@router.post("/chat", response_model=UnderstandingChatResponse)
async def chat_understanding(project_id: str, request: UnderstandingChatRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    understanding = project.understanding
    if not understanding:
        raise HTTPException(status_code=404, detail="Understanding not generated yet")

    try:
        if not openai_client:
            return UnderstandingChatResponse(
                response="I encountered an error processing your question. Please try again.",
                sources=[],
            )

        project_story = str(understanding.project_story or "")

        relevant_files, relevant_routes, relevant_features = await asyncio.gather(
            semantic_search(project_id, request.message, db),
            find_relevant_routes(project_id, request.message, db),
            find_relevant_features(project_id, request.message, db),
            return_exceptions=True,
        )

        if isinstance(relevant_files, Exception):
            logger.error("Relevant file retrieval failed for project %s: %s", project_id, relevant_files)
            relevant_files = []
        if isinstance(relevant_routes, Exception):
            logger.error("Relevant route retrieval failed for project %s: %s", project_id, relevant_routes)
            relevant_routes = []
        if isinstance(relevant_features, Exception):
            logger.error("Relevant feature retrieval failed for project %s: %s", project_id, relevant_features)
            relevant_features = []

        system_prompt = build_grounded_prompt(
            user_question=request.message,
            relevant_files=relevant_files,
            relevant_routes=relevant_routes,
            relevant_features=relevant_features,
            project_understanding=project_story,
            page_context=request.page_context,
        )

        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for item in (request.history or [])[-6:]:
            role = item.get("role", "")
            content = item.get("content", "")
            if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": request.message})

        res = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                *messages,
            ],
            max_tokens=600,
            temperature=0.3,
        )
        answer = (res.choices[0].message.content or "").strip()
        return UnderstandingChatResponse(
            response=answer,
            sources=[
                {
                    "file_path": item["file_path"],
                    "file_type": item["file_type"],
                    "summary": item["summary"],
                }
                for item in relevant_files[:4]
            ],
        )
    except Exception as exc:
        logger.error("Chat failed for project %s: %s", project_id, exc)
        return UnderstandingChatResponse(
            response="I encountered an error processing your question. Please try again.",
            sources=[],
        )
