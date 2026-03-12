from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.services.identity import make_component_key
from app.services.route_extraction import detect_routes


RUNTIME_MARKERS: set[str] = {
    "Dockerfile", "package.json", "requirements.txt", "go.mod",
    "Cargo.toml", "pom.xml", "Gemfile",
}
SOURCE_EXTENSIONS: set[str] = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".cs", ".go",
    ".rs", ".rb", ".php", ".swift", ".kt", ".cpp", ".cc", ".cxx", ".c",
}
ENTRY_FILES: dict[str, set[str]] = {
    "Python": {"main.py", "app.py", "wsgi.py", "asgi.py"},
    "JavaScript": {"index.js", "App.tsx", "server.js", "App.jsx"},
    "TypeScript": {"index.ts", "App.tsx", "server.ts"},
    "C#": {"Program.cs", "Startup.cs"},
    "Go": {"main.go"},
    "Rust": {"main.rs"},
    "Java": {"Main.java", "Application.java"},
    "Ruby": {"app.rb"},
    "PHP": {"index.php"},
}

_FRONTEND_MARKERS: set[str] = {
    "vite.config.ts", "vite.config.js", "next.config.js", "next.config.mjs",
    "angular.json", "nuxt.config.js", "nuxt.config.ts",
}
_BACKEND_MARKERS: set[str] = {
    "requirements.txt", "pyproject.toml", "Pipfile", "go.mod",
    "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "composer.json", "manage.py",
}
_FRONTEND_NAMES: set[str] = {"frontend", "client", "web", "ui"}
_BACKEND_NAMES: set[str] = {"backend", "server", "api"}
_SERVICE_NAMES: set[str] = {"service", "services", "svc", "microservice"}
_WORKER_NAMES: set[str] = {"worker", "scheduler", "cron", "jobs", "consumer"}
_LIBRARY_NAMES: set[str] = {"lib", "library", "sdk", "packages", "shared", "common"}
_CLI_NAMES: set[str] = {"cli", "cmd", "command"}
_WRAPPER_CHILD_NAMES: set[str] = {"app", "src", "api", "web", "client", "server"}

_ROLE_ORDER = [
    "entry",
    "frontend_entry",
    "controller",
    "service",
    "repository",
    "middleware",
    "config_infra",
    "model_schema",
    "frontend_page",
    "frontend_ui",
    "shared",
]

_PY_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\.\w]+)\s+import|import\s+([\w.]+))", re.M)
_JS_IMPORT_RE = re.compile(r"(?:import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]|require\(\s*['\"]([^'\"]+)['\"]\s*\))", re.M)


@dataclass
class ComponentCandidate:
    name: str
    type: str
    root_path: str
    component_key: str
    entry_file: Optional[str]
    file_count: int
    languages: list[str]
    markers: list[str]
    key_files: list[str]
    detected_roles: list[str]
    role_counts: dict[str, int]
    ownership_summary: dict
    boundary_evidence: list[str]
    best_target: dict
    confidence: float
    confidence_label: str
    score: float = 0.0
    source_files: list[str] = field(default_factory=list)
    direct_source_count: int = 0
    route_count: int = 0
    wrapper_child: Optional[str] = None

    def strength_key(self) -> tuple:
        return (
            round(self.score, 4),
            self.route_count,
            len(self.detected_roles),
            1 if self.entry_file else 0,
            self.direct_source_count,
            -self.root_path.count("/"),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "root_path": self.root_path,
            "component_key": self.component_key,
            "entry_file": self.entry_file,
            "file_count": self.file_count,
            "languages": self.languages,
            "entry_points": [self.entry_file] if self.entry_file else [],
            "markers": self.markers,
            "key_files": self.key_files,
            "detected_roles": self.detected_roles,
            "role_counts": self.role_counts,
            "ownership_summary": self.ownership_summary,
            "boundary_evidence": self.boundary_evidence,
            "best_target": self.best_target,
            "confidence": self.confidence,
            "confidence_label": self.confidence_label,
        }


