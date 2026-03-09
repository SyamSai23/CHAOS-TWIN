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

    # ── Tool-to-component mapping (used by both paths) ──
    frontend_tool_frameworks = {
        "TypeScript",
        "Vite",
        "Next.js",
        "Angular",
    }
    backend_tool_frameworks = {
        "Python (pip)",
        "Python (modern)",
        "Python (pipenv)",
        "Django",
        "Go modules",
        "Java (Maven)",
        "Java (Gradle)",
        "Rust (Cargo)",
    }
    shared_tool_frameworks = {
        "Docker",
        "Docker Compose",
        "Environment config",
        "Make",
    }

    # ── Database detection (independent of component path) ──
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

    # ── Component & entry-point nodes ──
    components = scan.components or []
    _rich = [c for c in components if isinstance(c, dict) and "root_path" in c]

    frontend_key = ""
    backend_key = ""

    if _rich:
        # ── New path: use scanned component roots ──
        for comp in _rich:
            ct = comp.get("type", "other")
            cname = comp.get("name", "component")

            if ct == "frontend":
                label = cname.replace("_", " ").title() if cname.lower() != "frontend" else "Frontend"
                key = add_node("frontend", label)
                if not frontend_key:
                    frontend_key = key
            elif ct in ("backend", "service"):
                label = cname.replace("_", " ").title() if cname.lower() != "backend" else "Backend"
                key = add_node("backend", label)
                if not backend_key:
                    backend_key = key
            # Skip data/infra/docs/config/other types

        # Entry-point child nodes from component data
        for comp in _rich:
            ct = comp.get("type", "other")
            if ct == "frontend":
                parent = frontend_key
            elif ct in ("backend", "service"):
                parent = backend_key
            else:
                parent = ""

            for ep in comp.get("entry_points", []):
                ep_key = add_node("entry_point", ep, data={"path": ep})
                if parent:
                    add_edge(parent, ep_key, "contains")

        all_eps = [ep for c in _rich for ep in c.get("entry_points", [])]
        has_frontend_entry = any(_is_frontend_entry_path(ep) for ep in all_eps)
        has_backend_entry = any(
            os.path.basename(ep).lower() in {"main.py", "app.py", "server.py", "manage.py", "program.cs"}
            for ep in all_eps
        )
        has_backend_node_entry = any(ep.endswith((".js", ".ts")) for ep in all_eps)
    else:
        # ── Fallback: heuristic detection (pre-v2 scans) ──
        frontend_framework_signals = {
            "Node.js", "TypeScript", "Vite", "Next.js", "Angular",
        }
        backend_framework_signals = {
            "Python (pip)", "Python (modern)", "Python (pipenv)", "Django",
            "Go modules", "Java (Maven)", "Java (Gradle)", "Rust (Cargo)", ".NET",
        }
        frontend_key_file_signals = {
            "package.json", "vite.config.ts", "vite.config.js",
            "next.config.js", "next.config.mjs", "angular.json", "tsconfig.json",
        }
        backend_key_file_signals = {
            "requirements.txt", "pyproject.toml", "pipfile", "manage.py",
            "go.mod", "pom.xml", "build.gradle", "cargo.toml",
        }

        has_frontend_entry = any(_is_frontend_entry_path(ep) for ep in entry_points)
        has_backend_entry = any(
            os.path.basename(ep).lower() in {"main.py", "app.py", "server.py", "manage.py", "program.cs"}
            for ep in entry_points
        )
        has_backend_node_entry = any(ep.endswith((".js", ".ts")) for ep in entry_points)

        has_frontend = (
            scan.project_type in {"frontend web app", "full-stack app"}
            or has_frontend_entry
            or any(fw in frontend_framework_signals for fw in frameworks)
            or any(name in frontend_key_file_signals for name in key_file_names)
            or any(lang in {"TypeScript (JSX)", "JavaScript (JSX)"} for lang in languages)
            or "frontend" in {d.lower() for d in top_dirs}
        )
        has_backend = (
            scan.project_type in {"backend API", ".NET backend", "full-stack app"}
            or has_backend_entry
            or any(fw in backend_framework_signals for fw in frameworks)
            or any(name in backend_key_file_signals for name in key_file_names)
            or "backend" in {d.lower() for d in top_dirs}
        )

        if has_frontend:
            frontend_key = add_node("frontend", "Frontend")
        if has_backend:
            backend_key = add_node("backend", "Backend")

        for path in entry_points:
            ep_key = add_node("entry_point", path, data={"path": path})
            is_frontend_entry = _is_frontend_entry_path(path)
            if is_frontend_entry and frontend_key:
                add_edge(frontend_key, ep_key, "contains")
            elif backend_key:
                add_edge(backend_key, ep_key, "contains")
            elif frontend_key:
                add_edge(frontend_key, ep_key, "contains")

    database_key = add_node("database", "Database") if has_database else ""

    # ── Runtime nodes ──
    # Only language runtimes that define how the app executes.
    # Docker is infrastructure, not a language runtime — skip it here.
    runtime_keys: dict[str, str] = {}
    has_python_runtime_signal = "Python" in languages or any(name.startswith("Python") for name in frameworks)
    has_node_runtime_signal = (
        any(name in languages for name in {"JavaScript", "TypeScript", "TypeScript (JSX)", "JavaScript (JSX)"})
        or "Node.js" in frameworks
    )
    has_dotnet_runtime_signal = "C#" in languages or any(ep.endswith("Program.cs") for ep in entry_points)

    if has_python_runtime_signal:
        runtime_keys["python"] = add_node("runtime", "Python Runtime")
    if has_node_runtime_signal:
        runtime_keys["node"] = add_node("runtime", "Node.js Runtime")
    if has_dotnet_runtime_signal:
        runtime_keys["dotnet"] = add_node("runtime", ".NET Runtime")

    # ── Tool nodes ──
    # Only architecture-defining frameworks get promoted to graph nodes.
    # Commodity tooling (bundlers, package managers, config) is stored as
    # metadata on the component node instead of cluttering the graph.
    PROMOTED_FRAMEWORKS: set[str] = {
        "Django",
        "Next.js",
        "Angular",
    }
    DEMOTED_FRAMEWORKS: set[str] = {
        "TypeScript",
        "Vite",
        "Python (pip)",
        "Python (modern)",
        "Python (pipenv)",
        "Docker",
        "Docker Compose",
        "Environment config",
        "Make",
        "Node.js",
    }

    # Collect demoted tools per component for metadata
    frontend_tools: list[str] = []
    backend_tools: list[str] = []

    for framework in sorted(frameworks):
        if framework in DEMOTED_FRAMEWORKS:
            # Store as metadata instead of creating a node
            if framework in frontend_tool_frameworks:
                frontend_tools.append(framework)
            elif framework in backend_tool_frameworks:
                backend_tools.append(framework)
            else:
                # Shared tools go to both
                frontend_tools.append(framework)
                backend_tools.append(framework)
            continue

        if framework in PROMOTED_FRAMEWORKS:
            tool_key = add_node("tool", framework)
            if framework in frontend_tool_frameworks and frontend_key:
                add_edge(frontend_key, tool_key, "uses")
            elif framework in backend_tool_frameworks and backend_key:
                add_edge(backend_key, tool_key, "uses")
            elif frontend_key:
                add_edge(frontend_key, tool_key, "uses")
            elif backend_key:
                add_edge(backend_key, tool_key, "uses")

    # Attach tool metadata to component nodes
    if frontend_key and frontend_tools:
        nodes[frontend_key].data["tools"] = frontend_tools
    if backend_key and backend_tools:
        nodes[backend_key].data["tools"] = backend_tools

    if frontend_key and "node" in runtime_keys and has_frontend_entry:
        add_edge(frontend_key, runtime_keys["node"], "runs_on")
    if backend_key and "python" in runtime_keys and has_backend_entry:
        add_edge(backend_key, runtime_keys["python"], "runs_on")
    if backend_key and "dotnet" in runtime_keys and has_backend_entry:
        add_edge(backend_key, runtime_keys["dotnet"], "runs_on")
    if backend_key and "node" in runtime_keys and has_backend_node_entry:
        add_edge(backend_key, runtime_keys["node"], "runs_on")

    if has_database and backend_key:
        add_edge(backend_key, database_key, "connects_to")

    edge_specs = [
        EdgeSpec(source_key=s, target_key=t, edge_type=e)
        for s, t, e in sorted(edges)
    ]
    node_specs = sorted(nodes.values(), key=lambda n: n.key)

    return node_specs, edge_specs
