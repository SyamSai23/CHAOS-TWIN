from __future__ import annotations

import asyncio
import json
import os
import posixpath
import re
import time
import traceback
import zipfile
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

import enry
from openai import AsyncOpenAI
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session
from tree_sitter_languages import get_parser

from app.config import OPENAI_API_KEY, WORKSPACE_DIR
from app.db.session import SessionLocal
from app.models.project import Project
from app.models.upload import Upload
from app.services.scanner_v3 import unwrap_root_dir
from app.services.understanding_generator import generate_understanding_backend

_openai_semaphore = asyncio.Semaphore(3)
MAX_INDEXABLE_SOURCE_FILES = 500

TREE_SITTER_SUPPORTED = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rb": "ruby",
    ".rs": "rust",
    ".cs": "c_sharp",
    ".cpp": "cpp",
    ".c": "c",
    ".php": "php",
}

IMPORT_PATTERNS = [
    r'["\'](\./[^"\']+)["\']',
    r'["\'](\.\./[^"\']+)["\']',
    r'from\s+["\']([^"\']+)["\']',
    r'require\(["\']([^"\']+)["\']\)',
    r'from\s+([\w.]+)\s+import',
    r'import\s+([\w.]+);',
    r'using\s+([\w.]+);',
    r'require_relative\s+[\'"]([^\'"]+)[\'"]',
    r'use\s+([\w:]+)',
    r'require_once\s+[\'"]([^\'"]+)[\'"]',
]

CLASSIFICATION_ALLOWED_TYPES = {
    "entry_point",
    "route",
    "controller",
    "model",
    "service",
    "middleware",
    "config",
    "utility",
    "test",
    "migration",
    "other",
}

CLASSIFICATION_ALLOWED_DOMAINS = {
    "auth",
    "user",
    "payment",
    "product",
    "notification",
    "search",
    "booking",
    "analytics",
    "core",
    "other",
}


def _client() -> AsyncOpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required for file indexing")
    return AsyncOpenAI(api_key=OPENAI_API_KEY)


def _normalize_zip_path(path: str, root_prefix: str | None) -> str:
    normalized = path.replace("\\", "/").lstrip("/")
    if root_prefix and normalized.startswith(root_prefix):
        normalized = normalized[len(root_prefix):].lstrip("/")
    return posixpath.normpath(normalized).lstrip("./")


def _zip_root_prefix(zip_file: zipfile.ZipFile) -> str | None:
    top_levels = {
        entry.filename.replace("\\", "/").split("/", 1)[0]
        for entry in zip_file.infolist()
        if entry.filename and not entry.is_dir() and not entry.filename.startswith("__MACOSX/")
    }
    if len(top_levels) != 1:
        return None
    only = next(iter(top_levels))
    return f"{only}/"


def should_index_file(file_path: str, content_bytes: bytes) -> bool:
    if enry.is_vendor(file_path):
        return False
    if enry.is_generated(file_path, content_bytes):
        return False
    if enry.is_binary(content_bytes):
        return False
    if enry.is_documentation(file_path):
        return False
    return True


def _cap_content_lines(content: str) -> tuple[str, int]:
    lines = content.splitlines()
    line_count = len(lines)
    if line_count <= 400:
        return content, line_count
    kept = lines[:350] + lines[-50:]
    return "\n".join(kept), line_count


