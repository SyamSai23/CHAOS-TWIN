from __future__ import annotations

import asyncio
import json
import logging
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
from app.models.scan import Scan
from app.models.upload import Upload
from app.routers.analyze import _enrich_with_phrases, _upsert_analysis
from app.services.ast_analyzer import RouteAnalyzer
from app.services.phrase_generator import PhraseGenerator
from app.services.scanner_v3 import unwrap_root_dir
from app.services.understanding_generator import generate_understanding_backend

_openai_semaphore = asyncio.Semaphore(5)
MAX_INDEXABLE_SOURCE_FILES = 500
MAX_PRIORITIZED_SOURCE_FILES = 150
SUMMARIZATION_BATCH_SIZE = 20

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
    "page",
    "component",
    "hook",
    "store",
    "config",
    "util",
    "test",
    "style",
    "other",
}
VALID_TYPES = CLASSIFICATION_ALLOWED_TYPES

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

logger = logging.getLogger(__name__)


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


async def prioritize_source_files(
    file_index: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    def is_likely_test_file(path: str) -> bool:
        path_lower = path.lower()
        parts = path_lower.replace("\\", "/").split("/")
        filename = parts[-1]

        immediate_parent = parts[-2] if len(parts) >= 2 else ""
        if immediate_parent in ["__tests__", "tests", "specs", "__mocks__", "mocks", "fixtures", "e2e"]:
            return True

        if any(
            filename.endswith(ext)
            for ext in [
                ".test.ts",
                ".test.tsx",
                ".test.js",
                ".test.jsx",
                ".spec.ts",
                ".spec.tsx",
                ".spec.js",
                ".spec.jsx",
                ".test.py",
                ".spec.py",
            ]
        ):
            return True

        if any(
            filename.endswith(ext)
            for ext in [
                ".min.js",
                ".min.css",
                ".map",
                ".snap",
                "package-lock.json",
                "yarn.lock",
                "pnpm-lock.yaml",
            ]
        ):
            return True

        return False

    source_paths = list(file_index.keys())
    non_test_paths = [path for path in source_paths if not is_likely_test_file(path)]
    test_paths = [path for path in source_paths if is_likely_test_file(path)]
    logger.info(
        f"[indexer] pre-filtered {len(test_paths)} test/generated files, "
        f"{len(non_test_paths)} source files remain"
    )

    filtered_file_index = {path: file_index[path] for path in non_test_paths}
    total_files = len(filtered_file_index)
    if total_files <= MAX_PRIORITIZED_SOURCE_FILES:
        return filtered_file_index

    print(
        f"[indexer] {total_files} files found, running prioritization to select top "
        f"{MAX_PRIORITIZED_SOURCE_FILES}"
    )

    try:
        client = _client()
        all_paths = list(filtered_file_index.keys())
        prompt = f"""You are helping analyze a software codebase for a junior developer.

Here is the complete file tree:
{chr(10).join(all_paths)}

Select the {MAX_PRIORITIZED_SOURCE_FILES} most important files for understanding this codebase.

Prioritize in this order:
1. Entry points (main files, app files, server files, index files at root level)
2. Route definitions and URL mappings
3. Controllers and request handlers
4. Core business logic and services
5. Data models and schemas
6. Configuration files (package.json, requirements.txt, docker-compose.yml etc)
7. Key frontend pages and components

Deprioritize:
- Test files (*test*, *spec*, __tests__)
- Generated files (*.min.js, dist/, build/, .next/)
- Vendor/dependency files (node_modules/, vendor/)
- Style files (*.css, *.scss) unless very few exist
- Asset files (images, fonts, icons)
- Lock files (package-lock.json, yarn.lock)

Return ONLY a JSON array of file paths from the provided list. Do not invent paths.
Return exactly {MAX_PRIORITIZED_SOURCE_FILES} paths or fewer if the total is under {MAX_PRIORITIZED_SOURCE_FILES}.
"""

        async with _openai_semaphore:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You rank codebase files by importance. Return only valid JSON arrays of file paths from the provided list.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )

        payload = response.choices[0].message.content or "[]"
        selected_paths_raw = _extract_json_array(payload)
        selected_paths: list[str] = []
        if not selected_paths_raw:
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, list):
                    selected_paths = [str(item).strip() for item in parsed if isinstance(item, str)]
            except json.JSONDecodeError:
                selected_paths = []

        logger.debug(f"[indexer] GPT returned sample paths: {selected_paths[:5]}")
        logger.debug(f"[indexer] Source file sample paths: {all_paths[:5]}")

        normalized_source: dict[str, str] = {}
        for path in all_paths:
            key = path.lstrip("/").replace("\\", "/").lower()
            normalized_source[key] = path

        matched_paths: list[str] = []
        seen: set[str] = set()
        for gpt_path in selected_paths:
            normalized_gpt = gpt_path.lstrip("/").replace("\\", "/").lower()
            if normalized_gpt in normalized_source:
                original = normalized_source[normalized_gpt]
                if original not in seen:
                    matched_paths.append(original)
                    seen.add(original)
                continue

            for key, original in normalized_source.items():
                if key.endswith(normalized_gpt) or normalized_gpt.endswith(key):
                    if original not in seen:
                        matched_paths.append(original)
                        seen.add(original)
                    break

        if len(matched_paths) < 10:
            raise ValueError("prioritization returned no valid file paths")

        prioritized = {
            path: filtered_file_index[path]
            for path in all_paths
            if path in seen
        }
        print(
            f"[indexer] prioritization complete: {len(prioritized)} files selected from "
            f"{total_files}"
        )
        return prioritized
    except Exception as exc:
        print(f"[indexer] prioritization failed, using all {total_files} files")
        print(f"[indexer] prioritization warning: {exc}")
        return filtered_file_index


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
    file_type = str(item.get("file_type") or item.get("type") or "other").strip().lower()
    domain_area = str(item.get("domain_area", "other")).strip().lower()
    return {
        "file_path": file_path,
        "file_type": file_type if file_type in CLASSIFICATION_ALLOWED_TYPES else "other",
        "domain_area": domain_area if domain_area in CLASSIFICATION_ALLOWED_DOMAINS else "other",
        "is_important": bool(
            item.get(
                "is_important",
                file_type
                in {
                    "entry_point",
                    "controller",
                    "route",
                    "model",
                    "service",
                    "page",
                    "store",
                },
            )
        ),
        "one_line_description": str(item.get("one_line_description", "")).strip(),
    }


