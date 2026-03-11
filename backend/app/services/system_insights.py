from __future__ import annotations

import hashlib
import logging
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.graph_edge import GraphEdge
from app.models.graph_node import GraphNode
from app.models.scan import Scan
from app.models.simulation_run import SimulationRun
from app.services.project_model_loader import load_valid_project_model_snapshot

logger = logging.getLogger(__name__)


@dataclass
class AnalysisArtifacts:
    scan: Scan
    snapshot_id: Optional[str]
    project_model: Optional[Any]
    graph_nodes: list[GraphNode]
    graph_edges: list[GraphEdge]
    graph_provenance: str
    simulation_run: Optional[SimulationRun]
    simulation_mode: Optional[str]


@dataclass
class DetectorResult:
    insights: list[dict]
    skipped_reason: Optional[str] = None


def load_latest_analysis_artifacts(project_id: str, db: Session) -> AnalysisArtifacts:
    scan = (
        db.query(Scan)
        .filter(Scan.project_id == project_id)
        .order_by(Scan.created_at.desc())
        .first()
    )
    if scan is None:
        raise ValueError("No scan found for this project")

    snapshot_id = None
    project_model = None
    snapshot_with_model = load_valid_project_model_snapshot(db, project_id=project_id, scan_id=scan.id)
    if snapshot_with_model is not None:
        snapshot, project_model = snapshot_with_model
        snapshot_id = snapshot.id

    graph_nodes = (
        db.query(GraphNode)
        .filter(GraphNode.project_id == project_id, GraphNode.scan_id == scan.id)
        .order_by(GraphNode.created_at.asc())
        .all()
    )
    graph_edges = (
        db.query(GraphEdge)
        .filter(GraphEdge.project_id == project_id, GraphEdge.scan_id == scan.id)
        .order_by(GraphEdge.created_at.asc())
        .all()
    )

    simulation_run = (
        db.query(SimulationRun)
        .filter(SimulationRun.project_id == project_id, SimulationRun.scan_id == scan.id)
        .order_by(SimulationRun.created_at.desc())
        .first()
    )
    simulation_mode = None
    if simulation_run is not None and isinstance(simulation_run.result, dict):
        simulation_mode = simulation_run.result.get("mode")

    return AnalysisArtifacts(
        scan=scan,
        snapshot_id=snapshot_id,
        project_model=project_model,
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
        graph_provenance=_graph_provenance(graph_nodes, graph_edges),
        simulation_run=simulation_run,
        simulation_mode=simulation_mode,
    )


def build_system_insights(project_id: str, db: Session) -> dict:
    artifacts = load_latest_analysis_artifacts(project_id=project_id, db=db)
    return build_system_insights_from_artifacts(project_id=project_id, artifacts=artifacts)


def build_system_insights_from_artifacts(project_id: str, artifacts: AnalysisArtifacts) -> dict:
    context = _build_graph_context(artifacts.graph_nodes, artifacts.graph_edges)
    detectors = [
        ("dependency_hotspot", _detect_dependency_hotspot),
        ("heavy_datastore_dependence", _detect_heavy_datastore_dependence),
        ("external_dependency_concentration", _detect_external_dependency_concentration),
        ("weak_architecture_understanding", _detect_weak_architecture_understanding),
        ("fallback_heavy_analysis_mode", _detect_fallback_heavy_analysis_mode),
        ("runtime_platform_concentration", _detect_runtime_platform_concentration),
        ("under_explained_zones", _detect_under_explained_zones),
    ]

    emitted: dict[str, dict] = {}
    skipped: list[str] = []

    for detector_name, detector in detectors:
        try:
            result = detector(project_id=project_id, artifacts=artifacts, context=context)
        except Exception:
            logger.exception(
                "System insights detector %s failed for project %s scan %s",
                detector_name,
                project_id,
                artifacts.scan.id,
            )
            skipped.append(f"{detector_name}: detector error")
            continue

        if result.skipped_reason:
            skipped.append(f"{detector_name}: {result.skipped_reason}")
        for insight in result.insights:
            emitted.setdefault(insight["insight_id"], insight)

    insights = sorted(
        emitted.values(),
        key=lambda insight: (
            -_severity_rank(insight["severity"]),
            -float(insight["confidence"]["score"]),
            insight["title"],
        ),
    )

    counts_by_severity = Counter(insight["severity"] for insight in insights)
    counts_by_category = Counter(insight["category"] for insight in insights)
    source_modes = _artifact_source_modes(artifacts)

    logger.info(
        "System insights built for project %s scan %s snapshot_used %s graph_provenance %s simulation_mode %s insight_count %s severity_counts %s category_counts %s detectors_skipped %s",
        project_id,
        artifacts.scan.id,
        artifacts.snapshot_id is not None,
        artifacts.graph_provenance,
        artifacts.simulation_mode,
        len(insights),
        dict(counts_by_severity),
        dict(counts_by_category),
        skipped,
    )

    return {
        "project_id": project_id,
        "scan_id": artifacts.scan.id,
        "snapshot_id": artifacts.snapshot_id,
        "graph_scan_id": artifacts.scan.id if artifacts.graph_nodes else None,
        "graph_provenance": artifacts.graph_provenance,
        "insight_count": len(insights),
        "counts_by_severity": dict(sorted(counts_by_severity.items())),
        "counts_by_category": dict(sorted(counts_by_category.items())),
        "insights": insights,
        "generated_from": {
            "generated_at": datetime.now(timezone.utc),
            "latest_scan_created_at": artifacts.scan.created_at,
            "canonical_snapshot_used": artifacts.snapshot_id is not None,
            "graph_used": bool(artifacts.graph_nodes),
            "graph_provenance": artifacts.graph_provenance,
            "simulation_used": artifacts.simulation_run is not None,
            "simulation_mode": artifacts.simulation_mode,
            "source_modes": source_modes,
            "detectors_run": [name for name, _ in detectors],
            "detectors_skipped": skipped,
        },
    }