def detect_components(files: list[dict], languages: list[str], root: str) -> list[dict]:
    routes = detect_routes(files=files, languages=languages, root=root, components=[])
    route_file_counts = Counter(
        route.get("file") for route in routes if isinstance(route, dict) and route.get("file")
    )
    route_prefixes = _route_prefixes_by_file(routes)
    import_tokens = _collect_import_tokens(files, root)
    candidate_paths = _candidate_paths(files)

    candidates: list[ComponentCandidate] = []
    for candidate_path in candidate_paths:
        candidate = _build_candidate(
            files=files,
            languages=languages,
            root=root,
            dir_path=candidate_path,
            route_file_counts=route_file_counts,
            route_prefixes=route_prefixes,
            import_tokens=import_tokens,
        )
        if candidate is not None:
            candidates.append(candidate)

    accepted = _select_candidates(candidates, files)
    return [candidate.to_dict() for candidate in accepted]


def _build_candidate(
    files: list[dict],
    languages: list[str],
    root: str,
    dir_path: str,
    route_file_counts: Counter,
    route_prefixes: dict[str, list[str]],
    import_tokens: dict[str, set[str]],
) -> Optional[ComponentCandidate]:
    scoped_files = [file_info for file_info in files if _is_under(dir_path, file_info["path"])]
    if not scoped_files:
        return None

    source_files = [file_info for file_info in scoped_files if file_info["extension"] in SOURCE_EXTENSIONS]
    if not source_files:
        return None

    direct_files = [file_info for file_info in scoped_files if _is_direct_child(dir_path, file_info["path"])]
    direct_basenames = {os.path.basename(file_info["path"]) for file_info in direct_files}
    direct_markers = sorted(direct_basenames & RUNTIME_MARKERS)
    direct_source_count = sum(1 for file_info in direct_files if file_info["extension"] in SOURCE_EXTENSIONS)
    entry_file = _find_entry_file(source_files, languages)
    scoped_languages = _scoped_languages(source_files)
    role_examples, role_counts = _classify_roles(source_files, route_file_counts)
    detected_roles = [role for role in _ROLE_ORDER if role in role_counts]
    route_files = sorted(
        path for path in route_file_counts if path and route_file_counts[path] and _is_under(dir_path, path)
    )
    route_count = sum(route_file_counts[path] for path in route_files)
    internal_import_count = _count_internal_imports(dir_path, source_files, import_tokens)
    wrapper_child = _dominant_child(dir_path, source_files)

    component_type, type_reasons = _classify_component_type(
        dir_path=dir_path,
        direct_basenames=direct_basenames,
        source_files=source_files,
        entry_file=entry_file,
        route_count=route_count,
        role_counts=role_counts,
    )

    score = 0.0
    evidence: list[str] = []

    if direct_markers:
        score += 3.0
        evidence.append(f"direct runtime markers: {', '.join(direct_markers[:3])}")
    if entry_file:
        entry_depth = _relative_path(dir_path, entry_file).count("/")
        score += 2.5 if entry_depth <= 1 else 1.5
        evidence.append(f"entrypoint proximity: {entry_file}")
    if route_count:
        score += min(3.0, 1.5 + (0.2 * min(route_count, 8)))
        evidence.append(f"route ownership: {route_count} routes across {len(route_files)} files")
    if detected_roles:
        score += min(2.5, 0.6 * len(detected_roles))
        evidence.append(f"structural roles: {', '.join(detected_roles[:4])}")
    if internal_import_count:
        score += min(2.0, 0.25 * internal_import_count)
        evidence.append(f"internal import cohesion: {internal_import_count} local import signals")
    if direct_source_count >= 2:
        score += 0.8
    if len(source_files) >= 8:
        score += 0.8
    if component_type != "unknown":
        score += 1.2
        evidence.extend(type_reasons[:2])
    if dir_path == "." and wrapper_child:
        score -= 1.0
        evidence.append(f"wrapper root dominated by {wrapper_child}")

    if score < 3.5:
        return None

    confidence = round(min(0.45 + (score / 12.0), 0.99), 2)
    confidence_label = "high" if confidence >= 0.8 else "medium" if confidence >= 0.65 else "low"
    best_target = _best_target_for_component(
        dir_path=dir_path,
        component_type=component_type,
        entry_file=entry_file,
        role_examples=role_examples,
        route_files=route_files,
        markers=direct_markers,
    )
    key_files = _build_key_files(dir_path, direct_markers, entry_file, role_examples, route_files, best_target)
    ownership_summary = {
        "owned_source_files": len(source_files),
        "direct_source_files": direct_source_count,
        "route_count": route_count,
        "route_files": route_files[:5],
        "route_prefixes": _stable_unique([
            prefix for path in route_files for prefix in route_prefixes.get(path, []) if prefix
        ])[:5],
        "role_examples": {role: paths[:3] for role, paths in role_examples.items()},
        "entry_file": entry_file,
        "internal_import_count": internal_import_count,
    }

    return ComponentCandidate(
        name=_component_name_for(dir_path, component_type),
        type=component_type,
        root_path=dir_path,
        component_key=make_component_key(dir_path),
        entry_file=entry_file,
        file_count=len(scoped_files),
        languages=scoped_languages,
        markers=direct_markers,
        key_files=key_files,
        detected_roles=detected_roles,
        role_counts=dict(sorted(role_counts.items())),
        ownership_summary=ownership_summary,
        boundary_evidence=evidence[:6],
        best_target=best_target,
        confidence=confidence,
        confidence_label=confidence_label,
        score=score,
        source_files=[file_info["path"] for file_info in source_files],
        direct_source_count=direct_source_count,
        route_count=route_count,
        wrapper_child=wrapper_child,
    )


