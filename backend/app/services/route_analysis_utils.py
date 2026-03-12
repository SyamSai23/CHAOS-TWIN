"""Helpers for route analysis payloads."""

from __future__ import annotations

import hashlib
import json


def compute_route_analysis_signature(analysis: dict) -> str:
    """Return a stable signature for the parts that affect route rendering and sequences."""
    payload = {
        "method": analysis.get("method"),
        "path": analysis.get("path"),
        "file": analysis.get("file"),
        "component": analysis.get("component"),
        "handler_function": analysis.get("handler_function"),
        "parameters": analysis.get("parameters", []),
        "return_type": analysis.get("return_type"),
        "phases": analysis.get("phases", []),
        "error_paths": analysis.get("error_paths", []),
        "participants": analysis.get("participants", []),
        "has_database": analysis.get("has_database", False),
        "has_filesystem": analysis.get("has_filesystem", False),
        "has_external": analysis.get("has_external", False),
        "complexity": analysis.get("complexity"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def ensure_route_analysis_signature(analysis: dict) -> dict:
    """Inject a signature into a route analysis payload when missing."""
    if analysis.get("analysis_signature"):
        return analysis
    analysis["analysis_signature"] = compute_route_analysis_signature(analysis)
    return analysis


def build_route_analysis_from_route(route: dict) -> dict:
    """Build a route-analysis-shaped payload from deterministic request-flow data."""
    request_flow = route.get("request_flow") or {}
    stages = request_flow.get("stages") or []
    grouped_steps: dict[str, list[dict]] = {
        "entry": [],
        "service": [],
        "data": [],
        "response": [],
    }

    participants = [
        {"id": "client", "label": "Client", "type": "client"},
        {
            "id": "route_file",
            "label": route.get("file") or route.get("component") or "Route",
            "type": "component",
        },
    ]
    participant_ids = {participant["id"] for participant in participants}

    handler_name = route.get("handler_function") or route.get("handler")
    if handler_name:
        participants.append({"id": "handler", "label": handler_name, "type": "component"})
        participant_ids.add("handler")

    has_database = False
    has_external = False
    has_filesystem = False

    for stage in stages:
        stage_type = str(stage.get("stage_type") or "")
        label = stage.get("label") or stage_type.replace("_", " ")
        technical = stage.get("symbol_name") or label
        step = {
            "type": _phase_step_type(stage_type),
            "label": label,
            "technical": technical,
            "file": stage.get("file_path"),
            "line_number": stage.get("line_start"),
            "confidence": stage.get("confidence"),
            "selection_reason": stage.get("selection_reason"),
        }
        phase_name = _phase_name_for_stage(stage_type)
        grouped_steps.setdefault(phase_name, []).append(step)
        if stage_type in {"data_access", "repository"}:
            has_database = True
        if stage_type == "external":
            has_external = True
            if "external" not in participant_ids:
                participants.append({"id": "external", "label": "External API", "type": "external"})
                participant_ids.add("external")

    if has_database and "database" not in participant_ids:
        participants.append({"id": "database", "label": "Database", "type": "database"})

    phases = []
    phase_order = [
        ("entry", "request_entry"),
        ("service", "service_logic"),
        ("data", "data_access"),
        ("response", "response"),
    ]
    for phase_id, name in phase_order:
        steps = grouped_steps.get(phase_id) or []
        if not steps:
            continue
        phases.append(
            {
                "phase_id": phase_id,
                "name": name,
                "description": _describe_phase_name(name, steps),
                "steps": steps,
            }
        )

    total_steps = sum(len(phase.get("steps") or []) for phase in phases)
    if total_steps <= 4:
        complexity = "simple"
    elif total_steps >= 10:
        complexity = "complex"
    else:
        complexity = "moderate"

    analysis = {
        "route_id": request_flow.get("route_id"),
        "method": route.get("method"),
        "path": route.get("path"),
        "file": route.get("file"),
        "component": route.get("component"),
        "handler_function": handler_name,
        "parameters": route.get("parameters") or [],
        "return_type": None,
        "phases": phases,
        "error_paths": [],
        "participants": participants,
        "has_database": has_database,
        "has_filesystem": has_filesystem,
        "has_external": has_external,
        "complexity": complexity,
        "request_flow": request_flow,
    }
    return ensure_route_analysis_signature(analysis)


def _phase_name_for_stage(stage_type: str) -> str:
    if stage_type in {"dispatch", "middleware", "auth", "validation", "handler"}:
        return "entry"
    if stage_type in {"service", "external"}:
        return "service"
    if stage_type in {"repository", "data_access"}:
        return "data"
    if stage_type == "response":
        return "response"
    return "service"


def _phase_step_type(stage_type: str) -> str:
    if stage_type == "repository":
        return "db_read"
    if stage_type == "data_access":
        return "db_write"
    if stage_type == "external":
        return "external"
    if stage_type == "response":
        return "response"
    return "service"


def _describe_phase_name(name: str, steps: list[dict]) -> str:
    if name == "request_entry":
        return "Accepts the request and applies any route-level checks."
    if name == "service_logic":
        return "Executes handler and service logic." if steps else "Executes business logic."
    if name == "data_access":
        return "Performs persistence and integration work."
    if name == "response":
        return "Returns a response to the client."
    return f"Executes {name.replace('_', ' ')} steps."