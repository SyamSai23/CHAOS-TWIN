import os
import zipfile
from typing import Optional

# Folders/files to ignore from scan inventory and summaries.
IGNORED_PATH_PARTS: set[str] = {
    "node_modules",
    ".git",
    ".next",
    "dist",
    "build",
    "coverage",
    "vendor",
    "target",
    "bin",
    "obj",
    "__pycache__",
    ".venv",
    "venv",
    "__MACOSX",
    ".DS_Store",
}


def _is_ignored_path(path: str) -> bool:
    """Return True if a path contains ignored folders/files."""
    parts = path.replace("\\", "/").split("/")
    return any(part in IGNORED_PATH_PARTS for part in parts)


# Maps file extensions to language names
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (JSX)",
    ".jsx": "JavaScript (JSX)",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".html": "HTML",
    ".css": "CSS",
    ".json": "JSON",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".md": "Markdown",
    ".sql": "SQL",
    ".sh": "Shell",
    ".toml": "TOML",
}

# Maps marker filenames to framework/tool names
FRAMEWORK_MARKERS: dict[str, str] = {
    "package.json": "Node.js",
    "tsconfig.json": "TypeScript",
    "requirements.txt": "Python (pip)",
    "pyproject.toml": "Python (modern)",
    "Pipfile": "Python (pipenv)",
    "go.mod": "Go modules",
    "Cargo.toml": "Rust (Cargo)",
    "pom.xml": "Java (Maven)",
    "build.gradle": "Java (Gradle)",
    "Gemfile": "Ruby (Bundler)",
    "composer.json": "PHP (Composer)",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
    "docker-compose.yaml": "Docker Compose",
    ".env": "Environment config",
    "Makefile": "Make",
    "vite.config.ts": "Vite",
    "vite.config.js": "Vite",
    "next.config.js": "Next.js",
    "next.config.mjs": "Next.js",
    "angular.json": "Angular",
    "manage.py": "Django",
    "settings.py": "Django",
}

# Files that are useful for understanding build/runtime/dependencies quickly.
KEY_FILE_NAMES: set[str] = {
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
    "requirements.txt",
    "pyproject.toml",
    "Pipfile",
    "poetry.lock",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "composer.json",
    "Gemfile",
    "tsconfig.json",
    "vite.config.ts",
    "vite.config.js",
    "next.config.js",
    "next.config.mjs",
    "angular.json",
    ".env",
}

# ── Entry-point scoring ──
# Maps filename → base score.  Higher = stronger startup signal.
ENTRY_POINT_SCORES: dict[str, int] = {
    # Strong backend startup files
    "main.py": 100,
    "app.py": 95,
    "server.py": 90,
    "manage.py": 85,
    "__main__.py": 85,
    "Program.cs": 100,
    # Node.js / TS server-side entry points
    "server.js": 90,
    "server.ts": 90,
    "app.js": 85,
    "app.ts": 85,
    # SPA / frontend entry points (extra bonus applied when inside src/)
    "main.tsx": 80,
    "main.jsx": 80,
    "main.ts": 75,
    "main.js": 75,
    "index.tsx": 60,
    "index.jsx": 60,
    "index.ts": 40,
    "index.js": 40,
}

MAX_ENTRY_POINTS_PER_COMPONENT = 2

# ── Component-root markers ──
# Files whose presence in a directory indicates a "component root".
COMPONENT_MARKER_FILES: set[str] = {
    # Frontend
    "package.json",
    "vite.config.ts", "vite.config.js",
    "next.config.js", "next.config.mjs",
    "angular.json", "nuxt.config.js", "nuxt.config.ts",
    # Backend
    "requirements.txt", "pyproject.toml", "Pipfile",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
    "Gemfile", "composer.json", "manage.py",
    # General
    "Dockerfile", "Program.cs",
}

FRONTEND_ROOT_MARKERS: set[str] = {
    "vite.config.ts", "vite.config.js",
    "next.config.js", "next.config.mjs",
    "angular.json", "nuxt.config.js", "nuxt.config.ts",
}