def _select_candidates(candidates: list[ComponentCandidate], files: list[dict]) -> list[ComponentCandidate]:
    if not candidates:
        return []

    by_root = {candidate.root_path: candidate for candidate in candidates}
    top_level = [
        candidate
        for candidate in candidates
        if candidate.root_path != "." and candidate.root_path.count("/") == 0 and candidate.score >= 5.0
    ]
    monorepo_mode = len(top_level) >= 2

    accepted: list[ComponentCandidate] = []
    if monorepo_mode:
        accepted = sorted(top_level, key=lambda item: (item.root_path, -item.score))
    else:
        strongest = max(
            candidates,
            key=lambda item: (
                item.score,
                item.route_count,
                len(item.detected_roles),
                1 if item.root_path != "." else 0,
                item.direct_source_count,
            ),
        )
        if strongest.root_path == "." and strongest.wrapper_child and strongest.wrapper_child in by_root:
            child = by_root[strongest.wrapper_child]
            if child.strength_key() >= strongest.strength_key():
                strongest = child
        accepted = [strongest]

        additional = [
            candidate for candidate in candidates
            if candidate.root_path != strongest.root_path
            and not _overlaps(candidate.root_path, strongest.root_path)
            and candidate.score >= 5.5
        ]
        accepted.extend(sorted(additional, key=lambda item: item.root_path))

    accepted = _dedupe_nested_candidates(sorted(accepted, key=lambda item: item.root_path.count("/")))

    non_root = [candidate for candidate in accepted if candidate.root_path != "."]
    root_candidate = next((candidate for candidate in accepted if candidate.root_path == "."), None)
    if non_root and root_candidate is not None:
        claimed_prefixes = [candidate.root_path + "/" for candidate in non_root]
        unclaimed_sources = [
            file_info["path"] for file_info in files
            if file_info["extension"] in SOURCE_EXTENSIONS
            and not any(file_info["path"].startswith(prefix) for prefix in claimed_prefixes)
        ]
        if len(unclaimed_sources) < 5:
            accepted = non_root

    return sorted(accepted, key=lambda item: item.root_path)


def _dedupe_nested_candidates(candidates: list[ComponentCandidate]) -> list[ComponentCandidate]:
    accepted: list[ComponentCandidate] = []
    for candidate in candidates:
        nested_parent = next(
            (
                parent for parent in accepted
                if parent.root_path != "." and candidate.root_path.startswith(parent.root_path + "/")
            ),
            None,
        )
        if nested_parent is None:
            accepted.append(candidate)
            continue
        if candidate.strength_key() > nested_parent.strength_key() and nested_parent.wrapper_child == candidate.root_path:
            accepted = [item for item in accepted if item.root_path != nested_parent.root_path]
            accepted.append(candidate)
    return accepted


def _candidate_paths(files: list[dict]) -> list[str]:
    candidates = {"."}
    for file_info in files:
        parts = file_info["path"].split("/")
        if len(parts) >= 2:
            candidates.add(parts[0])
        if len(parts) >= 3:
            candidates.add(parts[0] + "/" + parts[1])
    return sorted(candidates)