def build_summary_risks_from_insights(insights: list[dict]) -> list[dict]:
    risks: list[dict] = []
    for insight in insights:
        if insight["category"] != "risk":
            continue
        evidence_labels = [ref.get("label") or ref.get("ref_id") for ref in insight.get("evidence_refs", [])]
        risks.append(
            {
                "category": insight["subtype"],
                "severity": insight["severity"],
                "confidence": insight["confidence"]["label"],
                "explanation": insight["explanation"],
                "supporting_ids": (
                    insight.get("supporting_entity_ids", [])
                    + insight.get("supporting_graph_node_ids", [])
                    + insight.get("supporting_graph_edge_ids", [])
                )[:6],
                "evidence_refs": evidence_labels[:4],
            }
        )
    return risks[:4]


def _detect_dependency_hotspot(project_id: str, artifacts: AnalysisArtifacts, context: dict) -> DetectorResult:
    if not artifacts.graph_nodes or not artifacts.graph_edges:
        return DetectorResult(insights=[], skipped_reason="requires a non-empty graph")

    candidates: list[tuple[float, GraphNode, int, int]] = []
    max_degree = max((context["degree"].get(node.id, 0) for node in artifacts.graph_nodes), default=0)
    impacted_count = len(artifacts.simulation_run.impacted_nodes) if artifacts.simulation_run is not None else 0
    simulated_node_id = artifacts.simulation_run.failed_node_id if artifacts.simulation_run is not None else None

    for node in artifacts.graph_nodes:
        if node.node_type not in {"component", "database", "runtime", "external"}:
            continue
        degree = context["degree"].get(node.id, 0)
        dependent_count = len({edge.source_node_id for edge in context["incoming_edges"].get(node.id, [])})
        if degree < 2 and not (simulated_node_id == node.id and impacted_count >= 2):
            continue
        simulation_bonus = 0.0
        if simulated_node_id == node.id:
            simulation_bonus = min(0.35, impacted_count / max(1, len(artifacts.graph_nodes) - 1))
        score = (degree / max(1, max_degree)) * 0.65 + simulation_bonus + (0.08 if node.canonical_entity_id else 0.0)
        candidates.append((score, node, degree, dependent_count))

    if not candidates:
        return DetectorResult(insights=[], skipped_reason="no node showed enough centrality to justify a hotspot insight")

    score, node, degree, dependent_count = sorted(candidates, key=lambda item: (-item[0], -item[2], item[1].label))[0]
    severity = "high" if score >= 0.8 or (simulated_node_id == node.id and impacted_count >= 3) else "medium"
    confidence = _make_confidence(
        0.86 if node.canonical_entity_id or simulated_node_id == node.id else 0.74,
        [
            "derived from persisted graph centrality",
            "boosted by latest simulation impact" if simulated_node_id == node.id else "no matching latest simulation boost",
            "canonical provenance available" if node.canonical_entity_id else "graph-only evidence",
        ],
    )
    incident_edges = _incident_edges(node.id, context)
    evidence_refs = [_graph_node_ref(node)]
    evidence_refs.extend(_graph_edge_refs(incident_edges[:4], context["node_by_id"]))
    evidence_refs.extend(_canonical_entity_evidence_refs(artifacts.project_model, node.canonical_entity_id, limit=2))
    if simulated_node_id == node.id and artifacts.simulation_run is not None:
        evidence_refs.append(_simulation_ref(artifacts.simulation_run, "latest_simulation_from_hotspot"))

    explanation = (
        f"{node.label} was detected as a dependency hotspot because {degree} graph links currently pass through it"
        f" and {dependent_count} upstream dependents rely on it. This matters because concentrated dependency flow can widen"
        f" blast radius when the node fails. Current evidence comes from persisted graph centrality"
        f"{f' and the latest simulation impacting {impacted_count} downstream nodes' if simulated_node_id == node.id else ''}."
        f" Certainty is {confidence['label']} because the signal is grounded in current graph structure"
        f"{', canonical provenance' if node.canonical_entity_id else ''}{' and simulation metadata' if simulated_node_id == node.id else ''}."
    )

    return DetectorResult(
        insights=[
            _build_insight(
                project_id=project_id,
                artifacts=artifacts,
                category="risk",
                subtype="dependency_hotspot",
                severity=severity,
                confidence=confidence,
                title=f"{node.label} is a dependency hotspot",
                explanation=explanation,
                evidence_refs=evidence_refs,
                supporting_entity_ids=_entity_ids_for_node(node),
                supporting_graph_node_ids=[node.id],
                supporting_graph_edge_ids=[edge.id for edge in incident_edges[:6]],
                source_modes=_source_modes(artifacts, include_scan=False, include_graph=True, include_snapshot=bool(node.canonical_entity_id), include_simulation=simulated_node_id == node.id),
                tags=[node.node_type, "blast-radius"],
            )
        ]
    )


