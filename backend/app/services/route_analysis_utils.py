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