def _classify_component_type(
    dir_path: str,
    direct_basenames: set[str],
    source_files: list[dict],
    entry_file: Optional[str],
    route_count: int,
    role_counts: Counter,
) -> tuple[str, list[str]]:
    dirname = os.path.basename(dir_path).lower() if dir_path != "." else ""
    reasons: list[str] = []

    if dirname in _WORKER_NAMES:
        return "worker", [f"directory naming convention: {dirname}"]
    if dirname in _CLI_NAMES:
        return "cli", [f"directory naming convention: {dirname}"]

    frontend_signal = 0
    backend_signal = 0
    service_signal = 0
    library_signal = 0

    if dirname in _FRONTEND_NAMES:
        frontend_signal += 3
        reasons.append(f"directory naming convention: {dirname}")
    if dirname in _BACKEND_NAMES:
        backend_signal += 3
        reasons.append(f"directory naming convention: {dirname}")
    if dirname in _SERVICE_NAMES:
        service_signal += 3
        reasons.append(f"directory naming convention: {dirname}")
    if dirname in _LIBRARY_NAMES:
        library_signal += 2
        reasons.append(f"directory naming convention: {dirname}")

    if direct_basenames & _FRONTEND_MARKERS:
        frontend_signal += 3
        reasons.append("frontend runtime marker detected")
    if direct_basenames & _BACKEND_MARKERS:
        backend_signal += 3
        reasons.append("backend runtime marker detected")

    if role_counts.get("frontend_entry") or role_counts.get("frontend_ui") or role_counts.get("frontend_page"):
        frontend_signal += 3
    if role_counts.get("controller") or route_count:
        backend_signal += 3
    if role_counts.get("service"):
        service_signal += 2
    if role_counts.get("repository") or role_counts.get("config_infra") or role_counts.get("model_schema"):
        backend_signal += 2
    if role_counts.get("shared") and not route_count and not (direct_basenames & (RUNTIME_MARKERS | _BACKEND_MARKERS | _FRONTEND_MARKERS)):
        library_signal += 1

    if entry_file and entry_file.endswith((".tsx", ".jsx")):
        frontend_signal += 2
    if entry_file and entry_file.endswith((".py", ".java", ".go", ".rb", ".ts", ".js")) and route_count:
        backend_signal += 2

    if frontend_signal >= 4 and backend_signal >= 4:
        return "fullstack", reasons
    if service_signal >= max(frontend_signal, backend_signal) and service_signal >= 3:
        return "service", reasons
    if frontend_signal >= max(backend_signal, library_signal) and frontend_signal >= 3:
        return "frontend", reasons
    if backend_signal >= max(frontend_signal, library_signal) and backend_signal >= 3:
        return "backend", reasons
    if library_signal >= 2:
        return "library", reasons
    return "unknown", reasons


def _classify_roles(source_files: list[dict], route_file_counts: Counter) -> tuple[dict[str, list[str]], Counter]:
    role_examples: dict[str, list[str]] = defaultdict(list)
    role_counts: Counter = Counter()

    for file_info in source_files:
        path = file_info["path"]
        roles = _roles_for_path(path, file_info["extension"], route_file_counts.get(path, 0))
        for role in roles:
            role_counts[role] += 1
            role_examples[role].append(path)

    return {role: sorted(paths) for role, paths in role_examples.items()}, role_counts


def _roles_for_path(path: str, extension: str, route_hits: int) -> set[str]:
    roles: set[str] = set()
    normalized = path.replace("\\", "/").lower()
    parts = normalized.split("/")
    basename = os.path.basename(normalized)

    if basename in {"main.py", "app.py", "server.py", "main.tsx", "main.jsx", "server.ts", "server.js"}:
        roles.add("entry")
    if basename in {"main.tsx", "main.jsx"}:
        roles.add("frontend_entry")

    if route_hits or any(part in {"routers", "router", "controllers", "controller", "routes"} for part in parts):
        roles.add("controller")
    if any(part in {"services", "service", "usecases", "usecase"} for part in parts):
        roles.add("service")
    if any(part in {"repositories", "repository", "repos", "repo", "dao", "daos", "stores", "store"} for part in parts):
        roles.add("repository")
    if any(part in {"middleware", "middlewares", "guards", "guard", "interceptors", "interceptor"} for part in parts):
        roles.add("middleware")
    if any(part in {"config", "configs", "infra", "infrastructure"} for part in parts):
        roles.add("config_infra")
    if any(part in {"models", "model", "schemas", "schema", "entities", "entity", "dto", "dtos"} for part in parts):
        roles.add("model_schema")
    if "db" in parts and basename in {"session.py", "schema.py", "engine.py", "connection.py"}:
        roles.add("config_infra")

    if extension in {".tsx", ".jsx", ".ts", ".js"}:
        if any(part in {"components", "component", "ui", "widgets", "layouts", "layout"} for part in parts) or basename in {"app.tsx", "app.jsx"}:
            roles.add("frontend_ui")
        if any(part in {"pages", "page", "views", "view", "screens", "screen"} for part in parts):
            roles.add("frontend_page")
        if any(part in {"shared", "common", "hooks", "utils", "types", "store", "state", "api", "lib"} for part in parts):
            roles.add("shared")

    return roles


