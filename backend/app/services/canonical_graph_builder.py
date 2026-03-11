"""Canonical ProjectModel to persisted graph projection.

This layer is intentionally conservative for v1.
It projects only strong architecture entities and semantically meaningful edges.
"""

from __future__ import annotations

from app.domain.system_model.entities import Component, DataStore, ExternalIntegration, ProjectModel, RuntimeNode
from app.domain.system_model.relations import Relation, RelationType
from app.services.graph_builder import EdgeSpec, NodeSpec

_PROJECTABLE_RELATION_TYPES: set[RelationType] = {
    RelationType.USES_RUNTIME,
    RelationType.CONNECTS_TO,
    RelationType.DEPENDS_ON,
    RelationType.READS_FROM,
    RelationType.WRITES_TO,
    RelationType.INTEGRATES_WITH,
    RelationType.CALLS,
    RelationType.EMITS_TO,
    RelationType.CONSUMES_FROM,
}

_PROJECTABLE_ENTITY_KINDS = {"component", "runtime_node", "data_store", "external_integration"}


def build_graph_from_project_model(model: ProjectModel) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    nodes: dict[str, NodeSpec] = {}
    edges: dict[tuple[str, str, str], EdgeSpec] = {}

    for component in sorted(model.components.values(), key=lambda entity: entity.id):
        nodes[component.id] = NodeSpec(
            key=component.id,
            node_type="component",
            label=_component_label(component),
            data={
                "graph_source": "canonical_snapshot",
                "canonical_id": component.id,
                "canonical_kind": component.entity_kind.value,
                "component_type": component.kind,
                "root_path": component.root_path,
                "entry_file": component.entry_file,
                "languages": component.languages,
                "frameworks": component.frameworks,
                "confidence_score": component.confidence.score,
                "confidence_label": component.confidence.label.value,
            },
            canonical_entity_id=component.id,
            canonical_entity_kind=component.entity_kind.value,
            confidence_score=component.confidence.score,
            confidence_label=component.confidence.label.value,
        )

    for runtime_node in sorted(model.runtime_nodes.values(), key=lambda entity: entity.id):
        nodes[runtime_node.id] = NodeSpec(
            key=runtime_node.id,
            node_type="runtime",
            label=runtime_node.name,
            data={
                "graph_source": "canonical_snapshot",
                "canonical_id": runtime_node.id,
                "canonical_kind": runtime_node.entity_kind.value,
                "runtime_kind": runtime_node.kind,
                "version": runtime_node.version,
                "confidence_score": runtime_node.confidence.score,
                "confidence_label": runtime_node.confidence.label.value,
            },
            canonical_entity_id=runtime_node.id,
            canonical_entity_kind=runtime_node.entity_kind.value,
            confidence_score=runtime_node.confidence.score,
            confidence_label=runtime_node.confidence.label.value,
        )

    for data_store in sorted(model.data_stores.values(), key=lambda entity: entity.id):
        nodes[data_store.id] = NodeSpec(
            key=data_store.id,
            node_type="database",
            label=data_store.technology or data_store.name,
            data={
                "graph_source": "canonical_snapshot",
                "canonical_id": data_store.id,
                "canonical_kind": data_store.entity_kind.value,
                "store_kind": data_store.kind,
                "store_name": data_store.name,
                "technology": data_store.technology,
                "runtime_node_id": data_store.runtime_node_id,
                "confidence_score": data_store.confidence.score,
                "confidence_label": data_store.confidence.label.value,
            },
            canonical_entity_id=data_store.id,
            canonical_entity_kind=data_store.entity_kind.value,
            confidence_score=data_store.confidence.score,
            confidence_label=data_store.confidence.label.value,
        )

    for integration in sorted(model.external_integrations.values(), key=lambda entity: entity.id):
        nodes[integration.id] = NodeSpec(
            key=integration.id,
            node_type="external",
            label=integration.provider or integration.name,
            data={
                "graph_source": "canonical_snapshot",
                "canonical_id": integration.id,
                "canonical_kind": integration.entity_kind.value,
                "integration_kind": integration.kind,
                "integration_name": integration.name,
                "provider": integration.provider,
                "confidence_score": integration.confidence.score,
                "confidence_label": integration.confidence.label.value,
            },
            canonical_entity_id=integration.id,
            canonical_entity_kind=integration.entity_kind.value,
            confidence_score=integration.confidence.score,
            confidence_label=integration.confidence.label.value,
        )

    for relation in sorted(model.relations.values(), key=lambda entity: entity.id):
        projected_edge = _project_relation(model, relation)
        if projected_edge is None:
            continue
        edge_key = (
            projected_edge.source_key,
            projected_edge.target_key,
            projected_edge.edge_type,
        )
        if edge_key not in edges:
            edges[edge_key] = projected_edge

    node_specs = sorted(nodes.values(), key=lambda node: node.key)
    edge_specs = [
        edge
        for key, edge in sorted(edges.items())
        if key[0] in nodes and key[1] in nodes
    ]
    return node_specs, edge_specs


