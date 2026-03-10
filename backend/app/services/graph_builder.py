"""Graph builder V2 — builds architecture graph from scanner_v3 output.

Reads exclusively from the Scan model columns. No file-system access.
No AI/LLM. Every node and edge traces back to a specific scan field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.models.scan import Scan


# ── Data classes (unchanged interface for router) ────────────────────

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


# ── Slug helper ──────────────────────────────────────────────────────

def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


# ── Known services lookup tables ─────────────────────────────────────

_DB_NAMES: set[str] = {
    "postgres", "postgresql", "mysql", "mariadb", "mongo", "mongodb",
    "redis", "sqlite", "cassandra", "cockroachdb", "dynamodb",
    "mssql", "sqlserver",
}

_TOOL_NAMES: set[str] = {
    "nginx", "rabbitmq", "celery", "kafka", "elasticsearch",
    "opensearch", "zookeeper", "traefik", "consul", "vault",
    "prometheus", "grafana", "minio", "mailhog", "localstack",
}

_RUNTIME_MAP: dict[str, str] = {
    "Python": "Python Runtime",
    "TypeScript": "Node.js Runtime",
    "JavaScript": "Node.js Runtime",
    "Java": "JVM Runtime",
    "Kotlin": "JVM Runtime",
    "C#": ".NET Runtime",
    "Go": "Go Runtime",
    "Rust": "Rust Runtime",
    "Ruby": "Ruby Runtime",
    "PHP": "PHP Runtime",
}

_EXTERNAL_DEPS: dict[str, str] = {
    "boto3": "AWS / S3",
    "aws-sdk": "AWS / S3",
    "@aws-sdk": "AWS / S3",
    "stripe": "Stripe",
    "stripe-python": "Stripe",
    "sendgrid": "SendGrid",
    "@sendgrid": "SendGrid",
    "twilio": "Twilio",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "firebase": "Firebase",
    "@firebase": "Firebase",
    "firebase-admin": "Firebase",
    "supabase": "Supabase",
    "elasticsearch": "Search Engine",
    "opensearch": "Search Engine",
    "celery": "Task Queue",
    "pika": "RabbitMQ",
    "aio-pika": "RabbitMQ",
    "kafka-python": "Kafka",
    "confluent-kafka": "Kafka",
}

_DB_DEPS: dict[str, str] = {
    "psycopg": "PostgreSQL",
    "psycopg2": "PostgreSQL",
    "psycopg2-binary": "PostgreSQL",
    "asyncpg": "PostgreSQL",
    "pymysql": "MySQL",
    "mysql-connector": "MySQL",
    "mysql-connector-python": "MySQL",
    "pymongo": "MongoDB",
    "motor": "MongoDB",
    "mongoose": "MongoDB",
    "redis": "Redis",
    "ioredis": "Redis",
    "sqlite3": "SQLite",
    "better-sqlite3": "SQLite",
    "prisma": "Database",
    "sequelize": "Database",
    "typeorm": "Database",
}


# ── Main builder ─────────────────────────────────────────────────────

def build_graph_from_scan(scan: Scan) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    """Build architecture graph from scanner_v3 scan output."""

    nodes: dict[str, NodeSpec] = {}
    edges: set[tuple[str, str, str]] = set()

    def add_node(
        node_type: str, label: str, data: Optional[dict] = None
    ) -> str:
        key = f"{node_type}:{_slugify(label)}"
        if key not in nodes:
            nodes[key] = NodeSpec(key=key, node_type=node_type, label=label, data=data or {})
        else:
            # Merge metadata into existing node
            if data:
                nodes[key].data.update(data)
        return key

    def add_edge(src: str, tgt: str, etype: str) -> None:
        if src and tgt and src != tgt:
            edges.add((src, tgt, etype))

    # ── Extract scan fields ──────────────────────────────────────────
    components = scan.components or []
    docker_services = scan.docker_services or []
    service_graph = scan.service_graph or []
    routes = scan.routes or []
    dependencies = scan.dependencies or {}
    confidence = scan.confidence_scores or {}
    languages = set(scan.languages or [])

    # ── Rule 1 & 2: Component + entry point nodes ────────────────────
    comp_keys: dict[str, str] = {}  # component name → node key
    entry_owners: dict[str, tuple[str, str]] = {}  # entry_file → (comp_key, comp_type)

    for comp in components:
        if not isinstance(comp, dict):
            continue
        cname = comp.get("name", "component")
        ctype = comp.get("type", "unknown")
        node_type = "component"

        label = cname.replace("_", " ").title()
        comp_langs = comp.get("languages", [])
        primary_lang = comp_langs[0] if comp_langs else None

        data = {
            "component_type": ctype,
            "language": primary_lang,
            "file_count": comp.get("file_count"),
            "entry_file": comp.get("entry_file"),
        }
        key = add_node(node_type, label, data)
        comp_keys[cname] = key

        # Rule 2 — track entry point ownership (deduplicate later)
        entry_file = comp.get("entry_file")
        if entry_file:
            prev = entry_owners.get(entry_file)
            if prev is None:
                entry_owners[entry_file] = (key, ctype)
            else:
                # Prefer frontends for frontend-like entries, backends otherwise
                is_fe_entry = entry_file.endswith((".tsx", ".jsx", ".vue"))
                if is_fe_entry and ctype == "frontend":
                    entry_owners[entry_file] = (key, ctype)
                elif not is_fe_entry and ctype in ("backend", "service"):
                    entry_owners[entry_file] = (key, ctype)

    # Create entry point nodes with deduplicated ownership
    for entry_file, (owner_key, _) in entry_owners.items():
        ep_key = add_node("entry_point", entry_file, {"path": entry_file})
        add_edge(owner_key, ep_key, "contains")

    # ── Rule 3: Service graph → connects_to edges ────────────────────
    # Map docker service names to component keys if they match
    docker_to_comp: dict[str, str] = {}
    for comp in components:
        if not isinstance(comp, dict):
            continue
        cname = comp.get("name", "").lower()
        docker_to_comp[cname] = comp_keys.get(comp.get("name", ""), "")

    for link in service_graph:
        if not isinstance(link, dict):
            continue
        src_name = link.get("from", "")
        tgt_name = link.get("to", "")
        src_key = docker_to_comp.get(src_name.lower(), "")
        tgt_key = docker_to_comp.get(tgt_name.lower(), "")
        # The target might be a db/tool node created below — defer
        if src_key and tgt_key:
            add_edge(src_key, tgt_key, "connects_to")

    # ── Rule 4: Docker services → database / tool nodes ──────────────
    docker_node_keys: dict[str, str] = {}  # docker service name → node key

    for svc in docker_services:
        if not isinstance(svc, dict):
            continue
        name = svc.get("name", "")
        image = svc.get("image", "")
        ports = svc.get("ports", [])
        name_lower = name.lower()
        image_lower = image.lower()

        # Skip if this docker service matches a detected component
        if name_lower in docker_to_comp and docker_to_comp[name_lower]:
            docker_node_keys[name_lower] = docker_to_comp[name_lower]
            continue

        # Check if it's a database
        is_db = any(db in name_lower or db in image_lower for db in _DB_NAMES)
        if is_db:
            # Determine specific DB name from image
            db_label = _detect_db_label(name_lower, image_lower)
            key = add_node("database", db_label, {
                "image": image, "ports": ports,
            })
            docker_node_keys[name_lower] = key
            continue

        # Check if it's a tool
        is_tool = any(t in name_lower or t in image_lower for t in _TOOL_NAMES)
        if is_tool:
            tool_label = name.replace("-", " ").replace("_", " ").title()
            key = add_node("tool", tool_label, {
                "image": image, "ports": ports,
            })
            docker_node_keys[name_lower] = key
            continue

        # Unknown docker service — create as tool
        key = add_node("tool", name.replace("-", " ").replace("_", " ").title(), {
            "image": image, "ports": ports,
        })
        docker_node_keys[name_lower] = key

    # Now resolve service_graph edges that point to docker services
    for link in service_graph:
        if not isinstance(link, dict):
            continue
        src_name = link.get("from", "").lower()
        tgt_name = link.get("to", "").lower()
        src_key = docker_to_comp.get(src_name) or docker_node_keys.get(src_name, "")
        tgt_key = docker_node_keys.get(tgt_name, "")
        if src_key and tgt_key:
            add_edge(src_key, tgt_key, "uses")

    # ── Rule 5: Runtime nodes ────────────────────────────────────────
    runtime_keys: dict[str, str] = {}  # runtime label → node key

    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_langs = comp.get("languages", [])
        ckey = comp_keys.get(comp.get("name", ""), "")
        if not ckey:
            continue
        for lang in comp_langs:
            rt_label = _RUNTIME_MAP.get(lang)
            if not rt_label:
                continue
            # Only if language confidence > 0.3
            if lang in confidence and confidence[lang] < 0.3:
                continue
            if rt_label not in runtime_keys:
                runtime_keys[rt_label] = add_node("runtime", rt_label)
            add_edge(ckey, runtime_keys[rt_label], "runs_on")

    # ── Rule 6: External service detection from dependencies ─────────
    external_keys: dict[str, str] = {}  # external label → node key

    all_dep_names: dict[str, list[str]] = {}  # dep_name → list of lang keys
    for lang_key, dep_list in dependencies.items():
        if not isinstance(dep_list, list):
            continue
        for dep in dep_list:
            dep_name = dep.get("name", "") if isinstance(dep, dict) else str(dep)
            if dep_name:
                all_dep_names.setdefault(dep_name.lower(), []).append(lang_key)

    # Match external deps
    for dep_name, lang_keys in all_dep_names.items():
        ext_label = _EXTERNAL_DEPS.get(dep_name)
        if not ext_label:
            continue
        if ext_label not in external_keys:
            external_keys[ext_label] = add_node("external", ext_label)
        # Find which component has this dependency
        comp_key = _find_comp_for_dep(lang_keys, components, comp_keys)
        if comp_key:
            add_edge(comp_key, external_keys[ext_label], "uses")

    # ── Rule 7: Database detection from dependencies ─────────────────
    dep_db_keys: dict[str, str] = {}  # db label → node key

    for dep_name, lang_keys in all_dep_names.items():
        db_label = _DB_DEPS.get(dep_name)
        if not db_label:
            continue
        # Check if a database node with this label already exists from docker
        existing = _find_existing_db_node(db_label, nodes)
        if existing:
            db_key = existing
        elif db_label not in dep_db_keys:
            db_key = add_node("database", db_label)
            dep_db_keys[db_label] = db_key
        else:
            db_key = dep_db_keys[db_label]
        comp_key = _find_comp_for_dep(lang_keys, components, comp_keys)
        if comp_key:
            add_edge(comp_key, db_key, "uses")

    # If sqlalchemy is in deps and we have a postgres docker service, link them
    if "sqlalchemy" in all_dep_names:
        pg_key = _find_existing_db_node("PostgreSQL", nodes)
        if pg_key:
            comp_key = _find_comp_for_dep(
                all_dep_names.get("sqlalchemy", []), components, comp_keys
            )
            if comp_key:
                add_edge(comp_key, pg_key, "uses")

    # ── Rule 8: Route-based call edges ───────────────────────────────
    if routes and len(comp_keys) > 1:
        # Find frontend components that might call backend routes
        fe_comps = {n: k for n, k in comp_keys.items()
                    if _comp_type(n, components) == "frontend"}
        be_comps = {n: k for n, k in comp_keys.items()
                    if _comp_type(n, components) in ("backend", "service")}
        if fe_comps and be_comps:
            # Frontend → Backend call edge (one per pair)
            for fe_key in fe_comps.values():
                for be_key in be_comps.values():
                    add_edge(fe_key, be_key, "calls")

    # ── Fallback: connect orphan database/tool nodes to backend ─────
    _connected_targets = {tgt for _, tgt, _ in edges}
    be_comp_keys = [
        k for n, k in comp_keys.items()
        if _comp_type(n, components) in ("backend", "service")
    ]
    # Fall back to any component if no backend found
    fallback_comp = be_comp_keys[0] if be_comp_keys else (
        next(iter(comp_keys.values())) if comp_keys else ""
    )
    if fallback_comp:
        for key, node in list(nodes.items()):
            if node.node_type in ("database", "tool") and key not in _connected_targets:
                add_edge(fallback_comp, key, "uses")

    # ── Rule 9: Noise control / cap at 20 nodes ─────────────────────
    if len(nodes) > 20:
        _prune_nodes(nodes, edges, comp_keys)

    # ── Build output ─────────────────────────────────────────────────
    node_specs = sorted(nodes.values(), key=lambda n: n.key)
    edge_specs = [
        EdgeSpec(source_key=s, target_key=t, edge_type=e)
        for s, t, e in sorted(edges)
        if s in nodes and t in nodes
    ]

    return node_specs, edge_specs


# ── Helpers ──────────────────────────────────────────────────────────

def _detect_db_label(name: str, image: str) -> str:
    """Determine a nice label for a database from docker name/image."""
    combined = f"{name} {image}"
    if "postgres" in combined:
        return "PostgreSQL"
    if "mysql" in combined or "mariadb" in combined:
        return "MySQL"
    if "mongo" in combined:
        return "MongoDB"
    if "redis" in combined:
        return "Redis"
    if "sqlite" in combined:
        return "SQLite"
    if "cassandra" in combined:
        return "Cassandra"
    if "mssql" in combined or "sqlserver" in combined:
        return "SQL Server"
    return name.replace("-", " ").replace("_", " ").title()


def _find_existing_db_node(
    db_label: str, nodes: dict[str, NodeSpec]
) -> Optional[str]:
    """Find an existing database node that matches a label."""
    target = _slugify(db_label)
    for key, node in nodes.items():
        if node.node_type == "database" and _slugify(node.label) == target:
            return key
    # Partial match (e.g. "PostgreSQL" matches "database:postgresql")
    for key, node in nodes.items():
        if node.node_type == "database" and target in _slugify(node.label):
            return key
    return None


def _find_comp_for_dep(
    lang_keys: list[str],
    components: list[dict],
    comp_keys: dict[str, str],
) -> Optional[str]:
    """Find the best component key that owns a dependency.

    lang_keys are like ["python", "npm"].
    """
    lang_to_component_lang = {
        "python": {"Python"},
        "npm": {"JavaScript", "TypeScript"},
        "java": {"Java", "Kotlin"},
        "go": {"Go"},
        "rust": {"Rust"},
        "ruby": {"Ruby"},
    }
    target_langs: set[str] = set()
    for lk in lang_keys:
        target_langs |= lang_to_component_lang.get(lk, set())

    for comp in components:
        if not isinstance(comp, dict):
            continue
        comp_langs = set(comp.get("languages", []))
        if comp_langs & target_langs:
            return comp_keys.get(comp.get("name", ""))
    # Fallback: return first component
    if comp_keys:
        return next(iter(comp_keys.values()))
    return None


def _comp_type(name: str, components: list[dict]) -> str:
    for comp in components:
        if isinstance(comp, dict) and comp.get("name") == name:
            return comp.get("type", "unknown")
    return "unknown"


def _prune_nodes(
    nodes: dict[str, NodeSpec],
    edges: set[tuple[str, str, str]],
    comp_keys: dict[str, str],
) -> None:
    """Prune graph to max 20 nodes by priority."""
    priority = {"component": 0, "entry_point": 1, "database": 2, "external": 3, "runtime": 4, "tool": 5}
    sorted_keys = sorted(
        nodes.keys(),
        key=lambda k: (priority.get(nodes[k].node_type, 6), k),
    )
    keep = set(sorted_keys[:20])
    to_remove = set(nodes.keys()) - keep
    for k in to_remove:
        del nodes[k]
    # Remove edges referencing removed nodes
    to_discard = {e for e in edges if e[0] in to_remove or e[1] in to_remove}
    edges -= to_discard
