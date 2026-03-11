from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.graph_edge import GraphEdge
from app.models.graph_node import GraphNode
from app.models.scan import Scan
from app.models.simulation_run import SimulationRun
from app.services.system_insights import (
    AnalysisArtifacts,
    build_summary_risks_from_insights,
    build_system_insights_from_artifacts,
    load_latest_analysis_artifacts,
)

logger = logging.getLogger(__name__)


def build_system_intelligence_summary(project_id: str, db: Session) -> dict:
    artifacts = load_latest_analysis_artifacts(project_id=project_id, db=db)
    scan = artifacts.scan
    entity_counts = _entity_counts(scan=scan, project_model=artifacts.project_model, graph_nodes=artifacts.graph_nodes)
    route_counts = _route_counts(scan=scan, project_model=artifacts.project_model)
    system_type_guess = _infer_system_type(scan=scan, project_model=artifacts.project_model, entity_counts=entity_counts, route_counts=route_counts)
    primary_stack = _infer_primary_stack(scan=scan, project_model=artifacts.project_model)
    architecture_hints = _architecture_hints(
        scan=scan,
        project_model=artifacts.project_model,
        entity_counts=entity_counts,
        route_counts=route_counts,
        graph_edges=artifacts.graph_edges,
    )
    dependency_metrics = _dependency_metrics(artifacts.project_model, artifacts.graph_nodes, artifacts.graph_edges)
    runtime_dependency_highlights = _runtime_dependency_highlights(dependency_metrics)
    critical_nodes = _critical_nodes(
        graph_nodes=artifacts.graph_nodes,
        graph_edges=artifacts.graph_edges,
        simulation_run=artifacts.simulation_run,
    )
    confidence_summary = _confidence_summary(
        scan=scan,
        snapshot_used=artifacts.snapshot_id is not None,
        graph_nodes=artifacts.graph_nodes,
        graph_provenance=artifacts.graph_provenance,
        simulation_mode=artifacts.simulation_mode,
        route_counts=route_counts,
    )
    top_findings = _top_findings(
        scan=scan,
        project_model=artifacts.project_model,
        route_counts=route_counts,
        architecture_hints=architecture_hints,
        critical_nodes=critical_nodes,
        confidence_summary=confidence_summary,
        snapshot_id=artifacts.snapshot_id,
    )
    top_risks = _top_risks(
        project_model=artifacts.project_model,
        graph_nodes=artifacts.graph_nodes,
        graph_edges=artifacts.graph_edges,
        critical_nodes=critical_nodes,
        dependency_metrics=dependency_metrics,
        confidence_summary=confidence_summary,
        simulation_run=artifacts.simulation_run,
        simulation_mode=artifacts.simulation_mode,
        graph_provenance=artifacts.graph_provenance,
    )
    insights_payload = build_system_insights_from_artifacts(project_id=project_id, artifacts=artifacts)
    insight_backed_risks = build_summary_risks_from_insights(insights_payload["insights"])
    if insight_backed_risks:
        top_risks = insight_backed_risks
    overview_text = _overview_text(
        system_type_guess=system_type_guess,
        primary_stack=primary_stack,
        architecture_hints=architecture_hints,
        top_risks=top_risks,
        confidence_summary=confidence_summary,
    )

    logger.info(
        "System intelligence summary built for project %s scan %s snapshot_used %s graph_provenance %s confidence %s",
        project_id,
        scan.id,
        artifacts.snapshot_id is not None,
        artifacts.graph_provenance,
        confidence_summary["overall_label"],
    )

    return {
        "project_id": project_id,
        "scan_id": scan.id,
        "snapshot_id": artifacts.snapshot_id,
        "graph_scan_id": scan.id if artifacts.graph_nodes else None,
        "graph_provenance": artifacts.graph_provenance,
        "system_type_guess": system_type_guess,
        "primary_stack": primary_stack,
        "architecture_hints": architecture_hints,
        "component_counts": entity_counts,
        "route_counts": route_counts,
        "runtime_dependency_highlights": runtime_dependency_highlights,
        "critical_nodes": critical_nodes,
        "top_findings": top_findings,
        "top_risks": top_risks,
        "confidence_summary": confidence_summary,
        "overview_text": overview_text,
        "generated_from": {
            "generated_at": datetime.now(timezone.utc),
            "latest_scan_created_at": scan.created_at,
            "canonical_snapshot_used": artifacts.snapshot_id is not None,
            "graph_used": bool(artifacts.graph_nodes),
            "graph_provenance": artifacts.graph_provenance,
            "simulation_used": artifacts.simulation_run is not None,
            "simulation_mode": artifacts.simulation_mode,
        },
    }