BACKEND_ROOT_MARKERS: set[str] = {
    "requirements.txt", "pyproject.toml", "Pipfile",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
    "Gemfile", "composer.json", "manage.py", "Program.cs",
}

_FRONTEND_DIR_NAMES: set[str] = {"frontend", "client", "web", "ui"}
_BACKEND_DIR_NAMES: set[str] = {"backend", "server", "api"}
_SERVICE_DIR_NAMES: set[str] = {"scheduler", "worker", "cron", "jobs"}


def extract_zip(zip_path: str, dest_dir: str) -> str:
    """Extract a ZIP file safely into dest_dir. Returns the extraction path."""
    os.makedirs(dest_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            member_name = member.filename
            normalized_name = member_name.replace("\\", "/").lstrip("/")

            if _is_ignored_path(normalized_name):
                continue

            # Prevent path traversal attacks
            member_path = os.path.realpath(os.path.join(dest_dir, normalized_name))
            if not member_path.startswith(os.path.realpath(dest_dir)):
                raise ValueError(f"Unsafe path in ZIP: {member_name}")

            # Extract only non-ignored members to keep workspace clean.
            zf.extract(member, dest_dir)

    return dest_dir


def collect_file_inventory(root_dir: str) -> list[dict]:
    """Walk the directory tree and return a list of file info dicts."""
    inventory: list[dict] = []

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Prune ignored directories so os.walk won't descend into them.
        dirnames[:] = [d for d in dirnames if d not in IGNORED_PATH_PARTS]

        for filename in filenames:
            if filename in IGNORED_PATH_PARTS:
                continue
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root_dir)
            if _is_ignored_path(rel_path):
                continue
            _, ext = os.path.splitext(filename)
            size = os.path.getsize(full_path)

            inventory.append({
                "path": rel_path,
                "extension": ext,
                "size_bytes": size,
            })

    return inventory


def detect_languages(files: list[dict]) -> list[str]:
    """Detect languages from file extensions."""
    languages: set[str] = set()
    for f in files:
        ext = f["extension"]
        if ext in EXTENSION_TO_LANGUAGE:
            languages.add(EXTENSION_TO_LANGUAGE[ext])
    return sorted(languages)


def detect_frameworks(files: list[dict]) -> list[str]:
    """Detect frameworks/tools from well-known marker files."""
    frameworks: set[str] = set()
    for f in files:
        filename = os.path.basename(f["path"])
        if filename in FRAMEWORK_MARKERS:
            frameworks.add(FRAMEWORK_MARKERS[filename])
    return sorted(frameworks)


def collect_key_files(files: list[dict]) -> list[str]:
    """Return important config/build/dependency files found in the scan."""
    result: set[str] = set()
    for f in files:
        path = f["path"]
        filename = os.path.basename(path)
        if filename in KEY_FILE_NAMES:
            result.add(path)
    return sorted(result)


def collect_top_level_dirs(root_dir: str) -> list[str]:
    """Return root-level directories from the extracted project."""
    dirs: list[str] = []
    for name in os.listdir(root_dir):
        if name in IGNORED_PATH_PARTS:
            continue
        full_path = os.path.join(root_dir, name)
        if os.path.isdir(full_path):
            dirs.append(name)
    return sorted(dirs)


def unwrap_root_dir(root_dir: str) -> str:
    """If root contains only a single wrapper folder (no files), return the inner path.

    Many ZIPs extract with one outer folder like PROJECT-main/.
    This unwraps that so top_level_dirs and file paths are more meaningful.
    """
    try:
        entries = os.listdir(root_dir)
    except OSError:
        return root_dir
    visible = [
        e for e in entries
        if not e.startswith(".") and e not in IGNORED_PATH_PARTS
    ]
    dirs = [e for e in visible if os.path.isdir(os.path.join(root_dir, e))]
    files = [e for e in visible if os.path.isfile(os.path.join(root_dir, e))]
    if len(dirs) == 1 and len(files) == 0:
        return os.path.join(root_dir, dirs[0])
    return root_dir


