"""Heuristic-based failure simulation on the project architecture graph.

Given a single failed node, build an edge-type-aware impact graph and BFS
to find all impacted nodes.  Compute a simple severity and produce a
plain-English summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class SimulationResult:
    failed_node_id: str
    failed_node_label: str
    failed_node_type: str
    impacted_nodes: list[dict]   # [{id, label, node_type, distance}]
    severity: str                # low / medium / high
    summary: str


# Node types that are considered high-impact origins when they fail.
HIGH_IMPACT_TYPES = {"backend", "database"}
# Node types that are considered medium-impact origins.
MEDIUM_IMPACT_TYPES = {"frontend", "runtime"}


def simulate_failure(
    failed_node_id: str,
    nodes: list[dict],
    edges: list[dict],
) -> SimulationResult:
    """Run edge-type-aware BFS from the failed node to find impacted nodes.

    Propagation direction depends on the edge type so that impact flows
    realistically (e.g. a runtime failure impacts the apps that run on it,
    not the other way around).    Parameters
    ----------
    failed_node_id : str
        The id of the node that fails.
    nodes : list[dict]
        Each dict has at least {id, node_type, label}.
    edges : list[dict]
        Each dict has at least {source_node_id, target_node_id, edge_type}.

    Returns
    -------
    SimulationResult with impact analysis.
    """
    node_map: dict[str, dict] = {n["id"]: n for n in nodes}
    failed_node = node_map.get(failed_node_id)
    if failed_node is None:
        raise ValueError(f"Node {failed_node_id} not found in graph")

    # Build a directed "impact graph" — an adjacency list where an entry
    # `A → [B]` means "if A fails, B is impacted".
    #
    # Each edge type has its own propagation rule based on what the edge
    # means in a real architecture:
    #
    #   contains   (parent → child):  parent fails  → children impacted  (forward)
    #                                  child fails   → parent impacted    (reverse)
    #   runs_on    (app → runtime):   runtime fails  → app impacted      (reverse)
    #                                  app fails     → no runtime impact  (—)
    #   uses       (component → tool): tool fails    → component impacted (reverse)
    #                                  component fails → no tool impact   (—)
    #   connects_to (A → B):          either side fails → other impacted (both)
    #
    impact: dict[str, list[str]] = {}

    for edge in edges:
        src = edge["source_node_id"]
        tgt = edge["target_node_id"]
        etype = edge["edge_type"]

        if etype == "contains":
            # Parent fails → children impacted, child fails → parent impacted
            impact.setdefault(src, []).append(tgt)
            impact.setdefault(tgt, []).append(src)

        elif etype == "runs_on":
            # Runtime (target) fails → app (source) impacted
            impact.setdefault(tgt, []).append(src)

        elif etype == "uses":
            # Tool/dep (target) fails → user (source) impacted
            impact.setdefault(tgt, []).append(src)

        elif etype == "connects_to":
            # Network link — failure on either side impacts the other
            impact.setdefault(src, []).append(tgt)
            impact.setdefault(tgt, []).append(src)

        else:
            # Unknown edge type — default to forward propagation
            impact.setdefault(src, []).append(tgt)

    # BFS along the impact graph to find all affected nodes
    visited: set[str] = {failed_node_id}
    queue: list[tuple[str, int]] = [(failed_node_id, 0)]  # (node_id, distance)
    impacted: list[dict] = []

    while queue:
        current_id, dist = queue.pop(0)
        for neighbor_id in impact.get(current_id, []):
            if neighbor_id in visited:
                continue
            visited.add(neighbor_id)
            neighbor = node_map.get(neighbor_id)
            if neighbor is None:
                continue
            impacted.append({
                "id": neighbor["id"],
                "label": neighbor["label"],
                "node_type": neighbor["node_type"],
                "distance": dist + 1,
            })
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