async def extract_source_files(zip_path: str) -> dict[str, dict[str, Any]]:
    file_index: dict[str, dict[str, Any]] = {}
    skipped = 0

    with zipfile.ZipFile(zip_path, "r") as archive:
        root_prefix = _zip_root_prefix(archive)
        for entry in archive.infolist():
            if entry.is_dir() or entry.filename.startswith("__MACOSX/"):
                continue
            normalized_path = _normalize_zip_path(entry.filename, root_prefix)
            if not normalized_path or normalized_path.startswith(".git/"):
                continue
            try:
                content_bytes = archive.read(entry)
            except Exception:
                skipped += 1
                continue
            if not should_index_file(normalized_path, content_bytes):
                skipped += 1
                continue

            try:
                decoded = content_bytes.decode("utf-8", errors="ignore")
            except Exception:
                skipped += 1
                continue

            capped_content, line_count = _cap_content_lines(decoded)
            _, extension = os.path.splitext(normalized_path)
            file_index[normalized_path] = {
                "content": capped_content,
                "line_count": line_count,
                "extension": extension.lower(),
                "size_bytes": len(content_bytes),
            }

    print(f"[indexer] extracted {len(file_index)} source files (skipped {skipped} vendor/generated/binary)")
    return file_index


def _first_lines(content: str, line_count: int) -> str:
    return "\n".join(content.splitlines()[:line_count])


def _extract_json_array(payload: str) -> list[dict[str, Any]]:
    text_payload = payload.strip()
    try:
        parsed = json.loads(text_payload)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        for value in parsed.values():
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    start = text_payload.find("[")
    end = text_payload.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text_payload[start : end + 1])
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass
    return []


def _normalize_classification(file_path: str, item: dict[str, Any]) -> dict[str, Any]:
    file_type = str(item.get("file_type", "other")).strip().lower()
    domain_area = str(item.get("domain_area", "other")).strip().lower()
    return {
        "file_path": file_path,
        "file_type": file_type if file_type in CLASSIFICATION_ALLOWED_TYPES else "other",
        "domain_area": domain_area if domain_area in CLASSIFICATION_ALLOWED_DOMAINS else "other",
        "is_important": bool(item.get("is_important", False)),
        "one_line_description": str(item.get("one_line_description", "")).strip(),
    }


async def classify_files_batch(
    file_index: dict[str, dict[str, Any]], project_context: dict[str, str]
) -> dict[str, dict[str, Any]]:
    client = _client()
    paths = list(file_index.keys())
    results: dict[str, dict[str, Any]] = {}

    async def classify_single_batch(batch_paths: list[str]) -> list[dict[str, Any]]:
        file_sections = []
        for path in batch_paths:
            preview = _first_lines(file_index[path]["content"], 30)
            file_sections.append(f"=== {path} ===\n{preview}")

        prompt = f"""You are classifying source code files for a junior developer tool.
Read the actual code content — do not guess from filename alone.

Project: {project_context.get('name', 'Unknown')}
Purpose: {project_context.get('core_purpose', '')}

Classify each file below:

{chr(10).join(file_sections)}

For EACH file return JSON:
{{
  "file_path": "exact path",
  "file_type": one of exactly: entry_point | route | controller |
               model | service | middleware | config | utility |
               test | migration | other,
  "domain_area": the business domain: auth | user | payment |
                 product | notification | search | booking |
                 analytics | core | other,
  "is_important": true if this file contains core business logic,
  "one_line_description": "what this file does in one sentence"
}}

Rules:
- Read the actual code to determine type
- A @RestController annotation means controller
- A mongoose.Schema means model
- router.get/post/put means route
- Works for any language: Java, Go, Ruby, Rust, C#, PHP, Swift etc
- Return JSON array only, no other text
"""

        async with _openai_semaphore:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You classify code files by reading their content. Return only valid JSON arrays.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
        payload = response.choices[0].message.content or "[]"
        return _extract_json_array(payload)

    batches = [paths[start : start + 15] for start in range(0, len(paths), 15)]
    tasks = [classify_single_batch(batch) for batch in batches]
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

    for batch_result in batch_results:
        if isinstance(batch_result, Exception):
            print(f"[indexer] classify batch failed: {batch_result}")
            continue
        for item in batch_result:
            path = str(item.get("file_path", "")).strip()
            if path in file_index:
                results[path] = _normalize_classification(path, item)

    for path in paths:
        if path not in results:
            results[path] = _normalize_classification(path, {})

    type_counts = Counter(result["file_type"] for result in results.values())
    print(f"[indexer] classified {len(results)} files: {dict(type_counts)}")
    return results


