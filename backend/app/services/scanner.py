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

# Entry points that are meaningful at any depth (true startup files)
DEEP_ENTRY_POINT_NAMES: set[str] = {
    "main.py", "app.py", "server.py", "manage.py", "Program.cs",
    "__main__.py",
}

# JS/TS entry points only meaningful at root level or inside src/
SHALLOW_ENTRY_POINT_NAMES: set[str] = {
    "index.js", "index.ts", "index.tsx", "index.jsx",
    "main.js", "main.ts", "main.tsx", "main.jsx",
    "server.js", "server.ts", "app.js", "app.ts",
}


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


def collect_entry_points(files: list[dict]) -> list[str]:
    """Find likely startup entry files across multiple components.

    DEEP entry points (main.py, app.py, etc.) are found up to 5 levels deep.
    SHALLOW entry points (index.js, main.tsx, etc.) are found if:
      - Their parent directory is 'src' (at any depth), OR
      - They are within 3 levels of root (covers component roots like backend/server.js)
    """
    result: set[str] = set()
    for f in files:
        path = f["path"]
        filename = os.path.basename(path)
        parts = path.replace("\\", "/").split("/")
        depth = len(parts)
        parent = parts[-2] if depth >= 2 else ""

        if filename in DEEP_ENTRY_POINT_NAMES:
            if depth <= 5:
                result.add(path)
        elif filename in SHALLOW_ENTRY_POINT_NAMES:
            if parent == "src" or depth <= 3:
                result.add(path)
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