def count_extensions(files: list[dict]) -> dict[str, int]:
    """Count how many files exist per extension (skip extensionless files)."""
    counts: dict[str, int] = {}
    for f in files:
        ext = f["extension"]
        if not ext:
            continue
        counts[ext] = counts.get(ext, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[0]))


def _score_entry_point(path: str) -> int:
    """Score an entry-point candidate.  Higher = stronger startup signal."""
    filename = os.path.basename(path)
    base_score = ENTRY_POINT_SCORES.get(filename, 0)
    if base_score == 0:
        return 0

    parts = path.replace("\\", "/").split("/")
    depth = len(parts)
    parent = parts[-2] if depth >= 2 else ""

    # Bonus: file lives directly inside src/
    if parent == "src":
        base_score += 15

    # Penalty: deep nesting beyond 4 levels reduces confidence
    if depth > 4:
        base_score -= (depth - 4) * 10

    # Heavy penalty: nested index.* NOT directly inside src/
    if filename in ("index.js", "index.ts", "index.tsx", "index.jsx") and parent != "src" and depth > 2:
        base_score -= 40

    return max(base_score, 0)


def _classify_component_root(dir_path: str, markers: list[str]) -> str:
    """Classify a component root by its markers and directory name."""
    dir_name = (os.path.basename(dir_path) or "").lower()
    marker_set = {m.lower() for m in markers}

    if marker_set & {m.lower() for m in FRONTEND_ROOT_MARKERS}:
        return "frontend"
    if marker_set & {m.lower() for m in BACKEND_ROOT_MARKERS}:
        return "backend"
    if dir_name in _FRONTEND_DIR_NAMES:
        return "frontend"
    if dir_name in _BACKEND_DIR_NAMES:
        return "backend"
    if dir_name in _SERVICE_DIR_NAMES:
        return "service"
    # package.json with no strong marker → likely frontend
    if "package.json" in marker_set:
        return "frontend"
    if "dockerfile" in marker_set:
        return "service"
    return "other"


def detect_component_roots(files: list[dict]) -> list[dict]:
    """Find directories that contain component-marker files.

    Returns a list of component dicts with keys:
        root_path, name, type, markers, entry_points (empty list).

    Nested roots are suppressed when an ancestor is already a root.
    When sub-directory roots exist the bare top-level root (\".\") is
    dropped because it is typically monorepo tooling.
    """
    # 1. Group marker files by parent directory
    dir_markers: dict[str, list[str]] = {}
    for f in files:
        filename = os.path.basename(f["path"])
        if filename in COMPONENT_MARKER_FILES:
            parent = os.path.dirname(f["path"]) or "."
            dir_markers.setdefault(parent, []).append(filename)

    # 2. Sort shallowest first
    sorted_dirs = sorted(dir_markers.keys(), key=lambda d: (d.count("/"), d))

    # 3. Accept roots, suppressing dirs nested under an already-accepted one
    accepted: list[str] = []
    for d in sorted_dirs:
        is_nested = any(
            d.startswith(existing + "/")
            for existing in accepted
            if existing != "."
        )
        if not is_nested:
            accepted.append(d)

    # 4. Drop bare root when deeper component roots exist
    non_root = [d for d in accepted if d != "."]
    if non_root and "." in accepted:
        accepted.remove(".")

    # 5. Build result
    results: list[dict] = []
    for d in accepted:
        markers = dir_markers[d]
        comp_type = _classify_component_root(d, markers)
        name = os.path.basename(d) if d != "." else "root"
        results.append({
            "root_path": d,
            "name": name,
            "type": comp_type,
            "markers": sorted(markers),
            "entry_points": [],
        })
    return results