def _tree_sitter_candidates(extension: str, source_bytes: bytes) -> set[str]:
    language_name = TREE_SITTER_SUPPORTED.get(extension)
    if not language_name:
        return set()
    try:
        parser = get_parser(language_name)
        tree = parser.parse(source_bytes)
    except Exception:
        return set()

    candidates: set[str] = set()
    importish_tokens = ("import", "require", "include", "using", "use")
    string_node_types = {
        "string",
        "string_literal",
        "interpreted_string_literal",
        "raw_string_literal",
    }

    def walk(node: Any) -> None:
        node_type = getattr(node, "type", "")
        node_text = source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")

        if node_type in string_node_types:
            value = node_text.strip().strip("\"'`")
            if value:
                candidates.add(value)

        if node_type and any(token in node_type for token in importish_tokens):
            for pattern in IMPORT_PATTERNS:
                for match in re.findall(pattern, node_text):
                    if isinstance(match, tuple):
                        candidates.update(str(item) for item in match if item)
                    elif match:
                        candidates.add(str(match))

        for child in getattr(node, "children", []):
            walk(child)

    walk(tree.root_node)
    return {candidate for candidate in candidates if candidate}


def _regex_candidates(content: str) -> set[str]:
    candidates: set[str] = set()
    for pattern in IMPORT_PATTERNS:
        for match in re.findall(pattern, content):
            if isinstance(match, tuple):
                candidates.update(str(item) for item in match if item)
            elif match:
                candidates.add(str(match))
    return candidates


def _expand_candidate_paths(base: str, known_extensions: set[str]) -> list[str]:
    candidates = [base]
    if any(base.endswith(extension) for extension in known_extensions):
        return candidates
    for extension in known_extensions:
        candidates.append(f"{base}{extension}")
        candidates.append(posixpath.join(base, f"index{extension}"))
        candidates.append(posixpath.join(base, f"main{extension}"))
    candidates.append(posixpath.join(base, "__init__.py"))
    candidates.append(posixpath.join(base, "mod.rs"))
    return candidates


def _resolve_import_target(
    source_file: str,
    raw_import: str,
    existing_paths: set[str],
    known_extensions: set[str],
) -> str | None:
    candidate = raw_import.strip().strip("\"'`;")
    if not candidate or candidate.startswith("@") or candidate.startswith("http"):
        return None

    source_dir = str(PurePosixPath(source_file).parent)
    possible_bases: list[str] = []
    if candidate.startswith("./") or candidate.startswith("../"):
        resolved = posixpath.normpath(posixpath.join(source_dir, candidate))
        possible_bases.append(resolved)
    else:
        normalized = candidate.replace("::", "/")
        if "/" in normalized:
            possible_bases.append(posixpath.normpath(normalized))
        dotted = normalized.replace(".", "/")
        if dotted != normalized:
            possible_bases.append(posixpath.normpath(dotted))
        possible_bases.append(posixpath.normpath(normalized))

    seen: set[str] = set()
    for base in possible_bases:
        for expanded in _expand_candidate_paths(base, known_extensions):
            normalized = posixpath.normpath(expanded)
            if normalized in seen:
                continue
            seen.add(normalized)
            if normalized in existing_paths:
                return normalized
    return None