def _detect_heavy_datastore_dependence(project_id: str, artifacts: AnalysisArtifacts, context: dict) -> DetectorResult:
    database_nodes = [node for node in artifacts.graph_nodes if node.node_type == "database"]
    component_nodes = [node for node in artifacts.graph_nodes if node.node_type == "component"]
    if not database_nodes or not component_nodes:
        return DetectorResult(insights=[], skipped_reason="requires database and component nodes in the current graph")

    candidates: list[tuple[int, float, GraphNode, list[GraphEdge]]] = []
    for node in database_nodes:
        incoming_edges = [
            edge
            for edge in context["incoming_edges"].get(node.id, [])
            if context["node_by_id"].get(edge.source_node_id) is not None
            and context["node_by_id"][edge.source_node_id].node_type == "component"
        ]
        dependents = sorted({edge.source_node_id for edge in incoming_edges})
        if len(dependents) < 2:
            continue
        share = len(dependents) / max(1, len(component_nodes))
        if share < 0.5 and len(database_nodes) > 1:
            continue
        candidates.append((len(dependents), share, node, incoming_edges))

    if not candidates:
        return DetectorResult(insights=[], skipped_reason="no datastore showed enough concentrated dependency to justify an insight")

    dependent_count, share, node, incoming_edges = sorted(candidates, key=lambda item: (-item[0], -item[1], item[2].label))[0]
    severity = "high" if dependent_count >= 3 and (share >= 0.75 or len(database_nodes) == 1) else "medium"
    confidence = _make_confidence(
        0.84 if node.canonical_entity_id else 0.7,
        [
            "derived from datastore incoming dependency count",
            "supported by canonical datastore provenance" if node.canonical_entity_id else "supported by persisted graph edges only",
        ],
    )
    explanation = (
        f"Datastore dependence appears concentrated around {node.label}: {dependent_count} component nodes currently depend on it,"
        f" representing about {int(round(share * 100))}% of graph-visible components. This matters because a shared datastore"
        f" can become a single operational bottleneck or failure amplifier. Current evidence comes from datastore-linked graph edges"
        f"{', with canonical backing' if node.canonical_entity_id else ''}. Certainty is {confidence['label']} because the concentration"
        f" is directly observable in persisted dependency edges."
    )
    evidence_refs = [_graph_node_ref(node)]
    evidence_refs.extend(_graph_edge_refs(incoming_edges[:4], context["node_by_id"]))
    evidence_refs.extend(_canonical_entity_evidence_refs(artifacts.project_model, node.canonical_entity_id, limit=2))
    evidence_refs.append(_scan_ref(artifacts.scan.id, "docker_services", "latest scan infrastructure metadata"))

    return DetectorResult(
        insights=[
            _build_insight(
                project_id=project_id,
                artifacts=artifacts,
                category="risk",
                subtype="heavy_datastore_dependence",
                severity=severity,
                confidence=confidence,
                title=f"{node.label} concentrates datastore dependencies",
                explanation=explanation,
                evidence_refs=evidence_refs,
                supporting_entity_ids=_entity_ids_for_node(node),
                supporting_graph_node_ids=[node.id],
                supporting_graph_edge_ids=[edge.id for edge in incoming_edges[:6]],
                source_modes=_source_modes(artifacts, include_scan=True, include_graph=True, include_snapshot=bool(node.canonical_entity_id), include_simulation=False),
                tags=["datastore", "concentration"],
            )
        ]
    )


