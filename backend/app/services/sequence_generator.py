"""Sequence diagram generator — derives runtime request flow from scan + graph data.

Per-route diagrams read from route_analyses table (analysis_data JSONB).
System-level diagrams still use Scan model columns and Graph nodes/edges.
No file-system access. No AI/LLM.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.scan import Scan
from app.models.graph_node import GraphNode
from app.models.graph_edge import GraphEdge
from app.models.route_analysis import RouteAnalysis
from app.services.route_analysis_utils import build_route_analysis_from_route, ensure_route_analysis_signature
from app.services.identity import make_route_id


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

_DIRECT_PROVENANCE = {
    "route_detection",
    "route_metadata",
    "direct_handler",
    "direct_code_signal",
    "route_completion",
}

_KNOWN_PROVIDER_LABELS: dict[str, tuple[str, str]] = {
    "stripe": ("Stripe API", "external"),
    "sendgrid": ("SendGrid API", "external"),
    "twilio": ("Twilio API", "external"),
    "slack": ("Slack API", "external"),
    "openai": ("OpenAI API", "external"),
    "anthropic": ("Anthropic API", "external"),
    "billinggateway": ("Billing Gateway", "external"),
    "billing_gateway": ("Billing Gateway", "external"),
    "s3": ("S3 API", "external"),
    "aws": ("AWS API", "external"),
    "redis": ("Redis Cache", "database"),
    "cache": ("Cache", "database"),
    "postgres": ("Database", "database"),
    "postgresql": ("Database", "database"),
    "mysql": ("Database", "database"),
    "mongo": ("Database", "database"),
    "mongodb": ("Database", "database"),
    "database": ("Database", "database"),
    "rabbitmq": ("Message Queue", "queue"),
    "kafka": ("Message Queue", "queue"),
    "celery": ("Task Queue", "queue"),
}


def _route_id(method: str, path: str) -> str:
    return make_route_id(method, path)


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
    rid = make_route_id(method, path, route_file)

    resolved_route = _find_scan_route(scan, rid) or {}
    effective_route = {
        **resolved_route,
        **route,
        "method": method,
        "path": path,
        "file": route_file,
        "component": route.get("component") or resolved_route.get("component") or "unknown",
    }

    analysis: dict[str, Any] = {}
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
            analysis = ensure_route_analysis_signature(dict(record.analysis_data))

    request_flow = _preferred_request_flow(effective_route, analysis)
    sequence_source = _sequence_source_for_route(effective_route, analysis, request_flow)
    warnings: list[str] = []

    if request_flow and not analysis:
        flow_route = {**effective_route, "request_flow": request_flow}
        analysis = build_route_analysis_from_route(flow_route)

    if request_flow:
        return _generate_request_flow_sequence(
            scan=scan,
            route=effective_route,
            request_flow=request_flow,
            analysis=analysis,
            sequence_source=sequence_source,
            warnings=warnings,
        )

    if analysis:
        warnings.append("Sequence fell back to legacy analysis because deterministic request_flow was unavailable.")
        return _generate_fallback_route_sequence(
            scan=scan,
            route=effective_route,
            analysis=analysis,
            sequence_source="route_analysis_fallback",
            warnings=warnings,
        )

    warnings.append("Sequence fell back to minimal route metadata because no deterministic request_flow or stored analysis was available.")
    return _generate_fallback_route_sequence(
        scan=scan,
        route=effective_route,
        analysis={},
        sequence_source="minimal_fallback",
        warnings=warnings,
    )


def _find_scan_route(scan: Scan, route_id: str) -> Optional[dict]:
    for route in scan.routes or []:
        if not isinstance(route, dict):
            continue
        method = str(route.get("method") or "GET").upper()
        path = str(route.get("path") or "/")
        file_path = str(route.get("file") or "")
        if make_route_id(method, path, file_path) == route_id:
            return dict(route)
    return None


def _preferred_request_flow(route: dict, analysis: dict) -> Optional[dict]:
    candidates = [
        route.get("request_flow"),
        analysis.get("request_flow"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("stages"):
            return dict(candidate)
    return None


def _sequence_source_for_route(route: dict, analysis: dict, request_flow: Optional[dict]) -> str:
    if request_flow and route.get("request_flow"):
        return "request_flow"
    if request_flow and analysis.get("request_flow"):
        return "analysis_request_flow"
    if analysis:
        return "route_analysis_fallback"
    return "minimal_fallback"


def _generate_request_flow_sequence(
    scan: Scan,
    route: dict,
    request_flow: dict,
    analysis: dict,
    sequence_source: str,
    warnings: list[str],
) -> dict:
    method = str(route.get("method") or "GET").upper()
    path = str(route.get("path") or "/")
    route_file = str(route.get("file") or "")
    rid = make_route_id(method, path, route_file)
    error_paths = list(analysis.get("error_paths") or [])
    analysis_signature = analysis.get("analysis_signature")

    participants: list[dict[str, Any]] = []
    participant_ids: set[str] = set()
    participant_meta: dict[str, dict[str, Any]] = {}
    participant_order = 0

    def add_participant(pid: str, label: str, ptype: str, metadata: Optional[dict[str, Any]] = None) -> str:
        nonlocal participant_order
        if pid in participant_ids:
            return pid
        if any(label.lower().endswith(suffix) for suffix in _SKIP_SUFFIXES):
            return pid
        participant_ids.add(pid)
        participant_meta[pid] = dict(metadata or {})
        participants.append({
            "id": pid,
            "label": label,
            "type": ptype,
            "order": participant_order,
            "metadata": participant_meta[pid],
        })
        participant_order += 1
        return pid

    add_participant("client", "Client", "client")

    entry_stage = _first_stage(request_flow, {"dispatch", "handler"})
    entry_label = _entry_participant_label(route, entry_stage)
    entry_anchor = _stage_anchor(entry_stage) if entry_stage else _route_anchor(route)
    entry_id = add_participant(
        "entry",
        entry_label,
        "component",
        metadata={
            "role": "entry",
            **entry_anchor,
        },
    )

    messages: list[dict[str, Any]] = []
    message_order = 0

    def add_message(
        from_p: str,
        to_p: str,
        label: str,
        message_type: str,
        visual_step: int,
        stage: Optional[dict] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> str:
        nonlocal message_order
        if from_p not in participant_ids or to_p not in participant_ids:
            return ""
        stage_anchor = _stage_anchor(stage) if stage else {}
        message = {
            "id": str(uuid.uuid4()),
            "from_participant": from_p,
            "to_participant": to_p,
            "label": label,
            "message_type": message_type,
            "step": visual_step,
            "order": message_order,
            "sequence_source": sequence_source,
            "source_stage_step": stage.get("step") if isinstance(stage, dict) else None,
            "source_stage_type": stage.get("stage_type") if isinstance(stage, dict) else None,
            "file_path": stage_anchor.get("file_path"),
            "symbol_name": stage_anchor.get("symbol_name"),
            "class_name": stage_anchor.get("class_name"),
            "line_start": stage_anchor.get("line_start"),
            "line_end": stage_anchor.get("line_end"),
            "confidence": stage.get("confidence") if isinstance(stage, dict) else None,
            "is_inferred": _stage_is_inferred(stage),
            "provenance": stage.get("provenance") if isinstance(stage, dict) else None,
            "code_anchor": stage_anchor or None,
            "best_target": stage_anchor or None,
        }
        if extra:
            message.update(extra)
        messages.append(message)
        message_order += 1
        return message["id"]

    stages = [stage for stage in request_flow.get("stages") or [] if isinstance(stage, dict)]
    stage_counter = 0
    dispatch_emitted = False
    response_emitted = False
    actor_stack: list[str] = [entry_id]
    participant_stack: list[dict[str, Any]] = [{"id": entry_id, "type": "entry", "label": entry_label}]

    for stage in stages:
        stage_type = str(stage.get("stage_type") or "")
        if stage_type == "dispatch":
            if not dispatch_emitted:
                add_message("client", entry_id, _dispatch_message_label(route), "call", stage_counter, stage=stage)
                stage_counter += 1
                dispatch_emitted = True
            continue

        if not dispatch_emitted:
            add_message("client", entry_id, _dispatch_message_label(route), "call", stage_counter, stage=entry_stage)
            stage_counter += 1
            dispatch_emitted = True

        if stage_type in {"middleware", "auth", "validation", "handler"}:
            actor_id = actor_stack[-1]
            add_message(actor_id, actor_id, _stage_message_label(stage, route), "call", stage_counter, stage=stage)
            stage_counter += 1
            continue

        if stage_type in {"service", "repository"}:
            participant = _participant_for_stage(stage_type, stage)
            target_id = add_participant(
                participant["id"],
                participant["label"],
                participant["type"],
                metadata=participant["metadata"],
            )
            caller_id = actor_stack[-1]
            if target_id == caller_id:
                add_message(caller_id, target_id, _stage_message_label(stage, route), "call", stage_counter, stage=stage)
            else:
                add_message(caller_id, target_id, _stage_message_label(stage, route), "call", stage_counter, stage=stage)
                actor_stack.append(target_id)
                participant_stack.append(participant)
            stage_counter += 1
            continue

        if stage_type == "data_access":
            participant = _participant_for_stage("data_access", stage)
            target_id = add_participant(
                participant["id"],
                participant["label"],
                participant["type"],
                metadata=participant["metadata"],
            )
            caller_id = actor_stack[-1]
            add_message(caller_id, target_id, _stage_message_label(stage, route), "call", stage_counter, stage=stage)
            stage_counter += 1
            add_message(target_id, caller_id, _return_message_label(stage, participant["label"]), "return", stage_counter, stage=stage)
            stage_counter += 1
            continue

        if stage_type == "external":
            participant = _participant_for_stage("external", stage)
            target_id = add_participant(
                participant["id"],
                participant["label"],
                participant["type"],
                metadata=participant["metadata"],
            )
            caller_id = actor_stack[-1]
            add_message(caller_id, target_id, _stage_message_label(stage, route), "call", stage_counter, stage=stage)
            stage_counter += 1
            add_message(target_id, caller_id, _return_message_label(stage, participant["label"]), "return", stage_counter, stage=stage)
            stage_counter += 1
            continue

        if stage_type == "response":
            while len(actor_stack) > 1:
                callee = actor_stack.pop()
                callee_meta = participant_stack.pop()
                caller = actor_stack[-1]
                add_message(callee, caller, _internal_return_label(callee_meta), "return", stage_counter, stage=stage)
                stage_counter += 1
            add_message(entry_id, "client", _response_message_label(stage, route), "return", stage_counter, stage=stage)
            stage_counter += 1
            response_emitted = True
            continue

        actor_id = actor_stack[-1]
        add_message(actor_id, actor_id, _stage_message_label(stage, route), "call", stage_counter, stage=stage)
        stage_counter += 1

    if not dispatch_emitted:
        add_message("client", entry_id, _dispatch_message_label(route), "call", stage_counter, stage=entry_stage)
        stage_counter += 1

    if not response_emitted:
        while len(actor_stack) > 1:
            callee = actor_stack.pop()
            callee_meta = participant_stack.pop()
            caller = actor_stack[-1]
            add_message(callee, caller, _internal_return_label(callee_meta), "return", stage_counter, stage=stages[-1] if stages else None)
            stage_counter += 1
        add_message(entry_id, "client", _default_response_label(route), "return", stage_counter, stage=stages[-1] if stages else None)
        stage_counter += 1
        if not any((request_flow.get("summary") or {}).values()):
            warnings.append("Request flow was present but sparse, so the generated sequence remains intentionally minimal.")

    degraded = sequence_source != "request_flow" or any(_stage_is_inferred(stage) for stage in stages)
    if degraded and not warnings:
        warnings.append("Sequence includes inferred or fallback-backed steps and intentionally omits unsupported detail.")

    return _finalize_route_sequence(
        scan=scan,
        route=route,
        participants=participants,
        messages=messages,
        error_paths=error_paths,
        analysis_signature=analysis_signature,
        sequence_source=sequence_source,
        request_flow=request_flow,
        warnings=warnings,
        degraded=degraded,
    )


def _generate_fallback_route_sequence(
    scan: Scan,
    route: dict,
    analysis: dict,
    sequence_source: str,
    warnings: list[str],
) -> dict:
    method = str(route.get("method") or "GET").upper()
    path = str(route.get("path") or "/")
    route_file = str(route.get("file") or "")
    handler_raw = analysis.get("handler_function", route.get("handler_function", ""))
    a_file = str(analysis.get("file") or route_file)
    component = str(route.get("component") or "unknown")
    phases: list[dict] = list(analysis.get("phases") or [])
    error_paths: list[dict] = list(analysis.get("error_paths") or [])
    has_database = bool(analysis.get("has_database", False))
    has_external = bool(analysis.get("has_external", False))
    analysis_signature = analysis.get("analysis_signature")

    participants: list[dict[str, Any]] = []
    participant_ids: set[str] = set()
    order_counter = 0

    def add_p(pid: str, label: str, ptype: str) -> None:
        nonlocal order_counter
        if pid in participant_ids:
            return
        if any(label.lower().endswith(suffix) for suffix in _SKIP_SUFFIXES):
            return
        participant_ids.add(pid)
        participants.append({
            "id": pid,
            "label": label,
            "type": ptype,
            "order": order_counter,
            "metadata": {"role": ptype, "sequence_source": sequence_source},
        })
        order_counter += 1

    add_p("client", "Client", "client")
    file_label = _short_file(a_file) if a_file else component
    add_p("route_file", file_label, "component")
    handler_label = _format_handler(handler_raw)
    add_p("handler", handler_label, "component")
    needs_db = has_database or any(
        step.get("type") in ("db_read", "db_write")
        for phase in phases for step in phase.get("steps", [])
    )
    if needs_db:
        add_p("database", "Database", "database")
    if has_external:
        add_p("external", "External API", "external")

    messages: list[dict[str, Any]] = []
    msg_order = 0

    def add_msg(from_p: str, to_p: str, label: str, msg_type: str, step: int, extra: Optional[dict[str, Any]] = None) -> str:
        nonlocal msg_order
        if from_p not in participant_ids or to_p not in participant_ids:
            return ""
        message = {
            "id": str(uuid.uuid4()),
            "from_participant": from_p,
            "to_participant": to_p,
            "label": label,
            "message_type": msg_type,
            "step": step,
            "order": msg_order,
            "sequence_source": sequence_source,
            "source_stage_step": None,
            "source_stage_type": None,
            "file_path": a_file,
            "symbol_name": handler_raw or None,
            "class_name": None,
            "line_start": None,
            "line_end": None,
            "confidence": None,
            "is_inferred": True,
            "provenance": sequence_source,
            "code_anchor": {"file_path": a_file, "symbol_name": handler_raw or None} if a_file else None,
            "best_target": {"file_path": a_file, "symbol_name": handler_raw or None} if a_file else None,
        }
        if extra:
            message.update(extra)
        messages.append(message)
        msg_order += 1
        return message["id"]

    step = 0
    add_msg("client", "route_file", _dispatch_message_label(route), "call", step)
    step += 1

    for phase in phases:
        for phase_step in phase.get("steps", []):
            if phase_step.get("is_error_path"):
                continue
            step_type = phase_step.get("type", "")
            technical = phase_step.get("technical", phase_step.get("label", ""))
            if step_type == "db_read":
                add_msg("handler", "database", f"Query {_humanize_identifier(technical) or 'database'}", "call", step)
                step += 1
                add_msg("database", "handler", "rows", "return", step)
                step += 1
            elif step_type == "db_write":
                add_msg("handler", "database", "Persist changes", "call", step)
                step += 1
                add_msg("database", "handler", "ok", "return", step)
                step += 1
            elif step_type == "service":
                add_msg("handler", "handler", _humanize_identifier(technical) or "Run service logic", "call", step)
                step += 1
            elif step_type == "external":
                add_msg("handler", "external", _humanize_identifier(technical) or "Call external API", "call", step)
                step += 1
                add_msg("external", "handler", "response", "return", step)
                step += 1
            elif step_type == "response":
                add_msg("handler", "client", _default_response_label(route), "return", step)
                step += 1

    if not any(message["to_participant"] == "client" and message["message_type"] == "return" for message in messages):
        add_msg("handler", "route_file", "result", "return", step)
        step += 1
        add_msg("route_file", "client", _default_response_label(route), "return", step)

    return _finalize_route_sequence(
        scan=scan,
        route=route,
        participants=participants,
        messages=messages,
        error_paths=error_paths,
        analysis_signature=analysis_signature,
        sequence_source=sequence_source,
        request_flow=None,
        warnings=warnings,
        degraded=True,
    )


def _finalize_route_sequence(
    scan: Scan,
    route: dict,
    participants: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    error_paths: list[dict],
    analysis_signature: Optional[str],
    sequence_source: str,
    request_flow: Optional[dict],
    warnings: list[str],
    degraded: bool,
) -> dict:
    method = str(route.get("method") or "GET").upper()
    path = str(route.get("path") or "/")
    route_file = str(route.get("file") or "")
    rid = make_route_id(method, path, route_file)

    active_pids: set[str] = {"client"}
    for message in messages:
        active_pids.add(message["from_participant"])
        active_pids.add(message["to_participant"])

    final_participants = [participant for participant in participants if participant["id"] in active_pids]
    for index, participant in enumerate(final_participants):
        participant["order"] = index

    mermaid_string = _build_route_mermaid(final_participants, messages[:20], error_paths)
    flow = {
        "flow_id": str(uuid.uuid4()),
        "flow_name": f"{method} {path}",
        "route_example": f"{method} {path}",
        "message_ids": [message["id"] for message in messages[:20]],
    }

    has_db = any(participant["type"] == "database" for participant in final_participants)
    has_ext = any(participant["type"] == "external" for participant in final_participants)
    comp_count = sum(1 for participant in final_participants if participant["type"] == "component")

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
            "analysis_signature": analysis_signature,
            "sequence_source": sequence_source,
            "request_flow_stage_count": len((request_flow or {}).get("stages") or []),
            "request_flow_confidence": (request_flow or {}).get("confidence"),
            "degraded": degraded,
            "warnings": warnings,
        },
    }


def _build_route_mermaid(participants: list[dict[str, Any]], messages: list[dict[str, Any]], error_paths: list[dict]) -> str:
    mermaid_lines = ["sequenceDiagram"]
    for participant in participants:
        mermaid_lines.append(f"    participant {participant['id']} as {_mermaid_escape(participant['label'])}")

    for message in messages:
        arrow = "->>" if message["message_type"] == "call" else "-->>"
        if message["message_type"] == "async":
            arrow = "-)"
        mermaid_lines.append(
            f"    {message['from_participant']}{arrow}{message['to_participant']}: {_mermaid_escape(message['label'])}"
        )

    if error_paths:
        primary_responder = next((participant["id"] for participant in participants if participant["id"] != "client"), "entry")
        for index, error_path in enumerate(error_paths):
            condition = error_path.get("trigger", "error")
            status_code = error_path.get("status_code", 400)
            error_message = error_path.get("message", "error")
            mermaid_lines.append(f"    alt {_mermaid_escape(condition)}")
            mermaid_lines.append(
                f"        {primary_responder}-->>client: {status_code} {_mermaid_escape(error_message)}"
            )
            if index == 0:
                mermaid_lines.append("    else success")
                mermaid_lines.append(f"        {primary_responder}-->>client: {_default_success_text(status_code)}")
            mermaid_lines.append("    end")
    return "\n".join(mermaid_lines)


def _first_stage(request_flow: dict, stage_types: set[str]) -> Optional[dict]:
    for stage in request_flow.get("stages") or []:
        if isinstance(stage, dict) and stage.get("stage_type") in stage_types:
            return stage
    return None


def _entry_participant_label(route: dict, stage: Optional[dict]) -> str:
    controller_name = str((stage or {}).get("class_name") or route.get("controller_name") or "")
    handler_name = str((stage or {}).get("symbol_name") or route.get("handler_function") or route.get("handler") or "")
    if controller_name and handler_name:
        return f"{controller_name}.{handler_name}()"
    if handler_name:
        return f"{handler_name}()"
    file_path = str((stage or {}).get("file_path") or route.get("file") or route.get("component") or "Route")
    return _short_file(file_path)


def _participant_for_stage(role: str, stage: dict) -> dict[str, Any]:
    anchor = _stage_anchor(stage)
    label, participant_type = _participant_label_and_type(role, stage, anchor)
    pid_seed = "|".join([
        role,
        str(anchor.get("file_path") or ""),
        str(anchor.get("class_name") or ""),
        str(anchor.get("symbol_name") or ""),
        label,
    ])
    participant_id = f"{participant_type}_{hashlib.md5(pid_seed.encode('utf-8')).hexdigest()[:10]}"
    return {
        "id": participant_id,
        "label": label,
        "type": participant_type,
        "metadata": {
            "role": role,
            **anchor,
        },
    }


def _participant_label_and_type(role: str, stage: dict, anchor: dict[str, Any]) -> tuple[str, str]:
    text = " ".join(
        value for value in [
            str(anchor.get("class_name") or ""),
            str(anchor.get("symbol_name") or ""),
            str(anchor.get("file_path") or ""),
            str(stage.get("label") or ""),
        ] if value
    ).lower()
    for token, (label, participant_type) in _KNOWN_PROVIDER_LABELS.items():
        if token in text:
            if role == "data_access" and participant_type == "external":
                continue
            return label, participant_type

    if role == "service":
        return _preferred_component_label(stage, anchor, fallback="Service"), "component"
    if role == "repository":
        return _preferred_component_label(stage, anchor, fallback="Repository"), "component"
    if role == "external":
        return _preferred_external_label(stage, anchor), "external"
    if role == "data_access":
        return _preferred_datastore_label(stage, anchor)
    return _preferred_component_label(stage, anchor, fallback="Component"), "component"


def _preferred_component_label(stage: dict, anchor: dict[str, Any], fallback: str) -> str:
    class_name = str(anchor.get("class_name") or "")
    if class_name:
        return _titleize_identifier(class_name)
    file_path = str(anchor.get("file_path") or "")
    if file_path:
        stem = file_path.replace("\\", "/").split("/")[-1].split(".")[0]
        if stem and stem.lower() not in {"index", "main", "app"}:
            return _titleize_identifier(stem)
    symbol_name = str(anchor.get("symbol_name") or "")
    if symbol_name:
        return _titleize_identifier(symbol_name)
    label = str(stage.get("label") or "")
    human = _titleize_identifier(label)
    return human or fallback


def _preferred_external_label(stage: dict, anchor: dict[str, Any]) -> str:
    label = _preferred_component_label(stage, anchor, fallback="External API")
    if label.lower().endswith(" api"):
        return label
    if any(token in label.lower() for token in {"gateway", "service", "provider", "client"}):
        return label
    return f"{label} API"


def _preferred_datastore_label(stage: dict, anchor: dict[str, Any]) -> tuple[str, str]:
    text = " ".join(
        value for value in [
            str(anchor.get("class_name") or ""),
            str(anchor.get("symbol_name") or ""),
            str(anchor.get("file_path") or ""),
            str(stage.get("label") or ""),
        ] if value
    ).lower()
    if any(token in text for token in {"redis", "cache"}):
        return "Redis Cache" if "redis" in text else "Cache", "database"
    if any(token in text for token in {"rabbitmq", "kafka", "queue", "celery"}):
        return "Message Queue", "queue"
    return "Database", "database"


def _dispatch_message_label(route: dict) -> str:
    method = str(route.get("method") or "GET").upper()
    path = str(route.get("path") or "/")
    return f"{method} {path}"


def _stage_message_label(stage: dict, route: dict) -> str:
    stage_type = str(stage.get("stage_type") or "")
    text = _stage_text(stage)
    text_blob = _stage_text_blob(stage)
    if stage_type == "middleware":
        hint = _first_hint(stage)
        return f"run {hint}" if hint else "run middleware"
    if stage_type == "auth":
        if any(fragment in text_blob for fragment in {"jwt", "token", "bearer", "auth", "guard", "session"}):
            return "verify auth token"
        if any(token in text for token in {"role", "permission", "acl", "scope"}):
            return "check permissions"
        return "authorize request"
    if stage_type == "validation":
        if any(token in text for token in {"query", "param", "path"}):
            return "validate request params"
        return "validate request payload"
    if stage_type == "handler":
        symbol_name = str(stage.get("symbol_name") or "")
        if symbol_name:
            return f"invoke {_humanize_identifier(symbol_name)} handler"
        return "invoke route handler"
    if stage_type == "service":
        action = _humanize_stage_action(stage)
        return action or "run service logic"
    if stage_type == "repository":
        action = _humanize_stage_action(stage)
        return action or "use repository"
    if stage_type == "data_access":
        datastore_label, _ = _preferred_datastore_label(stage, _stage_anchor(stage))
        if datastore_label.lower().endswith("cache"):
            if _looks_write_like(stage, route):
                return "update cache entry"
            return "read cache entry"
        if _looks_write_like(stage, route):
            return "persist changes"
        return "query database"
    if stage_type == "external":
        external_label = _preferred_external_label(stage, _stage_anchor(stage))
        if external_label.lower().endswith(" api"):
            return f"call {external_label}"
        return f"call {external_label}"
    if stage_type == "response":
        return _response_message_label(stage, route)
    human = _humanize_identifier(str(stage.get("label") or ""))
    return human or stage_type.replace("_", " ")


def _return_message_label(stage: dict, participant_label: str) -> str:
    stage_type = str(stage.get("stage_type") or "")
    if stage_type == "external":
        if participant_label.lower().endswith(" api"):
            return "provider response"
        return f"{participant_label.lower()} result"
    if stage_type == "data_access":
        if participant_label.lower().endswith("cache"):
            return "cache result"
        if _looks_write_like(stage, {}):
            return "write complete"
        return "query result"
    return "result"


def _internal_return_label(participant: dict[str, Any]) -> str:
    role = str(participant.get("metadata", {}).get("role") or participant.get("type") or "component")
    if role == "repository":
        return "repository result"
    if role == "service":
        return "service result"
    return "result"


def _response_message_label(stage: dict, route: dict) -> str:
    status_map = {"POST": "201", "DELETE": "204", "GET": "200", "PUT": "200", "PATCH": "200"}
    method = str(route.get("method") or "GET").upper()
    status = status_map.get(method, "200")
    label = _humanize_identifier(str(stage.get("label") or ""))
    if label and "response" not in label:
        return f"return {status} {label}"
    return f"return {status} response"


def _default_response_label(route: dict) -> str:
    return _response_message_label({"label": "response"}, route)


def _default_success_text(status_code: int) -> str:
    if status_code == 201:
        return "201 Created"
    if status_code == 204:
        return "204 No Content"
    return "200 OK"


def _stage_anchor(stage: Optional[dict]) -> dict[str, Any]:
    if not isinstance(stage, dict):
        return {}
    code_anchor = dict(stage.get("code_anchor") or {})
    evidence = dict(stage.get("evidence") or {})
    return {
        "file_path": stage.get("file_path") or code_anchor.get("file_path") or evidence.get("file_path"),
        "symbol_name": stage.get("symbol_name") or code_anchor.get("symbol_name") or evidence.get("symbol_name"),
        "class_name": stage.get("class_name") or code_anchor.get("class_name") or evidence.get("class_name"),
        "line_start": stage.get("line_start") or code_anchor.get("line_start") or evidence.get("line_start"),
        "line_end": stage.get("line_end") or code_anchor.get("line_end") or evidence.get("line_end"),
        "anchor_kind": stage.get("anchor_kind") or code_anchor.get("anchor_kind") or evidence.get("anchor_kind"),
        "target_rank": stage.get("target_rank") or code_anchor.get("target_rank") or evidence.get("target_rank"),
        "selection_reason": stage.get("selection_reason") or code_anchor.get("selection_reason") or evidence.get("selection_reason"),
    }


def _route_anchor(route: dict) -> dict[str, Any]:
    best_target = dict(route.get("best_target") or route.get("evidence") or {})
    return {
        "file_path": best_target.get("file_path") or route.get("file"),
        "symbol_name": best_target.get("symbol_name") or route.get("handler_function") or route.get("handler"),
        "class_name": best_target.get("class_name") or route.get("controller_name"),
        "line_start": best_target.get("line_start") or route.get("line_start"),
        "line_end": best_target.get("line_end") or route.get("line_end"),
        "anchor_kind": best_target.get("anchor_kind"),
        "target_rank": best_target.get("target_rank"),
        "selection_reason": best_target.get("selection_reason"),
    }


def _stage_is_inferred(stage: Optional[dict]) -> bool:
    if not isinstance(stage, dict):
        return False
    if stage.get("is_inferred") is not None:
        return bool(stage.get("is_inferred"))
    provenance = str(stage.get("provenance") or "")
    return bool(provenance) and provenance not in _DIRECT_PROVENANCE


def _stage_text(stage: dict) -> set[str]:
    values = [
        str(stage.get("label") or ""),
        str(stage.get("symbol_name") or ""),
        str(stage.get("class_name") or ""),
        str(stage.get("file_path") or ""),
        " ".join(str(hint) for hint in stage.get("hints") or []),
    ]
    return {token.lower() for token in _humanize_identifier(" ".join(values)).split() if token}


def _stage_text_blob(stage: dict) -> str:
    values = [
        str(stage.get("label") or ""),
        str(stage.get("symbol_name") or ""),
        str(stage.get("class_name") or ""),
        str(stage.get("file_path") or ""),
        " ".join(str(hint) for hint in stage.get("hints") or []),
        str(stage.get("selection_reason") or ""),
    ]
    return _humanize_identifier(" ".join(values)).lower()


def _first_hint(stage: dict) -> str:
    hints = [hint for hint in stage.get("hints") or [] if hint]
    if not hints:
        return ""
    return _humanize_identifier(str(hints[0]))


def _humanize_stage_action(stage: dict) -> str:
    symbol_name = str(stage.get("symbol_name") or "")
    label = str(stage.get("label") or "")
    if symbol_name:
        return _normalize_action_phrase(_humanize_identifier(symbol_name))
    if label:
        return _normalize_action_phrase(_humanize_identifier(label))
    return ""


def _normalize_action_phrase(text: str) -> str:
    phrase = text.strip().lower()
    for prefix in ("run ", "call ", "invoke ", "handle ", "perform ", "dispatch "):
        if phrase.startswith(prefix):
            phrase = phrase[len(prefix):]
            break
    return phrase


def _looks_write_like(stage: dict, route: dict) -> bool:
    text = _humanize_identifier(" ".join([
        str(stage.get("label") or ""),
        str(stage.get("symbol_name") or ""),
        str(stage.get("class_name") or ""),
    ])).lower()
    if any(token in text for token in {"save", "create", "insert", "update", "delete", "persist", "write", "commit"}):
        return True
    method = str(route.get("method") or "GET").upper()
    return method in {"POST", "PUT", "PATCH", "DELETE"}


def _humanize_identifier(value: str) -> str:
    if not value:
        return ""
    text = value.replace("::", ".")
    text = text.split("/")[-1]
    text = text.split(".")[0] if text.count(".") == 1 and not text.endswith("()") else text
    text = text.replace("_", " ").replace("-", " ")
    normalized: list[str] = []
    for char in text:
        if normalized and char.isupper() and normalized[-1].islower():
            normalized.append(" ")
        normalized.append(char)
    return " ".join("".join(normalized).split())


def _titleize_identifier(value: str) -> str:
    return " ".join(word.capitalize() for word in _humanize_identifier(value).split())
