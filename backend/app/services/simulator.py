"""Failure simulation on the project architecture graph.

Uses a semantic-aware graph interpretation when persisted canonical provenance
is available and falls back to the original edge-type BFS behavior otherwise.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from app.services.simulation_interpreter import SimulationGraphContext, build_simulation_context


@dataclass
class SimulationResult:
    failed_node_id: str
    failed_node_label: str
    failed_node_type: str
    impacted_nodes: list[dict]   # [{id, label, node_type, distance}]
    severity: str                # low / medium / high
    summary: str
    result_metadata: dict = field(default_factory=dict)


# Node types that are considered high-impact origins when they fail.
HIGH_IMPACT_TYPES = {"backend", "database"}
# Node types that are considered medium-impact origins.
MEDIUM_IMPACT_TYPES = {"frontend", "runtime"}


def simulate_failure(
    failed_node_id: str,
    nodes: list[dict],
    edges: list[dict],
) -> SimulationResult:
    context = build_simulation_context(nodes, edges)
    if context.mode == "semantic":
        return _simulate_semantic(failed_node_id, context)
    return _simulate_basic(failed_node_id, nodes, edges, context)


def _simulate_semantic(
    failed_node_id: str,
    context: SimulationGraphContext,
) -> SimulationResult:
    failed_node = context.nodes.get(failed_node_id)
    if failed_node is None:
        raise ValueError(f"Node {failed_node_id} not found in graph")

    min_strength = 0.18
    strengths: dict[str, float] = {failed_node_id: 1.0}
    distances: dict[str, int] = {failed_node_id: 0}
    reasons: dict[str, dict] = {}
    queue = deque([failed_node_id])

    while queue:
        current_id = queue.popleft()
        current_strength = strengths[current_id]
        current_distance = distances[current_id]

        for transition in context.transitions.get(current_id, []):
            propagated_strength = current_strength * transition.weight
            if propagated_strength < min_strength:
                continue

            previous_strength = strengths.get(transition.to_node_id, 0.0)
            previous_distance = distances.get(transition.to_node_id, 10**9)
            if propagated_strength <= previous_strength and current_distance + 1 >= previous_distance:
                continue

            strengths[transition.to_node_id] = propagated_strength
            distances[transition.to_node_id] = min(previous_distance, current_distance + 1)
            reasons[transition.to_node_id] = {
                "dependency_type": transition.category,
                "why": transition.reason,
                "impact_score": round(propagated_strength, 3),
                "confidence_score": transition.confidence_score,
                "confidence_label": transition.confidence_label,
                "canonical_relation_type": transition.canonical_relation_type,
                "inference_stage": transition.inference_stage,
                "graph_source": transition.graph_source,
                "collapsed": transition.collapsed,
            }
            queue.append(transition.to_node_id)

    impacted_nodes = []
    for node_id, node in context.nodes.items():
        if node_id == failed_node_id or node_id not in strengths:
            continue
        impacted_nodes.append(
            {
                "id": node.id,
                "label": node.label,
                "node_type": node.node_type,
                "distance": distances[node_id],
                **reasons[node_id],
            }
        )

    impacted_nodes.sort(key=lambda item: (-item["impact_score"], item["distance"], item["label"]))
    severity = _compute_semantic_severity(failed_node, impacted_nodes, len(context.nodes))
    summary = _build_semantic_summary(failed_node, impacted_nodes, severity)

    return SimulationResult(
        failed_node_id=failed_node_id,
        failed_node_label=failed_node.label,
        failed_node_type=failed_node.node_type,
        impacted_nodes=impacted_nodes,
        severity=severity,
        summary=summary,
        result_metadata={
            "mode": "semantic",
            "graph_provenance": {
                "node_count": context.stats.get("node_count", 0),
                "edge_count": context.stats.get("edge_count", 0),
                "canonical_node_count": context.stats.get("canonical_node_count", 0),
                "canonical_edge_count": context.stats.get("canonical_edge_count", 0),
                "invalid_edge_count": context.stats.get("invalid_edge_count", 0),
            },
        },
    )


def _simulate_basic(
    failed_node_id: str,
    nodes: list[dict],
    edges: list[dict],
    context: SimulationGraphContext,
) -> SimulationResult:
    node_map: dict[str, dict] = {n["id"]: n for n in nodes}
    failed_node = node_map.get(failed_node_id)
    if failed_node is None:
        raise ValueError(f"Node {failed_node_id} not found in graph")

    impact: dict[str, list[str]] = {}

    for edge in edges:
        src = edge["source_node_id"]
        tgt = edge["target_node_id"]
        etype = edge["edge_type"]

        if etype == "contains":
            impact.setdefault(src, []).append(tgt)
            impact.setdefault(tgt, []).append(src)
        elif etype == "runs_on":
            impact.setdefault(tgt, []).append(src)
        elif etype == "uses":
            impact.setdefault(tgt, []).append(src)
        elif etype == "connects_to":
            impact.setdefault(src, []).append(tgt)
            impact.setdefault(tgt, []).append(src)
        else:
            impact.setdefault(src, []).append(tgt)

    visited: set[str] = {failed_node_id}
    queue = deque([(failed_node_id, 0)])
    impacted: list[dict] = []

    while queue:
        current_id, dist = queue.popleft()
        for neighbor_id in impact.get(current_id, []):
            if neighbor_id in visited:
                continue
            visited.add(neighbor_id)
            neighbor = node_map.get(neighbor_id)
            if neighbor is None:
                continue
            impacted.append(
                {
                    "id": neighbor["id"],
                    "label": neighbor["label"],
                    "node_type": neighbor["node_type"],
                    "distance": dist + 1,
                    "dependency_type": "generic_dependency",
                    "why": "basic graph traversal over current graph edges",
                    "graph_source": "raw_scan_fallback",
                }
            )
            queue.append((neighbor_id, dist + 1))

    severity = _compute_severity(failed_node, impacted, len(nodes))
    summary = _build_summary(failed_node, impacted, severity)

    return SimulationResult(
        failed_node_id=failed_node_id,
        failed_node_label=failed_node["label"],
        failed_node_type=failed_node["node_type"],
        impacted_nodes=impacted,
        severity=severity,
        summary=summary,
        result_metadata={
            "mode": "basic",
            "graph_provenance": {
                "node_count": context.stats.get("node_count", 0),
                "edge_count": context.stats.get("edge_count", 0),
                "canonical_node_count": context.stats.get("canonical_node_count", 0),
                "canonical_edge_count": context.stats.get("canonical_edge_count", 0),
                "invalid_edge_count": context.stats.get("invalid_edge_count", 0),
            },
        },
    )


def _compute_severity(
    failed_node: dict,
    impacted: list[dict],
    total_nodes: int,
) -> str:
    """Simple heuristic: combine node-type weight + fraction of graph impacted."""
    if total_nodes <= 1:
        return "low"

    impact_ratio = len(impacted) / (total_nodes - 1)  # exclude the failed node itself
    node_type = failed_node["node_type"]

    # High-impact source types get a boost
    if node_type in HIGH_IMPACT_TYPES:
        if impact_ratio >= 0.3:
            return "high"
        if impact_ratio >= 0.1:
            return "medium"
        return "low"

    if node_type in MEDIUM_IMPACT_TYPES:
        if impact_ratio >= 0.5:
            return "high"
        if impact_ratio >= 0.2:
            return "medium"
        return "low"

    # Default (tool, entry_point, etc.)
    if impact_ratio >= 0.6:
        return "high"
    if impact_ratio >= 0.3:
        return "medium"
    return "low"


def _compute_semantic_severity(
    failed_node,
    impacted: list[dict],
    total_nodes: int,
) -> str:
    if total_nodes <= 1 or not impacted:
        return "low"

    weighted_impact = sum(node.get("impact_score", 0.0) for node in impacted)
    coverage_score = weighted_impact / max(1, total_nodes - 1)
    peak_score = max(node.get("impact_score", 0.0) for node in impacted)
    origin_factor = {
        "database": 1.0,
        "runtime": 0.95,
        "component": 0.85,
        "external": 0.75,
    }.get(_node_type_value(failed_node), 0.65)

    severity_score = (coverage_score * 0.5) + (peak_score * 0.35) + (origin_factor * 0.15)
    if severity_score >= 0.66:
        return "high"
    if severity_score >= 0.33:
        return "medium"
    return "low"


def _build_summary(
    failed_node: dict,
    impacted: list[dict],
    severity: str,
) -> str:
    """Generate a short plain-English summary of the failure impact."""
    label = failed_node["label"]
    ntype = failed_node["node_type"]
    count = len(impacted)

    if count == 0:
        return f"If {label} ({ntype}) fails, no other components are directly affected."

    impacted_types = sorted({n["node_type"] for n in impacted})
    type_str = ", ".join(impacted_types)

    severity_word = {"low": "minor", "medium": "moderate", "high": "significant"}[severity]

    node_word = "component" if count == 1 else "components"
    return (
        f"If {label} ({ntype}) fails, it causes {severity_word} impact — "
        f"{count} {node_word} affected ({type_str})."
    )


def _build_semantic_summary(
    failed_node,
    impacted: list[dict],
    severity: str,
) -> str:
    label = failed_node.label
    ntype = failed_node.node_type
    count = len(impacted)
    if count == 0:
        return f"If {label} ({ntype}) fails, semantic analysis found no direct downstream impact."

    top_categories = sorted({node.get("dependency_type", "generic_dependency") for node in impacted})
    category_str = ", ".join(top_categories[:3])
    severity_word = {"low": "minor", "medium": "moderate", "high": "significant"}[severity]
    return (
        f"If {label} ({ntype}) fails, semantic dependency analysis predicts {severity_word} impact — "
        f"{count} components affected through {category_str}."
    )


def _node_type_value(failed_node) -> str:
    if hasattr(failed_node, "node_type"):
        return failed_node.node_type
    return failed_node.get("node_type", "unknown")
