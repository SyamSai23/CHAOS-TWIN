"""Canonical system model for CHAOS-TWIN.

This package defines the first normalized internal representation intended to
become the single source of truth for codebase understanding across scanning,
graph derivation, route journey analysis, code-peek evidence, simulation, and
future assistant features.

Practical v1 scope:
- Define explicit entities and typed relations.
- Make evidence and confidence first-class.
- Provide deterministic IDs.
- Add a scan adapter so current pipelines can start producing the model.
- Avoid rewriting existing APIs or storage in one step.
"""

from app.domain.system_model.adapters import build_project_model_from_scan
from app.domain.system_model.entities import (
    Component,
    DataStore,
    ExternalIntegration,
    ModelGeneration,
    Module,
    ProjectModel,
    Route,
    RuntimeNode,
    Service,
    SourceModel,
    SourceType,
)
from app.domain.system_model.evidence import (
    Confidence,
    ConfidenceLabel,
    Evidence,
    SourcePathKind,
    make_confidence,
)
from app.domain.system_model.relations import (
    InferenceStage,
    Relation,
    RelationDirection,
    RelationType,
)
from app.domain.system_model.validation import assert_valid_project_model, validate_project_model

__all__ = [
    "build_project_model_from_scan",
    "assert_valid_project_model",
    "validate_project_model",
    "ProjectModel",
    "SourceModel",
    "SourceType",
    "Component",
    "Module",
    "Route",
    "Service",
    "DataStore",
    "ExternalIntegration",
    "RuntimeNode",
    "Relation",
    "RelationType",
    "RelationDirection",
    "Evidence",
    "Confidence",
    "ConfidenceLabel",
    "SourcePathKind",
    "ModelGeneration",
    "InferenceStage",
    "make_confidence",
]