def _entity_counts(scan: Scan, project_model, graph_nodes: list[GraphNode]) -> dict:
    component_type_counts = Counter()
    for component in scan.components or []:
        if not isinstance(component, dict):
            continue
        component_type_counts[component.get("type", "unknown")] += 1

    graph_type_counts = Counter(node.node_type for node in graph_nodes)
    return {
        "scan_components_total": len(scan.components or []),
        "frontend_components": component_type_counts.get("frontend", 0),
        "backend_components": component_type_counts.get("backend", 0),
        "service_components": component_type_counts.get("service", 0),
        "unknown_components": component_type_counts.get("unknown", 0),
        "canonical_components": len(getattr(project_model, "components", {}) or {}),
        "canonical_services": len(getattr(project_model, "services", {}) or {}),
        "canonical_modules": len(getattr(project_model, "modules", {}) or {}),
        "data_stores": _entity_collection_size(project_model, "data_stores", graph_type_counts.get("database", 0)),
        "external_integrations": _entity_collection_size(project_model, "external_integrations", graph_type_counts.get("external", 0)),
        "runtime_nodes": _entity_collection_size(project_model, "runtime_nodes", graph_type_counts.get("runtime", 0)),
    }


def _entity_collection_size(project_model, attr_name: str, fallback: int) -> int:
    collection = getattr(project_model, attr_name, None)
    if isinstance(collection, dict):
        return len(collection)
    return fallback


def _route_counts(scan: Scan, project_model) -> dict:
    routes = list(getattr(project_model, "routes", {}).values()) if project_model else list(scan.routes or [])
    methods = Counter()
    for route in routes:
        method = route.method if hasattr(route, "method") else route.get("method", "ANY")
        methods[str(method).upper()] += 1
    return {
        "total": len(routes),
        "by_method": dict(sorted(methods.items())),
    }


def _infer_system_type(scan: Scan, project_model, entity_counts: dict, route_counts: dict) -> str:
    frontend_count = entity_counts["frontend_components"]
    backend_like_count = entity_counts["backend_components"] + entity_counts["service_components"]
    route_total = route_counts["total"]
    data_store_count = entity_counts["data_stores"]
    external_count = entity_counts["external_integrations"]
    service_count = entity_counts["canonical_services"]

    if frontend_count and backend_like_count:
        if route_total > 0 and (data_store_count > 0 or external_count > 0):
            return "service-backed web app"
        return "full-stack application"
    if route_total > 0:
        if backend_like_count <= 1 and service_count <= 2:
            return "monolith-ish REST API"
        return "REST API"
    if frontend_count and backend_like_count == 0:
        return "frontend application"
    if backend_like_count >= 2:
        return "service-oriented backend system"
    return (scan.project_type or "software system").replace("_", " ")


