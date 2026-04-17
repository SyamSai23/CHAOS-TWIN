import os
import json
import logging
from datetime import datetime, timezone
import asyncio
from typing import Any, Optional
import re

from sqlalchemy.orm import Session
from sqlalchemy import text
from openai import AsyncOpenAI
from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.db.session import SessionLocal
from app.models.project import Project
from app.models.project_understanding import ProjectUnderstanding

logger = logging.getLogger(__name__)

# GPT-4o context window is 128K tokens
# Reserve 4000 tokens for the response output
# Reserve 1000 tokens for system prompt overhead
GPT4O_MAX_CONTEXT = 128000
RESPONSE_RESERVE = 5000
MAX_PROMPT_TOKENS = GPT4O_MAX_CONTEXT - RESPONSE_RESERVE  # ~123000 tokens

def update_status(project_id: str, status: str, db_session: Session = None):
    # Helper to push status to the database
    local_db = False
    if not db_session:
        local_db = True
        db_session = SessionLocal()
    try:
        understanding = db_session.query(ProjectUnderstanding).filter(ProjectUnderstanding.project_id == project_id).first()
        if not understanding:
            understanding = ProjectUnderstanding(project_id=project_id, status=status)
            db_session.add(understanding)
        else:
            understanding.status = status
            
        # Track lifecycle timestamps so stale "generating" states can be recovered.
        if status in {"generating", "complete"}:
            understanding.generated_at = datetime.now(timezone.utc)

        db_session.commit()
    except Exception as e:
        logger.error(f"Failed to update understanding status: {e}")
        db_session.rollback()
    finally:
        if local_db:
            db_session.close()


_DEPTH_TIER_FIELDS = (
    "project_story_beginner",
    "project_story_intermediate",
    "project_story_advanced",
    "key_decisions_beginner",
    "key_decisions_intermediate",
    "key_decisions_advanced",
    "gotchas_beginner",
    "gotchas_intermediate",
    "gotchas_advanced",
)


def understanding_has_depth_tiers(understanding: Optional[ProjectUnderstanding]) -> bool:
    if understanding is None:
        return False
    return all(getattr(understanding, field) is not None for field in _DEPTH_TIER_FIELDS)


def _strip_json_fences(payload: str) -> str:
    return re.sub(r"```json|```", "", payload or "").strip()


def _parse_json_object(payload: str) -> dict[str, Any]:
    parsed = json.loads(_strip_json_fences(payload) or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object")
    return parsed


def _parse_json_array(payload: str) -> list[dict[str, Any]]:
    parsed = json.loads(_strip_json_fences(payload) or "[]")
    if not isinstance(parsed, list):
        raise ValueError("Expected JSON array")
    return [item for item in parsed if isinstance(item, dict)]


async def generate_depth_tiers(project_id: str, db_session: Session) -> str:
    understanding = (
        db_session.query(ProjectUnderstanding)
        .filter(ProjectUnderstanding.project_id == project_id)
        .first()
    )
    if not understanding:
        raise ValueError("Understanding not generated yet")

    if understanding_has_depth_tiers(understanding):
        return "cached"

    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required for depth tier generation")

    existing_project_story = understanding.project_story or ""
    existing_key_decisions = understanding.key_decisions or []
    existing_gotchas = understanding.gotchas or []

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    story_prompt = f"""
You are explaining a software project to different audiences.

Original project story:
{existing_project_story}

Rewrite this for THREE different audience levels. Return ONLY a JSON object:
{{
  "beginner": "2-3 sentences using simple analogies. No technical terms. Compare to everyday things. Example: 'This app is like a digital library where...'",
  "intermediate": "3-4 sentences with technical context but no deep implementation details. Name the frameworks and patterns used.",
  "advanced": "4-5 sentences covering architecture decisions, tradeoffs, scalability considerations, and non-obvious design choices."
}}
"""

    decisions_prompt = f"""
You are explaining architectural decisions to different audiences.

Original key decisions:
{json.dumps(existing_key_decisions)}

For each decision, rewrite the explanation for THREE audience levels.
Return ONLY a JSON array with the same number of items:
[
  {{
    "title": "same title",
    "beginner": "Plain English. Use analogies. Why does this matter to a non-technical person?",
    "intermediate": "Technical summary with the key pattern named. What problem does it solve?",
    "advanced": "Deep tradeoffs, alternatives considered, performance/scaling implications, edge cases."
  }}
]
"""

    gotchas_prompt = f"""
You are explaining code gotchas/warnings to different audiences.

Original gotchas:
{json.dumps(existing_gotchas)}

For each gotcha, rewrite for THREE audience levels.
Return ONLY a JSON array:
[
  {{
    "title": "same title",
    "beginner": "Simple warning in plain English. What could go wrong and why should they care?",
    "intermediate": "Technical description of the issue with the specific file/function named.",
    "advanced": "Root cause, potential failure modes, how to properly fix it, related patterns to watch for."
  }}
]
"""

    async def generate_story_tiers() -> dict[str, Any]:
        res = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You return only valid JSON objects."},
                {"role": "user", "content": story_prompt},
            ],
            max_tokens=2500,
            response_format={"type": "json_object"},
        )
        return _parse_json_object(res.choices[0].message.content or "{}")

    async def generate_key_decision_tiers() -> list[dict[str, Any]]:
        res = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You return only valid JSON arrays."},
                {"role": "user", "content": decisions_prompt},
            ],
            max_tokens=4000,
        )
        return _parse_json_array(res.choices[0].message.content or "[]")

    async def generate_gotcha_tiers() -> list[dict[str, Any]]:
        res = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You return only valid JSON arrays."},
                {"role": "user", "content": gotchas_prompt},
            ],
            max_tokens=4000,
        )
        return _parse_json_array(res.choices[0].message.content or "[]")

    story_tiers, decision_tiers, gotcha_tiers = await asyncio.gather(
        generate_story_tiers(),
        generate_key_decision_tiers(),
        generate_gotcha_tiers(),
    )

    understanding.project_story_beginner = str(story_tiers.get("beginner", "") or "")
    understanding.project_story_intermediate = str(story_tiers.get("intermediate", "") or "")
    understanding.project_story_advanced = str(story_tiers.get("advanced", "") or "")

    understanding.key_decisions_beginner = [
        {"title": item.get("title", ""), "beginner": item.get("beginner", "")}
        for item in decision_tiers
    ]
    understanding.key_decisions_intermediate = [
        {"title": item.get("title", ""), "intermediate": item.get("intermediate", "")}
        for item in decision_tiers
    ]
    understanding.key_decisions_advanced = [
        {"title": item.get("title", ""), "advanced": item.get("advanced", "")}
        for item in decision_tiers
    ]

    understanding.gotchas_beginner = [
        {"title": item.get("title", ""), "beginner": item.get("beginner", "")}
        for item in gotcha_tiers
    ]
    understanding.gotchas_intermediate = [
        {"title": item.get("title", ""), "intermediate": item.get("intermediate", "")}
        for item in gotcha_tiers
    ]
    understanding.gotchas_advanced = [
        {"title": item.get("title", ""), "advanced": item.get("advanced", "")}
        for item in gotcha_tiers
    ]

    understanding.generated_at = datetime.now(timezone.utc)
    db_session.commit()
    db_session.refresh(understanding)
    return "generated"