def _detect_external_dependency_concentration(project_id: str, artifacts: AnalysisArtifacts, context: dict) -> DetectorResult:
    external_nodes = [node for node in artifacts.graph_nodes if node.node_type == "external"]
    component_nodes = [node for node in artifacts.graph_nodes if node.node_type == "component"]
    if not external_nodes or not component_nodes:
        return DetectorResult(insights=[], skipped_reason="requires external dependency nodes and component nodes in the graph")

    candidates: list[tuple[int, float, GraphNode, list[GraphEdge]]] = []
    for node in external_nodes:
        incoming_edges = [
            edge
            for edge in context["incoming_edges"].get(node.id, [])
            if context["node_by_id"].get(edge.source_node_id) is not None
            and context["node_by_id"][edge.source_node_id].node_type == "component"
        ]
        dependents = sorted({edge.source_node_id for edge in incoming_edges})
        if len(dependents) < 2:
            continue
        share = len(dependents) / max(1, len(component_nodes))
        if share < 0.5 and len(external_nodes) > 1:
            continue
        candidates.append((len(dependents), share, node, incoming_edges))

    if not candidates:
        return DetectorResult(insights=[], skipped_reason="no external integration showed enough dependency concentration")

    dependent_count, share, node, incoming_edges = sorted(candidates, key=lambda item: (-item[0], -item[1], item[2].label))[0]
    confidence = _make_confidence(
        0.78 if node.canonical_entity_id else 0.68,
        [
            "derived from external dependency fan-in",
            "canonical evidence available" if node.canonical_entity_id else "graph-only persisted evidence",
        ],
    )
    explanation = (
        f"External dependency usage appears concentrated around {node.label}: {dependent_count} component nodes currently connect to it,"
        f" representing about {int(round(share * 100))}% of graph-visible components. This matters because outages or contract changes"
        f" in a single provider can affect multiple parts of the system at once. Current evidence comes from persisted external-dependency"
        f" edges{', plus canonical provenance' if node.canonical_entity_id else ''}. Certainty is {confidence['label']} because the"
        f" concentration is visible in current graph links."
    )
    evidence_refs = [_graph_node_ref(node)]
    evidence_refs.extend(_graph_edge_refs(incoming_edges[:4], context["node_by_id"]))
    evidence_refs.extend(_canonical_entity_evidence_refs(artifacts.project_model, node.canonical_entity_id, limit=2))
    evidence_refs.append(_scan_ref(artifacts.scan.id, "dependencies", "latest dependency inventory"))

    return DetectorResult(
        insights=[
            _build_insight(
                project_id=project_id,
                artifacts=artifacts,
                category="risk",
                subtype="external_dependency_concentration",
                severity="medium",
                confidence=confidence,
                title=f"{node.label} concentrates external dependency usage",
                explanation=explanation,
                evidence_refs=evidence_refs,
                supporting_entity_ids=_entity_ids_for_node(node),
                supporting_graph_node_ids=[node.id],
                supporting_graph_edge_ids=[edge.id for edge in incoming_edges[:6]],
                source_modes=_source_modes(artifacts, include_scan=True, include_graph=True, include_snapshot=bool(node.canonical_entity_id), include_simulation=False),
                tags=["external", "concentration"],
            )
        ]
    )