def _infer_primary_stack(scan: Scan, project_model) -> list[str]:
    ordered_stack: list[str] = []
    for framework in scan.frameworks or []:
        _append_unique(ordered_stack, framework)
    for language in scan.languages or []:
        _append_unique(ordered_stack, language)

    if project_model is not None:
        for runtime in getattr(project_model, "runtime_nodes", {}).values():
            label = runtime.name if not runtime.version else f"{runtime.name} {runtime.version}"
            _append_unique(ordered_stack, label)
        for store in getattr(project_model, "data_stores", {}).values():
            _append_unique(ordered_stack, store.technology or store.kind or store.name)
        for integration in getattr(project_model, "external_integrations", {}).values():
            if integration.provider:
                _append_unique(ordered_stack, integration.provider)
    return ordered_stack[:6]


def _append_unique(values: list[str], candidate: Optional[str]) -> None:
    if not candidate:
        return
    if candidate not in values:
        values.append(candidate)


def _architecture_hints(scan: Scan, project_model, entity_counts: dict, route_counts: dict, graph_edges: list[GraphEdge]) -> list[str]:
    hints: list[str] = []
    if entity_counts["frontend_components"] and (entity_counts["backend_components"] or entity_counts["service_components"]):
        hints.append("frontend + backend split")
    if route_counts["total"] > 0 and entity_counts["data_stores"] > 0:
        hints.append("API + datastore pattern")
    if entity_counts["data_stores"] > 0 and entity_counts["external_integrations"] > 0:
        hints.append("stateful core with external integrations")
    if _has_layered_service_hints(project_model):
        hints.append("controller/service/repository-style layering signals")
    if _has_service_to_service_hints(project_model, graph_edges):
        hints.append("service-to-service dependency graph")
    return hints[:4]


def _has_layered_service_hints(project_model) -> bool:
    if project_model is None:
        return False
    relation_types = Counter(relation.relation_type.value for relation in project_model.relations.values())
    return (
        len(project_model.routes) >= 2
        and len(project_model.services) >= 1
        and len(project_model.modules) >= 2
        and (relation_types.get("BACKED_BY", 0) >= 1 or relation_types.get("EXPOSES_ROUTE", 0) >= 1)
        and (relation_types.get("READS_FROM", 0) >= 1 or relation_types.get("WRITES_TO", 0) >= 1)
    )


def _has_service_to_service_hints(project_model, graph_edges: list[GraphEdge]) -> bool:
    if project_model is not None:
        for relation in project_model.relations.values():
            if relation.relation_type.value in {"CALLS", "CONNECTS_TO", "DEPENDS_ON"}:
                return True
    return sum(1 for edge in graph_edges if edge.edge_type in {"calls", "connects_to"}) >= 2


def _dependency_metrics(project_model, graph_nodes: list[GraphNode], graph_edges: list[GraphEdge]) -> dict:
    if project_model is not None:
        return _dependency_metrics_from_project_model(project_model)
    return _dependency_metrics_from_graph(graph_nodes=graph_nodes, graph_edges=graph_edges)


def _dependency_metrics_from_project_model(project_model) -> dict:
    runtime_dependents = defaultdict(set)
    store_dependents = defaultdict(set)
    external_dependents = defaultdict(set)
    store_modes = Counter()
    external_edge_count = 0

    runtime_names = {item.id: item.name for item in project_model.runtime_nodes.values()}
    store_names = {
        item.id: (item.technology or item.name)
        for item in project_model.data_stores.values()
    }
    external_names = {
        item.id: (item.provider or item.name)
        for item in project_model.external_integrations.values()
    }

    for relation in project_model.relations.values():
        relation_type = relation.relation_type.value
        if relation_type == "USES_RUNTIME" and relation.target_id in runtime_names:
            runtime_dependents[relation.target_id].add(relation.source_id)
        if relation_type in {"READS_FROM", "WRITES_TO", "BACKED_BY"} and relation.target_id in store_names:
            store_dependents[relation.target_id].add(relation.source_id)
            store_modes[relation_type] += 1
        if relation_type in {"INTEGRATES_WITH", "CALLS", "CONNECTS_TO", "EMITS_TO", "CONSUMES_FROM"} and relation.target_id in external_names:
            external_dependents[relation.target_id].add(relation.source_id)
            external_edge_count += 1

    return {
        "runtime_dependents": {
            runtime_names[item_id]: len(dependents)
            for item_id, dependents in runtime_dependents.items()
        },
        "store_dependents": {
            store_names[item_id]: len(dependents)
            for item_id, dependents in store_dependents.items()
        },
        "store_edge_count": sum(store_modes.values()),
        "external_dependents": {
            external_names[item_id]: len(dependents)
            for item_id, dependents in external_dependents.items()
        },
        "external_edge_count": external_edge_count,
        "store_modes": dict(store_modes),
    }