def validate_projected_graph(node_specs: list[NodeSpec], edge_specs: list[EdgeSpec]) -> list[str]:
    errors: list[str] = []
    node_keys = set()

    for node in node_specs:
        if not node.key:
            errors.append("Projected node missing key")
        if not node.node_type:
            errors.append(f"Projected node {node.key or '<unknown>'} missing node_type")
        if not node.label:
            errors.append(f"Projected node {node.key or '<unknown>'} missing label")
        if node.key in node_keys:
            errors.append(f"Duplicate projected node key {node.key}")
        node_keys.add(node.key)
        if any(
            value is not None
            for value in (
                node.canonical_entity_id,
                node.canonical_entity_kind,
                node.confidence_score,
                node.confidence_label,
            )
        ):
            if not node.canonical_entity_id:
                errors.append(f"Projected node {node.key} missing canonical_entity_id")
            if not node.canonical_entity_kind:
                errors.append(f"Projected node {node.key} missing canonical_entity_kind")
            if node.confidence_score is None:
                errors.append(f"Projected node {node.key} missing confidence_score")
            if node.confidence_label is None:
                errors.append(f"Projected node {node.key} missing confidence_label")

    for edge in edge_specs:
        if edge.source_key not in node_keys:
            errors.append(f"Projected edge source {edge.source_key} is missing")
        if edge.target_key not in node_keys:
            errors.append(f"Projected edge target {edge.target_key} is missing")
        if not edge.edge_type:
            errors.append(
                f"Projected edge {edge.source_key}->{edge.target_key} missing edge_type"
            )
        if edge.source_key == edge.target_key:
            errors.append(f"Projected self-edge {edge.source_key}->{edge.target_key}")
        if any(
            value is not None
            for value in (
                edge.canonical_relation_id,
                edge.canonical_relation_type,
                edge.confidence_score,
                edge.confidence_label,
                edge.inference_stage,
            )
        ):
            if not edge.canonical_relation_id:
                errors.append(
                    f"Projected edge {edge.source_key}->{edge.target_key} missing canonical_relation_id"
                )
            if not edge.canonical_relation_type:
                errors.append(
                    f"Projected edge {edge.source_key}->{edge.target_key} missing canonical_relation_type"
                )
            if edge.confidence_score is None:
                errors.append(
                    f"Projected edge {edge.source_key}->{edge.target_key} missing confidence_score"
                )
            if edge.confidence_label is None:
                errors.append(
                    f"Projected edge {edge.source_key}->{edge.target_key} missing confidence_label"
                )
            if edge.inference_stage is None:
                errors.append(
                    f"Projected edge {edge.source_key}->{edge.target_key} missing inference_stage"
                )

    if not node_specs:
        errors.append("Projected graph contains no nodes")

    return errors


def _project_relation(model: ProjectModel, relation: Relation) -> EdgeSpec | None:
    if relation.relation_type not in _PROJECTABLE_RELATION_TYPES:
        return None

    source_id = _resolve_projectable_entity_id(model, relation.source_id)
    target_id = _resolve_projectable_entity_id(model, relation.target_id)
    if not source_id or not target_id or source_id == target_id:
        return None

    source_entity = model.get_entity(source_id)
    target_entity = model.get_entity(target_id)
    if source_entity is None or target_entity is None:
        return None

    edge_type = _edge_type_for_relation(relation, source_entity.entity_kind.value, target_entity.entity_kind.value)
    if edge_type is None:
        return None

    was_collapsed = source_id != relation.source_id or target_id != relation.target_id
    return EdgeSpec(
        source_key=source_id,
        target_key=target_id,
        edge_type=edge_type,
        data={
            "graph_source": "canonical_snapshot",
            "projection": {
                "collapsed": was_collapsed,
                "original_source_id": relation.source_id,
                "original_target_id": relation.target_id,
                "original_source_kind": relation.source_kind,
                "original_target_kind": relation.target_kind,
            },
        },
        canonical_relation_id=relation.id,
        canonical_relation_type=relation.relation_type.value,
        confidence_score=relation.confidence.score,
        confidence_label=relation.confidence.label.value,
        inference_stage=relation.inference_stage.value,
    )


def _resolve_projectable_entity_id(model: ProjectModel, entity_id: str) -> str | None:
    entity = model.get_entity(entity_id)
    if entity is None:
        return None

    if entity.entity_kind.value in _PROJECTABLE_ENTITY_KINDS:
        return entity.id

    component_id = getattr(entity, "component_id", None)
    if component_id and component_id in model.components:
        return component_id

    return None


def _edge_type_for_relation(relation: Relation, source_kind: str, target_kind: str) -> str | None:
    if relation.relation_type == RelationType.USES_RUNTIME and target_kind == "runtime_node":
        return "runs_on"

    if relation.relation_type == RelationType.CALLS and source_kind == "component" and target_kind == "component":
        return "calls"

    if relation.relation_type == RelationType.CONNECTS_TO:
        return "connects_to"

    if target_kind in {"data_store", "external_integration"}:
        return "uses"

    if target_kind == "component" and relation.relation_type in {RelationType.DEPENDS_ON, RelationType.CALLS}:
        return "connects_to"

    return None


def _component_label(component: Component) -> str:
    return component.name.replace("_", " ").title()