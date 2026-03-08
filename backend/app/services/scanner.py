import os
import zipfile

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
}

# JS/TS entry points only meaningful at root level or inside src/
SHALLOW_ENTRY_POINT_NAMES: set[str] = {
    "index.js", "index.ts", "index.tsx", "main.js", "main.ts", "main.tsx",
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
    """Find likely startup entry files. JS/TS index files only count at root or src/."""
    result: set[str] = set()
    for f in files:
        path = f["path"]
        filename = os.path.basename(path)
        # Depth: root-level has 1 part, src/ has 2 parts with parts[0]=="src"
        parts = path.replace("\\", "/").split("/")
        is_root_or_src = len(parts) == 1 or (len(parts) == 2 and parts[0] == "src")

        if filename in DEEP_ENTRY_POINT_NAMES:
            result.add(path)
        elif filename in SHALLOW_ENTRY_POINT_NAMES and is_root_or_src:
            result.add(path)
    return sorted(result)


def infer_project_type(
    files: list[dict],
    languages: list[str],
    frameworks: list[str],
    top_level_dirs: list[str],
) -> str:
    """Infer a simple project type label using file/layout heuristics."""
    file_paths = [f["path"] for f in files]
    file_names = [os.path.basename(path) for path in file_paths]

    has_frontend_signals = (
        "package.json" in file_names
        and (
            "src/main.tsx" in file_paths
            or "src/index.tsx" in file_paths
            or "vite.config.ts" in file_names
            or "vite.config.js" in file_names
            or "next.config.js" in file_names
            or "next.config.mjs" in file_names
            or "angular.json" in file_names
        )
    )

    has_backend_signals = (
        "requirements.txt" in file_names
        or "pyproject.toml" in file_names
        or "main.py" in file_names
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

    # Simple monorepo signal: common folder conventions or multiple package manifests.
    package_json_count = sum(1 for p in file_paths if os.path.basename(p) == "package.json")
    has_monorepo_layout = (
        "apps" in top_level_dirs
        or "packages" in top_level_dirs
        or "services" in top_level_dirs
        or package_json_count >= 2
    )

    if has_monorepo_layout:
        return "monorepo"
    if has_frontend_signals and (has_backend_signals or has_dotnet_signals):
        return "full-stack app"
    if has_dotnet_signals:
        return ".NET backend"
    if has_backend_signals:
        return "backend API"
    if has_frontend_signals:
        return "frontend web app"

    # Lightweight fallback for small scripts/data-heavy repos.
    ext_counts = count_extensions(files)
    if "Python" in languages or ".ipynb" in ext_counts:
        return "script/data project"

    return "unknown"
