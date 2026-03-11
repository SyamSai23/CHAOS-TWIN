"""Interpret persisted graph rows for semantic-aware simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class InterpretedNode:
    id: str
    label: str
    node_type: str
    data: dict
    canonical_entity_id: Optional[str] = None
    canonical_entity_kind: Optional[str] = None
    confidence_score: Optional[float] = None
    confidence_label: Optional[str] = None
    graph_source: str = "raw_scan_fallback"


@dataclass
class InterpretedEdge:
    source_node_id: str
    target_node_id: str
    edge_type: str
    data: dict
    canonical_relation_id: Optional[str] = None
    canonical_relation_type: Optional[str] = None
    confidence_score: Optional[float] = None
    confidence_label: Optional[str] = None
    inference_stage: Optional[str] = None
    graph_source: str = "raw_scan_fallback"
    semantic_category: str = "generic_dependency"
    collapsed: bool = False
    original_source_id: Optional[str] = None
    original_target_id: Optional[str] = None


@dataclass
class ImpactTransition:
    from_node_id: str
    to_node_id: str
    category: str
    weight: float
    reason: str
    canonical_relation_type: Optional[str]
    confidence_score: Optional[float]
    confidence_label: Optional[str]
    inference_stage: Optional[str]
    graph_source: str
    collapsed: bool


@dataclass
class SimulationGraphContext:
    nodes: dict[str, InterpretedNode]
    edges: list[InterpretedEdge]
    transitions: dict[str, list[ImpactTransition]]
    mode: str
    stats: dict[str, int] = field(default_factory=dict)


def build_simulation_context(nodes: list[dict], edges: list[dict]) -> SimulationGraphContext:
    node_map: dict[str, InterpretedNode] = {}
    for node in nodes:
        node_map[node["id"]] = InterpretedNode(
            id=node["id"],
            label=node["label"],
            node_type=node["node_type"],
            data=node.get("data") or {},
            canonical_entity_id=node.get("canonical_entity_id"),
            canonical_entity_kind=node.get("canonical_entity_kind"),
            confidence_score=_safe_confidence(node.get("confidence_score")),
            confidence_label=node.get("confidence_label"),
            graph_source=(node.get("data") or {}).get("graph_source", "raw_scan_fallback"),
        )

    interpreted_edges: list[InterpretedEdge] = []
    transitions: dict[str, list[ImpactTransition]] = {}
    invalid_edge_count = 0
    canonical_edge_count = 0
    canonical_node_count = sum(1 for node in node_map.values() if node.canonical_entity_id)

    for edge in edges:
        source_node_id = edge["source_node_id"]
        target_node_id = edge["target_node_id"]
        if source_node_id not in node_map or target_node_id not in node_map:
            invalid_edge_count += 1
            continue

        edge_data = edge.get("data") or {}
        projection = edge_data.get("projection") or {}
        interpreted_edge = InterpretedEdge(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            edge_type=edge["edge_type"],
            data=edge_data,
            canonical_relation_id=edge.get("canonical_relation_id"),
            canonical_relation_type=edge.get("canonical_relation_type"),
            confidence_score=_safe_confidence(edge.get("confidence_score")),
            confidence_label=edge.get("confidence_label"),
            inference_stage=edge.get("inference_stage"),
            graph_source=edge_data.get("graph_source", "raw_scan_fallback"),
            semantic_category=_semantic_category_for_edge(edge, node_map[source_node_id], node_map[target_node_id]),
            collapsed=bool(projection.get("collapsed", False)),
            original_source_id=projection.get("original_source_id"),
            original_target_id=projection.get("original_target_id"),
        )
        if interpreted_edge.canonical_relation_id:
            canonical_edge_count += 1
        interpreted_edges.append(interpreted_edge)

        for transition in _impact_transitions_for_edge(interpreted_edge, node_map):
            transitions.setdefault(transition.from_node_id, []).append(transition)

    semantic_mode = canonical_edge_count > 0 or canonical_node_count > 0
    return SimulationGraphContext(
        nodes=node_map,
        edges=interpreted_edges,
        transitions=transitions,
        mode="semantic" if semantic_mode else "basic",
        stats={
            "node_count": len(node_map),
            "edge_count": len(interpreted_edges),
            "canonical_node_count": canonical_node_count,
            "canonical_edge_count": canonical_edge_count,
            "invalid_edge_count": invalid_edge_count,
        },
    )


def _impact_transitions_for_edge(
    edge: InterpretedEdge,
    nodes: dict[str, InterpretedNode],
) -> list[ImpactTransition]:
    source = nodes[edge.source_node_id]
    target = nodes[edge.target_node_id]
    weight = _edge_weight(edge, target)
    transitions: list[ImpactTransition] = []

    def add_transition(from_node_id: str, to_node_id: str, reason: str) -> None:
        transitions.append(
            ImpactTransition(
                from_node_id=from_node_id,
                to_node_id=to_node_id,
                category=edge.semantic_category,
                weight=weight,
                reason=reason,
                canonical_relation_type=edge.canonical_relation_type,
                confidence_score=edge.confidence_score,
                confidence_label=edge.confidence_label,
                inference_stage=edge.inference_stage,
                graph_source=edge.graph_source,
                collapsed=edge.collapsed,
            )
        )

    if edge.semantic_category == "runtime_dependency":
        add_transition(edge.target_node_id, edge.source_node_id, "runtime failure impacts dependent component")
        return transitions

    if edge.semantic_category in {
        "service_dependency",
        "datastore_read_dependency",
        "datastore_write_dependency",
        "external_dependency",
        "cache_dependency",
    }:
        add_transition(edge.target_node_id, edge.source_node_id, _reason_for_category(edge.semantic_category))
        return transitions

    if edge.edge_type == "contains":
        add_transition(edge.source_node_id, edge.target_node_id, "container failure impacts contained node")
        add_transition(edge.target_node_id, edge.source_node_id, "contained node failure can bubble to parent")
        return transitions

    if edge.edge_type == "connects_to":
        add_transition(edge.source_node_id, edge.target_node_id, "connected component is impacted")
        add_transition(edge.target_node_id, edge.source_node_id, "connected component is impacted")
        return transitions

    if edge.edge_type == "runs_on":
        add_transition(edge.target_node_id, edge.source_node_id, "runtime failure impacts component")
        return transitions

    if edge.edge_type == "uses":
        add_transition(edge.target_node_id, edge.source_node_id, "dependency failure impacts dependent node")
        return transitions

    add_transition(edge.source_node_id, edge.target_node_id, "generic dependency propagates impact")
    return transitions


def _semantic_category_for_edge(
    edge: dict,
    source_node: InterpretedNode,
    target_node: InterpretedNode,
) -> str:
    relation_type = edge.get("canonical_relation_type")
    if relation_type == "USES_RUNTIME" or edge.get("edge_type") == "runs_on":
        return "runtime_dependency"
    if relation_type in {"CALLS", "CONNECTS_TO", "DEPENDS_ON"}:
        return "service_dependency"
    if relation_type == "READS_FROM":
        return "cache_dependency" if _is_cache_node(target_node) else "datastore_read_dependency"
    if relation_type in {"WRITES_TO", "BACKED_BY"}:
        return "cache_dependency" if _is_cache_node(target_node) else "datastore_write_dependency"
    if relation_type in {"INTEGRATES_WITH", "EMITS_TO", "CONSUMES_FROM"}:
        return "external_dependency"
    if target_node.node_type == "database":
        return "cache_dependency" if _is_cache_node(target_node) else "datastore_read_dependency"
    if target_node.node_type == "external":
        return "external_dependency"
    if edge.get("edge_type") in {"calls", "connects_to"}:
        return "service_dependency"
    return "generic_dependency"


def _edge_weight(edge: InterpretedEdge, target_node: InterpretedNode) -> float:
    base_weight = {
        "service_dependency": 0.82,
        "datastore_read_dependency": 0.72,
        "datastore_write_dependency": 0.88,
        "runtime_dependency": 0.95,
        "external_dependency": 0.68,
        "cache_dependency": 0.55,
        "generic_dependency": 0.7,
    }.get(edge.semantic_category, 0.7)

    confidence_multiplier = 0.85
    if edge.confidence_score is not None:
        confidence_multiplier = 0.55 + (max(0.0, min(edge.confidence_score, 1.0)) * 0.45)

    provenance_multiplier = 1.0 if edge.graph_source == "canonical_snapshot" else 0.78
    collapse_multiplier = 0.92 if edge.collapsed else 1.0
    cache_multiplier = 0.88 if _is_cache_node(target_node) else 1.0

    weight = base_weight * confidence_multiplier * provenance_multiplier * collapse_multiplier * cache_multiplier
    return max(0.05, min(weight, 0.98))


def _safe_confidence(raw_value) -> Optional[float]:
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(value, 1.0))


def _is_cache_node(node: InterpretedNode) -> bool:
    cache_markers = {
        (node.data or {}).get("store_kind"),
        (node.data or {}).get("technology"),
        node.label,
    }
    normalized = {str(value).lower() for value in cache_markers if value}
    return "cache" in normalized or "redis" in normalized


def _reason_for_category(category: str) -> str:
    return {
        "service_dependency": "service dependency failure impacts caller",
        "datastore_read_dependency": "read dependency failure blocks dependent component",
        "datastore_write_dependency": "write dependency failure blocks dependent component",
        "external_dependency": "external dependency failure impacts dependent component",
        "cache_dependency": "cache dependency failure degrades dependent component",
    }.get(category, "dependency failure impacts dependent component")