def _dependency_metrics_from_graph(graph_nodes: list[GraphNode], graph_edges: list[GraphEdge]) -> dict:
    node_by_id = {node.id: node for node in graph_nodes}
    runtime_dependents = defaultdict(set)
    store_dependents = defaultdict(set)
    external_dependents = defaultdict(set)
    store_modes = Counter()
    external_edge_count = 0

    for edge in graph_edges:
        source = node_by_id.get(edge.source_node_id)
        target = node_by_id.get(edge.target_node_id)
        if source is None or target is None:
            continue
        if target.node_type == "runtime":
            runtime_dependents[target.label].add(source.id)
        if target.node_type == "database":
            store_dependents[target.label].add(source.id)
            store_modes[edge.edge_type] += 1
        if target.node_type == "external":
            external_dependents[target.label].add(source.id)
            external_edge_count += 1

    return {
        "runtime_dependents": {label: len(dependents) for label, dependents in runtime_dependents.items()},
        "store_dependents": {label: len(dependents) for label, dependents in store_dependents.items()},
        "store_edge_count": sum(store_modes.values()),
        "external_dependents": {label: len(dependents) for label, dependents in external_dependents.items()},
        "external_edge_count": external_edge_count,
        "store_modes": dict(store_modes),
    }


def _runtime_dependency_highlights(dependency_metrics: dict) -> list[dict]:
    highlights: list[dict] = []
    for name, dependents in sorted(
        dependency_metrics.get("runtime_dependents", {}).items(),
        key=lambda item: (-item[1], item[0]),
    )[:2]:
        highlights.append(
            {
                "category": "runtime",
                "label": name,
                "detail": f"Shared by {dependents} dependent components or services.",
                "confidence": "high" if dependents >= 2 else "medium",
                "supporting_ids": [],
            }
        )

    for name, dependents in sorted(
        dependency_metrics.get("store_dependents", {}).items(),
        key=lambda item: (-item[1], item[0]),
    )[:2]:
        highlights.append(
            {
                "category": "datastore",
                "label": name,
                "detail": f"Referenced by {dependents} dependent components or services.",
                "confidence": "high" if dependents >= 2 else "medium",
                "supporting_ids": [],
            }
        )

    for name, dependents in sorted(
        dependency_metrics.get("external_dependents", {}).items(),
        key=lambda item: (-item[1], item[0]),
    )[:1]:
        highlights.append(
            {
                "category": "external_dependency",
                "label": name,
                "detail": f"Touched by {dependents} dependent components or services.",
                "confidence": "medium" if dependents >= 2 else "low",
                "supporting_ids": [],
            }
        )
    return highlights[:5]


