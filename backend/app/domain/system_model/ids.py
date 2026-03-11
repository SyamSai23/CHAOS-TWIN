"""Deterministic ID helpers for the canonical system model.

ID strategy, v1:
- IDs are deterministic and prefixed by entity kind.
- Where the platform already has stable IDs, reuse them for compatibility.
  - components reuse make_component_key(root_path)
  - routes reuse make_route_id(method, path, file_path)
- Other IDs derive from canonical attributes that should remain stable across scans
  of the same source snapshot.
- IDs never use random UUIDs because the model is intended to support long-lived
  cross-feature linking, evidence references, graph derivation, and future chat lookups.
"""

from __future__ import annotations

import hashlib

from app.services.identity import make_component_key, make_route_id


def normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def normalize_path(path: str) -> str:
    normalized = (path or ".").replace("\\", "/").strip()
    if not normalized:
        return "."
    return normalized.strip("/") or "."


def stable_digest(*parts: str) -> str:
    payload = "::".join(normalize_text(part) for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


def prefixed_id(prefix: str, *parts: str) -> str:
    return f"{prefix}:{stable_digest(*parts)}"


def make_project_model_id(project_id: str) -> str:
    return f"project-model:v1:{project_id}"


def make_source_model_id(
    project_id: str,
    logical_root: str,
    source_type: str,
    snapshot_ref: str = "",
) -> str:
    return prefixed_id("source", project_id, logical_root, source_type, snapshot_ref)


def make_component_id(root_path: str) -> str:
    return f"component:{make_component_key(root_path)}"


def make_module_id(
    project_id: str,
    source_relative_path: str,
    symbol: str = "",
    symbol_kind: str = "",
) -> str:
    return prefixed_id(
        "module",
        project_id,
        normalize_path(source_relative_path),
        symbol,
        symbol_kind,
    )


def make_route_entity_id(method: str, path: str, file_path: str = "") -> str:
    return f"route:{make_route_id(method, path, file_path)}"


def make_service_id(
    project_id: str,
    service_name: str,
    owner_id: str = "",
    module_id: str = "",
    symbol: str = "",
    kind: str = "",
) -> str:
    return prefixed_id(
        "service",
        project_id,
        owner_id,
        module_id,
        service_name,
        symbol,
        kind,
    )


def make_data_store_id(source_id: str, store_name: str, store_type: str = "") -> str:
    return prefixed_id("datastore", source_id, store_name, store_type)


def make_external_integration_id(
    source_id: str,
    integration_name: str,
    integration_type: str = "",
) -> str:
    return prefixed_id("external", source_id, integration_name, integration_type)


def make_runtime_node_id(source_id: str, runtime_name: str) -> str:
    return prefixed_id("runtime", source_id, runtime_name)


def make_relation_id(
    source_id: str,
    relation_type: str,
    target_id: str,
    qualifier: str = "",
) -> str:
    return prefixed_id("relation", source_id, relation_type, target_id, qualifier)


def make_evidence_id(
    source_id: str,
    file_path: str,
    symbol: str = "",
    symbol_kind: str = "",
    line_start: int = 0,
    line_end: int = 0,
    column_start: int = 0,
    column_end: int = 0,
    detector_type: str = "",
    parser_type: str = "",
    rule_name: str = "",
    extraction_source: str = "",
    path_kind: str = "source_relative",
) -> str:
    return prefixed_id(
        "evidence",
        source_id,
        normalize_path(file_path),
        symbol,
        symbol_kind,
        str(line_start),
        str(line_end),
        str(column_start),
        str(column_end),
        detector_type,
        parser_type,
        rule_name,
        extraction_source,
        path_kind,
    )