def collect_entry_points(
    files: list[dict],
    component_roots: Optional[list[dict]] = None,
) -> list[str]:
    """Score entry-point candidates and keep the top 1\u20132 per component.

    When *component_roots* is provided each component\u2019s ``entry_points``
    list is populated **in-place** so downstream code can use it.
    """
    # Score every candidate
    scored: list[tuple[str, int]] = []
    for f in files:
        score = _score_entry_point(f["path"])
        if score > 0:
            scored.append((f["path"], score))
    scored.sort(key=lambda x: -x[1])

    if not component_roots:
        # Fallback: no component info, return the top entries
        return [path for path, _ in scored[: MAX_ENTRY_POINTS_PER_COMPONENT * 2]]

    # Build prefix list sorted longest-first for longest-prefix matching
    prefix_map: list[tuple[str, dict]] = []
    for comp in component_roots:
        root = comp["root_path"]
        prefix = (root + "/") if root != "." else ""
        prefix_map.append((prefix, comp))
    prefix_map.sort(key=lambda x: -len(x[0]))

    # Assign each candidate to the most specific (longest) matching root
    comp_buckets: dict[str, list[tuple[str, int]]] = {
        comp["root_path"]: [] for comp in component_roots
    }
    orphans: list[tuple[str, int]] = []

    for path, sc in scored:
        matched = False
        for prefix, comp in prefix_map:
            if path.startswith(prefix):
                comp_buckets[comp["root_path"]].append((path, sc))
                matched = True
                break
        if not matched:
            orphans.append((path, sc))

    # Keep top 1-2 per component
    result: list[str] = []
    for comp in component_roots:
        bucket = comp_buckets[comp["root_path"]]
        bucket.sort(key=lambda x: -x[1])
        for path, sc in bucket[: MAX_ENTRY_POINTS_PER_COMPONENT]:
            if sc >= 20:  # minimum quality threshold
                result.append(path)
                comp["entry_points"].append(path)

    # Include any high-scoring orphans not claimed by a component
    for path, sc in orphans:
        if sc >= 60:
            result.append(path)

    return sorted(result)


def detect_components(
    top_level_dirs: list[str],
    files: list[dict],
    key_files: list[str],
    entry_points: list[str],
) -> list[dict]:
    """Detect distinct project components from directory layout and file markers.

    Each component dict has at minimum {"name": str, "type": str}.
    Types: frontend, backend, service, data, infra, docs, scripts, config, other.
    """
    FRONTEND_DIR_NAMES = {"frontend", "client", "web", "ui"}
    BACKEND_DIR_NAMES = {"backend", "server", "api"}
    SERVICE_DIR_NAMES = {"scheduler", "worker", "cron", "jobs"}
    DATA_DIR_NAMES = {"data", "datasets", "backtest_data", "models", "ml"}
    INFRA_DIR_NAMES = {"infra", "infrastructure", "deploy", "terraform", "k8s", "helm"}
    DOCS_DIR_NAMES = {"docs", "documentation", "doc"}
    SCRIPTS_DIR_NAMES = {"scripts", "tools"}

    FRONTEND_FILE_MARKERS = {
        "vite.config.ts", "vite.config.js",
        "next.config.js", "next.config.mjs",
        "angular.json", "nuxt.config.js", "nuxt.config.ts",
    }
    BACKEND_FILE_MARKERS = {
        "requirements.txt", "pyproject.toml", "Pipfile",
        "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
        "Gemfile", "composer.json", "manage.py",
    }

    components: list[dict] = []

    for d in top_level_dirs:
        prefix = d + "/"
        dir_files = [f for f in files if f["path"].startswith(prefix)]
        if not dir_files:
            continue

        dir_basenames = {os.path.basename(f["path"]) for f in dir_files}
        dir_entry_pts = [ep for ep in entry_points if ep.startswith(prefix)]
        d_lower = d.lower()

        has_fe_markers = bool(dir_basenames & FRONTEND_FILE_MARKERS)
        has_fe_src = any(
            "/src/" in f["path"]
            and os.path.basename(f["path"]) in {
                "main.tsx", "main.jsx", "index.tsx", "index.jsx",
                "App.tsx", "App.jsx",
            }
            for f in dir_files
        )
        has_be_markers = bool(dir_basenames & BACKEND_FILE_MARKERS)
        has_pkg_json = "package.json" in dir_basenames
        node_server = bool(dir_basenames & {"server.js", "server.ts", "app.js", "app.ts"})

        # Classify by strongest signal first
        if has_fe_markers or has_fe_src:
            comp_type = "frontend"
        elif has_be_markers:
            comp_type = "backend"
        elif has_pkg_json and node_server:
            comp_type = "backend"
        elif has_pkg_json and d_lower in FRONTEND_DIR_NAMES:
            comp_type = "frontend"
        elif d_lower in FRONTEND_DIR_NAMES:
            comp_type = "frontend"
        elif d_lower in BACKEND_DIR_NAMES:
            comp_type = "backend"
        elif d_lower in SERVICE_DIR_NAMES or dir_entry_pts:
            comp_type = "service"
        elif d_lower in DATA_DIR_NAMES:
            comp_type = "data"
        elif d_lower in INFRA_DIR_NAMES:
            comp_type = "infra"
        elif d_lower in DOCS_DIR_NAMES:
            comp_type = "docs"
        elif d_lower in SCRIPTS_DIR_NAMES:
            comp_type = "scripts"
        elif d_lower.startswith("."):
            comp_type = "config"
        else:
            comp_type = "other"

        component: dict = {"name": d, "type": comp_type}
        if dir_entry_pts:
            component["entry_points"] = dir_entry_pts
        components.append(component)

    return components