def _detect_weak_architecture_understanding(project_id: str, artifacts: AnalysisArtifacts, context: dict) -> DetectorResult:
    scan_component_count = len(artifacts.scan.components or [])
    graph_component_count = len(context["component_nodes"])
    reasons: list[str] = []
    evidence_refs: list[dict] = [_scan_ref(artifacts.scan.id, "components", "latest component scan metadata")]

    if not artifacts.graph_nodes:
        reasons.append("no same-scan graph is currently available")
    if artifacts.snapshot_id is None:
        reasons.append("no validated canonical snapshot is available")
    if scan_component_count > 0 and graph_component_count < scan_component_count:
        reasons.append(f"only {graph_component_count} graph component nodes are present for {scan_component_count} scanned components")

    if not reasons:
        return DetectorResult(insights=[], skipped_reason="architecture coverage looks strong enough that a weak-understanding insight would overstate uncertainty")

    if artifacts.graph_nodes:
        evidence_refs.append(_scan_ref(artifacts.scan.id, "routes", "latest route metadata"))
    confidence = _make_confidence(0.9, ["direct artifact coverage diagnostic"]) 
    explanation = (
        f"Architecture understanding is currently weak because {'; '.join(reasons)}. This matters because low artifact coverage"
        f" limits how precisely downstream features can explain dependencies or blast radius. Current evidence comes from comparing"
        f" the latest scan with same-scan canonical and graph artifacts. Certainty is {confidence['label']} because the gap is a"
        f" direct artifact-state observation rather than an inferred code smell."
    )

    return DetectorResult(
        insights=[
            _build_insight(
                project_id=project_id,
                artifacts=artifacts,
                category="analysis_diagnostic",
                subtype="weak_architecture_understanding",
                severity="medium",
                confidence=confidence,
                title="Architecture understanding is currently weak",
                explanation=explanation,
                evidence_refs=evidence_refs,
                supporting_entity_ids=[],
                supporting_graph_node_ids=[],
                supporting_graph_edge_ids=[],
                source_modes=_source_modes(artifacts, include_scan=True, include_graph=bool(artifacts.graph_nodes), include_snapshot=artifacts.snapshot_id is not None, include_simulation=False),
                tags=["coverage", "certainty"],
            )
        ]
    )


def _detect_fallback_heavy_analysis_mode(project_id: str, artifacts: AnalysisArtifacts, context: dict) -> DetectorResult:
    fallback_reasons: list[str] = []
    if artifacts.snapshot_id is None:
        fallback_reasons.append("canonical snapshot is unavailable")
    if artifacts.graph_provenance not in {"canonical_snapshot", "none"}:
        fallback_reasons.append(f"graph provenance is {artifacts.graph_provenance}")
    if artifacts.simulation_mode == "basic":
        fallback_reasons.append("latest simulation used basic propagation")

    if not fallback_reasons:
        return DetectorResult(insights=[], skipped_reason="analysis is not currently fallback-heavy")

    confidence = _make_confidence(0.92, ["directly derived from persisted artifact provenance"]) 
    explanation = (
        f"Current analysis is fallback-heavy because {'; '.join(fallback_reasons)}. This matters because fallback paths preserve"
        f" safety but reduce semantic precision for downstream insights and explanations. Current evidence comes from same-scan"
        f" snapshot, graph provenance, and simulation metadata. Certainty is {confidence['label']} because these are persisted mode"
        f" markers rather than inferred behavior."
    )
    evidence_refs = [
        _scan_ref(artifacts.scan.id, "scan", "latest scan artifact"),
        _scan_ref(artifacts.scan.id, "graph", f"graph provenance: {artifacts.graph_provenance}"),
    ]
    if artifacts.simulation_run is not None:
        evidence_refs.append(_simulation_ref(artifacts.simulation_run, "latest_simulation_mode"))

    severity = "medium" if artifacts.graph_provenance == "raw_scan_fallback" or artifacts.simulation_mode == "basic" else "low"
    return DetectorResult(
        insights=[
            _build_insight(
                project_id=project_id,
                artifacts=artifacts,
                category="analysis_diagnostic",
                subtype="fallback_heavy_analysis_mode",
                severity=severity,
                confidence=confidence,
                title="Current analysis relies on fallback paths",
                explanation=explanation,
                evidence_refs=evidence_refs,
                supporting_entity_ids=[],
                supporting_graph_node_ids=[],
                supporting_graph_edge_ids=[],
                source_modes=_source_modes(artifacts, include_scan=True, include_graph=bool(artifacts.graph_nodes), include_snapshot=artifacts.snapshot_id is not None, include_simulation=artifacts.simulation_run is not None),
                tags=["fallback", "diagnostic"],
            )
        ]
    )