def build_dependency_graph(file_index: dict[str, dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    existing_paths = set(file_index.keys())
    known_extensions = {data["extension"] for data in file_index.values() if data.get("extension")}
    dep_graph: dict[str, dict[str, list[str]]] = {
        path: {"imports": [], "imported_by": []} for path in existing_paths
    }

    for file_path, data in file_index.items():
        content = data["content"]
        content_bytes = content.encode("utf-8", errors="ignore")
        raw_candidates = set(_regex_candidates(content))
        if data["extension"] in TREE_SITTER_SUPPORTED:
            raw_candidates.update(_tree_sitter_candidates(data["extension"], content_bytes))

        resolved_imports: list[str] = []
        for raw_import in sorted(raw_candidates):
            target = _resolve_import_target(file_path, raw_import, existing_paths, known_extensions)
            if target and target != file_path and target not in resolved_imports:
                resolved_imports.append(target)

        dep_graph[file_path]["imports"] = resolved_imports

    for file_path, graph_entry in dep_graph.items():
        for target in graph_entry["imports"]:
            dep_graph[target]["imported_by"].append(file_path)

    edge_count = sum(len(entry["imports"]) for entry in dep_graph.values())
    print(f"[indexer] dependency graph: {len(dep_graph)} nodes, {edge_count} edges")
    return dep_graph


def calculate_importance_scores(
    file_index: dict[str, dict[str, Any]],
    classifications: dict[str, dict[str, Any]],
    dep_graph: dict[str, dict[str, list[str]]],
) -> dict[str, float]:
    type_weights = {
        "entry_point": 10,
        "route": 8,
        "controller": 7,
        "model": 6,
        "service": 5,
        "middleware": 4,
        "config": 2,
        "utility": 2,
        "test": -10,
        "migration": -5,
        "other": 1,
    }

    def score_file(file_path: str, classification: dict[str, Any]) -> float:
        score = 0.0
        imported_by = len(dep_graph.get(file_path, {}).get("imported_by", []))
        score += imported_by * 3
        score += type_weights.get(classification.get("file_type", "other"), 1)
        if classification.get("is_important"):
            score += 5
        return score

    return {
        file_path: score_file(file_path, classifications.get(file_path, {}))
        for file_path in file_index
    }


async def summarize_files_batch(
    file_index: dict[str, dict[str, Any]],
    classifications: dict[str, dict[str, Any]],
    scores: dict[str, float],
    project_context: dict[str, str],
) -> dict[str, dict[str, Any]]:
    client = _client()
    paths_to_summarize = [
        path
        for path in sorted(scores.keys(), key=lambda item: scores[item], reverse=True)
        if classifications.get(path, {}).get("file_type") not in {"test", "migration"}
    ]
    summaries: dict[str, dict[str, Any]] = {}
    total_batches = max((len(paths_to_summarize) + 9) // 10, 1)

    async def summarize_single_batch(
        batch_paths: list[str], batch_index: int
    ) -> tuple[int, list[dict[str, Any]]]:
        file_sections = []
        for path in batch_paths:
            classification = classifications.get(path, {})
            file_sections.append(
                f"=== {classification.get('file_type', 'other')}: {path} ===\n{file_index[path]['content']}"
            )

        prompt = f"""You are summarizing source code files to help junior developers understand a codebase.

Project: {project_context.get('name', 'Unknown')}
Purpose: {project_context.get('core_purpose', '')}
Framework: {project_context.get('framework', '')}

Summarize each file below. Write for a junior developer who has never seen this codebase.

{chr(10).join(file_sections)}

For EACH file return:
{{
  "file_path": "exact path",
  "summary": "2-3 sentences: what this file does, what problem it solves, how it connects to the rest of the system. Use actual function names and data from the code.",
  "exports": ["main functions, classes, routes, or models this file provides to the rest of the system"],
  "key_concepts": ["2-3 important concepts a junior needs to understand to work with this file"]
}}

Be specific. Mention actual names from the code.
Return JSON array only.
"""

        async with _openai_semaphore:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You summarize code for junior developers. Return only valid JSON arrays.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )

        payload = response.choices[0].message.content or "[]"
        print(f"[indexer] summarized batch {batch_index}/{total_batches}")
        return batch_index, _extract_json_array(payload)

    batches = [paths_to_summarize[start : start + 10] for start in range(0, len(paths_to_summarize), 10)]
    tasks = [
        summarize_single_batch(batch, batch_index)
        for batch_index, batch in enumerate(batches, start=1)
    ]
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

    for batch_result in batch_results:
        if isinstance(batch_result, Exception):
            print(f"[indexer] summarize batch failed: {batch_result}")
            continue
        _, items = batch_result
        for item in items:
            path = str(item.get("file_path", "")).strip()
            if path in file_index:
                summaries[path] = {
                    "file_path": path,
                    "summary": str(item.get("summary", "")).strip(),
                    "exports": list(item.get("exports", [])) if isinstance(item.get("exports", []), list) else [],
                    "key_concepts": list(item.get("key_concepts", [])) if isinstance(item.get("key_concepts", []), list) else [],
                }

    return summaries


def _build_embed_text(
    file_path: str,
    classification: dict[str, Any],
    summary_result: dict[str, Any],
) -> str:
    exports = summary_result.get("exports", [])
    key_concepts = summary_result.get("key_concepts", [])
    return (
        f"File: {file_path}. "
        f"Type: {classification.get('file_type', 'other')}. "
        f"Domain: {classification.get('domain_area', 'other')}. "
        f"Summary: {summary_result.get('summary', '')} "
        f"Exports: {', '.join(exports)}. "
        f"Concepts: {', '.join(key_concepts)}."
    )


async def generate_embeddings(
    summaries: dict[str, dict[str, Any]],
    classifications: dict[str, dict[str, Any]],
) -> dict[str, list[float]]:
    if not summaries:
        return {}

    client = _client()
    ordered_paths = list(summaries.keys())
    async with _openai_semaphore:
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=[
                _build_embed_text(path, classifications.get(path, {}), summaries[path])
                for path in ordered_paths
            ],
        )
    embeddings = {
        path: item.embedding
        for path, item in zip(ordered_paths, response.data)
    }
    print(f"[indexer] generated embeddings for {len(embeddings)} files")
    return embeddings


def _vector_literal(values: list[float] | None) -> str | None:
    if not values:
        return None
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


async def store_to_database(
    project_id: str,
    file_index: dict[str, dict[str, Any]],
    classifications: dict[str, dict[str, Any]],
    scores: dict[str, float],
    summaries: dict[str, dict[str, Any]],
    embeddings: dict[str, list[float]],
    dep_graph: dict[str, dict[str, list[str]]],
    db: Session | None = None,
) -> None:
    local_db = False
    if db is None:
        db = SessionLocal()
        local_db = True

    try:
        file_paths = list(file_index.keys())
        if file_paths:
            delete_missing = text(
                "DELETE FROM file_index WHERE project_id = :project_id AND file_path NOT IN :paths"
            ).bindparams(bindparam("paths", expanding=True))
            db.execute(delete_missing, {"project_id": project_id, "paths": file_paths})
            delete_graph_missing = text(
                "DELETE FROM dependency_graph WHERE project_id = :project_id AND file_path NOT IN :paths"
            ).bindparams(bindparam("paths", expanding=True))
            db.execute(delete_graph_missing, {"project_id": project_id, "paths": file_paths})
        else:
            db.execute(text("DELETE FROM file_index WHERE project_id = :project_id"), {"project_id": project_id})
            db.execute(text("DELETE FROM dependency_graph WHERE project_id = :project_id"), {"project_id": project_id})

        file_index_upsert = text(
            """
            INSERT INTO file_index (
                project_id, file_path, file_type, domain_area, summary, exports, key_concepts,
                full_content, line_count, importance_score, embedding
            ) VALUES (
                :project_id, :file_path, :file_type, :domain_area, :summary, CAST(:exports AS jsonb),
                CAST(:key_concepts AS jsonb), :full_content, :line_count, :importance_score,
                CAST(:embedding AS vector)
            )
            ON CONFLICT (project_id, file_path) DO UPDATE SET
                file_type = EXCLUDED.file_type,
                domain_area = EXCLUDED.domain_area,
                summary = EXCLUDED.summary,
                exports = EXCLUDED.exports,
                key_concepts = EXCLUDED.key_concepts,
                full_content = EXCLUDED.full_content,
                line_count = EXCLUDED.line_count,
                importance_score = EXCLUDED.importance_score,
                embedding = EXCLUDED.embedding
            """
        )

        dep_graph_upsert = text(
            """
            INSERT INTO dependency_graph (project_id, file_path, imports, imported_by)
            VALUES (:project_id, :file_path, CAST(:imports AS jsonb), CAST(:imported_by AS jsonb))
            ON CONFLICT (project_id, file_path) DO UPDATE SET
                imports = EXCLUDED.imports,
                imported_by = EXCLUDED.imported_by
            """
        )

        for file_path, file_data in file_index.items():
            classification = classifications.get(file_path, {})
            summary = summaries.get(file_path, {})
            db.execute(
                file_index_upsert,
                {
                    "project_id": project_id,
                    "file_path": file_path,
                    "file_type": classification.get("file_type", "other"),
                    "domain_area": classification.get("domain_area", "other"),
                    "summary": summary.get("summary", classification.get("one_line_description", "")),
                    "exports": json.dumps(summary.get("exports", [])),
                    "key_concepts": json.dumps(summary.get("key_concepts", [])),
                    "full_content": file_data.get("content", ""),
                    "line_count": file_data.get("line_count", 0),
                    "importance_score": float(scores.get(file_path, 0)),
                    "embedding": _vector_literal(embeddings.get(file_path)),
                },
            )

            graph_entry = dep_graph.get(file_path, {"imports": [], "imported_by": []})
            db.execute(
                dep_graph_upsert,
                {
                    "project_id": project_id,
                    "file_path": file_path,
                    "imports": json.dumps(graph_entry.get("imports", [])),
                    "imported_by": json.dumps(graph_entry.get("imported_by", [])),
                },
            )

        db.commit()
        print(f"[indexer] stored {len(file_index)} files to database")
    finally:
        if local_db:
            db.close()


async def upsert_indexing_status(
    project_id: str,
    status: str,
    db: Session | None = None,
    *,
    total_files: int | None = None,
    indexed_files: int | None = None,
    error: str | None = None,
) -> None:
    local_db = False
    if db is None:
        db = SessionLocal()
        local_db = True

    try:
        now_expr = "NOW()"
        if status == "indexing":
            db.execute(
                text(
                    f"""
                    INSERT INTO indexing_status (
                        project_id, status, total_files, indexed_files, started_at, completed_at, error_message
                    ) VALUES (
                        :project_id, :status, :total_files, :indexed_files, {now_expr}, NULL, NULL
                    )
                    ON CONFLICT (project_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        total_files = EXCLUDED.total_files,
                        indexed_files = EXCLUDED.indexed_files,
                        started_at = EXCLUDED.started_at,
                        completed_at = NULL,
                        error_message = NULL
                    """
                ),
                {
                    "project_id": project_id,
                    "status": status,
                    "total_files": total_files or 0,
                    "indexed_files": indexed_files or 0,
                },
            )
        else:
            completed_at_sql = "NOW()" if status in {"complete", "failed"} else "NULL"
            db.execute(
                text(
                    f"""
                    INSERT INTO indexing_status (
                        project_id, status, total_files, indexed_files, started_at, completed_at, error_message
                    ) VALUES (
                        :project_id, :status, :total_files, :indexed_files, NULL, {completed_at_sql}, :error_message
                    )
                    ON CONFLICT (project_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        total_files = EXCLUDED.total_files,
                        indexed_files = EXCLUDED.indexed_files,
                        completed_at = EXCLUDED.completed_at,
                        error_message = EXCLUDED.error_message
                    """
                ),
                {
                    "project_id": project_id,
                    "status": status,
                    "total_files": total_files or 0,
                    "indexed_files": indexed_files or 0,
                    "error_message": error,
                },
            )
        db.commit()
    finally:
        if local_db:
            db.close()


async def run_indexing_pipeline(
    project_id: str,
    zip_path: str,
    scan_data: dict[str, Any],
    db: Session | None = None,
) -> None:
    start_time = time.time()
    db_session = db or SessionLocal()
    own_session = db is None

    try:
        project = db_session.query(Project).filter(Project.id == project_id).first()
        project_context = {
            "name": project.name if project else scan_data.get("project_name", "Unknown"),
            "core_purpose": (project.executive_summary if project and project.executive_summary else scan_data.get("core_purpose", "")),
            "framework": scan_data.get("framework", "") or ", ".join(scan_data.get("frameworks", []) or []),
        }

        await upsert_indexing_status(project_id, "indexing", db_session)

        print(f"[indexer] {project_context['name']} | extracting files...")
        file_index = await extract_source_files(zip_path)
        file_count = len(file_index)

        if file_count > MAX_INDEXABLE_SOURCE_FILES:
            error_message = (
                f"Chaos Twin supports up to {MAX_INDEXABLE_SOURCE_FILES} source files per project. "
                f"Found {file_count} source files, so indexing was skipped."
            )
            print(
                f"[indexer] ERROR: Too many files ({file_count}). "
                f"Chaos Twin supports up to {MAX_INDEXABLE_SOURCE_FILES} source files. Skipping indexing."
            )
            await upsert_indexing_status(
                project_id,
                "failed",
                db_session,
                total_files=file_count,
                indexed_files=0,
                error=error_message,
            )
            return

        await upsert_indexing_status(
            project_id,
            "indexing",
            db_session,
            total_files=file_count,
            indexed_files=0,
        )

        print(f"[indexer] classifying {len(file_index)} files...")
        classifications = await classify_files_batch(file_index, project_context)

        print("[indexer] building dependency graph...")
        dep_graph = build_dependency_graph(file_index)

        print("[indexer] calculating importance scores...")
        scores = calculate_importance_scores(file_index, classifications, dep_graph)

        print("[indexer] summarizing files...")
        summaries = await summarize_files_batch(file_index, classifications, scores, project_context)

        print("[indexer] generating embeddings...")
        embeddings = await generate_embeddings(summaries, classifications)

        print("[indexer] storing to database...")
        await store_to_database(
            project_id,
            file_index,
            classifications,
            scores,
            summaries,
            embeddings,
            dep_graph,
            db_session,
        )

        elapsed = round(time.time() - start_time, 1)
        print(f"[indexer] complete in {elapsed}s | {len(file_index)} files indexed")

        await upsert_indexing_status(
            project_id,
            "complete",
            db_session,
            total_files=len(file_index),
            indexed_files=len(summaries),
        )

        upload = (
            db_session.query(Upload)
            .filter(Upload.project_id == project_id)
            .order_by(Upload.created_at.desc())
            .first()
        )
        if upload:
            workspace_path = os.path.join(str(WORKSPACE_DIR), project_id, upload.id)
            effective_root = unwrap_root_dir(workspace_path)
            understanding_scan_data = dict(scan_data)
            understanding_scan_data["project_name"] = project_context["name"]
            understanding_scan_data["core_purpose"] = project_context["core_purpose"]
            understanding_scan_data["framework"] = project_context["framework"]
            asyncio.create_task(
                generate_understanding_backend(project_id, understanding_scan_data, effective_root)
            )

    except Exception as e:
        print(f"[indexer] FAILED: {str(e)}")
        print(traceback.format_exc())
        await upsert_indexing_status(project_id, "failed", db_session, error=str(e))
    finally:
        if own_session:
            db_session.close()