def _estimate_tokens(prompt: str) -> int:
    return len(prompt) // 4


def _content_head(content: str, max_lines: int) -> str:
    return "\n".join((content or "").splitlines()[:max_lines])


def _load_indexed_file_context(
    project_id: str,
    db: Session,
    *,
    max_files: int = 12,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT
                file_path,
                file_type,
                domain_area,
                summary,
                exports,
                key_concepts,
                full_content,
                line_count,
                importance_score
            FROM file_index
            WHERE project_id = :project_id
            ORDER BY importance_score DESC, line_count DESC, file_path ASC
            LIMIT :limit
            """
        ),
        {"project_id": project_id, "limit": max_files},
    ).mappings().all()

    indexed_files: list[dict[str, Any]] = []
    for row in rows:
        indexed_files.append(
            {
                "path": row["file_path"],
                "file_type": row["file_type"] or "other",
                "domain_area": row["domain_area"] or "other",
                "summary": row["summary"] or "",
                "exports": list(row["exports"] or []),
                "key_concepts": list(row["key_concepts"] or []),
                "content": row["full_content"] or "",
                "line_count": int(row["line_count"] or 0),
                "importance_score": float(row["importance_score"] or 0),
            }
        )
    return indexed_files


async def shallow_read_all_files(effective_root: str, file_list: list[str]) -> dict[str, str]:
    snippets: dict[str, str] = {}

    for file_path in file_list[:60]:
        full_path = os.path.join(effective_root, file_path)
        if not os.path.isfile(full_path):
            continue
        try:
            with open(full_path, "r", errors="ignore") as f:
                content = f.read(3000)
            lines = content.split("\n")[:20]
            snippets[file_path] = "\n".join(lines)
        except Exception:
            continue

    return snippets


def _score_shallow_file(path: str) -> int:
    # Path-only prefilter used before snippet reads; universal scoring is applied after previews are loaded.
    lower = path.lower()
    score = 0

    if any(part in lower for part in ["/src/", "/app/", "/backend/", "/mobile/", "/frontend/"]):
        score += 40
    if any(part in lower for part in ["/routes", "/routers", "/controllers", "/services", "/agent", "/tools", "/models"]):
        score += 50
    if any(part in lower for part in ["/data/", "/assets/", "/public/", "/node_modules/"]):
        score -= 40
    if any(name in lower for name in ["readme", "license", ".gitignore", "yarn.lock", "package-lock", "uv.lock", "codelab", "makefile"]):
        score -= 120
    if lower.endswith(("package.json", "pyproject.toml", "vite.config.ts", "vite.config.js", "tailwind.config.cjs", "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json", "app.json", "babel.config.js")):
        score -= 80
    if any(name in lower for name in ["test", "spec", "__tests__", ".test.", ".spec."]):
        score -= 200

    if lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
        score += 60
    elif lower.endswith((".json", ".toml", ".yml", ".yaml", ".css", ".md", ".svg", ".png", ".jpg", ".ico")):
        score -= 20

    if lower.endswith(("main.py", "app.py", "server.js", "server.ts", "index.js", "index.ts", "app.js", "app.ts", "routes.js", "routes.ts")):
        score += 45

    return score


def _score_file_universally(path: str, content_preview: str) -> int:
    score = 0
    lines = content_preview.split("\n")

    # More non-empty, non-import lines usually means more business logic.
    logic_lines = [
        line for line in lines
        if line.strip()
        and not line.strip().startswith(("import", "from", "//", "#", "*"))
        and len(line.strip()) > 10
    ]
    score += len(logic_lines) * 3

    # Conditional/branching logic.
    if any(kw in content_preview for kw in ["if ", "else", "switch", "match", "try", "catch", "except"]):
        score += 20

    # Function/class definitions are a useful universal signal.
    if any(kw in content_preview for kw in ["def ", "function ", "class ", "async ", "=>"]):
        score += 15

    # Entry points are often important regardless of framework.
    lower_path = path.lower()
    if any(name in lower_path for name in ["main", "index", "app", "server", "init"]):
        score += 25

    # Tests should never be selected as top deep-read files.
    if any(name in lower_path for name in ["test", "spec", "__mock__", "fixture"]):
        score -= 500

    return score


def _imported_by_count_map(import_graph: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(import_graph, dict):
        return counts

    file_level = import_graph.get("file_level")
    if isinstance(file_level, list):
        for edge in file_level:
            if not isinstance(edge, dict):
                continue
            target = edge.get("to")
            if isinstance(target, str) and target.strip():
                counts[target] = counts.get(target, 0) + 1
    return counts


def _prioritize_shallow_files(file_records: list[dict[str, Any]], max_files: int = 60) -> list[str]:
    ranked = sorted(
        (str(file.get("path", "")) for file in file_records if isinstance(file.get("path"), str)),
        key=lambda path: (_score_shallow_file(path), path),
        reverse=True,
    )
    deduped: list[str] = []
    seen: set[str] = set()
    for path in ranked:
        if not path or path in seen:
            continue
        seen.add(path)
        deduped.append(path)
        if len(deduped) >= max_files:
            break
    return deduped


def _is_boilerplate_selection(path: str) -> bool:
    lower = path.lower()
    return any(
        token in lower
        for token in [
            "readme",
            "license",
            ".gitignore",
            "package-lock",
            "yarn.lock",
            "uv.lock",
            "makefile",
            "codelab",
        ]
    ) or lower.endswith(
        (
            "package.json",
            "pyproject.toml",
            "vite.config.ts",
            "vite.config.js",
            "tailwind.config.cjs",
            "tsconfig.json",
            "tsconfig.app.json",
            "tsconfig.node.json",
            "app.json",
            "babel.config.js",
        )
    )


def _augment_framework_detection(
    framework_detected: str,
    shallow_snippets: dict[str, str],
    dependencies: list[str],
    selected_files: list[str],
) -> str:
    combined = "\n".join(
        [framework_detected]
        + list(shallow_snippets.keys())
        + list(shallow_snippets.values())
        + dependencies
        + selected_files
    ).lower()

    detected: list[str] = []

    def _add(label: str):
        if label not in detected:
            detected.append(label)

    if "google.adk" in combined or " adk" in combined or "google-adk" in combined:
        _add("Google ADK")
    if "gemini" in combined:
        _add("Gemini")
    if "express" in combined:
        _add("Express")
    if "fastapi" in combined:
        _add("FastAPI")
    if "django" in combined:
        _add("Django")
    if "react native" in combined or "react-native" in combined:
        _add("React Native")
    if '"react"' in combined or "react/" in combined or "react-dom" in combined or "/frontend/src/" in combined:
        _add("React")
    if "vite" in combined:
        _add("Vite")
    if "tailwind" in combined:
        _add("Tailwind CSS")
    if any(term in combined for term in ["mlservice", "machine learning", "tensorflow", "inference", "embedding", "model score", "dealscore"]):
        _add("ML services")
    if "typescript" in combined:
        _add("TypeScript")
    if "python" in combined and "Google ADK" not in detected:
        _add("Python")

    if detected:
        return " + ".join(detected)
    return framework_detected


def _flatten_dependency_names(raw_dependencies: Any, max_items: int) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def _add_name(name: str):
        key = name.strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        names.append(name.strip())

    if isinstance(raw_dependencies, dict):
        for value in raw_dependencies.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        dep_name = item.get("name")
                        if isinstance(dep_name, str):
                            _add_name(dep_name)
                    elif isinstance(item, str):
                        _add_name(item)
    elif isinstance(raw_dependencies, list):
        for item in raw_dependencies:
            if isinstance(item, dict):
                dep_name = item.get("name")
                if isinstance(dep_name, str):
                    _add_name(dep_name)
            elif isinstance(item, str):
                _add_name(item)

    return names[:max_items]


def _trim_routes(raw_routes: Any, max_items: int) -> list[dict[str, str]]:
    trimmed: list[dict[str, str]] = []
    if not isinstance(raw_routes, list):
        return trimmed

    for item in raw_routes:
        if not isinstance(item, dict):
            continue
        method = str(item.get("method", "GET"))
        path = str(item.get("path", ""))
        summary = str(item.get("summary", ""))[:140]
        if not path:
            continue
        trimmed.append({"method": method, "path": path, "summary": summary})
        if len(trimmed) >= max_items:
            break
    return trimmed


def _normalize_file_records(raw_files: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(raw_files, list):
        return normalized
    for item in raw_files:
        if isinstance(item, dict):
            path = item.get("path")
            if not isinstance(path, str) or not path.strip():
                continue
            size_raw = item.get("size", item.get("file_size", item.get("bytes", 999)))
            try:
                size = int(size_raw)
            except Exception:
                size = 999
            normalized.append({"path": path, "size": size})
        elif isinstance(item, str):
            normalized.append({"path": item, "size": 999})
    return normalized


def pre_rank_files(file_list: list[dict[str, Any]], scan_data: dict[str, Any]) -> list[str]:
    scored_files: list[tuple[str, int]] = []
    import_graph = scan_data.get("import_graph", {})

    for file in file_list:
        score = 0
        path = str(file.get("path", ""))
        if not path:
            continue
        path_lower = path.lower()

        # Entry points — highest priority
        if any(name in path_lower for name in ["main", "index", "app", "server", "init"]):
            score += 100

        # Route files — very high priority
        if any(name in path_lower for name in ["route", "router", "controller", "handler", "endpoint"]):
            score += 80

        # Core business logic — high priority
        if any(name in path_lower for name in ["service", "core", "engine", "processor", "pipeline"]):
            score += 70

        # Models and schemas — medium priority
        if any(name in path_lower for name in ["model", "schema", "entity", "type"]):
            score += 50

        # Config and middleware — lower priority
        if any(name in path_lower for name in ["config", "middleware", "util", "helper", "lib"]):
            score += 30

        # Test files — never pick these
        if any(name in path_lower for name in ["test", "spec", "__tests__", ".test.", ".spec."]):
            score -= 1000

        # Penalize very short files (likely boilerplate)
        if int(file.get("size", 999)) < 200:
            score -= 20

        # Boost files heavily imported by others in import graph
        import_count = 0
        if isinstance(import_graph, dict):
            node = import_graph.get(path, {})
            if isinstance(node, dict):
                raw_count = node.get("imported_by_count", 0)
                if isinstance(raw_count, int):
                    import_count = raw_count
                elif isinstance(raw_count, str) and raw_count.isdigit():
                    import_count = int(raw_count)
                elif isinstance(node.get("imported_by"), list):
                    import_count = len(node.get("imported_by", []))
        score += import_count * 10

        scored_files.append((path, score))

    scored_files.sort(key=lambda x: x[1], reverse=True)
    return [f[0] for f in scored_files[:8]]


def _extract_core_terms(summary: str) -> list[str]:
    if not summary:
        return []
    raw_terms = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", summary.lower())
    stop_words = {
        "this", "that", "with", "from", "into", "your", "their", "about",
        "project", "application", "system", "codebase", "feature", "core",
        "build", "built", "tool", "tools", "uses", "using", "through",
        "and", "for", "the", "are", "is", "its", "into", "over", "when",
    }
    deduped: list[str] = []
    seen: set[str] = set()
    for term in raw_terms:
        if term in stop_words:
            continue
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped[:12]


def _boost_files_by_core_terms(file_paths: list[str], core_terms: list[str]) -> list[str]:
    if not file_paths or not core_terms:
        return file_paths
    scored: list[tuple[str, int]] = []
    for path in file_paths:
        lower = path.lower()
        score = 0
        for term in core_terms:
            if term in lower:
                score += 25
            # lightweight stemming match
            if term.endswith("s") and term[:-1] and term[:-1] in lower:
                score += 10
        scored.append((path, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [p for p, _ in scored]


def _build_call1_import_context(import_graph: Any) -> tuple[list[tuple[str, int]], list[str]]:
    import_counts: dict[str, int] = {}
    route_service_counts: dict[str, int] = {}
    if not isinstance(import_graph, dict):
        return [], []

    # Newer scans: edge list under import_graph["file_level"] with {"from","to"}.
    file_level = import_graph.get("file_level")
    if isinstance(file_level, list):
        for edge in file_level:
            if not isinstance(edge, dict):
                continue
            source = edge.get("from")
            target = edge.get("to")
            if isinstance(target, str) and target.strip():
                import_counts[target] = import_counts.get(target, 0) + 1
            if (
                isinstance(source, str)
                and isinstance(target, str)
                and "/routers/" in source
                and "/services/" in target
            ):
                route_service_counts[target] = route_service_counts.get(target, 0) + 1

    # Backward-compatible fallback for node-shaped graphs.
    for _file_path, node in import_graph.items():
        if not isinstance(node, dict):
            continue
        imports = node.get("imports", [])
        if not isinstance(imports, list):
            continue
        for imp in imports:
            if isinstance(imp, dict):
                imp_path = imp.get("path") or imp.get("file") or imp.get("target")
            else:
                imp_path = imp
            if isinstance(imp_path, str) and imp_path.strip():
                import_counts[imp_path] = import_counts.get(imp_path, 0) + 1

    most_imported = sorted(import_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    route_service_files = [
        path for path, _count in sorted(route_service_counts.items(), key=lambda x: x[1], reverse=True)
    ][:10]
    return most_imported, route_service_files


def _entry_point_candidates(file_records: list[dict[str, Any]], max_items: int = 10) -> list[str]:
    result: list[str] = []
    for file in file_records:
        path = str(file.get("path", "")).lower()
        if not path:
            continue
        if any(name in path for name in ["main", "index", "app", "server", "init"]):
            result.append(str(file.get("path")))
        if len(result) >= max_items:
            break
    return result


def _compose_call1_file_pool(
    file_records: list[dict[str, Any]],
    pre_ranked_candidates: list[str],
    most_imported_files: list[tuple[str, int]],
    route_service_files: list[str],
    entry_points: list[str],
    max_items: int = 50,
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(path: str):
        if not isinstance(path, str) or not path.strip() or path in seen:
            return
        seen.add(path)
        ordered.append(path)

    for path in route_service_files:
        _add(path)
    for path, _count in most_imported_files:
        _add(path)
    for path in pre_ranked_candidates:
        _add(path)
    for path in entry_points:
        _add(path)

    # Always surface likely deep-logic services for scanner/intelligence backends.
    service_focus_terms = ["scanner", "understanding", "graph_builder", "analy", "extract", "builder"]
    for file in file_records:
        path = str(file.get("path", ""))
        lower = path.lower()
        if "/services/" in lower and any(term in lower for term in service_focus_terms):
            _add(path)

    for file in file_records:
        _add(str(file.get("path", "")))
        if len(ordered) >= max_items:
            break

    return ordered[:max_items]


def _save_understanding_fragment(project_id: str, docs: dict[str, Any], status: str):
    db_save: Session = SessionLocal()
    try:
        understanding = (
            db_save.query(ProjectUnderstanding)
            .filter(ProjectUnderstanding.project_id == project_id)
            .first()
        )
        if not understanding:
            understanding = ProjectUnderstanding(project_id=project_id)
            db_save.add(understanding)

        if "project_story" in docs:
            understanding.project_story = docs.get("project_story", "") or ""
        if "system_map" in docs:
            understanding.system_map = docs.get("system_map", []) or []
        if "data_journey" in docs:
            understanding.data_journey = docs.get("data_journey", []) or []
        if "key_decisions" in docs:
            understanding.key_decisions = docs.get("key_decisions", []) or []
        if "gotchas" in docs:
            understanding.gotchas = docs.get("gotchas", []) or []
        if "glossary" in docs:
            understanding.glossary = docs.get("glossary", []) or []

        understanding.status = status
        understanding.generated_at = datetime.now(timezone.utc)
        db_save.commit()
    finally:
        db_save.close()


async def generate_understanding_backend(project_id: str, scan_data: dict, effective_root: str):
    """
    Background worker that runs the optimized 2-stage pipeline for Project Understanding.
    Creates its own DB session so it doesn't collide with the request.
    """
    update_status(project_id, "generating")

    if not OPENAI_API_KEY:
        logger.warning(f"Skipping understanding generation for {project_id}: No OpenAI key")
        update_status(project_id, "failed")
        return

    logger.info(f"Starting async understanding generation for project {project_id}")
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    
    # Simplify scan data to avoid huge token costs
    file_records = _normalize_file_records(scan_data.get("files", []))
    files_list = _prioritize_shallow_files(file_records, max_files=60)
    trimmed_routes = _trim_routes(scan_data.get("routes", []), max_items=10)
    trimmed_dependencies = _flatten_dependency_names(scan_data.get("dependencies", {}), max_items=15)
    project_name = scan_data.get("project_name", "Unknown Project")  # backfilled below from DB when available
    
    db: Session = SessionLocal()
    indexed_files: list[dict[str, Any]] = []
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        project_name = project.name if project else "Project"
        indexed_files = _load_indexed_file_context(project_id, db, max_files=12)
    finally:
        db.close()

    call2_context = {
        "project_name": project_name,
        "languages": scan_data.get("languages", []),
        "dependencies": trimmed_dependencies,  # max 15 dependencies
        "routes": trimmed_routes,  # max 10 routes
        "components": scan_data.get("components", []),
        "files": [item["path"] for item in indexed_files] if indexed_files else files_list,
    }

    try:
        # ──────────────────────────────────────────────────────────
        # Pass 1 — Prefer indexed files from DB, fall back to shallow disk reads
        # ──────────────────────────────────────────────────────────
        using_index = bool(indexed_files)
        indexed_by_path = {item["path"]: item for item in indexed_files}
        if using_index:
            candidate_paths = [item["path"] for item in indexed_files]
            shallow_snippets = {
                item["path"]: _content_head(item.get("content", ""), 20)
                for item in indexed_files
                if item.get("content")
            }
        else:
            candidate_paths = files_list
            shallow_snippets = await shallow_read_all_files(effective_root, files_list)

        route_paths = [f"{r['method']} {r['path']}" for r in call2_context["routes"]]
        file_map_parts: list[str] = []
        imported_by_counts = _imported_by_count_map(scan_data.get("import_graph", {}))
        shallow_paths = sorted(
            list(candidate_paths),
            key=lambda path: (
                _score_file_universally(path, shallow_snippets.get(path, "")) + (imported_by_counts.get(path, 0) * 5),
                path,
            ),
            reverse=True,
        )

        for path in shallow_paths:
            snippet = shallow_snippets.get(path, "")
            if using_index:
                indexed_item = indexed_by_path.get(path, {})
                file_map_parts.append(
                    "\n".join(
                        [
                            f"--- {path} ---",
                            f"Type: {indexed_item.get('file_type', 'other')}",
                            f"Domain: {indexed_item.get('domain_area', 'other')}",
                            f"Importance: {indexed_item.get('importance_score', 0)}",
                            f"Summary: {indexed_item.get('summary', '')}",
                            f"Exports: {json.dumps(indexed_item.get('exports', []))}",
                            f"Concepts: {json.dumps(indexed_item.get('key_concepts', []))}",
                            "Preview:",
                            snippet,
                        ]
                    )
                )
            else:
                file_map_parts.append(f"--- {path} ---\n{snippet}")
        file_map = "\n\n".join(file_map_parts)

        selection_rules = """
UNIVERSAL FILE SELECTION RULES — apply to any language, any framework:

PREFER files that:
- Contain actual business logic (conditions, loops, data transformations)
- Import AND use multiple other modules (central orchestrators)
- Define the core behavior of the application
- Contain the most lines of actual code in their first 20 lines
- Are imported by many other files (high centrality)

AVOID files that:
- Mainly just map paths to other functions (thin routers/url configs)
- Are mostly imports with little own logic
- Are configuration only (settings, constants, env vars)
- Are boilerplate or auto-generated
- Just re-export things from other files

UNIVERSAL PATTERNS TO RECOGNIZE:
- A file that creates/initializes the main app object = always important
- A file that contains the core data transformation = always important
- A file that orchestrates multiple services = always important
- A file that defines the main AI agent/model = always important
- A file with the most complex logic visible in first 20 lines = important

DO NOT apply framework-specific rules.
DO NOT assume any naming convention.
Judge purely by what you actually see in the code snippets.

The goal: select 5 files that together tell the complete story
of what this application does and how it works.
A new developer should be able to understand the entire system
just from reading these 5 files.
"""

        call1_prompt = f"""You are analyzing a codebase. Below are the first 20 lines of every file.
Read them carefully and select the 5 most important files for deep analysis.

PROJECT: {project_name}
LANGUAGES: {json.dumps(call2_context["languages"])}
DEPENDENCIES: {json.dumps(call2_context["dependencies"])}
ROUTES DETECTED: {json.dumps(route_paths)}

FILE CONTEXTS:
{file_map}

{selection_rules}

Prefer files with higher importance when the summaries and previews support that choice.

Return JSON:
{{
  "framework_detected": "what framework/patterns this uses",
  "core_purpose": "what this application actually does in one sentence",
  "selected_files": ["path1", "path2", "path3", "path4", "path5"],
  "core_feature_file": "single most important file path",
  "reasoning": "what you saw in the snippets that led to this selection"
}}

Return only valid JSON.
"""
        call1_estimated_tokens = _estimate_tokens(call1_prompt)
        print(f"[understanding] call1 prompt estimate: ~{call1_estimated_tokens} tokens")
        while call1_estimated_tokens > MAX_PROMPT_TOKENS and len(shallow_paths) > 15:
            print(f"[understanding] prompt too large: ~{call1_estimated_tokens} tokens, trimming")
            shallow_paths = shallow_paths[: max(15, len(shallow_paths) - 10)]
            trimmed_file_map = "\n\n".join(
                f"--- {path} ---\n{shallow_snippets[path]}" for path in shallow_paths if path in shallow_snippets
            )
            call1_prompt = f"""You are analyzing a codebase from real file snippets.
PROJECT: {project_name}
LANGUAGES: {json.dumps(call2_context["languages"])}
DEPENDENCIES: {json.dumps(call2_context["dependencies"])}
ROUTES DETECTED: {json.dumps(route_paths)}

FILE CONTENTS (first 20 lines each):
{trimmed_file_map}

Return JSON with:
- framework_detected
- core_purpose
- selected_files
- core_feature_file
- reasoning
Return only valid JSON."""
            call1_estimated_tokens = _estimate_tokens(call1_prompt)
            print(f"[understanding] call1 prompt estimate: ~{call1_estimated_tokens} tokens")

        res1 = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You return only valid JSON."},
                    {"role": "user", "content": call1_prompt}
                ],
                max_tokens=4000,
                response_format={"type": "json_object"}
            ),
            timeout=30.0
        )
        
        call1_content = res1.choices[0].message.content or "{}"
        structured_data = json.loads(call1_content)
        framework_detected = str(structured_data.get("framework_detected", "")).strip()
        core_purpose = str(structured_data.get("core_purpose", "")).strip()
        selected_files = [
            p for p in structured_data.get("selected_files", [])
            if isinstance(p, str) and not _is_boilerplate_selection(p)
        ]
        for fallback_file in shallow_paths:
            if len(selected_files) >= 5:
                break
            if fallback_file not in selected_files and not _is_boilerplate_selection(fallback_file):
                selected_files.append(fallback_file)
        important_files = selected_files[:5]
        core_feature_file = structured_data.get("core_feature_file")
        if (
            not isinstance(core_feature_file, str)
            or not core_feature_file.strip()
            or _is_boilerplate_selection(core_feature_file)
        ):
            core_feature_file = important_files[0] if important_files else ""
        reasoning = str(structured_data.get("reasoning", "")).strip()
        framework_detected = _augment_framework_detection(
            framework_detected,
            shallow_snippets,
            call2_context["dependencies"],
            important_files,
        )
        print(f"[understanding] framework detected: {framework_detected}")
        print(f"[understanding] core purpose: {core_purpose}")
        print(f"[understanding] selected files: {important_files}")
        print(f"[understanding] reasoning: {reasoning}")
        
        # ──────────────────────────────────────────────────────────
        # Pass 2 — Use stored indexed content when available; fall back to disk
        # ──────────────────────────────────────────────────────────
        file_contents: dict[str, str] = {}
        for fpath in important_files:
            indexed_item = indexed_by_path.get(fpath)
            if indexed_item and indexed_item.get("content"):
                file_contents[fpath] = _content_head(str(indexed_item.get("content", "")), 100)
                continue

            full_path = os.path.join(effective_root, fpath)
            if not os.path.exists(full_path):
                continue
            try:
                with open(full_path, "r", errors="ignore") as f:
                    lines = f.readlines()
                    file_contents[fpath] = "".join(lines[:100])
            except Exception as e:
                logger.error(f"Failed to read file {fpath}: {e}")

        # Keep the payload tiny and trim further if needed.
        file_items = list(file_contents.items())[:5]
        compact_files = {k: v for k, v in file_items}
        indexed_summaries = {
            path: indexed_by_path[path].get("summary", "")
            for path in important_files
            if path in indexed_by_path and indexed_by_path[path].get("summary")
        }
        compact_context = {
            "project_name": call2_context["project_name"],
            "languages": call2_context["languages"],
            "dependencies": call2_context["dependencies"][:15],
            "routes": call2_context["routes"][:10],
            "components": call2_context["components"],
            "files": call2_context["files"][:50],
            "indexed_summaries": indexed_summaries,
        }
        actual_route_paths = [f"{r['method']} {r['path']}" for r in compact_context["routes"]]
        compact_structure = {
            "important_files": important_files[:5],
            "core_feature_file": core_feature_file,
            "framework_detected": framework_detected,
            "core_purpose": core_purpose,
            "reasoning": reasoning,
            "architecture_summary": structured_data.get("architecture_summary", ""),
            "data_flow": structured_data.get("data_flow", ""),
        }
        core_feature_content = ""
        if core_feature_file:
            core_feature_content = file_contents.get(core_feature_file, "")
            if not core_feature_content and core_feature_file in indexed_by_path:
                core_feature_content = _content_head(str(indexed_by_path[core_feature_file].get("content", "")), 120)
            if not core_feature_content:
                full_path = os.path.join(effective_root, core_feature_file)
                if os.path.exists(full_path):
                    try:
                        with open(full_path, "r", errors="ignore") as f:
                            core_feature_content = "".join(f.readlines()[:120])
                    except Exception:
                        core_feature_content = ""

        def _fit_files_to_prompt_budget(
            prompt_builder,
            dependencies: list[str],
            routes: list[dict[str, str]],
            files_payload: dict[str, str],
        ):
            if not files_payload:
                prompt = prompt_builder(dependencies, routes, files_payload)
                estimated = _estimate_tokens(prompt)
                return prompt, dependencies, routes, files_payload, estimated

            empty_files_payload = {path: "" for path in files_payload}
            base_prompt = prompt_builder(dependencies, routes, empty_files_payload)
            base_tokens = _estimate_tokens(base_prompt)
            available_chars = max((MAX_PROMPT_TOKENS - base_tokens) * 4, 0)
            chars_per_file = available_chars // max(len(files_payload), 1)

            truncated_files_payload = {
                path: content[:chars_per_file]
                for path, content in files_payload.items()
            }
            prompt = prompt_builder(dependencies, routes, truncated_files_payload)
            estimated = _estimate_tokens(prompt)
            if estimated > MAX_PROMPT_TOKENS:
                print(f"[understanding] prompt too large: ~{estimated} tokens, using single-pass truncation")
            files_payload = truncated_files_payload
            return prompt, dependencies, routes, files_payload, estimated

        def _build_call2a_prompt(dependencies: list[str], routes: list[dict[str, str]], files_payload: dict[str, str]) -> str:
            scoped_context = dict(compact_context)
            scoped_context["dependencies"] = dependencies
            scoped_context["routes"] = routes
            return f"""Framework detected: {framework_detected}
Core purpose: {core_purpose}

You are generating documentation for a codebase named {project_name}.
Here is the context:
{json.dumps(scoped_context)}

Structure Analysis:
{json.dumps(compact_structure)}

Important File Contents:
{json.dumps(files_payload)}

Indexed File Summaries:
{json.dumps(indexed_summaries)}

Return ONE single JSON object with ONLY these keys and exact structures:
"project_story": 4 paragraph prose explaining 1. What it does, 2. How it's structured, 3. Key choices, 4. What's unique.
"system_map": array of up to 8 components, each with max 5 properties: "id", "name", "type", "description", "connects_to", "key_files", "color".
Component types must be exactly one of: "backend", "frontend", "mobile", "database", "external", "cache".
Never use "frontend" for mobile components — use "mobile" instead.
"""

        def _build_call2b_prompt(dependencies: list[str], routes: list[dict[str, str]], files_payload: dict[str, str]) -> str:
            scoped_context = dict(compact_context)
            scoped_context["dependencies"] = dependencies
            scoped_context["routes"] = routes
            return f"""Framework detected: {framework_detected}
Core purpose: {core_purpose}

You are generating documentation for a codebase named {project_name}.
Here is the context:
{json.dumps(scoped_context)}

Structure Analysis:
{json.dumps(compact_structure)}

Important File Contents:
{json.dumps(files_payload)}

Indexed File Summaries:
{json.dumps(indexed_summaries)}

Return ONE single JSON object with ONLY these keys and exact structures:
"data_journey": array of up to 8 step objects with "step", "actor", "action", "detail", "type" (request|validation|processing|database|external|response).
"data_journey" requirements:
Using the actual routes from this codebase, trace exactly how one specific real request flows through the system end to end.
Pick the most interesting route (preferably a POST route that touches the database).
For each step use the ACTUAL route path, ACTUAL function names, ACTUAL field names from the code.
Do not use generic terms like "process request" or "save to database".
Example of good step:
  actor: "Express Router"
  action: "POST /spots/:spot_id/bookings received"
  detail: "Extracts spot_id from params, user_id from session"
Example of bad step:
  actor: "Backend"
  action: "Process booking request"
  detail: "Save booking"
Return max 8 steps as JSON array.
Routes available: {json.dumps(actual_route_paths)}
File contents: {json.dumps(files_payload)}
IMPORTANT: The core feature of this application is identified as being in:
{core_feature_file}

Trace the data journey through THIS specific feature — not a secondary feature like alerts or health checks.
Use the actual route from this file as your example.

File content of core feature:
{core_feature_content}
"key_decisions": array of 4-5 decision objects with "title", "decision", "why", "tradeoff", "icon".
"gotchas": array of 4-5 gotchas with "title", "description", "severity" (high|medium|low), "affected".
"gotchas" requirements:
Analyze this codebase for SPECIFIC gotchas a new developer would actually hit.
Rules:
- No generic advice like "set environment variables" or "configure CORS"
- Every gotcha must reference a specific file, service, or pattern in THIS codebase
- Think about: external service dependencies, startup order requirements, missing error handling in specific routes, hardcoded values, race conditions, memory issues, API rate limits
Bad example: "Ensure environment variables are set"
Good example: "The ML service must be running BEFORE the server starts — if it's down, POST /scan requests will hang for 30 seconds before timing out because there's no startup connection check in src/index.ts"
Codebase context:
{json.dumps(files_payload)}
{json.dumps(dependencies)}
{json.dumps(routes)}
"glossary": array of 8-10 terms with "term", "plain_english", "used_in".
"glossary" requirements:
Extract 8-10 domain-specific terms from THIS codebase only.
Rules:
- Only include terms that are specific to this project's domain
- Do NOT include generic tech terms (API, Controller, Model, React, MongoDB)
- DO include business domain terms (Spot, Booking, Owner, Guest) when present
- DO include project-specific patterns or naming conventions
- DO include any custom terminology used in the codebase
For each term explain what it means in the context of THIS specific application, not in general.
Example of good term:
  term: "Spot"
  plain_english: "A rentable space listed by a host on the platform"
  used_in: ["backend/src/models/Spot.js"]
Example of bad term:
  term: "API"
  plain_english: "Application Programming Interface"
File contents: {json.dumps(files_payload)}
"""
        call2a_prompt, deps2a, routes2a, files2a, est2a = _fit_files_to_prompt_budget(
            _build_call2a_prompt,
            compact_context["dependencies"][:],
            compact_context["routes"][:],
            dict(compact_files),
        )
        print(f"[understanding] call2a prompt estimate: ~{est2a} tokens")

        call2b_prompt, deps2b, routes2b, files2b, est2b = _fit_files_to_prompt_budget(
            _build_call2b_prompt,
            deps2a[:],
            routes2a[:],
            dict(files2a),
        )
        print(f"[understanding] call2b prompt estimate: ~{est2b} tokens")

        async def call_2a() -> dict[str, Any]:
            res2a = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You return only valid JSON matching the exact requested keys and structure."},
                    {"role": "user", "content": call2a_prompt},
                ],
                max_tokens=4000,
                response_format={"type": "json_object"},
            )
            return json.loads(res2a.choices[0].message.content or "{}")

        async def call_2b() -> dict[str, Any]:
            res2b = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You return only valid JSON matching the exact requested keys and structure."},
                    {"role": "user", "content": call2b_prompt},
                ],
                max_tokens=4000,
                response_format={"type": "json_object"},
            )
            return json.loads(res2b.choices[0].message.content or "{}")

        results = await asyncio.gather(
            asyncio.wait_for(call_2a(), timeout=90.0),
            asyncio.wait_for(call_2b(), timeout=90.0),
            return_exceptions=True,
        )
        res_2a, res_2b = results

        section_2a_ok = not isinstance(res_2a, Exception)
        section_2b_ok = not isinstance(res_2b, Exception)

        if section_2a_ok:
            docs_2a = res_2a
            _save_understanding_fragment(
                project_id,
                {
                    "project_story": docs_2a.get("project_story", ""),
                    "system_map": docs_2a.get("system_map", []),
                },
                status="partial",
            )
        else:
            logger.error(
                f"Understanding call2a failed: {type(res_2a).__name__}: {str(res_2a) or '<no error message>'}"
            )

        if section_2b_ok:
            docs_2b = res_2b
            _save_understanding_fragment(
                project_id,
                {
                    "data_journey": docs_2b.get("data_journey", []),
                    "key_decisions": docs_2b.get("key_decisions", []),
                    "gotchas": docs_2b.get("gotchas", []),
                    "glossary": docs_2b.get("glossary", []),
                },
                status="partial",
            )
        else:
            logger.error(
                f"Understanding call2b failed: {type(res_2b).__name__}: {str(res_2b) or '<no error message>'}"
            )

        if section_2a_ok and section_2b_ok:
            _save_understanding_fragment(project_id, {}, status="complete")
            logger.info(f"Successfully generated and saved understanding for project {project_id}")
        elif section_2a_ok or section_2b_ok:
            _save_understanding_fragment(project_id, {}, status="partial")
            logger.warning(
                f"Saved partial understanding for project {project_id}: call2a_ok={section_2a_ok}, call2b_ok={section_2b_ok}"
            )
        else:
            raise RuntimeError("Both call2a and call2b failed")

    except Exception as e:
        import traceback
        error_type = type(e).__name__
        error_message = str(e) or "<no error message>"
        logger.error(f"Understanding pipeline failed: {error_type}: {error_message}")
        logger.error(traceback.format_exc())
        # Apply error recovery fallback
        fallback = {
            "project_story": f"{project_name} is a {''.join([str(lang) for lang in call2_context['languages']])} project with {len(call2_context['routes'])} API routes.",
            "system_map": [],
            "data_journey": [],
            "key_decisions": [],
            "gotchas": [],
            "glossary": []
        }
        
        db_fallback: Session = SessionLocal()
        try:
            understanding = db_fallback.query(ProjectUnderstanding).filter(ProjectUnderstanding.project_id == project_id).first()
            if not understanding:
                understanding = ProjectUnderstanding(project_id=project_id)
                db_fallback.add(understanding)

            understanding.project_story = fallback["project_story"]
            understanding.system_map = fallback["system_map"]
            understanding.data_journey = fallback["data_journey"]
            understanding.key_decisions = fallback["key_decisions"]
            understanding.gotchas = fallback["gotchas"]
            understanding.glossary = fallback["glossary"]
            understanding.status = "failed"
            understanding.generated_at = datetime.now(timezone.utc)

            db_fallback.commit()
        finally:
            db_fallback.close()