def _detect_runtime_platform_concentration(project_id: str, artifacts: AnalysisArtifacts, context: dict) -> DetectorResult:
    runtime_nodes = [node for node in artifacts.graph_nodes if node.node_type == "runtime"]
    component_nodes = [node for node in artifacts.graph_nodes if node.node_type == "component"]
    if not runtime_nodes or not component_nodes:
        return DetectorResult(insights=[], skipped_reason="requires runtime and component nodes in the graph")

    candidates: list[tuple[int, float, GraphNode, list[GraphEdge]]] = []
    for node in runtime_nodes:
        incoming_edges = [
            edge
            for edge in context["incoming_edges"].get(node.id, [])
            if context["node_by_id"].get(edge.source_node_id) is not None
            and context["node_by_id"][edge.source_node_id].node_type == "component"
        ]
        dependents = sorted({edge.source_node_id for edge in incoming_edges})
        if len(dependents) < 2:
            continue
        share = len(dependents) / max(1, len(component_nodes))
        if share < 0.6 and len(runtime_nodes) > 1:
            continue
        candidates.append((len(dependents), share, node, incoming_edges))

    if not candidates:
        return DetectorResult(insights=[], skipped_reason="no runtime node showed strong enough concentration")

    dependent_count, share, node, incoming_edges = sorted(candidates, key=lambda item: (-item[0], -item[1], item[2].label))[0]
    confidence = _make_confidence(
        0.82 if node.canonical_entity_id else 0.72,
        [
            "derived from runtime fan-in",
            "canonical runtime provenance available" if node.canonical_entity_id else "supported by graph runtime edges",
        ],
    )
    explanation = (
        f"Runtime platform concentration was detected around {node.label}: {dependent_count} component nodes currently run on it,"
        f" representing about {int(round(share * 100))}% of graph-visible components. This matters because shared runtime or"
        f" infrastructure concentration can amplify deployment or platform faults. Current evidence comes from runtime-linked graph"
        f" edges{', with canonical runtime provenance' if node.canonical_entity_id else ''}. Certainty is {confidence['label']}"
        f" because the dependency fan-in is directly visible in the current graph."
    )
    evidence_refs = [_graph_node_ref(node)]
    evidence_refs.extend(_graph_edge_refs(incoming_edges[:4], context["node_by_id"]))
    evidence_refs.extend(_canonical_entity_evidence_refs(artifacts.project_model, node.canonical_entity_id, limit=2))

    return DetectorResult(
        insights=[
            _build_insight(
                project_id=project_id,
                artifacts=artifacts,
                category="risk",
                subtype="runtime_platform_concentration",
                severity="medium" if share < 0.85 else "high",
                confidence=confidence,
                title=f"{node.label} concentrates runtime dependence",
                explanation=explanation,
                evidence_refs=evidence_refs,
                supporting_entity_ids=_entity_ids_for_node(node),
                supporting_graph_node_ids=[node.id],
                supporting_graph_edge_ids=[edge.id for edge in incoming_edges[:6]],
                source_modes=_source_modes(artifacts, include_scan=False, include_graph=True, include_snapshot=bool(node.canonical_entity_id), include_simulation=False),
                tags=["runtime", "concentration"],
            )
        ]
    )


def _detect_under_explained_zones(project_id: str, artifacts: AnalysisArtifacts, context: dict) -> DetectorResult:
    if not artifacts.graph_nodes:
        return DetectorResult(insights=[], skipped_reason="requires a graph to identify disconnected or under-explained zones")

    isolated_component_nodes = [
        node for node in context["component_nodes"] if context["degree"].get(node.id, 0) == 0
    ]
    missing_component_count = max(0, len(artifacts.scan.components or []) - len(context["component_nodes"]))
    disconnected_component_count = sum(
        1
        for group in context["connected_components"]
        if len(group) <= 2 and any(context["node_by_id"][node_id].node_type == "component" for node_id in group)
    )

    if not isolated_component_nodes and missing_component_count == 0 and disconnected_component_count == 0:
        return DetectorResult(insights=[], skipped_reason="no isolated or missing component zones were detected")

    isolated_labels = [node.label for node in isolated_component_nodes[:3]]
    reasons: list[str] = []
    if missing_component_count:
        reasons.append(f"{missing_component_count} scanned components do not appear as graph component nodes")
    if isolated_labels:
        reasons.append(f"isolated component nodes include {', '.join(isolated_labels)}")
    if disconnected_component_count:
        reasons.append(f"{disconnected_component_count} small disconnected graph zones are present")

    confidence = _make_confidence(0.84, ["derived from graph connectivity and scan-to-graph coverage gaps"]) 
    explanation = (
        f"Some architecture zones remain under-explained because {'; '.join(reasons)}. This matters because disconnected or"
        f" missing zones reduce confidence in dependency narratives and make downstream explanations less complete. Current evidence"
        f" comes from scan component counts and graph connectivity structure. Certainty is {confidence['label']} because the gaps"
        f" are directly observable in persisted artifacts."
    )
    evidence_refs = [_scan_ref(artifacts.scan.id, "components", "latest component scan metadata")]
    evidence_refs.extend(_graph_node_ref(node) for node in isolated_component_nodes[:3])

    return DetectorResult(
        insights=[
            _build_insight(
                project_id=project_id,
                artifacts=artifacts,
                category="analysis_diagnostic",
                subtype="under_explained_zones",
                severity="medium" if missing_component_count or disconnected_component_count > 1 else "low",
                confidence=confidence,
                title="Some architecture zones remain under-explained",
                explanation=explanation,
                evidence_refs=evidence_refs,
                supporting_entity_ids=[],
                supporting_graph_node_ids=[node.id for node in isolated_component_nodes[:6]],
                supporting_graph_edge_ids=[],
                source_modes=_source_modes(artifacts, include_scan=True, include_graph=True, include_snapshot=False, include_simulation=False),
                tags=["coverage", "connectivity"],
            )
        ]
    )