def _critical_nodes(
    graph_nodes: list[GraphNode],
    graph_edges: list[GraphEdge],
    simulation_run: Optional[SimulationRun],
) -> list[dict]:
    if not graph_nodes:
        return []

    degree_map = Counter()
    for edge in graph_edges:
        degree_map[edge.source_node_id] += 1
        degree_map[edge.target_node_id] += 1

    max_degree = max(degree_map.values(), default=1)
    impacted_count = len(simulation_run.impacted_nodes) if simulation_run is not None else 0
    simulated_node_id = simulation_run.failed_node_id if simulation_run is not None else None
    severity_bonus = {
        "high": 0.25,
        "medium": 0.15,
        "low": 0.05,
    }.get(simulation_run.severity if simulation_run is not None else "", 0.0)

    ranked_nodes: list[tuple[float, dict]] = []
    for node in graph_nodes:
        degree_score = degree_map.get(node.id, 0) / max_degree
        type_bonus = 0.12 if node.node_type in {"database", "runtime", "external"} else 0.06
        canonical_bonus = 0.08 if node.canonical_entity_id else 0.0
        simulation_bonus = 0.0
        reason = "High connectivity across the current graph."
        if simulated_node_id == node.id:
            simulation_bonus = min(0.3, impacted_count / max(1, len(graph_nodes) - 1)) + severity_bonus
            reason = f"Latest simulation from this node impacted {impacted_count} downstream components."
        elif node.node_type in {"database", "runtime", "external"}:
            reason = "Shared dependency with elevated centrality in the current graph."

        score = min(0.99, round((degree_score * 0.62) + type_bonus + canonical_bonus + simulation_bonus, 3))
        if score < 0.22:
            continue

        ranked_nodes.append(
            (
                score,
                {
                    "node_id": node.id,
                    "label": node.label,
                    "node_type": node.node_type,
                    "criticality_score": score,
                    "graph_source": (node.data or {}).get("graph_source"),
                    "canonical_entity_id": node.canonical_entity_id,
                    "reason": reason,
                },
            )
        )

    ranked_nodes.sort(key=lambda item: (-item[0], item[1]["label"]))
    return [item[1] for item in ranked_nodes[:5]]


def _confidence_summary(
    scan: Scan,
    snapshot_used: bool,
    graph_nodes: list[GraphNode],
    graph_provenance: str,
    simulation_mode: Optional[str],
    route_counts: dict,
) -> dict:
    score = 0.2
    reasons: list[str] = []

    if scan.components:
        score += 0.12
        reasons.append("latest scan includes component structure")
    if route_counts["total"] > 0:
        score += 0.1
        reasons.append("latest scan includes route evidence")
    if snapshot_used:
        score += 0.18
        reasons.append("validated canonical snapshot available for the latest scan")
    else:
        score -= 0.05
        reasons.append("no validated canonical snapshot is available for the latest scan")
    if graph_nodes:
        score += 0.08
        reasons.append("graph available for the latest scan")
    if graph_provenance == "canonical_snapshot":
        score += 0.14
        reasons.append("graph is canonical-backed")
    elif graph_provenance == "raw_scan_fallback":
        score += 0.02
        score -= 0.08
        reasons.append("graph fell back to raw scan projection")
    if simulation_mode == "semantic":
        score += 0.06
        reasons.append("latest simulation used semantic propagation")
    elif simulation_mode == "basic":
        score -= 0.04
        reasons.append("latest simulation used basic fallback propagation")

    if not snapshot_used or graph_provenance != "canonical_snapshot":
        score = min(score, 0.69)
    if not snapshot_used and graph_provenance != "canonical_snapshot":
        score = min(score, 0.58)

    score = max(0.15, min(score, 0.92))
    label = _confidence_label(score)
    return {
        "overall_score": round(score, 3),
        "overall_label": label,
        "reasons": reasons,
        "canonical_snapshot_used": snapshot_used,
        "graph_used": bool(graph_nodes),
        "graph_provenance": graph_provenance,
        "simulation_mode": simulation_mode,
    }