def _build_key_files(
    dir_path: str,
    markers: list[str],
    entry_file: Optional[str],
    role_examples: dict[str, list[str]],
    route_files: list[str],
    best_target: dict,
) -> list[str]:
    key_files: list[str] = []
    best_target_path = str(best_target.get("file_path") or "")
    if best_target_path:
        key_files.append(best_target_path)
    for marker in markers:
        key_files.append(_join_path(dir_path, marker))
    if entry_file:
        key_files.append(entry_file)
    for role in _ROLE_ORDER:
        paths = role_examples.get(role) or []
        if paths:
            key_files.append(paths[0])
    key_files.extend(route_files[:2])
    return _stable_unique([path for path in key_files if path])[:8]


def _best_target_for_component(
    dir_path: str,
    component_type: str,
    entry_file: Optional[str],
    role_examples: dict[str, list[str]],
    route_files: list[str],
    markers: list[str],
) -> dict:
    if route_files and component_type in {"backend", "service", "worker", "fullstack"}:
        return {
            "file_path": route_files[0],
            "anchor_kind": "route_file",
            "target_rank": 88,
            "selection_reason": "component owns route files, so the strongest anchor is a routed source file",
        }
    if entry_file:
        return {
            "file_path": entry_file,
            "anchor_kind": "entry_file",
            "target_rank": 82,
            "selection_reason": "component entry file is the strongest direct representative anchor",
        }
    for role in _ROLE_ORDER:
        paths = role_examples.get(role) or []
        if paths:
            return {
                "file_path": paths[0],
                "anchor_kind": f"role_example:{role}",
                "target_rank": 70,
                "selection_reason": f"component is best anchored by a representative {role} file",
            }
    if markers:
        return {
            "file_path": _join_path(dir_path, markers[0]),
            "anchor_kind": "runtime_marker",
            "target_rank": 58,
            "selection_reason": "component falls back to a direct runtime marker file",
        }
    return {
        "file_path": dir_path,
        "anchor_kind": "component_root",
        "target_rank": 30,
        "selection_reason": "component falls back to its detected root path",
    }


def _component_name_for(dir_path: str, component_type: str) -> str:
    if dir_path == ".":
        return component_type if component_type != "unknown" else "root"
    basename = os.path.basename(dir_path)
    if basename in {"app", "src"} and component_type in {"backend", "frontend"}:
        return component_type
    return basename or component_type or "component"


def _find_entry_file(source_files: list[dict], languages: list[str]) -> Optional[str]:
    all_entry_names: set[str] = set()
    for language in languages:
        all_entry_names |= ENTRY_FILES.get(language, set())
    all_entry_names |= {
        "main.py", "app.py", "server.py", "manage.py",
        "index.ts", "index.js", "App.tsx", "server.ts", "server.js",
        "Program.cs", "Startup.cs", "main.go", "main.rs",
        "Main.java", "Application.java", "app.rb", "index.php",
        "main.tsx", "main.jsx", "app.ts", "app.js",
    }

    by_name: dict[str, list[str]] = defaultdict(list)
    for file_info in source_files:
        by_name[os.path.basename(file_info["path"])].append(file_info["path"])
    for paths in by_name.values():
        paths.sort(key=lambda path: path.count("/"))

    priority = [
        "main.py", "app.py", "server.py", "wsgi.py", "asgi.py",
        "Program.cs", "Startup.cs", "main.go", "main.rs",
        "Main.java", "Application.java", "server.ts", "server.js",
        "app.ts", "app.js", "main.tsx", "main.jsx", "index.tsx",
        "index.jsx", "index.ts", "index.js", "app.rb", "index.php",
    ]
    for name in priority:
        if name in by_name:
            return by_name[name][0]
    for name in sorted(all_entry_names):
        if name in by_name:
            return by_name[name][0]
    return None