async def classify_files_batch(
    file_index: dict[str, dict[str, Any]], project_context: dict[str, str]
) -> dict[str, dict[str, Any]]:
    client = _client()
    paths = list(file_index.keys())
    results: dict[str, dict[str, Any]] = {}

    def deterministic_classify(file_path: str, language: str) -> str | None:
        """Returns a type if we can determine it with certainty, else None."""
        path_lower = file_path.lower().replace("\\", "/")
        parts = path_lower.split("/")
        filename = parts[-1]

        if any(
            filename.endswith(ext)
            for ext in [
                ".test.ts",
                ".test.tsx",
                ".test.js",
                ".test.jsx",
                ".spec.ts",
                ".spec.tsx",
                ".spec.js",
                ".spec.jsx",
                "_test.go",
                "_test.py",
                ".test.py",
            ]
        ):
            return "test"

        if any(filename.endswith(ext) for ext in [".css", ".scss", ".sass", ".less"]):
            return "style"

        if filename in [
            "package.json",
            "tsconfig.json",
            "tsconfig.base.json",
            "docker-compose.yml",
            "docker-compose.yaml",
            "dockerfile",
            "requirements.txt",
            "pipfile",
            "pyproject.toml",
            "setup.py",
            "makefile",
            ".env",
            ".env.example",
            "jest.config.ts",
            "jest.config.js",
            "vite.config.ts",
            "webpack.config.js",
            "eslint.config.js",
            ".eslintrc.js",
            ".prettierrc",
            "tailwind.config.js",
            "tailwind.config.ts",
            "prisma/schema.prisma",
            "schema.prisma",
        ]:
            return "config"

        if filename in [
            ".eslintignore",
            "eslintignore",
            ".gitignore",
            "gitignore",
            ".prettierignore",
            "prettierignore",
            ".prettierrc",
            "prettierrc",
            ".editorconfig",
            "editorconfig",
            ".nvmrc",
            "nvmrc",
            ".babelrc",
            "babelrc",
            "migration_lock.toml",
            ".dockerignore",
            "dockerignore",
        ]:
            return "config"

        if any(seg in parts for seg in ["e2e", "cypress", "playwright"]):
            return "test"

        if filename == "prisma-client.ts" or filename == "prisma-client.js":
            return "service"

        if filename in ["seed.ts", "seed.js", "seed.py", "seeds.rb"]:
            return "util"

        return None

    def detect_language(file_path: str, content: str) -> str:
        try:
            detector = getattr(enry, "get_language", None)
            if callable(detector):
                detected = detector(file_path, content.encode("utf-8", errors="ignore"))
                if detected:
                    return str(detected)
        except Exception:
            pass

        extension = str(file_index[file_path].get("extension", "")).lower()
        fallback_map = {
            ".py": "Python",
            ".js": "JavaScript",
            ".jsx": "JavaScript",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".java": "Java",
            ".go": "Go",
            ".rb": "Ruby",
            ".rs": "Rust",
            ".cs": "C#",
            ".cpp": "C++",
            ".c": "C",
            ".php": "PHP",
            ".css": "CSS",
            ".scss": "SCSS",
            ".sass": "Sass",
            ".less": "Less",
            ".html": "HTML",
            ".vue": "Vue",
            ".swift": "Swift",
            ".kt": "Kotlin",
        }
        return fallback_map.get(extension, "Unknown")

    async def classify_single_batch(batch_paths: list[str]) -> list[dict[str, Any]]:
        file_list: list[dict[str, str]] = []
        for path in batch_paths:
            preview = _first_lines(file_index[path]["content"], 30)
            file_list.append(
                {
                    "path": path,
                    "language": detect_language(path, file_index[path]["content"]),
                    "preview": preview,
                }
            )

        prompt = f"""You are an expert software engineer helping a junior developer navigate an unfamiliar codebase.

Your job is to classify each file into exactly one category based on its PURPOSE — not its name or location.

Categories and their precise definitions:
- entry_point: The main starting file of the application. Where execution begins. Examples: main.ts, app.py, server.js, index.ts at root level, wsgi.py, manage.py
- controller: Handles incoming HTTP requests and returns responses. Contains request handlers, route handlers, view functions. Examples: UserController, views.py, handlers.go
- route: Defines URL mappings and routing configuration. Examples: routes.ts, urls.py, router.rb, routes.go — files whose PRIMARY purpose is mapping URLs to handlers
- model: Defines data structures, database schemas, or entity shapes. Examples: User.ts, Article.model.ts, schema.prisma, models.py
- service: Contains business logic, domain operations, data transformations. Not HTTP-specific. Examples: article.service.ts, payment_service.py, booking_service.go
- middleware: Intercepts requests/responses for cross-cutting concerns. Examples: auth.middleware.ts, logging.py, cors.go
- component: A reusable UI element. Examples: Button.tsx, ProductCard.vue, UserAvatar.jsx
- page: A full UI screen or view. Examples: LoginPage.tsx, DashboardScreen.tsx, home.html
- hook: Stateful logic abstraction. Examples: useAuth.ts, useCart.tsx
- store: State management. Examples: userSlice.ts, store.ts, AppContext.tsx
- config: Application configuration. Examples: database.config.ts, settings.py, .env files, docker-compose.yml, package.json, tsconfig.json
- util: Pure helper functions, shared utilities, constants. Examples: helpers.ts, utils.py, constants.go, formatters.ts
- test: Any test or spec file. Examples: *.test.ts, *.spec.js, *_test.go, test_*.py
- style: CSS, SCSS, styling files. Examples: styles.css, theme.scss, tailwind.config.js
- other: Only use this if NONE of the above categories fit after careful consideration

Rules:
1. Base your decision on the file's PURPOSE, not its name or folder
2. A file named "utils.ts" inside a controllers/ folder that handles requests is a CONTROLLER, not util
3. Never default to "other" without genuinely considering all categories
4. If a file could be multiple categories, pick the ONE that best describes its primary purpose
5. Config files (package.json, tsconfig, docker-compose, .env, Makefile, requirements.txt) are always "config"
6. Test files are always "test" regardless of what else they do

Here are the files to classify:
{json.dumps(file_list, ensure_ascii=False)}

For each file, you are given:
- path: the file path
- language: detected programming language
- preview: first 30 lines of the file

Return ONLY a JSON array, no markdown, no explanation:
[
  {{"path": "src/controllers/user.ts", "type": "controller"}},
  {{"path": "src/models/user.ts", "type": "model"}}
]
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
                max_tokens=1000,
                temperature=0.1,
            )
        payload = response.choices[0].message.content or "[]"
        items = _extract_json_array(payload)
        for item in items:
            if item.get("type") not in VALID_TYPES:
                item["type"] = "other"
        return items

    gpt_paths: list[str] = []
    for path in paths:
        detected_type = deterministic_classify(path, "")
        if detected_type is None:
            gpt_paths.append(path)
            continue
        results[path] = _normalize_classification(path, {"type": detected_type})

    batches = [gpt_paths[start : start + 15] for start in range(0, len(gpt_paths), 15)]
    tasks = [classify_single_batch(batch) for batch in batches]
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

    for batch_result in batch_results:
        if isinstance(batch_result, Exception):
            print(f"[indexer] classify batch failed: {batch_result}")
            continue
        for item in batch_result:
            path = str(item.get("path") or item.get("file_path") or "").strip()
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


async def detect_implicit_routes(project_id: str, extracted_files: list[str]) -> list[dict[str, Any]]:
    """
    Detect routes defined by file structure conventions.
    Works for Next.js, Nuxt, SvelteKit, and similar file-based routers.
    No GPT needed — purely structural.
    """
    implicit_routes: list[dict[str, Any]] = []

    for file_path in extracted_files:
        path_lower = file_path.lower().replace("\\", "/")
        parts = path_lower.split("/")

        if "pages" in parts and "api" in parts:
            api_idx = parts.index("api")
            route_parts = parts[api_idx + 1 :]
            route_path = "/" + "/".join(route_parts)
            route_path = re.sub(r"\[([^\]]+)\]", r":\1", route_path)
            route_path = re.sub(r"\.(ts|tsx|js|jsx)$", "", route_path)
            route_path = re.sub(r"/index$", "", route_path) or "/"
            implicit_routes.append(
                {
                    "method": "ANY",
                    "path": route_path,
                    "file": file_path,
                    "component": "api",
                    "source": "file_based",
                }
            )

        if "app" in parts and parts[-1] in ["route.ts", "route.js", "route.tsx"]:
            app_idx = parts.index("app")
            route_parts = parts[app_idx + 1 : -1]
            route_path = "/" + "/".join(route_parts)
            route_path = re.sub(r"\(([^\)]+)\)", "", route_path)
            route_path = re.sub(r"\[([^\]]+)\]", r":\1", route_path)
            route_path = route_path.replace("//", "/") or "/"
            implicit_routes.append(
                {
                    "method": "ANY",
                    "path": route_path,
                    "file": file_path,
                    "component": "api",
                    "source": "file_based",
                }
            )

    return implicit_routes


async def build_prefix_map(
    route_files: list[dict[str, Any]],
    workspace_root: str,
    openai_client: AsyncOpenAI,
) -> dict[str, str]:
    """
    Read route aggregator files to build a map of:
    filename/module -> URL prefix
    """
    prefix_map: dict[str, str] = {}

    for file_record in route_files:
        if str(file_record.get("file_type", "")) != "route":
            continue

        file_path = os.path.join(workspace_root, str(file_record.get("file_path", "")))
        if not os.path.exists(file_path):
            continue

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            async with _openai_semaphore:
                response = await openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    max_tokens=500,
                    messages=[
                        {
                            "role": "user",
                            "content": f"""This file registers routes with URL prefixes.