def _confidence_label(score: float) -> str:
    if score >= 0.72:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _top_findings(scan: Scan, project_model, route_counts: dict, architecture_hints: list[str], critical_nodes: list[dict], confidence_summary: dict, snapshot_id: Optional[str]) -> list[dict]:
    findings: list[tuple[int, dict]] = []

    if route_counts["total"] > 0:
        findings.append(
            (
                90,
                {
                    "category": "api_surface_present",
                    "severity": "low",
                    "confidence": "high" if route_counts["total"] >= 2 else "medium",
                    "explanation": f"The latest scan exposes {route_counts['total']} routes, indicating a meaningful API surface.",
                    "supporting_ids": [],
                    "evidence_refs": ["scan.routes"],
                },
            )
        )

    if architecture_hints:
        findings.append(
            (
                85,
                {
                    "category": "architecture_pattern_detected",
                    "severity": "low",
                    "confidence": "high" if len(architecture_hints) >= 2 else "medium",
                    "explanation": f"Architecture hints suggest {', '.join(architecture_hints[:2])}.",
                    "supporting_ids": [],
                    "evidence_refs": ["scan.components", "canonical_snapshot.relations" if project_model is not None else "graph.edges"],
                },
            )
        )

    if snapshot_id is not None and confidence_summary["graph_provenance"] == "canonical_snapshot":
        findings.append(
            (
                80,
                {
                    "category": "strong_canonical_coverage",
                    "severity": "low",
                    "confidence": "high",
                    "explanation": "The summary is grounded in both a validated canonical snapshot and a canonical-backed graph for the latest scan.",
                    "supporting_ids": [snapshot_id],
                    "evidence_refs": ["project_model_snapshot", "graph.nodes", "graph.edges"],
                },
            )
        )

    if critical_nodes:
        top_node = critical_nodes[0]
        findings.append(
            (
                75,
                {
                    "category": "dependency_hotspot_identified",
                    "severity": "medium" if top_node["criticality_score"] >= 0.55 else "low",
                    "confidence": confidence_summary["overall_label"],
                    "explanation": f"{top_node['label']} stands out as a dependency hotspot in the current graph.",
                    "supporting_ids": [top_node["node_id"]],
                    "evidence_refs": ["graph.nodes", "graph.edges"],
                },
            )
        )

    findings.sort(key=lambda item: -item[0])
    return [item[1] for item in findings[:4]]


