"""Sequence diagram generator — derives runtime request flow from scan + graph data.

Reads exclusively from Scan model columns and Graph nodes/edges.
No file-system access. No AI/LLM.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Optional

from app.models.scan import Scan
from app.models.graph_node import GraphNode
from app.models.graph_edge import GraphEdge


# ── Phase → human-readable labels ───────────────────────────────────

_PHASE_LABELS: dict[str, tuple[str, str]] = {
    # phase keyword → (call label, return label)
    "entry": ("HTTP Request", "HTTP Response"),
    "startup": ("HTTP Request", "HTTP Response"),
    "configuration": ("load config", "config loaded"),
    "settings": ("load config", "config loaded"),
    "routing": ("route request", "routed"),
    "url dispatch": ("dispatch to handler", "handler resolved"),
    "service": ("execute business logic", "result"),
    "business logic": ("execute business logic", "result"),
    "data access": ("query data", "query result"),
    "persistence": ("read / write data", "data result"),
}

# Queue-like tool names that should appear as participants
_QUEUE_NAMES = {"rabbitmq", "kafka", "celery", "task queue"}


def generate_sequence(
    scan: Scan,
    graph_nodes: list[GraphNode],
    graph_edges: list[GraphEdge],
) -> dict:
    """Generate sequence diagram data from scan and graph."""

    # Build lookup structures
    node_map: dict[str, GraphNode] = {n.id: n for n in graph_nodes}
    edges_by_source: dict[str, list[GraphEdge]] = {}
    for e in graph_edges:
        edges_by_source.setdefault(e.source_node_id, []).append(e)

    # ── Step 1: Build participants ───────────────────────────────────
    participants: list[dict] = []
    participant_ids: set[str] = set()
    order_counter = 0

    def add_participant(pid: str, label: str, ptype: str) -> None:
        nonlocal order_counter
        if pid in participant_ids:
            return
        participant_ids.add(pid)
        participants.append({
            "id": pid,
            "label": label,
            "type": ptype,
            "order": order_counter,
        })
        order_counter += 1

    # 1a. Always add Client first
    add_participant("client", "Client", "client")

    # 1b. Categorize graph nodes
    component_nodes: list[GraphNode] = []
    entry_point_nodes: list[GraphNode] = []
    database_nodes: list[GraphNode] = []
    external_nodes: list[GraphNode] = []
    queue_nodes: list[GraphNode] = []

    for node in graph_nodes:
        if node.node_type == "component":
            component_nodes.append(node)
        elif node.node_type == "entry_point":
            entry_point_nodes.append(node)
        elif node.node_type == "database":
            database_nodes.append(node)
        elif node.node_type == "external":
            external_nodes.append(node)
        elif node.node_type == "tool":
            if node.label.lower() in _QUEUE_NAMES:
                queue_nodes.append(node)
        # Skip runtime and non-queue tool nodes

    # 1c. Add components in execution_flow order if possible
    execution_flow = scan.execution_flow or []
    components_scan = scan.components or []
    comp_name_to_node: dict[str, GraphNode] = {}
    for node in component_nodes:
        comp_name_to_node[node.label.lower()] = node
        # Also map by data.component_type for matching
        data = node.data or {}
        ct = data.get("component_type", "")
        if ct:
            comp_name_to_node[ct] = node

    # Order: backends/services first (they handle requests), then frontends
    backend_nodes = [n for n in component_nodes
                     if (n.data or {}).get("component_type") in ("backend", "service")]
    frontend_nodes = [n for n in component_nodes
                      if (n.data or {}).get("component_type") == "frontend"]
    other_comp_nodes = [n for n in component_nodes
                        if n not in backend_nodes and n not in frontend_nodes]

    # For multi-component: frontend first (it initiates requests), then backend
    if frontend_nodes and backend_nodes:
        for n in frontend_nodes:
            add_participant(n.id, n.label, "component")
        for n in backend_nodes:
            add_participant(n.id, n.label, "component")
    else:
        for n in backend_nodes:
            add_participant(n.id, n.label, "component")
        for n in frontend_nodes:
            add_participant(n.id, n.label, "component")
    for n in other_comp_nodes:
        add_participant(n.id, n.label, "component")

    # 1d. Add database nodes connected via "uses" edges
    for node in database_nodes:
        has_edge = any(
            e.target_node_id == node.id and e.edge_type == "uses"
            for e in graph_edges
        )
        if has_edge:
            add_participant(node.id, node.label, "database")

    # 1e. Add external service nodes connected via "uses" edges
    for node in external_nodes:
        has_edge = any(
            e.target_node_id == node.id and e.edge_type == "uses"
            for e in graph_edges
        )
        if has_edge:
            add_participant(node.id, node.label, "external")

    # 1f. Add queue nodes
    for node in queue_nodes:
        add_participant(node.id, node.label, "queue")

    # ── Step 2: Build messages from execution_flow ───────────────────
    messages: list[dict] = []
    msg_order = 0

    def add_msg(
        from_p: str, to_p: str, label: str,
        msg_type: str, step: int,
    ) -> str:
        nonlocal msg_order
        if from_p not in participant_ids or to_p not in participant_ids:
            return ""
        if from_p == to_p:
            return ""
        mid = str(uuid.uuid4())
        messages.append({
            "id": mid,
            "from_participant": from_p,
            "to_participant": to_p,
            "label": label,
            "message_type": msg_type,
            "step": step,
            "order": msg_order,
        })
        msg_order += 1
        return mid

    # Determine the primary backend component (receives requests)
    primary_backend: Optional[str] = None
    if backend_nodes:
        primary_backend = backend_nodes[0].id
    elif other_comp_nodes:
        primary_backend = other_comp_nodes[0].id
    elif component_nodes:
        primary_backend = component_nodes[0].id

    primary_frontend: Optional[str] = None
    if frontend_nodes:
        primary_frontend = frontend_nodes[0].id

    # Determine the entry target (where Client sends requests)
    entry_target = primary_frontend or primary_backend

    if not entry_target:
        # Not enough data
        return _build_response(scan, participants, messages, [],
                               component_nodes, database_nodes,
                               external_nodes)

    # ── Step 2a: Multi-component cross-call (frontend → backend) ─────
    is_multi = bool(primary_frontend and primary_backend)
    cross_call_step = 0

    # Routes for enriching labels
    routes = scan.routes or []
    route_labels = _pick_route_labels(routes, max_count=3)

    if is_multi and primary_frontend and primary_backend:
        # Client → Frontend
        fe_label = "Open app"
        add_msg("client", primary_frontend, fe_label, "call", 0)

        # Frontend → Backend (with route info if available)
        for i, rl in enumerate(route_labels[:1]):
            cross_call_step = 1
            add_msg(primary_frontend, primary_backend,
                    f"API call ({rl})", "call", 1)
    elif entry_target:
        # Single-component: Client → component
        call_label = f"Request ({route_labels[0]})" if route_labels else "HTTP Request"
        add_msg("client", entry_target, call_label, "call", 0)

    # ── Step 2b: Walk execution_flow phases ──────────────────────────
    # Map phases to messages
    if primary_backend and execution_flow:
        prev_participant = primary_backend
        flow_step_base = 2 if is_multi else 1

        for ef_step in execution_flow:
            phase = ef_step.get("phase", "")
            files = ef_step.get("files", [])
            step_num = ef_step.get("step", 0)

            if not files:
                continue

            call_label, return_label = _phase_to_labels(phase)

            if "entry" in phase.lower() or "startup" in phase.lower():
                # Already handled by the initial Client → component
                continue

            if "config" in phase.lower() or "setting" in phase.lower():
                # Internal operation within the backend
                add_msg(primary_backend, primary_backend,
                        call_label, "call", flow_step_base + step_num)
                continue

            if "routing" in phase.lower() or "dispatch" in phase.lower():
                add_msg(primary_backend, primary_backend,
                        call_label, "call", flow_step_base + step_num)
                continue

            if "service" in phase.lower() or "business" in phase.lower():
                add_msg(primary_backend, primary_backend,
                        call_label, "call", flow_step_base + step_num)

                # Add external service calls in this phase
                for node in external_nodes:
                    if node.id in participant_ids:
                        # Check if this external is connected to the backend
                        connected = any(
                            e.source_node_id == primary_backend
                            and e.target_node_id == node.id
                            for e in graph_edges
                        )
                        if connected:
                            add_msg(primary_backend, node.id,
                                    "API call", "call",
                                    flow_step_base + step_num)
                            add_msg(node.id, primary_backend,
                                    "response", "return",
                                    flow_step_base + step_num)
                continue

            if "data" in phase.lower() or "persist" in phase.lower():
                # Database calls
                for node in database_nodes:
                    if node.id in participant_ids:
                        connected = any(
                            e.source_node_id == primary_backend
                            and e.target_node_id == node.id
                            for e in graph_edges
                        )
                        if connected:
                            add_msg(primary_backend, node.id,
                                    "query / read / write", "call",
                                    flow_step_base + step_num)
                            add_msg(node.id, primary_backend,
                                    "result", "return",
                                    flow_step_base + step_num)
                continue

    # ── Step 2c: If no execution_flow, derive from graph edges ───────
    if not execution_flow and primary_backend:
        step_num = 2 if is_multi else 1

        # Database calls from graph edges
        for node in database_nodes:
            if node.id in participant_ids:
                connected = any(
                    e.source_node_id == primary_backend
                    and e.target_node_id == node.id
                    for e in graph_edges
                )
                if connected:
                    add_msg(primary_backend, node.id,
                            "query data", "call", step_num)
                    add_msg(node.id, primary_backend,
                            "result", "return", step_num)
                    step_num += 1

        # External service calls from graph edges
        for node in external_nodes:
            if node.id in participant_ids:
                connected = any(
                    e.source_node_id == primary_backend
                    and e.target_node_id == node.id
                    for e in graph_edges
                )
                if connected:
                    add_msg(primary_backend, node.id,
                            "API call", "call", step_num)
                    add_msg(node.id, primary_backend,
                            "response", "return", step_num)
                    step_num += 1

    # ── Step 2d: Return arrows ───────────────────────────────────────
    if is_multi and primary_frontend and primary_backend:
        last_step = (execution_flow[-1]["step"] + 3) if execution_flow else 10
        add_msg(primary_backend, primary_frontend,
                "JSON response", "return", last_step)
        add_msg(primary_frontend, "client",
                "Render response", "return", last_step + 1)
    elif entry_target:
        last_step = (execution_flow[-1]["step"] + 2) if execution_flow else 10
        resp_label = "HTTP Response"
        add_msg(entry_target, "client", resp_label, "return", last_step)

    # ── Step 3: Build flows ──────────────────────────────────────────
    flows = _build_flows(messages, route_labels)

    # ── Trim to max 20 messages per flow ─────────────────────────────
    for flow in flows:
        flow["message_ids"] = flow["message_ids"][:20]

    return _build_response(scan, participants, messages, flows,
                           component_nodes, database_nodes,
                           external_nodes)


# ── Helpers ──────────────────────────────────────────────────────────

def _phase_to_labels(phase: str) -> tuple[str, str]:
    """Map an execution_flow phase string to call/return labels."""
    phase_lower = phase.lower()
    for key, (call_l, ret_l) in _PHASE_LABELS.items():
        if key in phase_lower:
            return call_l, ret_l
    return phase, "done"


def _pick_route_labels(routes: list[dict], max_count: int = 3) -> list[str]:
    """Pick the most meaningful route labels."""
    if not routes:
        return []
    labels: list[str] = []
    seen: set[str] = set()
    for r in routes:
        method = r.get("method", "GET")
        path = r.get("path", "/")
        label = f"{method} {path}"
        if label not in seen:
            seen.add(label)
            labels.append(label)
        if len(labels) >= max_count:
            break
    return labels


def _build_flows(
    messages: list[dict],
    route_labels: list[str],
) -> list[dict]:
    """Group messages into flows."""
    if not messages:
        return []

    all_msg_ids = [m["id"] for m in messages]

    # Primary flow
    primary_flow = {
        "flow_id": str(uuid.uuid4()),
        "flow_name": "HTTP Request Flow",
        "route_example": route_labels[0] if route_labels else None,
        "message_ids": all_msg_ids,
    }

    flows = [primary_flow]

    # Add up to 2 additional route example flows
    for i, rl in enumerate(route_labels[1:3]):
        flows.append({
            "flow_id": str(uuid.uuid4()),
            "flow_name": f"Example: {rl}",
            "route_example": rl,
            "message_ids": all_msg_ids,
        })

    return flows[:3]


def _build_response(
    scan: Scan,
    participants: list[dict],
    messages: list[dict],
    flows: list[dict],
    component_nodes: list,
    database_nodes: list,
    external_nodes: list,
) -> dict:
    """Build the final response dict."""
    # Remove participants that have no messages
    active_pids: set[str] = set()
    for m in messages:
        active_pids.add(m["from_participant"])
        active_pids.add(m["to_participant"])
    # Always keep client
    active_pids.add("client")

    filtered_participants = [p for p in participants if p["id"] in active_pids]
    # Re-number order
    for i, p in enumerate(filtered_participants):
        p["order"] = i

    has_db = any(p["type"] == "database" for p in filtered_participants)
    has_ext = any(p["type"] == "external" for p in filtered_participants)
    comp_count = sum(1 for p in filtered_participants if p["type"] == "component")

    return {
        "project_id": scan.project_id,
        "participants": filtered_participants,
        "messages": messages,
        "flows": flows,
        "metadata": {
            "component_count": comp_count,
            "step_count": len(scan.execution_flow or []),
            "has_external_calls": has_ext,
            "has_database": has_db,
            "is_multi_component": comp_count > 1,
        },
    }


# ═══════════════════════════════════════════════════════════════════════
#  Per-route sequence diagram generator
# ═══════════════════════════════════════════════════════════════════════

def _route_id(method: str, path: str) -> str:
    raw = f"{method.upper()}:{path}"
    return hashlib.md5(raw.encode()).hexdigest()


# Classify a file path into a role category based on its parent folders.
# Returns (role, label) where role determines behaviour:
#   "skip"       → models/schemas/db: never become participants
#   "db_trigger" → db/database files: cause DB node to be added instead
#   "actor"      → services/routers/etc: become real participants
_ROLE_MAP: dict[str, tuple[str, str]] = {
    # folders whose files are actors (become participants)
    "routers":     ("actor", "dispatch to handler"),
    "routes":      ("actor", "dispatch to handler"),
    "controllers": ("actor", "handle request"),
    "services":    ("actor", "execute business logic"),
    "service":     ("actor", "execute business logic"),
    "utils":       ("actor", "utility call"),
    "helpers":     ("actor", "utility call"),
    "middleware":   ("actor", "middleware processing"),
    "views":       ("actor", "dispatch to handler"),
    "api":         ("actor", "dispatch to handler"),
    # folders whose files are NOT actors
    "models":      ("skip", ""),
    "schemas":     ("skip", ""),
    "db":          ("db_trigger", "query database"),
    "database":    ("db_trigger", "query database"),
    "migrations":  ("skip", ""),
    "config":      ("skip", ""),
    "settings":    ("skip", ""),
}


def _classify_file(file_path: str) -> tuple[str, str]:
    """Classify a file → (role, label).

    role is one of: "actor", "skip", "db_trigger", "unknown".
    """
    parts = file_path.replace("\\", "/").split("/")
    for part in reversed(parts[:-1]):
        entry = _ROLE_MAP.get(part.lower())
        if entry:
            return entry
    return ("unknown", "process request")


def _module_name(file_path: str) -> str:
    """Extract a short module name from a file path."""
    parts = file_path.replace("\\", "/").split("/")
    fname = parts[-1] if parts else file_path
    for ext in (".py", ".ts", ".js", ".tsx", ".jsx"):
        if fname.endswith(ext):
            fname = fname[: -len(ext)]
            break
    return fname


def generate_sequence_for_route(
    scan: Scan,
    graph_nodes: list[GraphNode],
    graph_edges: list[GraphEdge],
    route: dict,
) -> dict:
    """Generate a sequence diagram for a single API route.

    route = { method, path, file, component }
    """
    method = route.get("method", "GET").upper()
    path = route.get("path", "/")
    route_file = route.get("file", "")
    component = route.get("component", "unknown")

    # ── Step 1 & 2: Trace imports from route handler (max depth 2) ──
    import_graph = scan.import_graph or {}
    file_level: list[dict] = import_graph.get("file_level", [])

    # Build adjacency: file → list of files it imports
    imports_of: dict[str, list[str]] = {}
    for edge in file_level:
        src = edge.get("from", "")
        dst = edge.get("to", "")
        if src and dst:
            imports_of.setdefault(src, []).append(dst)

    # Depth 1: direct imports of route handler file
    depth1 = imports_of.get(route_file, [])
    # Depth 2: imports of depth-1 files (only "actor" depth-1 files)
    depth2: list[str] = []
    for f in depth1:
        role, _ = _classify_file(f)
        if role != "actor":
            continue
        for f2 in imports_of.get(f, []):
            if f2 != route_file and f2 not in depth1:
                depth2.append(f2)

    # Deduplicate preserving order
    all_imports_ordered: list[str] = []
    seen_files: set[str] = set()
    for f in depth1 + depth2:
        if f not in seen_files:
            seen_files.add(f)
            all_imports_ordered.append(f)

    # ── Classify every import ───────────────────────────────────────
    actor_files: list[tuple[str, str]] = []   # (file, label)
    needs_db = False                           # whether to add DB participant

    for f in all_imports_ordered:
        role, label = _classify_file(f)
        if role == "actor":
            actor_files.append((f, label))
        elif role == "db_trigger" or role == "skip":
            # models/schemas/db imports → trigger DB participant, not a module
            needs_db = True
        elif role == "unknown":
            # Unknown folder — only include if it's not __init__
            mod = _module_name(f)
            if mod != "__init__":
                actor_files.append((f, label))

    # ── Step 3: Build participants ──────────────────────────────────
    participants: list[dict] = []
    participant_ids: set[str] = set()
    order_counter = 0

    def add_p(pid: str, label: str, ptype: str) -> None:
        nonlocal order_counter
        if pid in participant_ids:
            return
        participant_ids.add(pid)
        participants.append({
            "id": pid,
            "label": label,
            "type": ptype,
            "order": order_counter,
        })
        order_counter += 1

    # Always start with Client
    add_p("client", "Client", "client")

    # The owning component
    comp_pid = f"comp_{component}"
    add_p(comp_pid, component, "component")

    # Categorize graph nodes for database/external lookup
    node_map: dict[str, GraphNode] = {n.id: n for n in graph_nodes}
    db_nodes = [n for n in graph_nodes if n.node_type == "database"]
    ext_nodes = [n for n in graph_nodes if n.node_type == "external"]

    # Build connected-target sets from graph edges
    comp_graph_node = None
    for n in graph_nodes:
        if n.node_type == "component" and n.label.lower() == component.lower():
            comp_graph_node = n
            break

    connected_db_ids: set[str] = set()
    connected_ext_ids: set[str] = set()
    if comp_graph_node:
        for e in graph_edges:
            if e.source_node_id == comp_graph_node.id:
                target = node_map.get(e.target_node_id)
                if target and target.node_type == "database":
                    connected_db_ids.add(target.id)
                elif target and target.node_type == "external":
                    connected_ext_ids.add(target.id)

    # Actor modules from import chain (skip route handler's own file)
    handler_mod = _module_name(route_file)
    actor_participants: list[tuple[str, str, str]] = []  # (pid, label, call_label)
    for f, call_label in actor_files:
        mod = _module_name(f)
        if mod == handler_mod or mod == "__init__":
            continue
        pid = f"mod_{mod}"
        if pid not in participant_ids:
            actor_participants.append((pid, mod, call_label))
            add_p(pid, mod, "component")

    # Database participants (add if imports touched db/models/schemas)
    db_participant_ids: list[str] = []
    if needs_db:
        for n in db_nodes:
            if n.id in connected_db_ids:
                add_p(n.id, n.label, "database")
                db_participant_ids.append(n.id)
                break  # one DB participant is enough

    # External participants
    ext_participant_ids: list[str] = []
    for n in ext_nodes:
        if n.id in connected_ext_ids:
            add_p(n.id, n.label, "external")
            ext_participant_ids.append(n.id)

    # Enforce max 4 participants (Client + component + up to 2 others)
    if len(participants) > 4:
        participants = participants[:4]
        participant_ids = {p["id"] for p in participants}
        for i, p in enumerate(participants):
            p["order"] = i

    # ── Step 4: Build messages ──────────────────────────────────────
    messages: list[dict] = []
    msg_order = 0

    def add_msg(from_p: str, to_p: str, label: str, msg_type: str, step: int) -> str:
        nonlocal msg_order
        if from_p not in participant_ids or to_p not in participant_ids:
            return ""
        if from_p == to_p:
            return ""
        mid = str(uuid.uuid4())
        messages.append({
            "id": mid,
            "from_participant": from_p,
            "to_participant": to_p,
            "label": label,
            "message_type": msg_type,
            "step": step,
            "order": msg_order,
        })
        msg_order += 1
        return mid

    step = 0

    # Message 1: Client → component
    add_msg("client", comp_pid, f"{method} {path}", "call", step)
    step += 1

    last_sender = comp_pid

    # Messages for each actor in chain
    for pid, _mod, call_label in actor_participants:
        if pid not in participant_ids:
            continue
        add_msg(last_sender, pid, call_label, "call", step)
        step += 1
        add_msg(pid, last_sender, "result", "return", step)
        step += 1

    # Database messages
    service_pid = last_sender
    for db_id in db_participant_ids:
        if db_id in participant_ids:
            add_msg(service_pid, db_id, "query database", "call", step)
            step += 1
            add_msg(db_id, service_pid, "rows / result", "return", step)
            step += 1

    # External messages
    for ext_id in ext_participant_ids:
        if ext_id in participant_ids:
            add_msg(service_pid, ext_id, "API call", "call", step)
            step += 1
            add_msg(ext_id, service_pid, "response", "return", step)
            step += 1

    # Final return to Client
    status_map = {"POST": "201", "DELETE": "204", "GET": "200", "PUT": "200", "PATCH": "200"}
    status = status_map.get(method, "200")
    if last_sender != comp_pid and last_sender in participant_ids:
        add_msg(last_sender, comp_pid, "data", "return", step)
        step += 1
    add_msg(comp_pid, "client", f"{status} response", "return", step)

    # Enforce max 20 messages
    messages = messages[:20]

    # ── Step 5: Build flows ─────────────────────────────────────────
    flow = {
        "flow_id": str(uuid.uuid4()),
        "flow_name": f"{method} {path}",
        "route_example": f"{method} {path}",
        "message_ids": [m["id"] for m in messages],
    }

    # Re-number orders on trimmed participants
    active_pids: set[str] = {"client"}
    for m in messages:
        active_pids.add(m["from_participant"])
        active_pids.add(m["to_participant"])
    final_participants = [p for p in participants if p["id"] in active_pids]
    for i, p in enumerate(final_participants):
        p["order"] = i

    has_db = any(p["type"] == "database" for p in final_participants)
    has_ext = any(p["type"] == "external" for p in final_participants)
    comp_count = sum(1 for p in final_participants if p["type"] == "component")

    return {
        "project_id": scan.project_id,
        "route_id": _route_id(method, path),
        "route_method": method,
        "route_path": path,
        "participants": final_participants,
        "messages": messages,
        "flows": [flow],
        "metadata": {
            "component_count": comp_count,
            "step_count": len(messages),
            "has_external_calls": has_ext,
            "has_database": has_db,
            "is_multi_component": comp_count > 1,
        },
    }
