"""Component Deep Dive — targeted internal analysis for one component.

Given a component (identified by its ``root_path`` from the scan), this
module reads the actual file contents, parses imports, detects internal
relationships, and produces a structured component-level understanding.
"""

from __future__ import annotations

import os
import re
from typing import Optional

# ── Constants ────────────────────────────────────────────────────────
_MAX_FILE_READ_BYTES = 64 * 1024  # 64 KB cap per file to stay safe
_MAX_FILES_TO_READ = 120          # cap on files we'll actually open

# Files unlikely to contain meaningful logic
_SKIP_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff", ".woff2",
    ".ttf", ".eot", ".mp3", ".mp4", ".zip", ".tar", ".gz", ".lock",
    ".map", ".min.js", ".min.css", ".pyc", ".pyo", ".class",
}

_SKIP_FILENAMES: set[str] = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    ".DS_Store", "Thumbs.db",
}

# Patterns to ignore for internal dependency detection
_IGNORE_DIR_PARTS: set[str] = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", "coverage",
}

# Directories that contain runtime artifacts, not real source.
# Paths whose *local* part starts with one of these are excluded.
_ARTIFACT_DIRS: set[str] = {"workspaces", "uploads"}

# ── Import parsing regexes ───────────────────────────────────────────

# Python: from foo.bar import baz  |  import foo.bar
_PY_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE
)