def infer_project_type(
    files: list[dict],
    languages: list[str],
    frameworks: list[str],
    top_level_dirs: list[str],
    components: Optional[list[dict]] = None,
) -> str:
    """Infer project type using component analysis with file-level fallback."""

    # --- Phase 1: component-based classification ---
    if components:
        comp_types = {c["type"] for c in components}
        meaningful = [c for c in components if c["type"] in {"frontend", "backend", "service"}]

        has_fe = "frontend" in comp_types
        has_be = "backend" in comp_types
        has_svc = "service" in comp_types

        if len(meaningful) >= 3 or (has_fe and has_be and has_svc):
            return "monorepo / multi-component app"
        if has_fe and (has_be or has_svc):
            return "full-stack app"
        if has_be and has_svc:
            return "monorepo / multi-component app"
        if has_fe:
            return "frontend web app"
        if has_be:
            return "backend API"
        if has_svc:
            return "backend API"

    # --- Phase 2: file-level fallback (flat repos, no component dirs) ---
    file_paths = [f["path"] for f in files]
    file_names = [os.path.basename(path) for path in file_paths]

    has_frontend_signals = (
        "package.json" in file_names
        and (
            any(name in file_names for name in (
                "vite.config.ts", "vite.config.js",
                "next.config.js", "next.config.mjs", "angular.json",
            ))
            or any(
                path in ("src/main.tsx", "src/index.tsx", "src/main.jsx", "src/index.jsx")
                for path in file_paths
            )
        )
    )

    has_backend_signals = (
        "requirements.txt" in file_names
        or "pyproject.toml" in file_names
        or "manage.py" in file_names
        or "app.py" in file_names
        or "server.py" in file_names
        or "server.js" in file_names
        or "go.mod" in file_names
        or "pom.xml" in file_names
        or "build.gradle" in file_names
    )

    has_dotnet_signals = "Program.cs" in file_names or any(
        name.endswith(".csproj") for name in file_names
    )

    package_json_count = sum(1 for n in file_names if n == "package.json")
    has_monorepo_layout = (
        "apps" in top_level_dirs
        or "packages" in top_level_dirs
        or "services" in top_level_dirs
        or package_json_count >= 3
    )

    if has_monorepo_layout:
        return "monorepo / multi-component app"
    if has_frontend_signals and (has_backend_signals or has_dotnet_signals):
        return "full-stack app"
    if has_dotnet_signals:
        return ".NET backend"
    if has_backend_signals:
        return "backend API"
    if has_frontend_signals:
        return "frontend web app"

    ext_counts = count_extensions(files)
    if "Python" in languages or ".ipynb" in ext_counts:
        return "script/data project"

    return "unknown"
