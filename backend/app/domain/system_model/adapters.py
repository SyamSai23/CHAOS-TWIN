"""Adapters that populate the canonical system model from current pipeline outputs.

V1 intentionally starts with the existing Scan model so the scanner can write into
the canonical model without forcing a rewrite of graph building, route analysis,
deep dive, or simulation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

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
from app.domain.system_model.evidence import Evidence, make_confidence
from app.domain.system_model.ids import (
    make_component_id,
    make_data_store_id,
    make_evidence_id,
    make_external_integration_id,
    make_module_id,
    make_project_model_id,
    make_route_entity_id,
    make_runtime_node_id,
    make_source_model_id,
    normalize_path,
)
from app.domain.system_model.relations import InferenceStage, Relation, RelationDirection, RelationType
from app.domain.system_model.validation import assert_valid_project_model
from app.models.project import Project
from app.models.scan import Scan
from app.models.upload import Upload


_DB_KEYWORDS = {
    "postgres": ("PostgreSQL", "sql"),
    "postgresql": ("PostgreSQL", "sql"),
    "mysql": ("MySQL", "sql"),
    "mariadb": ("MariaDB", "sql"),
    "mongo": ("MongoDB", "document"),
    "mongodb": ("MongoDB", "document"),
    "redis": ("Redis", "cache"),
    "sqlite": ("SQLite", "sql"),
    "dynamodb": ("DynamoDB", "nosql"),
}

_RUNTIME_NAMES = {
    "Python": "Python Runtime",
    "TypeScript": "Node.js Runtime",
    "JavaScript": "Node.js Runtime",
    "Java": "JVM Runtime",
    "Kotlin": "JVM Runtime",
    "Go": "Go Runtime",
    "Ruby": "Ruby Runtime",
    "PHP": "PHP Runtime",
    "Rust": "Rust Runtime",
}


class _ModelBuilder:
    def __init__(self, project: Project, scan: Scan, upload: Optional[Upload]) -> None:
        self.project = project
        self.scan = scan
        self.upload = upload
        self.sources: dict[str, SourceModel] = {}
        self.components: dict[str, Component] = {}
        self.modules: dict[str, Module] = {}
        self.routes: dict[str, Route] = {}
        self.services: dict[str, Service] = {}
        self.data_stores: dict[str, DataStore] = {}
        self.external_integrations: dict[str, ExternalIntegration] = {}
        self.runtime_nodes: dict[str, RuntimeNode] = {}
        self.relations: dict[str, Relation] = {}
        self._semantic_relations: dict[tuple[str, str, str, str], str] = {}
        self.evidence: dict[str, Evidence] = {}

        self.source = self._build_source()
        self.sources[self.source.id] = self.source

    def _build_source(self) -> SourceModel:
        source_type = SourceType.UPLOAD_ARCHIVE if self.upload else SourceType.WORKSPACE
        source_ref = self.upload.storage_path if self.upload else self.project.path
        logical_root = self.project.path or "."
        snapshot_ref = self.scan.id
        source_id = make_source_model_id(
            project_id=self.project.id,
            logical_root=logical_root,
            source_type=source_type.value,
            snapshot_ref=snapshot_ref,
        )
        evidence_id = self.add_evidence(
            source_id=source_id,
            file_path=normalize_path(logical_root),
            snippet_summary="Ingestion root for the analyzed source snapshot.",
            detector_type="scanner_v3",
            rule_name="source_ingestion",
            extraction_source="project.path",
            path_kind="logical_root",
            metadata={"upload_id": getattr(self.upload, "id", None)},
        )
        return SourceModel(
            id=source_id,
            project_id=self.project.id,
            logical_root=normalize_path(logical_root),
            source_type=source_type,
            source_ref=source_ref,
            snapshot_ref=snapshot_ref,
            ingestion_metadata={
                "project_name": self.project.name,
                "scan_id": self.scan.id,
                "upload_id": getattr(self.upload, "id", None),
                "upload_filename": getattr(self.upload, "filename", None),
            },
            evidence_ids=[evidence_id],
            confidence=make_confidence(
                1.0,
                "Source identity comes from persisted project/scan rows.",
                1,
                2,
                producer="build_project_model_from_scan",
            ),
        )

    def add_evidence(
        self,
        source_id: str,
        file_path: str,
        path_kind: str = "source_relative",
        symbol: Optional[str] = None,
        symbol_kind: Optional[str] = None,
        line_start: Optional[int] = None,
        line_end: Optional[int] = None,
        column_start: Optional[int] = None,
        column_end: Optional[int] = None,
        snippet_summary: Optional[str] = None,
        snippet_excerpt: Optional[str] = None,
        detector_type: Optional[str] = None,
        parser_type: Optional[str] = None,
        rule_name: Optional[str] = None,
        extraction_source: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        evidence_id = make_evidence_id(
            source_id=source_id,
            file_path=file_path,
            symbol=symbol or "",
            symbol_kind=symbol_kind or "",
            line_start=line_start or 0,
            line_end=line_end or 0,
            column_start=column_start or 0,
            column_end=column_end or 0,
            detector_type=detector_type or "",
            parser_type=parser_type or "",
            rule_name=rule_name or "",
            extraction_source=extraction_source or "",
            path_kind=path_kind,
        )
        if evidence_id not in self.evidence:
            self.evidence[evidence_id] = Evidence(
                id=evidence_id,
                source_id=source_id,
                file_path=normalize_path(file_path),
                path_kind=path_kind,
                symbol=symbol,
                symbol_kind=symbol_kind,
                line_start=line_start,
                line_end=line_end,
                column_start=column_start,
                column_end=column_end,
                snippet_summary=snippet_summary,
                snippet_excerpt=snippet_excerpt,
                detector_type=detector_type,
                parser_type=parser_type,
                rule_name=rule_name,
                extraction_source=extraction_source,
                metadata=metadata or {},
            )
        return evidence_id

    def add_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        rationale: str,
        evidence_ids: Optional[list[str]] = None,
        qualifier: str = "",
        metadata: Optional[dict] = None,
        score: float = 0.8,
        inference_stage: InferenceStage = InferenceStage.SCAN,
    ) -> None:
        source_entity = self.sources.get(source_id) or self.components.get(source_id) or self.modules.get(source_id) or self.routes.get(source_id) or self.services.get(source_id) or self.data_stores.get(source_id) or self.external_integrations.get(source_id) or self.runtime_nodes.get(source_id)
        target_entity = self.sources.get(target_id) or self.components.get(target_id) or self.modules.get(target_id) or self.routes.get(target_id) or self.services.get(target_id) or self.data_stores.get(target_id) or self.external_integrations.get(target_id) or self.runtime_nodes.get(target_id)
        semantic_key = (
            source_id,
            target_id,
            relation_type.value,
            inference_stage.value,
        )
        existing_relation_id = self._semantic_relations.get(semantic_key)
        if existing_relation_id is not None:
            existing_relation = self.relations[existing_relation_id]
            merged_evidence_ids = sorted(set(existing_relation.evidence_ids) | set(evidence_ids or []))
            existing_relation.evidence_ids = merged_evidence_ids
            existing_relation.confidence = make_confidence(
                max(existing_relation.confidence.score, score),
                existing_relation.confidence.rationale or rationale,
                len(merged_evidence_ids),
                max(existing_relation.confidence.signal_count, 1),
                producer="build_project_model_from_scan",
            )
            if qualifier:
                qualifiers = list(existing_relation.metadata.get("qualifiers") or [])
                if qualifier not in qualifiers:
                    qualifiers.append(qualifier)
                existing_relation.metadata = {
                    **existing_relation.metadata,
                    "qualifiers": qualifiers,
                }
            if metadata:
                existing_relation.metadata = {
                    **existing_relation.metadata,
                    **metadata,
                }
            return

        semantic_qualifier = qualifier or inference_stage.value
        relation_id = f"relation:{source_id}:{relation_type.value}:{target_id}:{semantic_qualifier}"
        self.relations[relation_id] = Relation(
            id=relation_id,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            direction=RelationDirection.DIRECTED,
            inference_stage=inference_stage,
            confidence=make_confidence(
                score,
                rationale,
                len(evidence_ids or []),
                1,
                producer="build_project_model_from_scan",
            ),
            source_kind=getattr(source_entity, "entity_kind", None).value if source_entity else None,
            target_kind=getattr(target_entity, "entity_kind", None).value if target_entity else None,
            evidence_ids=evidence_ids or [],
            metadata=metadata or {},
        )
        self._semantic_relations[semantic_key] = relation_id

    def ensure_module(
        self,
        component_id: str,
        file_path: str,
        reason: str,
        symbol: Optional[str] = None,
        symbol_kind: Optional[str] = None,
    ) -> Optional[str]:
        normalized = normalize_path(file_path)
        if normalized == ".":
            return None
        module_id = make_module_id(self.project.id, normalized, symbol or "", symbol_kind or "")
        if module_id in self.modules:
            return module_id
        evidence_id = self.add_evidence(
            source_id=self.source.id,
            file_path=normalized,
            symbol=symbol,
            symbol_kind=symbol_kind,
            snippet_summary=reason,
            detector_type="scanner_v3",
            rule_name="module_reference",
            extraction_source="scan.components/scan.routes",
        )
        self.modules[module_id] = Module(
            id=module_id,
            source_ids=[self.source.id],
            component_id=component_id,
            path=normalized,
            name=normalized.split("/")[-1],
            confidence=make_confidence(0.8, reason, 1, 1, producer="build_project_model_from_scan"),
            evidence_ids=[evidence_id],
            kind="file",
            symbol=symbol,
            symbol_kind=symbol_kind,
        )
        self.add_relation(
            source_id=component_id,
            target_id=module_id,
            relation_type=RelationType.CONTAINS,
            rationale="Component ownership of the module comes from current scan metadata.",
            evidence_ids=[evidence_id],
            qualifier=normalized,
        )
        return module_id

    def build_components(self) -> None:
        for raw_component in self.scan.components or []:
            if not isinstance(raw_component, dict):
                continue
            root_path = normalize_path(raw_component.get("root_path") or ".")
            component_id = make_component_id(root_path)
            best_target = dict(raw_component.get("best_target") or {})
            best_target_file = normalize_path(best_target.get("file_path") or root_path)
            confidence_score = float(
                (self.scan.confidence_scores or {}).get(raw_component.get("type", ""), 0.75)
            )
            evidence_id = self.add_evidence(
                source_id=self.source.id,
                file_path=best_target_file,
                line_start=best_target.get("line_start"),
                line_end=best_target.get("line_end"),
                symbol=best_target.get("symbol_name"),
                symbol_kind=best_target.get("symbol_kind"),
                snippet_summary=str(best_target.get("selection_reason") or "Component detected from scanner output."),
                detector_type="scanner_v3",
                rule_name="component_detection",
                extraction_source="scan.components",
                metadata={
                    "component_name": raw_component.get("name"),
                    "target_rank": best_target.get("target_rank"),
                    "anchor_kind": best_target.get("anchor_kind"),
                    "selection_reason": best_target.get("selection_reason"),
                },
            )
            component = Component(
                id=component_id,
                source_ids=[self.source.id],
                name=raw_component.get("name") or root_path.split("/")[-1] or "component",
                kind=raw_component.get("type") or "unknown",
                root_path=root_path,
                confidence=make_confidence(
                    confidence_score,
                    "Scanner component classification confidence.",
                    evidence_count=1,
                    signal_count=2,
                    producer="build_project_model_from_scan",
                ),
                evidence_ids=[evidence_id],
                entry_file=raw_component.get("entry_file"),
                languages=list(raw_component.get("languages") or []),
                frameworks=list(self.scan.frameworks or []),
                metadata={
                    "component_key": raw_component.get("component_key"),
                    "file_count": raw_component.get("file_count"),
                    "markers": list(raw_component.get("markers") or []),
                    "key_files": list(raw_component.get("key_files") or []),
                    "detected_roles": list(raw_component.get("detected_roles") or []),
                    "role_counts": dict(raw_component.get("role_counts") or {}),
                    "ownership_summary": dict(raw_component.get("ownership_summary") or {}),
                    "boundary_evidence": list(raw_component.get("boundary_evidence") or []),
                    "best_target": best_target,
                    "confidence_label": raw_component.get("confidence_label"),
                },
            )
            self.components[component_id] = component
            self.add_relation(
                source_id=self.source.id,
                target_id=component_id,
                relation_type=RelationType.CONTAINS,
                rationale="The source snapshot contains this detected component.",
                evidence_ids=[evidence_id],
                qualifier=root_path,
            )
            if component.entry_file:
                self.ensure_module(
                    component_id=component_id,
                    file_path=component.entry_file,
                    reason="Entry file from component scan metadata.",
                )

    def build_runtime_nodes(self) -> None:
        for language in self.scan.languages or []:
            runtime_name = _RUNTIME_NAMES.get(language)
            if not runtime_name:
                continue
            runtime_id = make_runtime_node_id(self.source.id, runtime_name)
            if runtime_id not in self.runtime_nodes:
                evidence_id = self.add_evidence(
                    source_id=self.source.id,
                    file_path=self.source.logical_root,
                    snippet_summary=f"Runtime inferred from detected language: {language}.",
                    detector_type="scanner_v3",
                    rule_name="language_runtime_mapping",
                    extraction_source="scan.languages",
                    path_kind="logical_root",
                )
                self.runtime_nodes[runtime_id] = RuntimeNode(
                    id=runtime_id,
                    source_ids=[self.source.id],
                    name=runtime_name,
                    kind=language,
                    confidence=make_confidence(
                        0.82,
                        "Runtime inferred from detected source language.",
                        1,
                        1,
                        producer="build_project_model_from_scan",
                    ),
                    evidence_ids=[evidence_id],
                )
            for component in self.components.values():
                if language in component.languages:
                    self.add_relation(
                        source_id=component.id,
                        target_id=runtime_id,
                        relation_type=RelationType.USES_RUNTIME,
                        rationale="Component language implies a runtime dependency.",
                        qualifier=language,
                        score=0.82,
                    )

    def build_routes(self) -> None:
        component_index = {component.name: component.id for component in self.components.values()}
        for raw_route in self.scan.routes or []:
            if not isinstance(raw_route, dict):
                continue
            method = str(raw_route.get("method") or "GET").upper()
            path = str(raw_route.get("path") or "/")
            best_target = dict(raw_route.get("best_target") or raw_route.get("evidence") or {})
            file_path = normalize_path(best_target.get("file_path") or raw_route.get("file") or ".")
            handler_name = raw_route.get("handler_function") or raw_route.get("handler")
            component_name = raw_route.get("component") or ""
            component_id = component_index.get(component_name)
            if not component_id and self.components:
                component_id = next(iter(self.components.keys()))
            if not component_id:
                continue

            route_id = make_route_entity_id(method, path, file_path)
            evidence_id = self.add_evidence(
                source_id=self.source.id,
                file_path=file_path,
                symbol=best_target.get("symbol_name") or handler_name,
                symbol_kind=best_target.get("symbol_kind") or ("handler" if handler_name else None),
                line_start=best_target.get("line_start") or raw_route.get("line_start"),
                line_end=best_target.get("line_end") or raw_route.get("line_end"),
                snippet_summary=str(best_target.get("selection_reason") or f"Route {method} {path} detected from scan metadata."),
                detector_type="scanner_v3",
                rule_name="route_detection",
                extraction_source="scan.routes",
                metadata={
                    "target_rank": best_target.get("target_rank"),
                    "anchor_kind": best_target.get("anchor_kind"),
                    "selection_reason": best_target.get("selection_reason"),
                    "controller_name": best_target.get("class_name") or raw_route.get("controller_name"),
                },
            )
            self.routes[route_id] = Route(
                id=route_id,
                source_ids=[self.source.id],
                method=method,
                path=path,
                file_path=file_path,
                component_id=component_id,
                handler_name=handler_name,
                parameters=list(raw_route.get("parameters") or []),
                confidence=make_confidence(
                    0.84,
                    "Route metadata comes from scanner route extraction.",
                    1,
                    1,
                    producer="build_project_model_from_scan",
                ),
                evidence_ids=[evidence_id],
                metadata={
                    "framework": raw_route.get("framework"),
                    "best_target": best_target,
                    "request_flow": raw_route.get("request_flow") or {},
                },
            )
            self.add_relation(
                source_id=component_id,
                target_id=route_id,
                relation_type=RelationType.EXPOSES_ROUTE,
                rationale="The component exposes this route according to scan output.",
                evidence_ids=[evidence_id],
                qualifier=f"{method}:{path}",
                score=0.84,
            )
            module_id = self.ensure_module(
                component_id=component_id,
                file_path=file_path,
                reason="Route file should exist as a canonical module reference.",
                symbol=handler_name,
                symbol_kind="handler",
            )
            if module_id:
                self.add_relation(
                    source_id=route_id,
                    target_id=module_id,
                    relation_type=RelationType.BACKED_BY,
                    rationale="The route is backed by the file that defines it.",
                    evidence_ids=[evidence_id],
                    qualifier=file_path,
                    score=0.86,
                )

    def build_infrastructure(self) -> None:
        component_index = {component.name: component.id for component in self.components.values()}

        for docker_service in self.scan.docker_services or []:
            if not isinstance(docker_service, dict):
                continue
            name = str(docker_service.get("name") or "")
            image = str(docker_service.get("image") or "")
            infra_meta = docker_service.get("infrastructure") or {}
            detected = None
            if infra_meta.get("entity_type") == "data_store":
                detected = (
                    str(infra_meta.get("name") or name or image),
                    str(infra_meta.get("kind") or "service"),
                )
            else:
                detected = _match_keyword(name, _DB_KEYWORDS) or _match_keyword(image, _DB_KEYWORDS)
            if not detected:
                continue
            label, store_type = detected
            store_id = make_data_store_id(self.source.id, label, store_type)
            if store_id not in self.data_stores:
                evidence_id = self.add_evidence(
                    source_id=self.source.id,
                    file_path=self.source.logical_root,
                    snippet_summary=f"Data store inferred from docker service {name or image}.",
                    detector_type="scanner_v3",
                    rule_name="docker_service_detection",
                    extraction_source="scan.docker_services",
                )
                self.data_stores[store_id] = DataStore(
                    id=store_id,
                    source_ids=[self.source.id],
                    name=label,
                    kind=store_type,
                    technology=image or name,
                    confidence=make_confidence(
                        0.9,
                        "Data store inferred from explicit docker service metadata.",
                        1,
                        1,
                        producer="build_project_model_from_scan",
                    ),
                    evidence_ids=[evidence_id],
                    metadata={"docker_service": name, "ports": docker_service.get("ports")},
                )
                self.add_relation(
                    source_id=self.source.id,
                    target_id=store_id,
                    relation_type=RelationType.CONTAINS,
                    rationale="The analyzed source explicitly declares this datastore in infrastructure metadata.",
                    evidence_ids=[evidence_id],
                    qualifier=name or image,
                    score=0.9,
                )

        for raw_component in self.scan.components or []:
            if not isinstance(raw_component, dict):
                continue
            component_name = raw_component.get("name") or ""
            component_id = component_index.get(component_name)
            if not component_id:
                continue
            for infra in raw_component.get("infrastructure") or []:
                if not isinstance(infra, dict):
                    continue
                entity_type = str(infra.get("entity_type") or "data_store")
                name = str(infra.get("name") or "")
                kind = str(infra.get("kind") or "unknown")
                confidence_score = float(infra.get("confidence") or 0.0)
                signals = set(infra.get("signals") or [])
                best_target = dict(infra.get("best_target") or {})
                evidence_ids: list[str] = []
                for evidence in infra.get("evidence") or []:
                    if not isinstance(evidence, dict):
                        continue
                    evidence_ids.append(
                        self.add_evidence(
                            source_id=self.source.id,
                            file_path=normalize_path(evidence.get("file") or raw_component.get("root_path") or "."),
                            line_start=evidence.get("line_start"),
                            line_end=evidence.get("line_end") or evidence.get("line_start"),
                            snippet_summary=f"Infrastructure evidence for {name}.",
                            snippet_excerpt=str(evidence.get("detail") or "")[:160],
                            detector_type="scanner_v3",
                            rule_name=str(evidence.get("type") or "infrastructure_detection"),
                            extraction_source="scan.components.infrastructure",
                            metadata={
                                "component": component_name,
                                "signal_type": evidence.get("type"),
                                "source": evidence.get("source"),
                                "target_rank": evidence.get("target_rank"),
                                "selection_reason": evidence.get("selection_reason"),
                            },
                        )
                    )

                if entity_type == "external_integration":
                    if confidence_score < 0.6 and signals == {"declared_dependency"}:
                        continue
                    integration_id = make_external_integration_id(self.source.id, name, kind)
                    if integration_id not in self.external_integrations:
                        self.external_integrations[integration_id] = ExternalIntegration(
                            id=integration_id,
                            source_ids=[self.source.id],
                            name=name,
                            kind=kind,
                            provider=infra.get("provider") or name,
                            confidence=make_confidence(
                                confidence_score or 0.65,
                                "External integration inferred from scanner infrastructure evidence.",
                                len(evidence_ids),
                                max(len(signals), 1),
                                producer="build_project_model_from_scan",
                            ),
                            evidence_ids=evidence_ids,
                            metadata={
                                "technology": infra.get("technology"),
                                "manifest_paths": list(infra.get("manifest_paths") or []),
                                "best_target": best_target,
                            },
                        )
                        self.add_relation(
                            source_id=self.source.id,
                            target_id=integration_id,
                            relation_type=RelationType.CONTAINS,
                            rationale="The analyzed source contains this detected external integration.",
                            evidence_ids=evidence_ids,
                            qualifier=name,
                            score=max(confidence_score, 0.65),
                        )
                    else:
                        integration = self.external_integrations[integration_id]
                        integration.evidence_ids = sorted(set(integration.evidence_ids) | set(evidence_ids))
                        integration.metadata = {
                            **integration.metadata,
                            "technology": integration.metadata.get("technology") or infra.get("technology"),
                            "manifest_paths": sorted(
                                set(integration.metadata.get("manifest_paths") or [])
                                | set(infra.get("manifest_paths") or [])
                            ),
                            "best_target": _prefer_best_target(
                                integration.metadata.get("best_target"),
                                best_target,
                            ),
                        }
                    self.add_relation(
                        source_id=component_id,
                        target_id=integration_id,
                        relation_type=RelationType.INTEGRATES_WITH,
                        rationale="Component-level infrastructure evidence shows this external integration.",
                        evidence_ids=evidence_ids,
                        qualifier=name,
                        metadata={"signals": sorted(signals)},
                        score=max(confidence_score, 0.65),
                    )
                    continue

                if confidence_score < 0.5 and signals == {"declared_dependency"}:
                    continue
                store_id = make_data_store_id(self.source.id, name, kind)
                if store_id not in self.data_stores:
                    self.data_stores[store_id] = DataStore(
                        id=store_id,
                        source_ids=[self.source.id],
                        name=name,
                        kind=kind,
                        technology=infra.get("technology") or name,
                        confidence=make_confidence(
                            confidence_score or 0.62,
                            "Infrastructure inferred from combined scanner dependency, docker, and code evidence.",
                            len(evidence_ids),
                            max(len(signals), 1),
                            producer="build_project_model_from_scan",
                        ),
                        evidence_ids=evidence_ids,
                        metadata={
                            "docker_services": list(infra.get("docker_services") or []),
                            "manifest_paths": list(infra.get("manifest_paths") or []),
                            "signals": sorted(signals),
                            "best_target": best_target,
                        },
                    )
                    self.add_relation(
                        source_id=self.source.id,
                        target_id=store_id,
                        relation_type=RelationType.CONTAINS,
                        rationale="The analyzed source contains this detected datastore or infrastructure service.",
                        evidence_ids=evidence_ids,
                        qualifier=name,
                        score=max(confidence_score, 0.62),
                    )
                else:
                    store = self.data_stores[store_id]
                    store.evidence_ids = sorted(set(store.evidence_ids) | set(evidence_ids))
                    store.metadata = {
                        **store.metadata,
                        "docker_services": sorted(
                            set(store.metadata.get("docker_services") or [])
                            | set(infra.get("docker_services") or [])
                        ),
                        "manifest_paths": sorted(
                            set(store.metadata.get("manifest_paths") or [])
                            | set(infra.get("manifest_paths") or [])
                        ),
                        "signals": sorted(
                            set(store.metadata.get("signals") or []) | set(signals)
                        ),
                        "best_target": _prefer_best_target(
                            store.metadata.get("best_target"),
                            best_target,
                        ),
                    }
                relation_type = RelationType.CONNECTS_TO
                if kind in {"sql", "document", "nosql", "cache"}:
                    relation_type = RelationType.READS_FROM
                elif kind in {"queue"}:
                    relation_type = RelationType.EMITS_TO
                self.add_relation(
                    source_id=component_id,
                    target_id=store_id,
                    relation_type=relation_type,
                    rationale="Component-level infrastructure evidence shows a connection to this internal service.",
                    evidence_ids=evidence_ids,
                    qualifier=name,
                    metadata={"signals": sorted(signals)},
                    score=max(confidence_score, 0.62),
                )

    def build(self) -> ProjectModel:
        self.build_components()
        self.build_runtime_nodes()
        self.build_routes()
        self.build_infrastructure()

        generation = ModelGeneration(
            model_version="system-model/v1",
            generated_at=(
                self.scan.created_at.isoformat()
                if self.scan.created_at is not None
                else datetime.now(timezone.utc).isoformat()
            ),
            generator="build_project_model_from_scan",
            source_snapshot_refs=[self.scan.id],
            metadata={
                "scan_id": self.scan.id,
                "project_type": self.scan.project_type,
                "file_count": self.scan.file_count,
            },
        )
        return assert_valid_project_model(
            ProjectModel(
                id=make_project_model_id(self.project.id),
                project_id=self.project.id,
                sources=self.sources,
                components=self.components,
                modules=self.modules,
                routes=self.routes,
                services=self.services,
                data_stores=self.data_stores,
                external_integrations=self.external_integrations,
                runtime_nodes=self.runtime_nodes,
                relations=self.relations,
                evidence=self.evidence,
                generation=generation,
                metadata={
                    "project_name": self.project.name,
                    "frameworks": list(self.scan.frameworks or []),
                    "languages": list(self.scan.languages or []),
                },
            )
        )


def _match_keyword(value: str, mapping: dict[str, tuple[str, str]]) -> Optional[tuple[str, str]]:
    lower = (value or "").lower()
    for keyword, result in mapping.items():
        if keyword in lower:
            return result
    return None


def _prefer_best_target(existing: Optional[dict], candidate: Optional[dict]) -> Optional[dict]:
    existing_target = dict(existing or {})
    candidate_target = dict(candidate or {})
    if not existing_target:
        return candidate_target or None
    if not candidate_target:
        return existing_target

    existing_rank = int(existing_target.get("target_rank") or 0)
    candidate_rank = int(candidate_target.get("target_rank") or 0)
    if candidate_rank > existing_rank:
        return candidate_target
    return existing_target


def build_project_model_from_scan(
    project: Project,
    scan: Scan,
    upload: Optional[Upload] = None,
) -> ProjectModel:
    """Build a canonical ProjectModel from the current Scan record.

    Integration guidance for v1:
    - scanner should populate this immediately after producing Scan JSON.
    - graph builder can migrate to read Components, RuntimeNodes, DataStores,
      ExternalIntegrations, and Relations rather than raw scan JSON.
    - route analysis can enrich Routes, Modules, Services, and Relations with
      tighter evidence and confidence later.
    - simulation can migrate to relation-type-aware traversal once graph edges
      are emitted from this model.
    """

    return _ModelBuilder(project=project, scan=scan, upload=upload).build()