# JS/TS: import ... from "./foo"  |  require("./foo")
_JS_IMPORT_RE = re.compile(
    r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]"""
    r"""|require\(\s*['"]([^'"]+)['"]\s*\))""",
    re.MULTILINE,
)

# ── Entry-point scoring (mirrors scanner.py but component-local) ─────
_ENTRY_SCORES: dict[str, int] = {
    "main.py": 100, "app.py": 95, "server.py": 90, "manage.py": 85,
    "__main__.py": 85, "Program.cs": 100,
    "server.js": 90, "server.ts": 90, "app.js": 85, "app.ts": 85,
    "main.tsx": 80, "main.jsx": 80, "main.ts": 75, "main.js": 75,
    "index.tsx": 60, "index.jsx": 60, "index.ts": 40, "index.js": 40,
}

# ── Flow-step templates (ordered by architectural layer) ─────────────
_FLOW_LAYER_ORDER: list[str] = [
    "entry / startup",
    "configuration / settings",
    "routing / URL dispatch",
    "middleware / hooks",
    "controllers / views / pages",
    "service / business logic",
    "data access / ORM / database",
    "utilities / helpers",
    "output / response / rendering",
]


# ── Helpers ──────────────────────────────────────────────────────────

def _safe_read(filepath: str) -> Optional[str]:
    """Read a file as text with size cap, returning None on failure."""
    try:
        size = os.path.getsize(filepath)
        if size > _MAX_FILE_READ_BYTES:
            return None
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _is_code_file(rel_path: str) -> bool:
    """Return True if the file looks like a source file worth reading."""
    _, ext = os.path.splitext(rel_path)
    basename = os.path.basename(rel_path)
    if ext.lower() in _SKIP_EXTENSIONS:
        return False
    if basename in _SKIP_FILENAMES:
        return False
    parts = rel_path.replace("\\", "/").split("/")
    if any(p in _IGNORE_DIR_PARTS for p in parts):
        return False
    return True


def _classify_file_role(rel_path: str, content: Optional[str]) -> str:
    """Assign a rough 'role' to a file based on name + content signals."""
    basename = os.path.basename(rel_path).lower()
    parent = os.path.basename(os.path.dirname(rel_path)).lower()

    # Config / settings
    if basename in (
        "settings.py", "config.py", "config.ts", "config.js",
        ".env", ".env.example", "tsconfig.json", "pyproject.toml",
        "package.json", "requirements.txt", "vite.config.ts",
        "vite.config.js", "next.config.js", "next.config.mjs",
        "angular.json", "docker-compose.yml", "dockerfile",
    ):
        return "configuration"

    # Entry / startup
    if basename in (
        "main.py", "app.py", "manage.py", "__main__.py",
        "main.ts", "main.tsx", "main.js", "main.jsx",
        "server.js", "server.ts", "server.py", "program.cs",
    ):
        return "entry"

    # Routing
    if "route" in basename or "router" in basename or "urls" in basename:
        return "routing"
    if parent in ("routes", "routers", "urls"):
        return "routing"

    # Middleware / hooks / plugins
    if "middleware" in basename or "hook" in basename or "plugin" in basename:
        return "middleware"
    if parent in ("middleware", "middlewares", "hooks", "plugins"):
        return "middleware"

    # Controllers / views / pages
    if "controller" in basename or "view" in basename or "page" in basename:
        return "controller"
    if parent in ("controllers", "views", "pages", "screens", "components"):
        return "controller"

    # Service / business logic
    if "service" in basename or "handler" in basename or "usecase" in basename:
        return "service"
    if parent in ("services", "handlers", "usecases", "domain", "core"):
        return "service"

    # Data / models / ORM
    if "model" in basename or "schema" in basename or "entity" in basename:
        return "data"
    if parent in ("models", "schemas", "entities", "db", "database", "orm", "migrations"):
        return "data"

    # Tests
    if "test" in basename or "spec" in basename:
        return "test"
    if parent in ("tests", "test", "__tests__", "specs"):
        return "test"

    # Utils / helpers
    if "util" in basename or "helper" in basename or "lib" in basename:
        return "utility"
    if parent in ("utils", "utilities", "helpers", "lib", "common", "shared"):
        return "utility"

    # Assets / styles
    _, ext = os.path.splitext(basename)
    if ext in (".css", ".scss", ".less", ".sass"):
        return "style"
    if ext in (".html", ".hbs", ".ejs", ".pug"):
        return "template"

    return "other"


def _parse_python_imports(content: str, comp_root: str) -> list[str]:
    """Extract Python import targets that look project-internal."""
    results: list[str] = []
    for match in _PY_IMPORT_RE.finditer(content):
        module = match.group(1) or match.group(2)
        if not module:
            continue
        # Skip stdlib / third-party (no dots for relative, or starts
        # with known top-level packages).  Heuristic: project-internal
        # modules usually have short dotted names referencing siblings.
        top = module.split(".")[0]
        # Relative imports (from . import ...) don't match our regex,
        # but explicit ones like `from app.services import ...` do.
        # We keep anything whose top-level name appears as a folder/file
        # inside the component — caller checks.
        results.append(module)
    return results


def _parse_js_imports(content: str) -> list[str]:
    """Extract JS/TS import targets that look project-internal (relative)."""
    results: list[str] = []
    for match in _JS_IMPORT_RE.finditer(content):
        target = match.group(1) or match.group(2)
        if not target:
            continue
        # Only relative imports (./  ../)  are internal
        if target.startswith("."):
            results.append(target)
    return results


def _resolve_relative_import(
    source_rel: str, target: str, comp_files_set: set[str],
) -> Optional[str]:
    """Resolve a relative JS/TS import to a file path within the component.

    Tries common extension resolutions (.ts, .tsx, .js, .jsx, /index.ts …).
    """
    source_dir = os.path.dirname(source_rel)
    raw = os.path.normpath(os.path.join(source_dir, target)).replace("\\", "/")
    # Try exact match first
    if raw in comp_files_set:
        return raw
    # Try with extensions
    for ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
        candidate = raw + ext
        if candidate in comp_files_set:
            return candidate
    # Try index files
    for ext in (".ts", ".tsx", ".js", ".jsx"):
        candidate = os.path.join(raw, "index" + ext).replace("\\", "/")
        if candidate in comp_files_set:
            return candidate
    return None


def _resolve_python_import(
    module: str,
    comp_top_dirs: set[str],
    comp_files_set: set[str],
    comp_root: str,
) -> Optional[str]:
    """Resolve a Python import to a file path within the component.

    Turns ``app.services.scanner`` → ``app/services/scanner.py`` if that
    file belongs to this component.
    """
    # Convert dotted path to filesystem path
    as_path = module.replace(".", "/")

    # Check if the import's top-level name matches a known dir in the component
    top_name = module.split(".")[0]
    if top_name not in comp_top_dirs:
        return None

    # Try as file (.py)
    candidate = as_path + ".py"
    if candidate in comp_files_set:
        return candidate
    # Try as package (__init__.py)
    candidate = os.path.join(as_path, "__init__.py").replace("\\", "/")
    if candidate in comp_files_set:
        return candidate
    return None


# ── Public API ───────────────────────────────────────────────────────

def run_deep_dive(
    component: dict,
    all_files: list[dict],
    workspace_root: str,
) -> dict:
    """Run a deep-dive analysis for one component.

    Parameters
    ----------
    component : dict
        A component dict from ``Scan.components`` with keys
        ``root_path``, ``name``, ``type``, ``markers``, ``entry_points``.
    all_files : list[dict]
        The full file inventory from the scan (``Scan.files``).
    workspace_root : str
        Absolute path to the extracted project root (the ``effective_root``
        used during scanning).

    Returns
    -------
    dict with keys: component_name, component_type, component_summary,
         internal_modules, important_files, internal_edges,
         probable_start_file, probable_flow_steps, notes.
    """
    comp_root = component["root_path"]  # e.g. "backend" or "."
    comp_prefix = (comp_root + "/") if comp_root != "." else ""

    # ── 1. Collect files belonging to this component ─────────────
    # Filter out workspace/upload artifacts (runtime dirs inside component)
    comp_files: list[dict] = []
    for f in all_files:
        path = f["path"]
        if comp_prefix:
            if not path.startswith(comp_prefix):
                continue
            local = path[len(comp_prefix):]
        else:
            local = path
        # Drop artifact directories
        first_part = local.split("/")[0] if "/" in local else ""
        if first_part in _ARTIFACT_DIRS:
            continue
        comp_files.append(f)

    comp_files_set: set[str] = {f["path"] for f in comp_files}

    # Also build a set of local (prefix-stripped) paths for import resolution
    comp_local_set: set[str] = set()
    for f in comp_files:
        local = f["path"]
        if comp_prefix and local.startswith(comp_prefix):
            local = local[len(comp_prefix):]
        comp_local_set.add(local)

    # ── 2. Read code files (up to cap) ──────────────────────────
    code_files = [f for f in comp_files if _is_code_file(f["path"])]
    # Sort smaller files first so we read more files within budget
    code_files.sort(key=lambda f: f["size_bytes"])
    code_files = code_files[:_MAX_FILES_TO_READ]

    file_contents: dict[str, str] = {}
    for f in code_files:
        abs_path = os.path.join(workspace_root, f["path"])
        content = _safe_read(abs_path)
        if content is not None:
            file_contents[f["path"]] = content

    # ── 3. Classify roles and build internal modules ────────────
    # Relative path within the component (strip comp_prefix)
    def _local(path: str) -> str:
        if comp_prefix and path.startswith(comp_prefix):
            return path[len(comp_prefix):]
        return path

    file_roles: dict[str, str] = {}
    for path in comp_files_set:
        content = file_contents.get(path)
        file_roles[path] = _classify_file_role(path, content)

    # Group files by directory to form "modules".
    # First pass: bucket by first directory level.
    _DEPTH1_SPLIT_THRESHOLD = 8  # split into sub-modules if a bucket is big
    raw_buckets: dict[str, list[str]] = {}
    for f in comp_files:
        local = _local(f["path"])
        parts = local.replace("\\", "/").split("/")
        if len(parts) == 1:
            bucket = "(root)"
        else:
            bucket = parts[0]
        raw_buckets.setdefault(bucket, []).append(f["path"])

    # Second pass: split large first-level buckets into sub-modules
    # using the second directory level if present.
    module_buckets: dict[str, list[str]] = {}
    for bucket, paths in raw_buckets.items():
        if bucket == "(root)" or len(paths) <= _DEPTH1_SPLIT_THRESHOLD:
            module_buckets[bucket] = paths
            continue
        # Check if there are subdirectories
        has_sub = any(
            len(_local(p).replace("\\", "/").split("/")) > 2 for p in paths
        )
        if not has_sub:
            module_buckets[bucket] = paths
            continue
        # Split by second-level directory
        for p in paths:
            local = _local(p)
            parts = local.replace("\\", "/").split("/")
            if len(parts) <= 2:
                sub_bucket = bucket  # files at module root stay in parent
            else:
                sub_bucket = parts[0] + "/" + parts[1]
            module_buckets.setdefault(sub_bucket, []).append(p)

    # Roles considered substantive for the "mixed" heuristic
    _TRIVIAL_ROLES: set[str] = {"other", "style", "template"}

    internal_modules: list[dict] = []
    for mod_name, paths in sorted(module_buckets.items()):
        roles_in_mod = {file_roles.get(p, "other") for p in paths}
        # Pick the dominant role
        role_counts: dict[str, int] = {}
        for p in paths:
            r = file_roles.get(p, "other")
            role_counts[r] = role_counts.get(r, 0) + 1
        dominant = max(role_counts, key=lambda k: role_counts[k])

        # If no clear majority, label as "core / mixed"
        total = sum(role_counts.values())
        dominant_pct = role_counts[dominant] / total if total else 1.0
        substantive = {r for r in roles_in_mod if r not in _TRIVIAL_ROLES}
        if dominant_pct < 0.5 and len(substantive) >= 3:
            dominant = "core / mixed"

        internal_modules.append({
            "name": mod_name,
            "file_count": len(paths),
            "dominant_role": dominant,
            "roles": sorted(roles_in_mod),
            "files": sorted(_local(p) for p in paths),
        })

    # ── 4. Identify important files ─────────────────────────────
    importance_scores: dict[str, int] = {}
    for path in comp_files_set:
        score = 0
        role = file_roles.get(path, "other")
        basename = os.path.basename(path).lower()

        # Role-based scoring
        if role == "entry":
            score += 50
        elif role == "routing":
            score += 40
        elif role == "configuration":
            score += 35
        elif role == "service":
            score += 30
        elif role == "data":
            score += 25
        elif role == "controller":
            score += 25
        elif role == "middleware":
            score += 20

        # Entry-point scoring
        if basename in (n.lower() for n in _ENTRY_SCORES):
            score += 30

        # Size signal — very small files are less significant
        fdict = next((f for f in comp_files if f["path"] == path), None)
        if fdict and fdict["size_bytes"] < 50:
            score -= 10

        # Marker files (package.json, requirements.txt, etc.)
        if basename in (
            "package.json", "requirements.txt", "pyproject.toml",
            "dockerfile", "docker-compose.yml",
        ):
            score += 20

        importance_scores[path] = score

    # Top important files (by score, then alphabetical for ties)
    sorted_by_importance = sorted(
        importance_scores.items(),
        key=lambda x: (-x[1], x[0]),
    )
    important_files: list[dict] = []
    for path, score in sorted_by_importance[:15]:
        if score <= 0:
            break
        important_files.append({
            "path": _local(path),
            "role": file_roles.get(path, "other"),
            "score": score,
        })

    # ── 5. Parse imports and build internal edges ───────────────
    # Determine language family from file extensions
    py_exts = {".py"}
    js_exts = {".js", ".jsx", ".ts", ".tsx", ".mjs"}

    # Compute top-level dir names inside component for Python resolution
    comp_top_dirs: set[str] = set()
    for f in comp_files:
        local = _local(f["path"])
        parts = local.replace("\\", "/").split("/")
        if len(parts) > 1:
            comp_top_dirs.add(parts[0])

    internal_edges: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()

    for path, content in file_contents.items():
        _, ext = os.path.splitext(path)
        ext = ext.lower()

        if ext in py_exts:
            raw_imports = _parse_python_imports(content, comp_root)
            for mod in raw_imports:
                resolved = _resolve_python_import(
                    mod, comp_top_dirs, comp_local_set, comp_root
                )
                if resolved and resolved != path:
                    edge_key = (_local(path), _local(resolved))
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        internal_edges.append({
                            "source": _local(path),
                            "target": _local(resolved),
                            "type": "imports",
                        })

        elif ext in js_exts:
            raw_imports = _parse_js_imports(content)
            for target in raw_imports:
                resolved = _resolve_relative_import(
                    _local(path), target, comp_local_set
                )
                if resolved and resolved != path:
                    edge_key = (_local(path), _local(resolved))
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        internal_edges.append({
                            "source": _local(path),
                            "target": _local(resolved),
                            "type": "imports",
                        })

    # — Build helper: file → module name
    file_to_module: dict[str, str] = {}
    for mod in internal_modules:
        for fpath in mod["files"]:
            file_to_module[fpath] = mod["name"]

    important_set: set[str] = {f["path"] for f in important_files}

    # — Score and rank edges
    for edge in internal_edges:
        w = 1
        src_mod = file_to_module.get(edge["source"], "")
        tgt_mod = file_to_module.get(edge["target"], "")
        if src_mod and tgt_mod and src_mod != tgt_mod:
            w += 3  # cross-module edges are more architecturally significant
        if edge["source"] in important_set or edge["target"] in important_set:
            w += 2  # involves an important file
        src_role = file_roles.get(
            (comp_prefix + edge["source"]) if comp_prefix else edge["source"], "other"
        )
        tgt_role = file_roles.get(
            (comp_prefix + edge["target"]) if comp_prefix else edge["target"], "other"
        )
        if src_role != tgt_role:
            w += 1  # cross-role is more interesting
        edge["weight"] = w

    internal_edges.sort(key=lambda e: -e["weight"])

    # — Aggregate module-level edges
    mod_edge_counts: dict[tuple[str, str], int] = {}
    for edge in internal_edges:
        src_mod = file_to_module.get(edge["source"], "(root)")
        tgt_mod = file_to_module.get(edge["target"], "(root)")
        if src_mod != tgt_mod:
            key = (src_mod, tgt_mod)
            mod_edge_counts[key] = mod_edge_counts.get(key, 0) + 1

    module_edges: list[dict] = [
        {"source_module": s, "target_module": t, "edge_count": c}
        for (s, t), c in sorted(
            mod_edge_counts.items(), key=lambda x: -x[1]
        )
    ]

    # ── 6. Determine probable start file ────────────────────────
    probable_start_file: Optional[str] = None

    # First check existing entry_points from the scan
    comp_entry_points = component.get("entry_points", [])
    if comp_entry_points:
        probable_start_file = _local(comp_entry_points[0])
    else:
        # Score files locally
        best_score = 0
        for path in comp_files_set:
            basename = os.path.basename(path)
            sc = _ENTRY_SCORES.get(basename, 0)
            if sc > best_score:
                best_score = sc
                probable_start_file = _local(path)

    # ── 7. Build probable flow steps ────────────────────────────
    # Map roles to flow layer names
    _ROLE_TO_LAYER: dict[str, str] = {
        "entry": "entry / startup",
        "configuration": "configuration / settings",
        "routing": "routing / URL dispatch",
        "middleware": "middleware / hooks",
        "controller": "controllers / views / pages",
        "service": "service / business logic",
        "data": "data access / ORM / database",
        "utility": "utilities / helpers",
        "template": "output / response / rendering",
        "style": "output / response / rendering",
    }

    # Which layers are actually present?
    present_layers: dict[str, list[str]] = {}
    for path, role in file_roles.items():
        layer = _ROLE_TO_LAYER.get(role)
        if layer:
            present_layers.setdefault(layer, []).append(_local(path))

    probable_flow_steps: list[dict] = []
    for layer_name in _FLOW_LAYER_ORDER:
        if layer_name in present_layers:
            example_files = sorted(present_layers[layer_name])[:3]
            probable_flow_steps.append({
                "step": layer_name,
                "example_files": example_files,
            })

    # ── 8. Build component summary ──────────────────────────────
    langs: set[str] = set()
    ext_to_lang = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".tsx": "TypeScript (JSX)", ".jsx": "JavaScript (JSX)",
        ".cs": "C#", ".go": "Go", ".rs": "Rust", ".java": "Java",
    }
    for f in comp_files:
        lang = ext_to_lang.get(f["extension"])
        if lang:
            langs.add(lang)

    component_summary = (
        f"{component['name']} ({component['type']}) — "
        f"{len(comp_files)} files, "
        f"{len(internal_modules)} modules, "
        f"languages: {', '.join(sorted(langs)) or 'N/A'}"
    )

    # ── 9. Notes / caveats ──────────────────────────────────────
    notes: list[str] = []
    if len(comp_files) > _MAX_FILES_TO_READ:
        notes.append(
            f"Component has {len(comp_files)} files; only the smallest "
            f"{_MAX_FILES_TO_READ} were read for import analysis."
        )
    unread = len(comp_files_set) - len(file_contents)
    if unread > 0:
        notes.append(
            f"{unread} files were skipped (binary, too large, or unreadable)."
        )
    if not internal_edges:
        notes.append(
            "No internal import edges detected. The component may use "
            "dynamic imports, config-based wiring, or a language not yet supported."
        )
    notes.append(
        "Flow steps are heuristic. Actual execution order may differ."
    )

    return {
        "component_name": component["name"],
        "component_type": component["type"],
        "component_summary": component_summary,
        "internal_modules": internal_modules,
        "important_files": important_files,
        "internal_edges": internal_edges,
        "module_edges": module_edges,
        "probable_start_file": probable_start_file,
        "probable_flow_steps": probable_flow_steps,
        "notes": notes,
    }