def _build_graph_context(graph_nodes: list[GraphNode], graph_edges: list[GraphEdge]) -> dict:
    node_by_id = {node.id: node for node in graph_nodes}
    incoming_edges: dict[str, list[GraphEdge]] = defaultdict(list)
    outgoing_edges: dict[str, list[GraphEdge]] = defaultdict(list)
    degree: Counter = Counter()
    adjacency: dict[str, set[str]] = defaultdict(set)

    for edge in graph_edges:
        incoming_edges[edge.target_node_id].append(edge)
        outgoing_edges[edge.source_node_id].append(edge)
        degree[edge.source_node_id] += 1
        degree[edge.target_node_id] += 1
        adjacency[edge.source_node_id].add(edge.target_node_id)
        adjacency[edge.target_node_id].add(edge.source_node_id)

    connected_components = _connected_components(node_by_id, adjacency)
    return {
        "node_by_id": node_by_id,
        "incoming_edges": incoming_edges,
        "outgoing_edges": outgoing_edges,
        "degree": degree,
        "connected_components": connected_components,
        "component_nodes": [node for node in graph_nodes if node.node_type == "component"],
    }


def _connected_components(node_by_id: dict[str, GraphNode], adjacency: dict[str, set[str]]) -> list[list[str]]:
    seen: set[str] = set()
    groups: list[list[str]] = []
    for node_id in node_by_id:
        if node_id in seen:
            continue
        queue = deque([node_id])
        seen.add(node_id)
        group: list[str] = []
        while queue:
            current = queue.popleft()
            group.append(current)
            for neighbor in adjacency.get(current, set()):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
        groups.append(sorted(group))
    return groups


def _graph_provenance(graph_nodes: list[GraphNode], graph_edges: list[GraphEdge]) -> str:
    if not graph_nodes and not graph_edges:
        return "none"

    markers = Counter()
    for node in graph_nodes:
        markers[_safe_graph_source(node.data)] += 1
    for edge in graph_edges:
        markers[_safe_graph_source(edge.data)] += 1
    if len(markers) == 1:
        return next(iter(markers.keys()))
    return markers.most_common(1)[0][0]


def _safe_graph_source(data: Any) -> str:
    if isinstance(data, dict):
        return str(data.get("graph_source", "unknown"))
    return "unknown"


def _artifact_source_modes(artifacts: AnalysisArtifacts) -> list[str]:
    return _source_modes(
        artifacts,
        include_scan=True,
        include_graph=bool(artifacts.graph_nodes),
        include_snapshot=artifacts.snapshot_id is not None,
        include_simulation=artifacts.simulation_run is not None,
    )


def _source_modes(
    artifacts: AnalysisArtifacts,
    include_scan: bool,
    include_graph: bool,
    include_snapshot: bool,
    include_simulation: bool,
) -> list[str]:
    source_modes: list[str] = []
    if include_scan:
        source_modes.append("scan")
    if include_snapshot and artifacts.snapshot_id is not None:
        source_modes.append("canonical_snapshot")
    if include_graph:
        source_modes.append(f"graph:{artifacts.graph_provenance}")
    if include_simulation and artifacts.simulation_mode:
        source_modes.append(f"simulation:{artifacts.simulation_mode}")
    return source_modes


def _build_insight(
    project_id: str,
    artifacts: AnalysisArtifacts,
    category: str,
    subtype: str,
    severity: str,
    confidence: dict,
    title: str,
    explanation: str,
    evidence_refs: list[dict],
    supporting_entity_ids: list[str],
    supporting_graph_node_ids: list[str],
    supporting_graph_edge_ids: list[str],
    source_modes: list[str],
    tags: list[str],
) -> dict:
    insight_id = _make_insight_id(
        project_id,
        artifacts.scan.id,
        subtype,
        *(supporting_entity_ids + supporting_graph_node_ids + supporting_graph_edge_ids),
    )
    return {
        "insight_id": insight_id,
        "category": category,
        "subtype": subtype,
        "severity": severity,
        "confidence": confidence,
        "title": title,
        "explanation": explanation,
        "evidence_refs": evidence_refs[:8],
        "supporting_entity_ids": sorted(set(supporting_entity_ids)),
        "supporting_graph_node_ids": sorted(set(supporting_graph_node_ids)),
        "supporting_graph_edge_ids": sorted(set(supporting_graph_edge_ids)),
        "scan_id": artifacts.scan.id,
        "snapshot_id": artifacts.snapshot_id,
        "graph_scan_id": artifacts.scan.id if artifacts.graph_nodes else None,
        "graph_provenance": artifacts.graph_provenance,
        "source_modes": source_modes,
        "tags": sorted(set(tags)),
    }


