import asyncio
import os
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from openai import OpenAI

from app.db.session import get_db
from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.models.project import Project
from app.models.scan import Scan
from app.models.project_understanding import ProjectUnderstanding
from app.schemas import ProjectUnderstandingResponse, UnderstandingChatRequest, UnderstandingChatResponse
from app.services.understanding_generator import generate_understanding_backend
from app.services.scanner_v3 import unwrap_root_dir
from app.config import WORKSPACE_DIR

router = APIRouter(prefix="/projects/{project_id}/understanding", tags=["understanding"])
logger = logging.getLogger(__name__)


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
def chat_understanding(project_id: str, request: UnderstandingChatRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    understanding = project.understanding
    if not understanding:
        raise HTTPException(status_code=404, detail="Understanding not generated yet")

    if not OPENAI_API_KEY:
        return UnderstandingChatResponse(response="AI Chat is unavailable (Missing API Key)")

    # Fetch context based on requested section
    section_data = ""
    target_section = request.section.lower().strip()
    
    if "story" in target_section:
        section_data = understanding.project_story
    elif "map" in target_section:
        section_data = str(understanding.system_map)
    elif "journey" in target_section:
        section_data = str(understanding.data_journey)
    elif "decision" in target_section:
        section_data = str(understanding.key_decisions)
    elif "gotcha" in target_section:
        section_data = str(understanding.gotchas)
    elif "glossary" in target_section:
        section_data = str(understanding.glossary)
    else:
        # Fallback to all text representations if section unclear
        section_data = f"Story: {understanding.project_story}\nGlossary: {understanding.glossary}"

    latest_scan, _, effective_root = _latest_scan_and_workspace(project)
    route_paths: list[str] = []
    dependencies: list[str] = []
    languages: list[str] = []
    if latest_scan:
        languages = latest_scan.languages or []
        route_paths = [
            f"{str(r.get('method', 'GET'))} {str(r.get('path', ''))}"
            for r in (latest_scan.routes or [])
            if isinstance(r, dict) and r.get("path")
        ][:30]

        dep_seen: set[str] = set()
        raw_deps = latest_scan.dependencies or {}
        if isinstance(raw_deps, dict):
            for value in raw_deps.values():
                if not isinstance(value, list):
                    continue
                for dep in value:
                    dep_name = dep.get("name") if isinstance(dep, dict) else dep
                    if isinstance(dep_name, str):
                        lowered = dep_name.lower().strip()
                        if lowered and lowered not in dep_seen:
                            dep_seen.add(lowered)
                            dependencies.append(dep_name)
        dependencies = dependencies[:40]

    top_files = _extract_top_file_paths(understanding, latest_scan, max_files=3)
    actual_file_contents = _read_file_contents(effective_root, top_files, max_lines=220)

    all_understanding_sections = {
        "project_story": understanding.project_story,
        "system_map": understanding.system_map,
        "data_journey": understanding.data_journey,
        "key_decisions": understanding.key_decisions,
        "gotchas": understanding.gotchas,
        "glossary": understanding.glossary,
    }

    system_prompt = f"""
You are an expert software architect who has deeply analyzed the {project.name} codebase.

You have complete knowledge of this project:

FULL PROJECT UNDERSTANDING:
{json.dumps(all_understanding_sections, ensure_ascii=False)}

ACTUAL SOURCE CODE (key files):
{json.dumps(actual_file_contents, ensure_ascii=False)}

ROUTES: {json.dumps(route_paths, ensure_ascii=False)}
DEPENDENCIES: {json.dumps(dependencies, ensure_ascii=False)}
LANGUAGES: {json.dumps(languages, ensure_ascii=False)}

RULES:
- Never just repeat what is already displayed to the user
- Always go DEEPER than the surface level
- Reference actual file names, function names, line patterns from the code
- Explain the WHY behind architectural decisions
- When asked about a flow, trace it through actual code, not abstract steps
- If asked what could go wrong, look at actual error handling in the code
- Keep answers focused: 3-6 sentences for simple questions, more for complex ones
- If you genuinely don't know something from the provided context, say so honestly

Response style:
- Start with a direct answer, not "Great question!"
- Use specific examples from the actual code
- Mention actual file paths when relevant
- If explaining a flow, number the steps
- End with a follow-up insight the user might not have thought to ask

Current section the user is reading: {target_section}
Current section data: {section_data}
"""

    history = request.history or []
    history_messages: list[dict[str, str]] = []
    for item in history:
        role = item.get("role", "")
        content = item.get("content", "")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            history_messages.append({"role": role, "content": content})

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        res = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                *history_messages,
                {"role": "user", "content": request.message},
            ],
            max_tokens=400,
            temperature=0.3
        )
        return UnderstandingChatResponse(response=(res.choices[0].message.content or "").strip())
    except Exception as e:
        return UnderstandingChatResponse(response=f"Error checking AI: {e}")
