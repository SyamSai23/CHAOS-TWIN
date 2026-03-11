"""Sequence diagram generator — derives runtime request flow from scan + graph data.

Per-route diagrams read from route_analyses table (analysis_data JSONB).
System-level diagrams still use Scan model columns and Graph nodes/edges.
No file-system access. No AI/LLM.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from app.models.scan import Scan
from app.models.graph_node import GraphNode
from app.models.graph_edge import GraphEdge
from app.models.route_analysis import RouteAnalysis


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

_SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".svg", ".css", ".html", ".gif", ".ico")


def _route_id(method: str, path: str) -> str:
    raw = f"{method.upper()}:{path}"
    return hashlib.md5(raw.encode()).hexdigest()


def _short_file(file_path: str) -> str:
    """Shorten a file path to its last 2 segments for participant label."""
    parts = file_path.replace("\\", "/").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else file_path


def _format_handler(handler: str) -> str:
    """Format handler name: 'SpotController.store' → 'SpotController.store()'."""
    if not handler:
        return "handler()"
    return handler if handler.endswith(")") else f"{handler}()"


def _mermaid_escape(text: str) -> str:
    """Escape special chars for Mermaid labels."""
    if not text:
        return ""
    return text.replace('"', "'").replace("\n", " ")


def generate_sequence_for_route(
    scan: Scan,
    graph_nodes: list[GraphNode],
    graph_edges: list[GraphEdge],
    route: dict,
    db: Optional[DBSession] = None,
) -> dict:
    """Generate a sequence diagram for a single API route.

    Reads analysis_data from route_analyses table when db session provided.
    Falls back to minimal diagram from route dict alone.
    """
    method = route.get("method", "GET").upper()
    path = route.get("path", "/")
    route_file = route.get("file", "")
    component = route.get("component", "unknown")
    rid = _route_id(method, path)

    # ── Fetch analysis_data from route_analyses table ───────────────
    analysis: dict = {}
    if db is not None:
        record = (
            db.query(RouteAnalysis)
            .filter(
                RouteAnalysis.project_id == scan.project_id,
                RouteAnalysis.route_id == rid,
            )
            .first()
        )
        if record and record.analysis_data:
            analysis = record.analysis_data

    phases: list[dict] = analysis.get("phases", [])
    error_paths: list[dict] = analysis.get("error_paths", [])
    handler_raw = analysis.get("handler_function", "")
    a_file = analysis.get("file", route_file)
    has_database = analysis.get("has_database", False)
    has_external = analysis.get("has_external", False)

    # ── Build participants ──────────────────────────────────────────
    participants: list[dict] = []
    participant_ids: set[str] = set()
    order_counter = 0

    def add_p(pid: str, label: str, ptype: str) -> None:
        nonlocal order_counter
        if pid in participant_ids:
            return
        # Filter static assets
        if any(label.lower().endswith(s) for s in _SKIP_SUFFIXES):
            return
        participant_ids.add(pid)
        participants.append({
            "id": pid, "label": label, "type": ptype, "order": order_counter,
        })
        order_counter += 1

    # 1. Client
    add_p("client", "Client", "client")
    # 2. Route file
    file_label = _short_file(a_file) if a_file else component
    add_p("route_file", file_label, "component")
    # 3. Handler
    handler_label = _format_handler(handler_raw)
    add_p("handler", handler_label, "component")
    # 4. Database — only if steps use db_read or db_write
    needs_db = has_database or any(
        s.get("type") in ("db_read", "db_write")
        for ph in phases for s in ph.get("steps", [])
    )
    if needs_db:
        add_p("database", "Database", "database")

    # ── Build messages from phases/steps ────────────────────────────
    messages: list[dict] = []
    msg_order = 0

    def add_msg(from_p: str, to_p: str, label: str, msg_type: str, step: int) -> str:
        nonlocal msg_order
        if from_p not in participant_ids or to_p not in participant_ids:
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
    # First arrow: Client → route_file
    add_msg("client", "route_file", f"{method} {path}", "call", step)
    step += 1

    # Walk phases in order
    for phase in phases:
        phase_id = phase.get("phase_id", "")
        steps = phase.get("steps", [])
        for s in steps:
            if s.get("is_error_path"):
                continue  # error paths handled separately via alt blocks
            stype = s.get("type", "")
            technical = s.get("technical", s.get("label", ""))
            if stype == "db_read":
                add_msg("handler", "database", f"SELECT {technical}", "call", step)
                step += 1
                add_msg("database", "handler", "rows", "return", step)
                step += 1
            elif stype == "db_write":
                verb = "INSERT" if "create" in technical.lower() else "UPDATE"
                add_msg("handler", "database", f"{verb} {technical}", "call", step)
                step += 1
                add_msg("database", "handler", "ok", "return", step)
                step += 1
            elif stype == "service":
                add_msg("handler", "handler", technical, "call", step)
                step += 1
            elif stype == "response":
                status_map = {"POST": "201", "DELETE": "204", "GET": "200",
                              "PUT": "200", "PATCH": "200"}
                status = status_map.get(method, "200")
                add_msg("handler", "client", f"{status} {technical}", "return", step)
                step += 1

    # If no response step was emitted, add a default return
    has_response_msg = any(
        m["to_participant"] == "client" and m["message_type"] == "return"
        for m in messages
    )
    if not has_response_msg:
        status_map = {"POST": "201", "DELETE": "204", "GET": "200",
                      "PUT": "200", "PATCH": "200"}
        status = status_map.get(method, "200")
        add_msg("handler", "route_file", "result", "return", step)
        step += 1
        add_msg("route_file", "client", f"{status} response", "return", step)
        step += 1

    # ── Build Mermaid string ────────────────────────────────────────
    mermaid_lines = ["sequenceDiagram"]
    for p in participants:
        mermaid_lines.append(f"    participant {p['id']} as {_mermaid_escape(p['label'])}")

    for m in messages:
        arrow = "->>" if m["message_type"] == "call" else "-->>"
        mermaid_lines.append(
            f"    {m['from_participant']}{arrow}{m['to_participant']}: {_mermaid_escape(m['label'])}"
        )

    # Alt blocks from error_paths
    if error_paths:
        ep = error_paths[0]
        condition = ep.get("trigger", "error")
        status_code = ep.get("status_code", 400)
        err_msg = ep.get("message", "error")
        mermaid_lines.append(f"    alt {_mermaid_escape(condition)}")
        mermaid_lines.append(
            f"        handler-->>client: {status_code} {_mermaid_escape(err_msg)}"
        )
        mermaid_lines.append("    else success")
        mermaid_lines.append("        handler-->>client: 200 OK")
        mermaid_lines.append("    end")
        for ep in error_paths[1:]:
            condition = ep.get("trigger", "error")
            status_code = ep.get("status_code", 400)
            err_msg = ep.get("message", "error")
            mermaid_lines.append(f"    alt {_mermaid_escape(condition)}")
            mermaid_lines.append(
                f"        handler-->>client: {status_code} {_mermaid_escape(err_msg)}"
            )
            mermaid_lines.append("    end")

    mermaid_string = "\n".join(mermaid_lines)

    # ── Build flows ─────────────────────────────────────────────────
    flow = {
        "flow_id": str(uuid.uuid4()),
        "flow_name": f"{method} {path}",
        "route_example": f"{method} {path}",
        "message_ids": [m["id"] for m in messages[:20]],
    }

    # Filter to active participants only
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
        "route_id": rid,
        "route_method": method,
        "route_path": path,
        "participants": final_participants,
        "messages": messages[:20],
        "flows": [flow],
        "mermaid_string": mermaid_string,
        "metadata": {
            "component_count": comp_count,
            "step_count": len(messages),
            "has_external_calls": has_ext,
            "has_database": has_db,
            "is_multi_component": comp_count > 1,
        },
    }