def _make_insight_id(project_id: str, scan_id: str, subtype: str, *supporting_ids: str) -> str:
    payload = "::".join([project_id, scan_id, subtype, *sorted(supporting_ids)])
    return f"insight:{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16]}"


def _make_confidence(score: float, reasons: list[str]) -> dict:
    safe_score = max(0.0, min(score, 0.99))
    return {
        "score": round(safe_score, 3),
        "label": "high" if safe_score >= 0.8 else "medium" if safe_score >= 0.55 else "low",
        "reasons": reasons,
    }


def _scan_ref(scan_id: str, field_name: str, label: str, metadata: Optional[dict] = None) -> dict:
    return {
        "ref_type": "scan_field",
        "artifact": "scan",
        "ref_id": f"{scan_id}:{field_name}",
        "label": label,
        "file_path": None,
        "metadata": metadata or {},
    }


def _graph_node_ref(node: GraphNode) -> dict:
    return {
        "ref_type": "graph_node",
        "artifact": "graph",
        "ref_id": node.id,
        "label": f"{node.label} ({node.node_type})",
        "file_path": None,
        "metadata": {
            "graph_source": _safe_graph_source(node.data),
            "canonical_entity_id": node.canonical_entity_id,
        },
    }


def _graph_edge_refs(edges: list[GraphEdge], node_by_id: dict[str, GraphNode]) -> list[dict]:
    refs: list[dict] = []
    for edge in edges:
        source = node_by_id.get(edge.source_node_id)
        target = node_by_id.get(edge.target_node_id)
        refs.append(
            {
                "ref_type": "graph_edge",
                "artifact": "graph",
                "ref_id": edge.id,
                "label": f"{source.label if source else edge.source_node_id} -> {target.label if target else edge.target_node_id} ({edge.edge_type})",
                "file_path": None,
                "metadata": {
                    "graph_source": _safe_graph_source(edge.data),
                    "canonical_relation_id": edge.canonical_relation_id,
                    "canonical_relation_type": edge.canonical_relation_type,
                },
            }
        )
    return refs


def _simulation_ref(simulation_run: SimulationRun, label: str) -> dict:
    return {
        "ref_type": "simulation_run",
        "artifact": "simulation",
        "ref_id": simulation_run.id,
        "label": label,
        "file_path": None,
        "metadata": {
            "failed_node_id": simulation_run.failed_node_id,
            "severity": simulation_run.severity,
            "impacted_count": len(simulation_run.impacted_nodes or []),
            "mode": (simulation_run.result or {}).get("mode") if isinstance(simulation_run.result, dict) else None,
        },
    }


def _canonical_entity_evidence_refs(project_model, entity_id: Optional[str], limit: int) -> list[dict]:
    if project_model is None or not entity_id:
        return []
    entity = project_model.get_entity(entity_id)
    if entity is None:
        return []
    refs: list[dict] = []
    for evidence_id in list(getattr(entity, "evidence_ids", []))[:limit]:
        evidence = project_model.evidence.get(evidence_id)
        if evidence is None:
            continue
        refs.append(
            {
                "ref_type": "canonical_evidence",
                "artifact": "canonical_snapshot",
                "ref_id": evidence.id,
                "label": evidence.snippet_summary or evidence.file_path,
                "file_path": evidence.file_path,
                "metadata": {
                    "symbol": evidence.symbol,
                    "rule_name": evidence.rule_name,
                    "detector_type": evidence.detector_type,
                },
            }
        )
    return refs


def _entity_ids_for_node(node: GraphNode) -> list[str]:
    if node.canonical_entity_id:
        return [node.canonical_entity_id]
    return []


def _incident_edges(node_id: str, context: dict) -> list[GraphEdge]:
    edges = context["incoming_edges"].get(node_id, []) + context["outgoing_edges"].get(node_id, [])
    seen: dict[str, GraphEdge] = {edge.id: edge for edge in edges}
    return list(seen.values())


def _severity_rank(severity: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(severity, 0)