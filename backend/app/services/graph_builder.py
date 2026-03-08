import os
from dataclasses import dataclass
from typing import Optional

from app.models.scan import Scan


@dataclass
class NodeSpec:
    key: str
    node_type: str
    label: str
    data: dict


@dataclass
class EdgeSpec:
    source_key: str
    target_key: str
    edge_type: str


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _path_parts(path: str) -> list[str]:
    normalized = path.replace("\\", "/").strip("/")
    return [part.lower() for part in normalized.split("/") if part]


def _is_frontend_entry_path(path: str) -> bool:
    """Heuristic frontend entrypoint check that works with wrapper folders."""
    parts = _path_parts(path)
    if not parts:
        return False

    filename = parts[-1]
    frontend_entry_names = {
        "main.js",
        "main.ts",
        "main.jsx",
        "main.tsx",
        "index.js",
        "index.ts",
        "index.jsx",
        "index.tsx",
    }
    if filename not in frontend_entry_names:
        return False

    # Accept root files and wrapped paths that contain /src/ anywhere.
    return len(parts) == 1 or "src" in parts[:-1]


def build_graph_from_scan(scan: Scan) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    """Build a simple architecture graph using existing scan summary fields only."""
    nodes: dict[str, NodeSpec] = {}
    edges: set[tuple[str, str, str]] = set()

    def add_node(node_type: str, label: str, data: Optional[dict] = None) -> str:
        key = f"{node_type}:{_normalize_key(label)}"
        if key not in nodes:
            nodes[key] = NodeSpec(
                key=key,
                node_type=node_type,
                label=label,
                data=data or {},
            )
        return key

    def add_edge(source_key: str, target_key: str, edge_type: str) -> None:
        if source_key == target_key:
            return
        edges.add((source_key, target_key, edge_type))

    top_dirs = set(scan.top_level_dirs or [])
    frameworks = set(scan.frameworks or [])
    languages = set(scan.languages or [])
    key_files = scan.key_files or []
    entry_points = scan.entry_points or []
    file_paths = [f.get("path", "") for f in (scan.files or []) if isinstance(f, dict)]

    key_file_names = {os.path.basename(path).lower() for path in key_files}

    frontend_framework_signals = {
        "Node.js",
        "TypeScript",
        "Vite",
        "Next.js",
        "Angular",
    }
    backend_framework_signals = {
        "Python (pip)",
        "Python (modern)",
        "Python (pipenv)",
        "Django",
        "Go modules",
        "Java (Maven)",
        "Java (Gradle)",
        "Rust (Cargo)",
        ".NET",
    }

    frontend_key_file_signals = {
        "package.json",
        "vite.config.ts",
        "vite.config.js",
        "next.config.js",
        "next.config.mjs",
        "angular.json",
        "tsconfig.json",
    }
    backend_key_file_signals = {
        "requirements.txt",
        "pyproject.toml",
        "pipfile",
        "manage.py",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "cargo.toml",
    }

    has_frontend_entry = any(_is_frontend_entry_path(ep) for ep in entry_points)
    has_backend_entry = any(
        os.path.basename(ep).lower() in {"main.py", "app.py", "server.py", "manage.py", "program.cs"}
        for ep in entry_points
    )

    has_frontend = (
        scan.project_type in {"frontend web app", "full-stack app"}
        or has_frontend_entry
        or any(framework in frontend_framework_signals for framework in frameworks)
        or any(name in frontend_key_file_signals for name in key_file_names)
        or any(language in {"TypeScript (JSX)", "JavaScript (JSX)"} for language in languages)
        or "frontend" in {d.lower() for d in top_dirs}
    )
    has_backend = (
        scan.project_type in {"backend API", ".NET backend", "full-stack app"}
        or has_backend_entry
        or any(framework in backend_framework_signals for framework in frameworks)
        or any(name in backend_key_file_signals for name in key_file_names)
        or "backend" in {d.lower() for d in top_dirs}
    )

    database_file_markers = {
        "schema.sql",
        "seed.sql",
        "alembic.ini",
        "schema.prisma",
        "db.sqlite3",
        "db.sqlite",
        "docker-compose.yml",
        "docker-compose.yaml",
    }
    database_path_keywords = {
        "/migrations/",
        "/alembic/",
        "/prisma/",
        "/sql/",
        "/database/",
        "/db/",
    }
    lower_file_paths = [
        "/" + p.lower().replace("\\", "/").strip("/")
        for p in file_paths
        if p
    ]

    has_database = (
        "SQL" in languages
        or "Django" in frameworks
        or any(name in database_file_markers for name in key_file_names)
        or any(
            os.path.basename(path).lower() in database_file_markers
            for path in file_paths
        )
        or any(any(keyword in path for keyword in database_path_keywords) for path in lower_file_paths)
    )

    frontend_key = add_node("frontend", "Frontend") if has_frontend else ""
    backend_key = add_node("backend", "Backend") if has_backend else ""
    database_key = add_node("database", "Database") if has_database else ""

    runtime_keys: dict[str, str] = {}
    if "Python" in languages or any(name.startswith("Python") for name in frameworks):
        runtime_keys["python"] = add_node("runtime", "Python Runtime")
    if any(name in languages for name in {"JavaScript", "TypeScript", "TypeScript (JSX)", "JavaScript (JSX)"}) or "Node.js" in frameworks:
        runtime_keys["node"] = add_node("runtime", "Node.js Runtime")
    if "C#" in languages or any(ep.endswith("Program.cs") for ep in entry_points):
        runtime_keys["dotnet"] = add_node("runtime", ".NET Runtime")
    if "Docker" in frameworks:
        runtime_keys["docker"] = add_node("runtime", "Docker")

    runtime_frameworks = {"Docker", "Node.js"}
    for framework in sorted(frameworks):
        if framework in runtime_frameworks:
            continue
        tool_key = add_node("tool", framework)
        if frontend_key:
            add_edge(frontend_key, tool_key, "uses")
        if backend_key:
            add_edge(backend_key, tool_key, "uses")

    for path in entry_points:
        ep_key = add_node("entry_point", path, data={"path": path})
        is_frontend_entry = _is_frontend_entry_path(path)

        if is_frontend_entry and frontend_key:
            add_edge(frontend_key, ep_key, "contains")
        elif backend_key:
            add_edge(backend_key, ep_key, "contains")
        elif frontend_key:
            add_edge(frontend_key, ep_key, "contains")

    if frontend_key and "node" in runtime_keys:
        add_edge(frontend_key, runtime_keys["node"], "runs_on")
    if backend_key and "python" in runtime_keys:
        add_edge(backend_key, runtime_keys["python"], "runs_on")
    if backend_key and "dotnet" in runtime_keys:
        add_edge(backend_key, runtime_keys["dotnet"], "runs_on")
    if backend_key and "node" in runtime_keys and any(ep.endswith((".js", ".ts")) for ep in entry_points):
        add_edge(backend_key, runtime_keys["node"], "runs_on")

    if frontend_key and "docker" in runtime_keys:
        add_edge(frontend_key, runtime_keys["docker"], "runs_on")
    if backend_key and "docker" in runtime_keys:
        add_edge(backend_key, runtime_keys["docker"], "runs_on")

    if has_database and backend_key:
        add_edge(backend_key, database_key, "connects_to")

    # Use key files as tool hints when no framework already surfaced.
    if "docker-compose.yml" in [os.path.basename(k) for k in key_files] or "docker-compose.yaml" in [os.path.basename(k) for k in key_files]:
        compose_tool_key = add_node("tool", "Docker Compose")
        if frontend_key:
            add_edge(frontend_key, compose_tool_key, "uses")
        if backend_key:
            add_edge(backend_key, compose_tool_key, "uses")

    edge_specs = [
        EdgeSpec(source_key=s, target_key=t, edge_type=e)
        for s, t, e in sorted(edges)
    ]
    node_specs = sorted(nodes.values(), key=lambda n: n.key)

    return node_specs, edge_specs