File: {file_record.get("file_path", "")}
Content:
{content[:5000]}

Extract all router/blueprint registrations with their URL prefixes.
Return ONLY a JSON array:
[
  {{"module": "users", "prefix": "/api/users"}},
  {{"module": "articles", "prefix": "/api/articles"}}
]

The "module" should be the imported module name or file name without extension.
If no prefix registrations found, return [].
Return ONLY JSON, no markdown.""",
                        }
                    ],
                )

            raw = (response.choices[0].message.content or "").strip()
            raw = re.sub(r"```json|```", "", raw).strip()
            registrations = json.loads(raw)
            if not isinstance(registrations, list):
                continue

            for reg in registrations:
                if isinstance(reg, dict) and reg.get("module") and reg.get("prefix"):
                    prefix_map[str(reg["module"]).lower()] = str(reg["prefix"])
        except Exception:
            continue

    expanded_map: dict[str, str] = {}
    for module, prefix in prefix_map.items():
        expanded_map[module] = prefix
        if "." in module:
            expanded_map[module.split(".")[-1]] = prefix
    prefix_map = expanded_map

    logger.info(f"[indexer] built prefix map: {prefix_map}")
    return prefix_map


def remove_unprefixed_duplicates(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Remove routes that are unprefixed duplicates of longer routes.

    Example: if we have both:
      GET /feed (file: articles_common.py)
      GET /articles/feed (file: articles_common.py)

    Keep only GET /articles/feed and drop GET /feed.
    """
    by_file: dict[str, list[dict[str, Any]]] = {}
    for route in routes:
        file_path = str(route.get("file", ""))
        by_file.setdefault(file_path, []).append(route)

    routes_to_remove: set[tuple[str, str, str]] = set()

    for file_path, file_routes in by_file.items():
        for i, route_a in enumerate(file_routes):
            path_a = str(route_a.get("path", ""))
            method_a = str(route_a.get("method", ""))
            for j, route_b in enumerate(file_routes):
                if i == j:
                    continue
                path_b = str(route_b.get("path", ""))
                method_b = str(route_b.get("method", ""))
                if (
                    method_a == method_b
                    and len(path_b) > len(path_a)
                    and path_b.endswith(path_a)
                    and path_a != "/"
                ):
                    routes_to_remove.add((method_a, path_a, file_path))

    cleaned = [
        route
        for route in routes
        if (str(route.get("method", "")), str(route.get("path", "")), str(route.get("file", "")))
        not in routes_to_remove
    ]

    removed_count = len(routes) - len(cleaned)
    if removed_count > 0:
        logger.info(f"[indexer] removed {removed_count} unprefixed duplicate routes")

    return cleaned


