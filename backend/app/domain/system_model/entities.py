"""Entity definitions for the canonical system model.

Each entity is intentionally explicit in v1. The goal is to give scanner, graph,
route analysis, simulation, and future chat/code-peek features a common language
without forcing a full pipeline rewrite yet.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from app.domain.system_model.evidence import Confidence, Evidence
from app.domain.system_model.relations import Relation


class ModelLayer(str, Enum):
    USER_FACING = "user_facing"
    DERIVED = "derived"
    INTERNAL = "internal"


class SourceType(str, Enum):
    UPLOAD_ARCHIVE = "upload_archive"
    WORKSPACE = "workspace"
    REPOSITORY = "repository"
    SNAPSHOT = "snapshot"


class EntityKind(str, Enum):
    SOURCE = "source"
    COMPONENT = "component"
    MODULE = "module"
    ROUTE = "route"
    SERVICE = "service"
    DATA_STORE = "data_store"
    EXTERNAL_INTEGRATION = "external_integration"
    RUNTIME_NODE = "runtime_node"


@dataclass
class SourceModel:
    """Raw source identity and ingestion metadata.

    Purpose:
    - Represents the source material being analyzed.
    - Separates source identity from the normalized ProjectModel view.

    Stable ID:
    - Derived from project_id + logical_root + source_type + snapshot_ref.

    Links:
    - Referenced by every entity through source_ids.

    Layer:
    - Internal.
    """

    id: str
    project_id: str
    logical_root: str
    source_type: SourceType
    source_ref: str
    snapshot_ref: Optional[str] = None
    ingestion_metadata: dict[str, Any] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)
    confidence: Optional[Confidence] = None
    layer: ModelLayer = ModelLayer.INTERNAL
    entity_kind: EntityKind = EntityKind.SOURCE


@dataclass
class Component:
    """User-facing deployable or logical application boundary.

    Stable ID:
    - Derived from root_path and aligned with existing component_key behavior.

    Links:
    - Contains Modules and optionally Services.
    - Exposes Routes.
    - Uses RuntimeNodes.
    - Connects to DataStores and ExternalIntegrations.

    Layer:
    - User-facing.
    """

    id: str
    source_ids: list[str]
    name: str
    kind: str
    root_path: str
    confidence: Confidence
    evidence_ids: list[str] = field(default_factory=list)
    entry_file: Optional[str] = None
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    layer: ModelLayer = ModelLayer.USER_FACING
    entity_kind: EntityKind = EntityKind.COMPONENT


@dataclass
class Module:
    """Internal code unit, typically a file-backed module.

    Stable ID:
    - Derived from component_id + relative file path.

    Links:
    - Belongs to a Component via CONTAINS.
    - May back Routes or Services.

    Layer:
    - Internal.
    """

    id: str
    source_ids: list[str]
    component_id: str
    path: str
    confidence: Confidence
    evidence_ids: list[str] = field(default_factory=list)
    name: Optional[str] = None
    kind: Optional[str] = None
    symbol: Optional[str] = None
    symbol_kind: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    layer: ModelLayer = ModelLayer.INTERNAL
    entity_kind: EntityKind = EntityKind.MODULE


@dataclass
class Route:
    """User-facing API route or endpoint.

    Stable ID:
    - Derived from method + path + file_path and aligned with existing route_id behavior.

    Links:
    - Exposed by a Component.
    - Optionally backed by a Module or Service.

    Layer:
    - User-facing.
    """

    id: str
    source_ids: list[str]
    method: str
    path: str
    file_path: str
    component_id: str
    confidence: Confidence
    evidence_ids: list[str] = field(default_factory=list)
    handler_name: Optional[str] = None
    parameters: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    layer: ModelLayer = ModelLayer.USER_FACING
    entity_kind: EntityKind = EntityKind.ROUTE


@dataclass
class Service:
    """Derived logical service capability within a component boundary.

    Stable ID:
    - Derived from scope + service name.

    Links:
    - Usually contained by a Component.
    - May be backed by Modules and called by Routes.

    Layer:
    - Derived.
    """

    id: str
    source_ids: list[str]
    name: str
    confidence: Confidence
    evidence_ids: list[str] = field(default_factory=list)
    component_id: Optional[str] = None
    module_ids: list[str] = field(default_factory=list)
    kind: Optional[str] = None
    symbol: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    layer: ModelLayer = ModelLayer.DERIVED
    entity_kind: EntityKind = EntityKind.SERVICE


@dataclass
class DataStore:
    """User-facing storage system or database dependency.

    Stable ID:
    - Derived from source + store name + store type.

    Links:
    - Connected to Components.
    - Can later support typed READS_FROM and WRITES_TO relations.

    Layer:
    - User-facing.
    """

    id: str
    source_ids: list[str]
    name: str
    kind: str
    confidence: Confidence
    evidence_ids: list[str] = field(default_factory=list)
    technology: Optional[str] = None
    runtime_node_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    layer: ModelLayer = ModelLayer.USER_FACING
    entity_kind: EntityKind = EntityKind.DATA_STORE


@dataclass
class ExternalIntegration:
    """User-facing external system integration.

    Stable ID:
    - Derived from source + integration name + integration type.

    Links:
    - Connected from Components and eventually callable Services.

    Layer:
    - User-facing.
    """

    id: str
    source_ids: list[str]
    name: str
    kind: str
    confidence: Confidence
    evidence_ids: list[str] = field(default_factory=list)
    provider: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    layer: ModelLayer = ModelLayer.USER_FACING
    entity_kind: EntityKind = EntityKind.EXTERNAL_INTEGRATION


@dataclass
class RuntimeNode:
    """Derived runtime or execution environment used by code entities.

    Stable ID:
    - Derived from source + runtime name.

    Links:
    - Used by Components or DataStores.

    Layer:
    - Derived.
    """

    id: str
    source_ids: list[str]
    name: str
    kind: str
    confidence: Confidence
    evidence_ids: list[str] = field(default_factory=list)
    version: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    layer: ModelLayer = ModelLayer.DERIVED
    entity_kind: EntityKind = EntityKind.RUNTIME_NODE


@dataclass
class ModelGeneration:
    """ProjectModel generation metadata."""

    model_version: str
    generated_at: str
    generator: str
    source_snapshot_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectModel:
    """Canonical analyzed system view for a project.

    Purpose:
    - Single source of truth for normalized system understanding.
    - Holds sources, typed entities, relations, evidence, and generation metadata.

    Stable ID:
    - Deterministic from project_id for v1.

    Links:
    - References all sources, entities, relations, and evidence by stable ID.

    Layer:
    - Internal.
    """

    id: str
    project_id: str
    sources: dict[str, SourceModel]
    components: dict[str, Component]
    modules: dict[str, Module]
    routes: dict[str, Route]
    services: dict[str, Service]
    data_stores: dict[str, DataStore]
    external_integrations: dict[str, ExternalIntegration]
    runtime_nodes: dict[str, RuntimeNode]
    relations: dict[str, Relation]
    evidence: dict[str, Evidence]
    generation: ModelGeneration
    metadata: dict[str, Any] = field(default_factory=dict)
    layer: ModelLayer = ModelLayer.INTERNAL

    def all_addressable_ids(self) -> set[str]:
        ids = set(self.sources.keys())
        ids.update(self.components.keys())
        ids.update(self.modules.keys())
        ids.update(self.routes.keys())
        ids.update(self.services.keys())
        ids.update(self.data_stores.keys())
        ids.update(self.external_integrations.keys())
        ids.update(self.runtime_nodes.keys())
        return ids

    def get_entity(self, entity_id: str) -> Any | None:
        collections = (
            self.sources,
            self.components,
            self.modules,
            self.routes,
            self.services,
            self.data_stores,
            self.external_integrations,
            self.runtime_nodes,
        )
        for collection in collections:
            if entity_id in collection:
                return collection[entity_id]
        return None

    def entity_kinds_by_id(self) -> dict[str, EntityKind]:
        return {entity_id: entity.entity_kind for entity_id, entity in {
            **self.sources,
            **self.components,
            **self.modules,
            **self.routes,
            **self.services,
            **self.data_stores,
            **self.external_integrations,
            **self.runtime_nodes,
        }.items()}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_generation(generator: str, snapshot_refs: Optional[list[str]] = None) -> ModelGeneration:
    return ModelGeneration(
        model_version="system-model/v1",
        generated_at=datetime.now(timezone.utc).isoformat(),
        generator=generator,
        source_snapshot_refs=snapshot_refs or [],
    )