def _scoped_languages(source_files: list[dict]) -> list[str]:
    counts: Counter = Counter()
    extension_to_language = {
        ".py": "Python",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".java": "Java",
        ".cs": "C#",
        ".go": "Go",
        ".rs": "Rust",
        ".rb": "Ruby",
        ".php": "PHP",
        ".swift": "Swift",
        ".kt": "Kotlin",
        ".cpp": "C++",
        ".cc": "C++",
        ".cxx": "C++",
        ".c": "C",
    }
    for file_info in source_files:
        language = extension_to_language.get(file_info["extension"])
        if language:
            counts[language] += 1
    return sorted(counts)


def _collect_import_tokens(files: list[dict], root: str) -> dict[str, set[str]]:
    imports: dict[str, set[str]] = {}
    for file_info in files:
        if file_info["extension"] not in SOURCE_EXTENSIONS:
            continue
        content = _safe_read(os.path.join(root, file_info["path"]))
        if not content:
            continue
        tokens: set[str] = set()
        if file_info["extension"] == ".py":
            for left, right in _PY_IMPORT_RE.findall(content):
                token = left or right
                if token:
                    tokens.add(token)
        elif file_info["extension"] in {".js", ".jsx", ".ts", ".tsx"}:
            for left, right in _JS_IMPORT_RE.findall(content):
                token = left or right
                if token:
                    tokens.add(token)
        imports[file_info["path"]] = tokens
    return imports


def _count_internal_imports(dir_path: str, source_files: list[dict], import_tokens: dict[str, set[str]]) -> int:
    candidate_name = os.path.basename(dir_path) if dir_path != "." else ""
    wrapper_child_name = ""
    if dir_path == ".":
        dominant_child = _dominant_child(dir_path, source_files)
        wrapper_child_name = os.path.basename(dominant_child) if dominant_child else ""
    count = 0
    for file_info in source_files:
        for token in import_tokens.get(file_info["path"], set()):
            if token.startswith((".", "./", "../")):
                count += 1
                break
            if candidate_name and token.startswith(candidate_name + "."):
                count += 1
                break
            if wrapper_child_name and token.startswith(wrapper_child_name + "."):
                count += 1
                break
    return count


def _route_prefixes_by_file(routes: list[dict]) -> dict[str, list[str]]:
    prefixes: dict[str, list[str]] = defaultdict(list)
    for route in routes:
        if not isinstance(route, dict):
            continue
        file_path = route.get("file")
        path = route.get("path")
        if not file_path or not path:
            continue
        parts = [segment for segment in str(path).split("/") if segment]
        if parts:
            prefixes[file_path].append("/" + parts[0])
    return {file_path: _stable_unique(values) for file_path, values in prefixes.items()}


def _dominant_child(dir_path: str, source_files: list[dict]) -> Optional[str]:
    counts: Counter = Counter()
    for file_info in source_files:
        relative = _relative_path(dir_path, file_info["path"])
        if "/" not in relative:
            continue
        child = relative.split("/", 1)[0]
        counts[child] += 1
    if not counts:
        return None
    child, count = counts.most_common(1)[0]
    if child not in _WRAPPER_CHILD_NAMES:
        return None
    if count / max(1, len(source_files)) < 0.65:
        return None
    return _join_path(dir_path, child)


def _is_under(root_path: str, file_path: str) -> bool:
    if root_path == ".":
        return True
    return file_path == root_path or file_path.startswith(root_path + "/")


def _is_direct_child(root_path: str, file_path: str) -> bool:
    relative = _relative_path(root_path, file_path)
    return "/" not in relative


def _relative_path(root_path: str, file_path: str) -> str:
    if root_path == ".":
        return file_path
    prefix = root_path + "/"
    return file_path[len(prefix):] if file_path.startswith(prefix) else file_path


def _overlaps(left: str, right: str) -> bool:
    if left == "." or right == ".":
        return True
    return left.startswith(right + "/") or right.startswith(left + "/")


def _join_path(root_path: str, child: str) -> str:
    if root_path == ".":
        return child
    return f"{root_path}/{child}"


def _safe_read(file_path: str, max_size: int = 1024 * 1024) -> Optional[str]:
    try:
        if os.path.getsize(file_path) > max_size:
            return None
        with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _stable_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
