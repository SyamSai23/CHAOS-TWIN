"""Helpers for loading validated canonical ProjectModel snapshots."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.domain.system_model.entities import (
    Component,
    DataStore,
    EntityKind,
    ExternalIntegration,
    ModelGeneration,
    ModelLayer,
    Module,
    ProjectModel,
    Route,
    RuntimeNode,
    Service,
    SourceModel,
    SourceType,
)
from app.domain.system_model.evidence import Confidence, ConfidenceLabel, Evidence, SourcePathKind
from app.domain.system_model.relations import InferenceStage, Relation, RelationDirection, RelationType
from app.domain.system_model.validation import validate_project_model
from app.models.project_model_snapshot import ProjectModelSnapshot

logger = logging.getLogger(__name__)


def load_valid_project_model_snapshot(
    db: Session,
    project_id: str,
    scan_id: Optional[str] = None,
) -> tuple[ProjectModelSnapshot, ProjectModel] | None:
    snapshot = _find_candidate_snapshot(db, project_id=project_id, scan_id=scan_id)
    if snapshot is None:
        return None

    if not isinstance(snapshot.model_data, dict):
        logger.warning(
            "Canonical snapshot missing model_data for project %s scan %s snapshot %s",
            project_id,
            scan_id or snapshot.scan_id,
            snapshot.id,
        )
        return None

    try:
        model = project_model_from_dict(snapshot.model_data)
    except Exception:
        logger.exception(
            "Failed to hydrate canonical snapshot for project %s scan %s snapshot %s",
            project_id,
            scan_id or snapshot.scan_id,
            snapshot.id,
        )
        return None

    validation_errors = validate_project_model(model)
    if validation_errors:
        logger.warning(
            "Canonical snapshot invalid at load time for project %s scan %s snapshot %s: %s",
            project_id,
            scan_id or snapshot.scan_id,
            snapshot.id,
            "; ".join(validation_errors[:3]),
        )
        return None

    return snapshot, model


def _find_candidate_snapshot(
    db: Session,
    project_id: str,
    scan_id: Optional[str],
) -> ProjectModelSnapshot | None:
    query = db.query(ProjectModelSnapshot).filter(
        ProjectModelSnapshot.project_id == project_id,
        ProjectModelSnapshot.status == "completed",
    )

    if scan_id is not None:
        return query.filter(ProjectModelSnapshot.scan_id == scan_id).first()

    return query.order_by(ProjectModelSnapshot.created_at.desc()).first()


def project_model_from_dict(payload: dict) -> ProjectModel:
    return ProjectModel(
        id=payload["id"],
        project_id=payload["project_id"],
        sources={key: _source_from_dict(value) for key, value in payload.get("sources", {}).items()},
        components={key: _component_from_dict(value) for key, value in payload.get("components", {}).items()},
        modules={key: _module_from_dict(value) for key, value in payload.get("modules", {}).items()},
        routes={key: _route_from_dict(value) for key, value in payload.get("routes", {}).items()},
        services={key: _service_from_dict(value) for key, value in payload.get("services", {}).items()},
        data_stores={key: _data_store_from_dict(value) for key, value in payload.get("data_stores", {}).items()},
        external_integrations={
            key: _external_integration_from_dict(value)
            for key, value in payload.get("external_integrations", {}).items()
        },
        runtime_nodes={
            key: _runtime_node_from_dict(value)
            for key, value in payload.get("runtime_nodes", {}).items()
        },
        relations={key: _relation_from_dict(value) for key, value in payload.get("relations", {}).items()},
        evidence={key: _evidence_from_dict(value) for key, value in payload.get("evidence", {}).items()},
        generation=_generation_from_dict(payload["generation"]),
        metadata=payload.get("metadata", {}),
        layer=ModelLayer(payload.get("layer", ModelLayer.INTERNAL.value)),
    )


def _confidence_from_dict(payload: Optional[dict]) -> Optional[Confidence]:
    if payload is None:
        return None
    return Confidence(
        score=payload["score"],
        label=ConfidenceLabel(payload["label"]),
        rationale=payload.get("rationale"),
        evidence_count=payload.get("evidence_count", 0),
        signal_count=payload.get("signal_count", 0),
        reasons=list(payload.get("reasons", [])),
        signals=payload.get("signals", {}),
        producer=payload.get("producer"),
    )


def _evidence_from_dict(payload: dict) -> Evidence:
    return Evidence(
        id=payload["id"],
        source_id=payload["source_id"],
        file_path=payload["file_path"],
        path_kind=SourcePathKind(payload.get("path_kind", SourcePathKind.SOURCE_RELATIVE.value)),
        symbol=payload.get("symbol"),
        symbol_kind=payload.get("symbol_kind"),
        line_start=payload.get("line_start"),
        line_end=payload.get("line_end"),
        column_start=payload.get("column_start"),
        column_end=payload.get("column_end"),
        snippet_summary=payload.get("snippet_summary"),
        snippet_excerpt=payload.get("snippet_excerpt"),
        detector_type=payload.get("detector_type"),
        parser_type=payload.get("parser_type"),
        rule_name=payload.get("rule_name"),
        extraction_source=payload.get("extraction_source"),
        metadata=payload.get("metadata", {}),
    )


def _relation_from_dict(payload: dict) -> Relation:
    return Relation(
        id=payload["id"],
        source_id=payload["source_id"],
        target_id=payload["target_id"],
        relation_type=RelationType(payload["relation_type"]),
        direction=RelationDirection(payload["direction"]),
        inference_stage=InferenceStage(payload["inference_stage"]),
        confidence=_confidence_from_dict(payload["confidence"]),
        source_kind=payload.get("source_kind"),
        target_kind=payload.get("target_kind"),
        evidence_ids=list(payload.get("evidence_ids", [])),
        metadata=payload.get("metadata", {}),
    )


def _source_from_dict(payload: dict) -> SourceModel:
    return SourceModel(
        id=payload["id"],
        project_id=payload["project_id"],
        logical_root=payload["logical_root"],
        source_type=SourceType(payload["source_type"]),
        source_ref=payload["source_ref"],
        snapshot_ref=payload.get("snapshot_ref"),
        ingestion_metadata=payload.get("ingestion_metadata", {}),
        evidence_ids=list(payload.get("evidence_ids", [])),
        confidence=_confidence_from_dict(payload.get("confidence")),
        layer=ModelLayer(payload.get("layer", ModelLayer.INTERNAL.value)),
        entity_kind=EntityKind(payload.get("entity_kind", EntityKind.SOURCE.value)),
    )


def _component_from_dict(payload: dict) -> Component:
    return Component(
        id=payload["id"],
        source_ids=list(payload.get("source_ids", [])),
        name=payload["name"],
        kind=payload["kind"],
        root_path=payload["root_path"],
        confidence=_confidence_from_dict(payload["confidence"]),
        evidence_ids=list(payload.get("evidence_ids", [])),
        entry_file=payload.get("entry_file"),
        languages=list(payload.get("languages", [])),
        frameworks=list(payload.get("frameworks", [])),
        metadata=payload.get("metadata", {}),
        layer=ModelLayer(payload.get("layer", ModelLayer.USER_FACING.value)),
        entity_kind=EntityKind(payload.get("entity_kind", EntityKind.COMPONENT.value)),
    )


def _module_from_dict(payload: dict) -> Module:
    return Module(
        id=payload["id"],
        source_ids=list(payload.get("source_ids", [])),
        component_id=payload["component_id"],
        path=payload["path"],
        confidence=_confidence_from_dict(payload["confidence"]),
        evidence_ids=list(payload.get("evidence_ids", [])),
        name=payload.get("name"),
        kind=payload.get("kind"),
        symbol=payload.get("symbol"),
        symbol_kind=payload.get("symbol_kind"),
        metadata=payload.get("metadata", {}),
        layer=ModelLayer(payload.get("layer", ModelLayer.INTERNAL.value)),
        entity_kind=EntityKind(payload.get("entity_kind", EntityKind.MODULE.value)),
    )


def _route_from_dict(payload: dict) -> Route:
    return Route(
        id=payload["id"],
        source_ids=list(payload.get("source_ids", [])),
        method=payload["method"],
        path=payload["path"],
        file_path=payload["file_path"],
        component_id=payload["component_id"],
        confidence=_confidence_from_dict(payload["confidence"]),
        evidence_ids=list(payload.get("evidence_ids", [])),
        handler_name=payload.get("handler_name"),
        parameters=list(payload.get("parameters", [])),
        metadata=payload.get("metadata", {}),
        layer=ModelLayer(payload.get("layer", ModelLayer.USER_FACING.value)),
        entity_kind=EntityKind(payload.get("entity_kind", EntityKind.ROUTE.value)),
    )


def _service_from_dict(payload: dict) -> Service:
    return Service(
        id=payload["id"],
        source_ids=list(payload.get("source_ids", [])),
        name=payload["name"],
        confidence=_confidence_from_dict(payload["confidence"]),
        evidence_ids=list(payload.get("evidence_ids", [])),
        component_id=payload.get("component_id"),
        module_ids=list(payload.get("module_ids", [])),
        kind=payload.get("kind"),
        symbol=payload.get("symbol"),
        metadata=payload.get("metadata", {}),
        layer=ModelLayer(payload.get("layer", ModelLayer.DERIVED.value)),
        entity_kind=EntityKind(payload.get("entity_kind", EntityKind.SERVICE.value)),
    )


def _data_store_from_dict(payload: dict) -> DataStore:
    return DataStore(
        id=payload["id"],
        source_ids=list(payload.get("source_ids", [])),
        name=payload["name"],
        kind=payload["kind"],
        confidence=_confidence_from_dict(payload["confidence"]),
        evidence_ids=list(payload.get("evidence_ids", [])),
        technology=payload.get("technology"),
        runtime_node_id=payload.get("runtime_node_id"),
        metadata=payload.get("metadata", {}),
        layer=ModelLayer(payload.get("layer", ModelLayer.USER_FACING.value)),
        entity_kind=EntityKind(payload.get("entity_kind", EntityKind.DATA_STORE.value)),
    )


def _external_integration_from_dict(payload: dict) -> ExternalIntegration:
    return ExternalIntegration(
        id=payload["id"],
        source_ids=list(payload.get("source_ids", [])),
        name=payload["name"],
        kind=payload["kind"],
        confidence=_confidence_from_dict(payload["confidence"]),
        evidence_ids=list(payload.get("evidence_ids", [])),
        provider=payload.get("provider"),
        metadata=payload.get("metadata", {}),
        layer=ModelLayer(payload.get("layer", ModelLayer.USER_FACING.value)),
        entity_kind=EntityKind(payload.get("entity_kind", EntityKind.EXTERNAL_INTEGRATION.value)),
    )


def _runtime_node_from_dict(payload: dict) -> RuntimeNode:
    return RuntimeNode(
        id=payload["id"],
        source_ids=list(payload.get("source_ids", [])),
        name=payload["name"],
        kind=payload["kind"],
        confidence=_confidence_from_dict(payload["confidence"]),
        evidence_ids=list(payload.get("evidence_ids", [])),
        version=payload.get("version"),
        metadata=payload.get("metadata", {}),
        layer=ModelLayer(payload.get("layer", ModelLayer.DERIVED.value)),
        entity_kind=EntityKind(payload.get("entity_kind", EntityKind.RUNTIME_NODE.value)),
    )


def _generation_from_dict(payload: dict) -> ModelGeneration:
    return ModelGeneration(
        model_version=payload["model_version"],
        generated_at=payload["generated_at"],
        generator=payload["generator"],
        source_snapshot_refs=list(payload.get("source_snapshot_refs", [])),
        metadata=payload.get("metadata", {}),
    )