def _top_risks(
    project_model,
    graph_nodes: list[GraphNode],
    graph_edges: list[GraphEdge],
    critical_nodes: list[dict],
    dependency_metrics: dict,
    confidence_summary: dict,
    simulation_run: Optional[SimulationRun],
    simulation_mode: Optional[str],
    graph_provenance: str,
) -> list[dict]:
    risks: list[tuple[int, dict]] = []
    node_count = len(graph_nodes)
    edge_count = len(graph_edges)

    if critical_nodes:
        top_node = critical_nodes[0]
        if top_node["criticality_score"] >= 0.6:
            risks.append(
                (
                    100,
                    {
                        "category": "single_point_of_failure",
                        "severity": "high" if top_node["criticality_score"] >= 0.75 else "medium",
                        "confidence": confidence_summary["overall_label"],
                        "explanation": f"{top_node['label']} carries unusually high centrality and could create concentrated downstream impact.",
                        "supporting_ids": [top_node["node_id"]],
                        "evidence_refs": ["graph.nodes", "graph.edges", "simulation.result" if simulation_run is not None else "graph.edges"],
                    },
                )
            )

    top_store = _top_metric_item(dependency_metrics.get("store_dependents", {}))
    if top_store is not None and top_store[1] >= 2:
        risks.append(
            (
                92,
                {
                    "category": "heavy_datastore_dependence",
                    "severity": "high" if top_store[1] >= 3 else "medium",
                    "confidence": "high" if project_model is not None else "medium",
                    "explanation": f"Datastore access appears concentrated around {top_store[0]}, which is referenced by {top_store[1]} dependent components or services.",
                    "supporting_ids": [],
                    "evidence_refs": ["canonical_snapshot.relations" if project_model is not None else "graph.edges"],
                },
            )
        )

    top_external = _top_metric_item(dependency_metrics.get("external_dependents", {}))
    if top_external is not None and top_external[1] >= 2:
        risks.append(
            (
                88,
                {
                    "category": "external_dependency_concentration",
                    "severity": "medium",
                    "confidence": "medium" if project_model is not None else "low",
                    "explanation": f"External dependency usage appears concentrated around {top_external[0]} with {top_external[1]} dependent components or services.",
                    "supporting_ids": [],
                    "evidence_refs": ["canonical_snapshot.relations" if project_model is not None else "graph.edges"],
                },
            )
        )

    isolated_ratio = _isolated_ratio(graph_nodes=graph_nodes, graph_edges=graph_edges)
    if node_count >= 4 and edge_count > 0 and isolated_ratio >= 0.3:
        risks.append(
            (
                76,
                {
                    "category": "sparse_graph_coverage",
                    "severity": "medium",
                    "confidence": "medium",
                    "explanation": "A meaningful portion of the current graph is weakly connected, which limits deterministic architecture conclusions.",
                    "supporting_ids": [],
                    "evidence_refs": ["graph.nodes", "graph.edges"],
                },
            )
        )

    if graph_provenance != "canonical_snapshot" or simulation_mode == "basic":
        risks.append(
            (
                72,
                {
                    "category": "fallback_heavy_analysis",
                    "severity": "medium",
                    "confidence": "high",
                    "explanation": "Some current analysis still depends on fallback graph or basic simulation paths, which lowers certainty for architecture and risk interpretation.",
                    "supporting_ids": [],
                    "evidence_refs": ["graph.nodes" if graph_nodes else "scan", "simulation.result" if simulation_run is not None else "scan"],
                },
            )
        )

    if confidence_summary["overall_label"] == "low":
        risks.append(
            (
                68,
                {
                    "category": "low_confidence_understanding",
                    "severity": "medium",
                    "confidence": "high",
                    "explanation": "The strongest current artifacts are not yet rich enough to support a high-confidence architecture summary.",
                    "supporting_ids": [],
                    "evidence_refs": ["scan", "project_model_snapshot", "graph.nodes"],
                },
            )
        )

    risks.sort(key=lambda item: -item[0])
    return [item[1] for item in risks[:4]]


def _top_metric_item(values: dict[str, int]) -> Optional[Tuple[str, int]]:
    if not values:
        return None
    return sorted(values.items(), key=lambda item: (-item[1], item[0]))[0]


def _isolated_ratio(graph_nodes: list[GraphNode], graph_edges: list[GraphEdge]) -> float:
    if not graph_nodes:
        return 0.0
    connected = set()
    for edge in graph_edges:
        connected.add(edge.source_node_id)
        connected.add(edge.target_node_id)
    isolated = sum(1 for node in graph_nodes if node.id not in connected)
    return isolated / len(graph_nodes)


def _overview_text(system_type_guess: str, primary_stack: list[str], architecture_hints: list[str], top_risks: list[dict], confidence_summary: dict) -> str:
    stack_text = ", ".join(primary_stack[:3]) if primary_stack else "the detected stack"
    architecture_text = architecture_hints[0] if architecture_hints else "a general application structure"
    risk_text = ""
    if top_risks:
        risk_text = f" The main current risk signal is {top_risks[0]['category'].replace('_', ' ')}."
    return (
        f"This project most likely behaves like a {system_type_guess} built around {stack_text}. "
        f"Current deterministic signals suggest {architecture_text}. "
        f"Summary confidence is {confidence_summary['overall_label']}.{risk_text}"
    )


def _graph_provenance(graph_nodes: list[GraphNode], graph_edges: list[GraphEdge]) -> str:
    if not graph_nodes and not graph_edges:
        return "none"

    markers = Counter()
    for node in graph_nodes:
        markers[(node.data or {}).get("graph_source", "unknown")] += 1
    for edge in graph_edges:
        markers[(edge.data or {}).get("graph_source", "unknown")] += 1

    if len(markers) == 1:
        return next(iter(markers.keys()))
    return markers.most_common(1)[0][0]