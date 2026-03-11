"""Typed relations for the canonical system model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.domain.system_model.evidence import Confidence


class RelationType(str, Enum):
    CONTAINS = "CONTAINS"
    EXPOSES_ROUTE = "EXPOSES_ROUTE"
    CALLS = "CALLS"
    READS_FROM = "READS_FROM"
    WRITES_TO = "WRITES_TO"
    DEPENDS_ON = "DEPENDS_ON"
    EMITS_TO = "EMITS_TO"
    CONSUMES_FROM = "CONSUMES_FROM"
    CONNECTS_TO = "CONNECTS_TO"
    USES_RUNTIME = "USES_RUNTIME"
    BACKED_BY = "BACKED_BY"
    INTEGRATES_WITH = "INTEGRATES_WITH"


class RelationDirection(str, Enum):
    DIRECTED = "directed"
    UNDIRECTED = "undirected"


class InferenceStage(str, Enum):
    SCAN = "scan"
    GRAPH = "graph"
    ROUTE_ANALYSIS = "route_analysis"
    DEEP_DIVE = "deep_dive"
    SIMULATION = "simulation"
    SEQUENCE = "sequence"
    MANUAL = "manual"


ALLOWED_RELATION_ENDPOINTS: dict[RelationType, tuple[set[str], set[str]]] = {
    RelationType.CONTAINS: (
        {"source", "component", "service"},
        {"component", "module", "service", "data_store", "external_integration", "runtime_node"},
    ),
    RelationType.EXPOSES_ROUTE: ({"component", "service"}, {"route"}),
    RelationType.CALLS: (
        {"component", "module", "route", "service"},
        {"component", "module", "route", "service", "external_integration"},
    ),
    RelationType.READS_FROM: ({"component", "module", "route", "service"}, {"data_store"}),
    RelationType.WRITES_TO: ({"component", "module", "route", "service"}, {"data_store"}),
    RelationType.DEPENDS_ON: (
        {"component", "module", "route", "service"},
        {"component", "module", "service", "runtime_node", "data_store", "external_integration"},
    ),
    RelationType.EMITS_TO: ({"component", "module", "route", "service"}, {"external_integration", "data_store"}),
    RelationType.CONSUMES_FROM: ({"component", "module", "route", "service"}, {"external_integration", "data_store"}),
    RelationType.CONNECTS_TO: (
        {"component", "service", "data_store", "external_integration"},
        {"component", "service", "data_store", "external_integration", "runtime_node"},
    ),
    RelationType.USES_RUNTIME: ({"component", "module", "service", "data_store"}, {"runtime_node"}),
    RelationType.BACKED_BY: ({"route", "service", "component"}, {"module", "runtime_node"}),
    RelationType.INTEGRATES_WITH: ({"component", "module", "route", "service"}, {"external_integration"}),
}


@dataclass
class Relation:
    """Normalized relation between two canonical IDs.

    Purpose:
    - Replaces ad hoc edge shapes with one typed linking mechanism.

    Stable ID:
    - Deterministic from source entity, relation type, target entity, and optional qualifier.

    Layer:
    - Derived.
    """

    id: str
    source_id: str
    target_id: str
    relation_type: RelationType
    direction: RelationDirection
    inference_stage: InferenceStage
    confidence: Confidence
    source_kind: str | None = None
    target_kind: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)