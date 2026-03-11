"""Validation helpers for canonical ProjectModel instances."""

from __future__ import annotations

from app.domain.system_model.entities import ProjectModel
from app.domain.system_model.relations import ALLOWED_RELATION_ENDPOINTS


def validate_project_model(model: ProjectModel) -> list[str]:
    errors: list[str] = []
    addressable_ids = model.all_addressable_ids()
    kind_map = model.entity_kinds_by_id()
    evidence_ids = set(model.evidence.keys())
    semantic_relation_keys: set[tuple[str, str, str, str]] = set()

    for source_id, source in model.sources.items():
        if source_id != source.id:
            errors.append(f"Source map key mismatch for {source_id}")
        if source.confidence is not None:
            _validate_confidence(errors, f"Source {source_id}", source.confidence)
        for evidence_id in source.evidence_ids:
            if evidence_id not in evidence_ids:
                errors.append(f"Source {source_id} references unknown evidence {evidence_id}")

    for relation_id, relation in model.relations.items():
        if relation.source_id not in addressable_ids:
            errors.append(f"Relation {relation_id} has unknown source_id {relation.source_id}")
        if relation.target_id not in addressable_ids:
            errors.append(f"Relation {relation_id} has unknown target_id {relation.target_id}")
        _validate_confidence(errors, f"Relation {relation_id}", relation.confidence)

        actual_source_kind = kind_map.get(relation.source_id)
        actual_target_kind = kind_map.get(relation.target_id)
        if relation.source_kind and actual_source_kind and relation.source_kind != actual_source_kind.value:
            errors.append(
                f"Relation {relation_id} source_kind {relation.source_kind} does not match {actual_source_kind.value}"
            )
        if relation.target_kind and actual_target_kind and relation.target_kind != actual_target_kind.value:
            errors.append(
                f"Relation {relation_id} target_kind {relation.target_kind} does not match {actual_target_kind.value}"
            )

        allowed = ALLOWED_RELATION_ENDPOINTS.get(relation.relation_type)
        if allowed and actual_source_kind and actual_target_kind:
            allowed_sources, allowed_targets = allowed
            if actual_source_kind.value not in allowed_sources:
                errors.append(
                    f"Relation {relation_id} has invalid source kind {actual_source_kind.value} for {relation.relation_type.value}"
                )
            if actual_target_kind.value not in allowed_targets:
                errors.append(
                    f"Relation {relation_id} has invalid target kind {actual_target_kind.value} for {relation.relation_type.value}"
                )

        semantic_key = (
            relation.source_id,
            relation.target_id,
            relation.relation_type.value,
            relation.inference_stage.value,
        )
        if semantic_key in semantic_relation_keys:
            errors.append(
                f"Duplicate semantic relation detected: {relation.source_id} {relation.relation_type.value} {relation.target_id}"
            )
        semantic_relation_keys.add(semantic_key)

        for evidence_id in relation.evidence_ids:
            if evidence_id not in evidence_ids:
                errors.append(f"Relation {relation_id} references unknown evidence {evidence_id}")

    entity_groups = {
        "Component": model.components,
        "Module": model.modules,
        "Route": model.routes,
        "Service": model.services,
        "DataStore": model.data_stores,
        "ExternalIntegration": model.external_integrations,
        "RuntimeNode": model.runtime_nodes,
    }
    for label, group in entity_groups.items():
        for entity_id, entity in group.items():
            if entity_id != entity.id:
                errors.append(f"Entity map key mismatch for {entity_id}")
            _validate_confidence(errors, f"{label} {entity_id}", entity.confidence)
            for source_id in entity.source_ids:
                if source_id not in model.sources:
                    errors.append(f"Entity {entity_id} references unknown source {source_id}")
            for evidence_id in entity.evidence_ids:
                if evidence_id not in evidence_ids:
                    errors.append(f"Entity {entity_id} references unknown evidence {evidence_id}")

            if hasattr(entity, "component_id") and getattr(entity, "component_id") is not None:
                component_id = getattr(entity, "component_id")
                if component_id not in model.components:
                    errors.append(f"Entity {entity_id} references unknown component {component_id}")

            if hasattr(entity, "module_ids"):
                for module_id in getattr(entity, "module_ids"):
                    if module_id not in model.modules:
                        errors.append(f"Entity {entity_id} references unknown module {module_id}")

            if hasattr(entity, "runtime_node_id") and getattr(entity, "runtime_node_id") is not None:
                runtime_node_id = getattr(entity, "runtime_node_id")
                if runtime_node_id not in model.runtime_nodes:
                    errors.append(f"Entity {entity_id} references unknown runtime node {runtime_node_id}")

    for evidence_id, evidence in model.evidence.items():
        if evidence_id != evidence.id:
            errors.append(f"Evidence map key mismatch for {evidence_id}")
        if evidence.source_id not in model.sources:
            errors.append(f"Evidence {evidence_id} references unknown source {evidence.source_id}")
        _validate_evidence_location(errors, evidence_id, evidence)

    return errors


def assert_valid_project_model(model: ProjectModel) -> ProjectModel:
    errors = validate_project_model(model)
    if errors:
        raise ValueError("Invalid ProjectModel: " + "; ".join(errors))
    return model


def _validate_confidence(errors: list[str], owner: str, confidence) -> None:
    if not 0.0 <= confidence.score <= 1.0:
        errors.append(f"{owner} has confidence score outside [0, 1]")
    if confidence.evidence_count < 0:
        errors.append(f"{owner} has negative evidence_count")
    if confidence.signal_count < 0:
        errors.append(f"{owner} has negative signal_count")


def _validate_evidence_location(errors: list[str], evidence_id: str, evidence) -> None:
    if not evidence.file_path:
        errors.append(f"Evidence {evidence_id} has empty file_path")
    if evidence.line_start is not None and evidence.line_start < 1:
        errors.append(f"Evidence {evidence_id} has invalid line_start {evidence.line_start}")
    if evidence.line_end is not None and evidence.line_end < 1:
        errors.append(f"Evidence {evidence_id} has invalid line_end {evidence.line_end}")
    if (
        evidence.line_start is not None
        and evidence.line_end is not None
        and evidence.line_end < evidence.line_start
    ):
        errors.append(f"Evidence {evidence_id} has line_end before line_start")
    if evidence.column_start is not None and evidence.column_start < 1:
        errors.append(f"Evidence {evidence_id} has invalid column_start {evidence.column_start}")
    if evidence.column_end is not None and evidence.column_end < 1:
        errors.append(f"Evidence {evidence_id} has invalid column_end {evidence.column_end}")
    if (
        evidence.column_start is not None
        and evidence.column_end is not None
        and evidence.column_end < evidence.column_start
    ):
        errors.append(f"Evidence {evidence_id} has column_end before column_start")