async def extract_routes_via_gpt(
    project_id: str,
    db: Session,
    workspace_root: str,
    extracted_files: list[str],
) -> list[dict[str, Any]]:
    """
    Extract routes from files classified as route/controller/entry_point.
    Uses GPT to understand any framework in any language.
    """
    route_files = db.execute(
        text(
            """
            SELECT file_path, file_type
            FROM file_index
            WHERE project_id = :project_id
              AND file_type IN :types
            ORDER BY importance_score DESC, file_path ASC
            """
        ).bindparams(bindparam("types", expanding=True)),
        {
            "project_id": project_id,
            "types": ["route", "controller", "entry_point", "middleware"],
        },
    ).mappings().all()

    service_route_files = db.execute(
        text(
            """
            SELECT file_path, file_type
            FROM file_index
            WHERE project_id = :project_id
              AND file_type = 'service'
              AND (
                file_path LIKE :routes_pattern
                OR file_path LIKE :api_pattern
                OR file_path LIKE :views_pattern
                OR file_path LIKE :handlers_pattern
              )
            ORDER BY importance_score DESC, file_path ASC
            """
        ),
        {
            "project_id": project_id,
            "routes_pattern": "%/routes/%",
            "api_pattern": "%/api/%",
            "views_pattern": "%/views/%",
            "handlers_pattern": "%/handlers/%",
        },
    ).mappings().all()

    seen_route_files: set[tuple[str, str]] = set()
    combined_route_files: list[dict[str, Any]] = []
    for record in list(route_files) + list(service_route_files):
        key = (str(record.get("file_path", "")), str(record.get("file_type", "")))
        if key in seen_route_files:
            continue
        seen_route_files.add(key)
        combined_route_files.append(dict(record))
    route_files = combined_route_files

    if not route_files:
        logger.info("[indexer] no route files found in file_index, skipping GPT route extraction")
        return []

    logger.info(
        f"[indexer] extracting routes from {len(route_files)} classified route/controller files"
    )

    openai_client = _client()
    extracted_lookup = set(extracted_files)
    all_routes: list[dict[str, Any]] = []
    prefix_map = await build_prefix_map(route_files, workspace_root, openai_client)

    for file_record in route_files:
        try:
            relative_path = str(file_record["file_path"])
            file_path = os.path.join(workspace_root, relative_path)
            if relative_path not in extracted_lookup or not os.path.exists(file_path):
                continue

            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            if len(content.strip()) < 50:
                continue

            file_module = relative_path.split("/")[-1]
            file_module = re.sub(r"\.(py|ts|tsx|js|jsx)$", "", file_module).lower()
            file_prefix = prefix_map.get(file_module, "")
            prefix_hint = (
                f"\nThis router is registered with prefix: {file_prefix}"
                if file_prefix
                else "\nNo known URL prefix for this file."
            )

            async with _openai_semaphore:
                response = await openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    max_tokens=2000,
                    messages=[
                        {
                            "role": "user",
                            "content": f"""You are analyzing source code to extract API routes and entry points.
This could be ANY language or framework. Do not assume anything.

File: {relative_path}
Language: {file_record["file_type"]}
{prefix_hint}
Content:
{content[:20000]}

Extract every HTTP route, API endpoint, URL handler, or page route defined in this file.

Look for ANY pattern that handles an incoming request:
- Function decorators: @app.get(), @router.post(), @GetMapping(), @Controller()
- Function registrations: app.get('/path', handler), router.use('/path', ...)
- URL mappings: urlpatterns = [path(...)], Route::get(...), r.GET(...)
- Export conventions: export async function GET(), export default handler
- Resource definitions: resources :articles, apiRouter.route('/path')

For each route found, return:
{{
  "method": "GET|POST|PUT|DELETE|PATCH|ANY",
  "path": "/exact/path/as/defined",
  "handler": "exact function or method name",
  "line_number": 42
}}

IMPORTANT:
- Use the EXACT path as written in the code, don't infer or expand
- If method cannot be determined, use "ANY"
- If this file defines NO routes, return []
- Return ONLY a JSON array, no markdown, no explanation
""",
                        }
                    ],
                )

            raw = (response.choices[0].message.content or "").strip()
            raw = re.sub(r"```json|```", "", raw).strip()
            routes = _extract_json_array(raw)

            for route in routes:
                if not isinstance(route, dict):
                    continue
                if not route.get("path"):
                    continue
                all_routes.append(
                    {
                        "method": str(route.get("method", "ANY")).upper(),
                        "path": str(route.get("path", "")),
                        "file": relative_path,
                        "component": str(file_record["file_type"]),
                        "handler": route.get("handler", ""),
                        "line_number": route.get("line_number", 0),
                        "source": "gpt_extracted",
                    }
                )

        except json.JSONDecodeError:
            logger.warning(f"[indexer] GPT returned invalid JSON for routes in {file_record['file_path']}")
            continue
        except Exception as e:
            logger.warning(f"[indexer] route extraction failed for {file_record['file_path']}: {e}")
            continue

    logger.info(f"[indexer] GPT extracted {len(all_routes)} routes from {len(route_files)} files")
    return all_routes


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
        "page": 7,
        "component": 4,
        "hook": 4,
        "store": 5,
        "config": 2,
        "util": 2,
        "test": -10,
        "style": 1,
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
        if classifications.get(path, {}).get("file_type") not in {"test"}
    ]
    summaries: dict[str, dict[str, Any]] = {}
    total_batches = max((len(paths_to_summarize) + SUMMARIZATION_BATCH_SIZE - 1) // SUMMARIZATION_BATCH_SIZE, 1)

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

    batches = [
        paths_to_summarize[start : start + SUMMARIZATION_BATCH_SIZE]
        for start in range(0, len(paths_to_summarize), SUMMARIZATION_BATCH_SIZE)
    ]
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
        file_index = await prioritize_source_files(file_index)
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
        else:
            logger.warning(f"[indexer] no upload found for project {project_id}, skipping route extraction")
            workspace_path = os.path.join(str(WORKSPACE_DIR), project_id)
            logger.warning(f"[indexer] no upload found, using fallback workspace path: {workspace_path}")

        effective_root = unwrap_root_dir(workspace_path)
        latest_scan = (
            db_session.query(Scan)
            .filter(Scan.project_id == project_id)
            .order_by(Scan.created_at.desc())
            .first()
        )

        existing_routes = []
        if latest_scan and latest_scan.routes:
            existing_routes = [route for route in latest_scan.routes if isinstance(route, dict)]
        print(f"[indexer] scanner routes: {len(existing_routes)} found (latest_scan={'found' if latest_scan else 'NONE'})")

        implicit_routes = await detect_implicit_routes(project_id, list(file_index.keys()))
        gpt_routes = await extract_routes_via_gpt(
            project_id,
            db_session,
            str(effective_root),
            list(file_index.keys()),
        )
        print(f"[indexer] route extraction complete: {len(implicit_routes)} implicit, {len(gpt_routes)} gpt")

        all_routes = existing_routes + implicit_routes + gpt_routes
        seen: set[tuple[str, str]] = set()
        unique_routes: list[dict[str, Any]] = []
        for route in all_routes:
            if not isinstance(route, dict):
                continue
            method = str(route.get("method", "ANY")).upper()
            path = str(route.get("path", "")).strip()
            if not path:
                continue
            key = (method, path)
            if key in seen:
                continue
            seen.add(key)
            normalized_route = dict(route)
            normalized_route["method"] = method
            normalized_route["path"] = path
            unique_routes.append(normalized_route)

        route_type_files = {
            str(row.file_path)
            for row in db_session.execute(
                text(
                    """
                    SELECT file_path
                    FROM file_index
                    WHERE project_id = :project_id
                      AND file_type = 'route'
                    """
                ),
                {"project_id": project_id},
            ).mappings().all()
        }
        unique_routes = [
            route
            for route in unique_routes
            if not (
                route.get("method") == "ANY"
                and str(route.get("file", "")) in route_type_files
            )
        ]
        logger.info(f"[indexer] after filtering aggregator routes: {len(unique_routes)} routes remain")

        unique_routes = remove_unprefixed_duplicates(unique_routes)

        logger.info(
            f"[indexer] total unique routes: {len(unique_routes)} "
            f"({len(implicit_routes)} file-based, {len(gpt_routes)} GPT-extracted)"
        )

        if latest_scan and unique_routes:
            latest_scan.routes = unique_routes
            db_session.flush()

            logger.info(f"[indexer] analyzing routes: {len(unique_routes)} found")
            analyzer = RouteAnalyzer(str(effective_root))
            phrase_gen = PhraseGenerator()
            analyzed = 0
            failed = 0

            for route in unique_routes:
                try:
                    result = analyzer.analyze_route(route)
                    if result is None:
                        failed += 1
                        continue
                    _enrich_with_phrases(result, phrase_gen)
                    _upsert_analysis(db_session, project_id, latest_scan.id, result)
                    analyzed += 1
                except Exception as route_error:
                    logger.warning(f"[indexer] deep analysis failed for {route.get('path', '')}: {route_error}")
                    failed += 1

            db_session.commit()
            logger.info(f"[indexer] route analysis complete: {analyzed} analyzed, {failed} failed")

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
