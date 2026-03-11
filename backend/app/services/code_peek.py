from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import WORKSPACE_DIR
from app.domain.system_model.evidence import SourcePathKind
from app.models.graph_edge import GraphEdge
from app.models.graph_node import GraphNode
from app.models.upload import Upload
from app.services.scanner_v3 import unwrap_root_dir
from app.services.system_insights import build_system_insights_from_artifacts, load_latest_analysis_artifacts

logger = logging.getLogger(__name__)

_MAX_SNIPPET_LINES = 120
_MAX_SNIPPET_CHARS = 12000
_PRE_CONTEXT_LINES = 6
_POST_CONTEXT_LINES = 10
_LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "shell",
    ".toml": "toml",
    ".xml": "xml",
}
_PREFERRED_INFRA_FILES = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    "compose.yml",
    "compose.yaml",
    "requirements.txt",
    "pyproject.toml",
    "package.json",
)
_CODE_FILE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".php",
    ".sql",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".sh",
}


@dataclass
class WorkspaceContext:
    workspace_root: Path
    workspace_path: Path
    upload_id: str


@dataclass
class RetrievalContext:
    project_id: str
    artifacts: Any
    scan: Any
    snapshot_id: Optional[str]
    project_model: Optional[Any]
    graph_nodes: list[GraphNode]
    graph_edges: list[GraphEdge]
    graph_provenance: str
    workspace: WorkspaceContext
    file_inventory: list[str]
    key_files: list[str]
    entry_points: list[str]


@dataclass
class Candidate:
    source_type: str
    source_id: str
    retrieval_mode: str
    selection_reason: str
    file_path: Optional[str] = None
    source_root_kind: str = SourcePathKind.SOURCE_RELATIVE.value
    evidence_id: Optional[str] = None
    canonical_entity_id: Optional[str] = None
    symbol_name: Optional[str] = None
    symbol_kind: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    column_start: Optional[int] = None
    column_end: Optional[int] = None
    confidence: Optional[dict] = None
    resolved_via: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def build_code_peek(
    project_id: str,
    db: Session,
    evidence_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    insight_id: Optional[str] = None,
    graph_node_id: Optional[str] = None,
    graph_edge_id: Optional[str] = None,
    file_path: Optional[str] = None,
    component_root: Optional[str] = None,
) -> dict:
    requested_modes = {
        "evidence_ref": evidence_id,
        "entity": entity_id,
        "insight": insight_id,
        "graph_node": graph_node_id,
        "graph_edge": graph_edge_id,
        "file": file_path,
    }
    selected_modes = [mode for mode, value in requested_modes.items() if value]
    if len(selected_modes) != 1:
        raise RuntimeError(
            "Provide exactly one retrieval target: evidence_id, entity_id, insight_id, graph_node_id, graph_edge_id, or file_path"
        )
    if component_root and not file_path:
        raise RuntimeError("component_root is only supported together with file_path")

    context = _load_retrieval_context(project_id=project_id, db=db)
    mode = selected_modes[0]

    if mode == "evidence_ref":
        candidate = _candidate_from_evidence_id(context, evidence_id)
    elif mode == "entity":
        candidate = _candidate_from_entity_id(context, entity_id, source_type="entity", source_id=entity_id)
    elif mode == "insight":
        candidate = _candidate_from_insight_id(context, insight_id)
    elif mode == "graph_node":
        candidate = _candidate_from_graph_node_id(context, graph_node_id)
    elif mode == "graph_edge":
        candidate = _candidate_from_graph_edge_id(context, graph_edge_id)
    else:
        candidate = _candidate_from_file_path(context, file_path, component_root)

    resolved_path = _resolve_candidate_path(context, candidate)
    if resolved_path is None:
        raise ValueError("No safe source file could be resolved for the requested target")

    snippet = _extract_snippet(
        resolved_path,
        line_start=candidate.line_start,
        line_end=candidate.line_end,
        symbol_name=candidate.symbol_name,
    )
    if snippet is None:
        raise ValueError("Resolved source file could not be read safely")

    relative_file_path = _to_workspace_relative(resolved_path, context.workspace.workspace_root)
    response = {
        "project_id": project_id,
        "scan_id": context.scan.id,
        "snapshot_id": context.snapshot_id,
        "source_type": candidate.source_type,
        "source_id": candidate.source_id,
        "file_path": relative_file_path,
        "source_root_kind": candidate.source_root_kind,
        "symbol_name": candidate.symbol_name,
        "symbol_kind": candidate.symbol_kind,
        "line_start": snippet["requested_line_start"],
        "line_end": snippet["requested_line_end"],
        "column_start": candidate.column_start,
        "column_end": candidate.column_end,
        "snippet_text": snippet["text"],
        "snippet_truncated": snippet["truncated"],
        "language": _detect_language(resolved_path),
        "evidence_id": candidate.evidence_id,
        "canonical_entity_id": candidate.canonical_entity_id,
        "graph_provenance": context.graph_provenance,
        "confidence": candidate.confidence,
        "generated_from": {
            "generated_at": datetime.now(timezone.utc),
            "retrieval_mode": candidate.retrieval_mode,
            "resolved_via": candidate.resolved_via,
            "selection_reason": candidate.selection_reason,
            "file_hit": True,
            "workspace_root_resolved": True,
            "snippet_line_start": snippet["snippet_line_start"],
            "snippet_line_end": snippet["snippet_line_end"],
        },
    }

    logger.info(
        "Code peek built for project %s scan %s mode %s target %s via %s file_hit %s snippet_range %s-%s",
        project_id,
        context.scan.id,
        candidate.retrieval_mode,
        candidate.source_id,
        ",".join(candidate.resolved_via),
        True,
        snippet["snippet_line_start"],
        snippet["snippet_line_end"],
    )
    return response


def _load_retrieval_context(project_id: str, db: Session) -> RetrievalContext:
    artifacts = load_latest_analysis_artifacts(project_id=project_id, db=db)
    workspace = _resolve_workspace_context(project_id=project_id, scan=artifacts.scan, db=db)
    return RetrievalContext(
        project_id=project_id,
        artifacts=artifacts,
        scan=artifacts.scan,
        snapshot_id=artifacts.snapshot_id,
        project_model=artifacts.project_model,
        graph_nodes=artifacts.graph_nodes,
        graph_edges=artifacts.graph_edges,
        graph_provenance=artifacts.graph_provenance,
        workspace=workspace,
        file_inventory=sorted(
            str(item.get("path"))
            for item in (artifacts.scan.files or [])
            if isinstance(item, dict) and item.get("path")
        ),
        key_files=[str(path) for path in (artifacts.scan.key_files or []) if path],
        entry_points=[str(path) for path in (artifacts.scan.entry_points or []) if path],
    )


def _resolve_workspace_context(project_id: str, scan: Any, db: Session) -> WorkspaceContext:
    upload = db.query(Upload).filter(Upload.id == scan.upload_id).first()
    if upload is None:
        raise ValueError("Upload not found for the latest scan")

    workspace_path = (WORKSPACE_DIR / project_id / upload.id).resolve()
    if not workspace_path.is_dir():
        raise ValueError("Workspace files not found on disk. Re-upload and re-scan.")

    effective_root = Path(unwrap_root_dir(str(workspace_path))).resolve()
    if not _is_relative_to(effective_root, workspace_path):
        raise ValueError("Resolved workspace root is outside the project workspace")

    return WorkspaceContext(
        workspace_root=effective_root,
        workspace_path=workspace_path,
        upload_id=upload.id,
    )


def _candidate_from_evidence_id(context: RetrievalContext, evidence_id: str) -> Candidate:
    if context.project_model is None:
        raise ValueError("No validated canonical snapshot is available for evidence retrieval")
    evidence = context.project_model.evidence.get(evidence_id)
    if evidence is None:
        raise ValueError("Evidence ID was not found in the latest validated canonical snapshot")

    return _candidate_from_evidence(
        context,
        evidence,
        source_type="evidence_ref",
        source_id=evidence_id,
        canonical_entity_id=None,
        confidence=None,
        resolved_via=["canonical_evidence"],
    )


def _candidate_from_entity_id(
    context: RetrievalContext,
    entity_id: str,
    source_type: str,
    source_id: str,
) -> Candidate:
    if context.project_model is None:
        raise ValueError("No validated canonical snapshot is available for entity retrieval")

    entity = context.project_model.get_entity(entity_id)
    if entity is None:
        raise ValueError("Canonical entity ID was not found in the latest validated canonical snapshot")

    candidates: list[Candidate] = []
    for candidate_evidence_id in list(getattr(entity, "evidence_ids", [])):
        evidence = context.project_model.evidence.get(candidate_evidence_id)
        if evidence is None:
            continue
        candidates.append(
            _candidate_from_evidence(
                context,
                evidence,
                source_type=source_type,
                source_id=source_id,
                canonical_entity_id=entity.id,
                confidence=_confidence_from_value(getattr(entity, "confidence", None)),
                resolved_via=["canonical_entity", "canonical_evidence"],
            )
        )

    candidates.extend(_path_candidates_for_entity(context, entity, source_type=source_type, source_id=source_id))
    best = _choose_best_candidate(candidates)
    if best is None:
        raise ValueError("No retrievable source location was found for the canonical entity")
    return best


def _candidate_from_insight_id(context: RetrievalContext, insight_id: str) -> Candidate:
    insights_payload = build_system_insights_from_artifacts(
        project_id=context.project_id,
        artifacts=context.artifacts,
    )
    insight = next((item for item in insights_payload["insights"] if item["insight_id"] == insight_id), None)
    if insight is None:
        raise ValueError("Insight ID was not found in the latest deterministic insights payload")

    candidates: list[Candidate] = []
    for evidence_ref in insight.get("evidence_refs", []):
        ref_type = evidence_ref.get("ref_type")
        metadata = evidence_ref.get("metadata") or {}
        if ref_type == "canonical_evidence":
            try:
                candidates.append(_candidate_from_evidence_id(context, evidence_ref.get("ref_id")))
            except ValueError:
                continue
            continue
        if ref_type == "graph_node" and metadata.get("canonical_entity_id"):
            try:
                candidates.append(
                    _candidate_from_entity_id(
                        context,
                        metadata["canonical_entity_id"],
                        source_type="insight",
                        source_id=insight_id,
                    )
                )
            except ValueError:
                continue
        if evidence_ref.get("file_path"):
            candidates.append(
                Candidate(
                    source_type="insight",
                    source_id=insight_id,
                    retrieval_mode="insight_supporting_file",
                    selection_reason="insight evidence exposed a concrete file path",
                    file_path=str(evidence_ref.get("file_path")),
                    source_root_kind=SourcePathKind.SOURCE_RELATIVE.value,
                    resolved_via=["deterministic_insight", "evidence_ref_file_path"],
                )
            )

    for candidate_entity_id in insight.get("supporting_entity_ids", []):
        try:
            candidates.append(
                _candidate_from_entity_id(
                    context,
                    candidate_entity_id,
                    source_type="insight",
                    source_id=insight_id,
                )
            )
        except ValueError:
            continue

    for candidate_graph_node_id in insight.get("supporting_graph_node_ids", []):
        try:
            candidates.append(_candidate_from_graph_node_id(context, candidate_graph_node_id))
        except ValueError:
            continue

    for candidate_graph_edge_id in insight.get("supporting_graph_edge_ids", []):
        try:
            candidates.append(_candidate_from_graph_edge_id(context, candidate_graph_edge_id))
        except ValueError:
            continue

    if not candidates:
        fallback_candidate = Candidate(
            source_type="insight",
            source_id=insight_id,
            retrieval_mode="insight_scan_fallback",
            selection_reason="insight is diagnostic-only, so retrieval falls back to the strongest same-scan file",
            resolved_via=["deterministic_insight", "scan_fallback_file"],
            metadata={"entity_kind": "insight_fallback"},
        )
        fallback_path = _pick_fallback_file(context, fallback_candidate)
        if fallback_path is not None:
            fallback_candidate.file_path = _to_workspace_relative(
                fallback_path,
                context.workspace.workspace_root,
            )
            candidates.append(fallback_candidate)

    best = _choose_best_candidate(candidates)
    if best is None:
        raise ValueError("No retrievable supporting code could be resolved for the insight")

    best.source_type = "insight"
    best.source_id = insight_id
    best.retrieval_mode = "insight_supporting_evidence"
    if "deterministic_insight" not in best.resolved_via:
        best.resolved_via.insert(0, "deterministic_insight")
    return best


def _candidate_from_graph_node_id(context: RetrievalContext, graph_node_id: str) -> Candidate:
    node = next((item for item in context.graph_nodes if item.id == graph_node_id), None)
    if node is None:
        raise ValueError("Graph node ID was not found in the current graph")

    if node.canonical_entity_id:
        candidate = _candidate_from_entity_id(
            context,
            node.canonical_entity_id,
            source_type="graph_node",
            source_id=graph_node_id,
        )
        candidate.retrieval_mode = "graph_node_via_canonical_entity"
        if "graph_provenance" not in candidate.resolved_via:
            candidate.resolved_via.append("graph_provenance")
        return candidate

    fallback_candidates: list[Candidate] = []
    node_data = node.data or {}
    entry_file = node_data.get("entry_file")
    root_path = node_data.get("root_path")
    if entry_file:
        fallback_candidates.append(
            Candidate(
                source_type="graph_node",
                source_id=graph_node_id,
                retrieval_mode="graph_node_direct_file",
                selection_reason="graph node carried an entry_file path",
                file_path=str(entry_file),
                source_root_kind=SourcePathKind.SOURCE_RELATIVE.value,
                confidence=_confidence_from_graph_node(node),
                resolved_via=["graph_node_data"],
            )
        )
    if root_path:
        fallback_candidates.append(
            Candidate(
                source_type="graph_node",
                source_id=graph_node_id,
                retrieval_mode="graph_node_direct_file",
                selection_reason="graph node carried a component root path",
                file_path=str(root_path),
                source_root_kind=SourcePathKind.SOURCE_RELATIVE.value,
                confidence=_confidence_from_graph_node(node),
                resolved_via=["graph_node_data"],
                metadata={"component_root": str(root_path)},
            )
        )
    best = _choose_best_candidate(fallback_candidates)
    if best is None:
        raise ValueError("Graph node does not have canonical provenance or a retrievable file path")
    return best


def _candidate_from_graph_edge_id(context: RetrievalContext, graph_edge_id: str) -> Candidate:
    edge = next((item for item in context.graph_edges if item.id == graph_edge_id), None)
    if edge is None:
        raise ValueError("Graph edge ID was not found in the current graph")

    candidates: list[Candidate] = []
    if context.project_model is not None and edge.canonical_relation_id:
        relation = context.project_model.relations.get(edge.canonical_relation_id)
        if relation is not None:
            relation_confidence = _confidence_from_value(relation.confidence)
            for evidence_id in relation.evidence_ids:
                evidence = context.project_model.evidence.get(evidence_id)
                if evidence is None:
                    continue
                candidates.append(
                    _candidate_from_evidence(
                        context,
                        evidence,
                        source_type="graph_edge",
                        source_id=graph_edge_id,
                        canonical_entity_id=relation.source_id,
                        confidence=relation_confidence,
                        resolved_via=["graph_edge_relation", "canonical_evidence"],
                    )
                )

            for endpoint_entity_id in (relation.source_id, relation.target_id):
                try:
                    candidates.append(
                        _candidate_from_entity_id(
                            context,
                            endpoint_entity_id,
                            source_type="graph_edge",
                            source_id=graph_edge_id,
                        )
                    )
                except ValueError:
                    continue

    for endpoint_node_id in (edge.source_node_id, edge.target_node_id):
        endpoint = next((item for item in context.graph_nodes if item.id == endpoint_node_id), None)
        if endpoint is None or not endpoint.canonical_entity_id:
            continue
        try:
            candidates.append(
                _candidate_from_entity_id(
                    context,
                    endpoint.canonical_entity_id,
                    source_type="graph_edge",
                    source_id=graph_edge_id,
                )
            )
        except ValueError:
            continue

    best = _choose_best_candidate(candidates)
    if best is None:
        raise ValueError("Graph edge does not have strong enough backing evidence for code retrieval")
    best.source_type = "graph_edge"
    best.source_id = graph_edge_id
    best.retrieval_mode = "graph_edge_backing_evidence"
    if "graph_provenance" not in best.resolved_via:
        best.resolved_via.append("graph_provenance")
    return best


def _candidate_from_file_path(
    context: RetrievalContext,
    file_path: str,
    component_root: Optional[str],
) -> Candidate:
    normalized_component_root = _normalize_relative_path(component_root) if component_root else None
    normalized_path = _normalize_relative_path(file_path)
    if normalized_component_root and not normalized_path.startswith(f"{normalized_component_root}/"):
        normalized_path = f"{normalized_component_root}/{normalized_path}" if normalized_component_root != "." else normalized_path

    source_type = "deep_dive_item" if normalized_component_root else "file"
    retrieval_mode = "deep_dive_item_file" if normalized_component_root else "direct_file_path"
    selection_reason = (
        "deep dive file resolved within the selected component root"
        if normalized_component_root
        else "file path was requested directly"
    )
    return Candidate(
        source_type=source_type,
        source_id=normalized_path,
        retrieval_mode=retrieval_mode,
        selection_reason=selection_reason,
        file_path=normalized_path,
        source_root_kind=SourcePathKind.SOURCE_RELATIVE.value,
        resolved_via=["direct_file_path"] if not normalized_component_root else ["deep_dive_item", "direct_file_path"],
        metadata={"component_root": normalized_component_root},
    )


def _candidate_from_evidence(
    context: RetrievalContext,
    evidence,
    source_type: str,
    source_id: str,
    canonical_entity_id: Optional[str],
    confidence: Optional[dict],
    resolved_via: list[str],
) -> Candidate:
    return Candidate(
        source_type=source_type,
        source_id=source_id,
        retrieval_mode="evidence_first",
        selection_reason=_selection_reason_for_evidence(evidence),
        file_path=evidence.file_path,
        source_root_kind=(evidence.path_kind.value if hasattr(evidence.path_kind, "value") else str(evidence.path_kind)),
        evidence_id=evidence.id,
        canonical_entity_id=canonical_entity_id,
        symbol_name=evidence.symbol,
        symbol_kind=evidence.symbol_kind,
        line_start=evidence.line_start,
        line_end=evidence.line_end,
        column_start=evidence.column_start,
        column_end=evidence.column_end,
        confidence=confidence,
        resolved_via=resolved_via,
        metadata={
            "rule_name": evidence.rule_name,
            "snippet_summary": evidence.snippet_summary,
            "detector_type": evidence.detector_type,
            "path_kind": evidence.path_kind.value if hasattr(evidence.path_kind, "value") else str(evidence.path_kind),
        },
    )


def _path_candidates_for_entity(context: RetrievalContext, entity, source_type: str, source_id: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    confidence = _confidence_from_value(getattr(entity, "confidence", None))
    entity_kind = getattr(getattr(entity, "entity_kind", None), "value", None)

    if getattr(entity, "path", None):
        candidates.append(
            Candidate(
                source_type=source_type,
                source_id=source_id,
                retrieval_mode="entity_direct_path",
                selection_reason="entity exposes a direct source path",
                file_path=entity.path,
                source_root_kind=SourcePathKind.SOURCE_RELATIVE.value,
                canonical_entity_id=getattr(entity, "id", None),
                symbol_name=getattr(entity, "symbol", None),
                symbol_kind=getattr(entity, "symbol_kind", None),
                confidence=confidence,
                resolved_via=["canonical_entity_path"],
            )
        )

    if getattr(entity, "file_path", None):
        candidates.append(
            Candidate(
                source_type=source_type,
                source_id=source_id,
                retrieval_mode="entity_direct_path",
                selection_reason="entity exposes a direct file_path",
                file_path=entity.file_path,
                source_root_kind=SourcePathKind.SOURCE_RELATIVE.value,
                canonical_entity_id=getattr(entity, "id", None),
                symbol_name=getattr(entity, "handler_name", None),
                symbol_kind="handler" if getattr(entity, "handler_name", None) else None,
                confidence=confidence,
                resolved_via=["canonical_entity_path"],
            )
        )

    if getattr(entity, "entry_file", None):
        candidates.append(
            Candidate(
                source_type=source_type,
                source_id=source_id,
                retrieval_mode="entity_entry_file",
                selection_reason="component entry_file is the strongest direct file reference",
                file_path=entity.entry_file,
                source_root_kind=SourcePathKind.SOURCE_RELATIVE.value,
                canonical_entity_id=getattr(entity, "id", None),
                confidence=confidence,
                resolved_via=["canonical_entity_path"],
                metadata={"component_root": getattr(entity, "root_path", None)},
            )
        )

    if getattr(entity, "root_path", None):
        candidates.append(
            Candidate(
                source_type=source_type,
                source_id=source_id,
                retrieval_mode="entity_component_root",
                selection_reason="component root is available and can be resolved to an entry or code file",
                file_path=entity.root_path,
                source_root_kind=SourcePathKind.SOURCE_RELATIVE.value,
                canonical_entity_id=getattr(entity, "id", None),
                confidence=confidence,
                resolved_via=["canonical_entity_path"],
                metadata={"component_root": entity.root_path, "entry_file": getattr(entity, "entry_file", None)},
            )
        )

    if entity_kind == "service":
        for module_id in list(getattr(entity, "module_ids", [])):
            module = context.project_model.modules.get(module_id) if context.project_model is not None else None
            if module is None:
                continue
            candidates.extend(_path_candidates_for_entity(context, module, source_type=source_type, source_id=source_id))

    if entity_kind in {"data_store", "external_integration", "runtime_node", "source"}:
        candidates.append(
            Candidate(
                source_type=source_type,
                source_id=source_id,
                retrieval_mode="entity_fallback_key_file",
                selection_reason="entity only has high-level evidence, so retrieval falls back to the strongest matching config or entry file",
                canonical_entity_id=getattr(entity, "id", None),
                confidence=confidence,
                resolved_via=["canonical_entity_fallback"],
                metadata={"entity_kind": entity_kind},
            )
        )

    return candidates


def _choose_best_candidate(candidates: list[Candidate]) -> Optional[Candidate]:
    if not candidates:
        return None

    def key(candidate: Candidate) -> tuple[int, int, int, int, str, str]:
        priority = _candidate_priority(candidate)
        has_file_path = 1 if candidate.file_path else 0
        has_line_range = 1 if candidate.line_start is not None else 0
        has_symbol = 1 if candidate.symbol_name else 0
        return (
            priority,
            has_file_path,
            has_line_range,
            has_symbol,
            candidate.evidence_id or "",
            candidate.file_path or candidate.source_id,
        )

    return sorted(candidates, key=key, reverse=True)[0]


def _candidate_priority(candidate: Candidate) -> int:
    if candidate.symbol_name and candidate.line_start is not None:
        return 4
    if candidate.line_start is not None:
        return 3
    if candidate.symbol_name:
        return 2
    if candidate.file_path:
        return 1
    return 0


def _resolve_candidate_path(context: RetrievalContext, candidate: Candidate) -> Optional[Path]:
    if candidate.file_path:
        resolved = _resolve_file_reference(
            workspace_root=context.workspace.workspace_root,
            raw_path=candidate.file_path,
            source_root_kind=candidate.source_root_kind,
        )
        if resolved is not None:
            component_root = candidate.metadata.get("component_root")
            if component_root and not _path_is_within_component_root(
                resolved,
                workspace_root=context.workspace.workspace_root,
                component_root=str(component_root),
            ):
                return None
            if resolved.is_dir():
                return _pick_best_file_from_directory(context, resolved, candidate)
            return resolved if resolved.is_file() else None

    return _pick_fallback_file(context, candidate)


def _resolve_file_reference(workspace_root: Path, raw_path: str, source_root_kind: str) -> Optional[Path]:
    if not raw_path:
        return None

    if source_root_kind == SourcePathKind.LOGICAL_ROOT.value:
        normalized = _normalize_relative_path(raw_path)
        if normalized in {".", ""}:
            return workspace_root

    raw_candidate = Path(raw_path)
    if raw_candidate.is_absolute():
        resolved = raw_candidate.resolve()
        if _is_relative_to(resolved, workspace_root):
            return resolved
        return None

    normalized = _normalize_relative_path(raw_path)
    resolved = (workspace_root / normalized).resolve()
    if _is_relative_to(resolved, workspace_root) and resolved.exists():
        return resolved

    return None


def _pick_best_file_from_directory(context: RetrievalContext, directory: Path, candidate: Candidate) -> Optional[Path]:
    directory_relative = _to_workspace_relative(directory, context.workspace.workspace_root)
    preferred_paths: list[str] = []
    entry_file = candidate.metadata.get("entry_file")
    component_root = candidate.metadata.get("component_root")
    if entry_file:
        preferred_paths.append(_normalize_relative_path(entry_file))
    if component_root:
        preferred_paths.extend(
            path for path in context.entry_points if _normalize_relative_path(path).startswith(f"{_normalize_relative_path(component_root)}/")
        )

    preferred_paths.extend(
        path for path in context.entry_points if _normalize_relative_path(path).startswith(f"{directory_relative}/")
    )
    preferred_paths.extend(
        path for path in context.key_files if _normalize_relative_path(path).startswith(f"{directory_relative}/")
    )

    for preferred in preferred_paths:
        preferred_file = _resolve_file_reference(
            workspace_root=context.workspace.workspace_root,
            raw_path=preferred,
            source_root_kind=SourcePathKind.SOURCE_RELATIVE.value,
        )
        if preferred_file is not None and preferred_file.is_file():
            return preferred_file

    return _first_code_file_under_directory(directory)


def _pick_fallback_file(context: RetrievalContext, candidate: Candidate) -> Optional[Path]:
    entity_kind = candidate.metadata.get("entity_kind")
    if entity_kind == "data_store":
        for preferred in _PREFERRED_INFRA_FILES:
            for key_file in context.key_files:
                if key_file.endswith(preferred):
                    resolved = _resolve_file_reference(
                        workspace_root=context.workspace.workspace_root,
                        raw_path=key_file,
                        source_root_kind=SourcePathKind.SOURCE_RELATIVE.value,
                    )
                    if resolved is not None and resolved.is_file():
                        return resolved

    for preferred in context.entry_points + context.key_files + context.file_inventory:
        resolved = _resolve_file_reference(
            workspace_root=context.workspace.workspace_root,
            raw_path=preferred,
            source_root_kind=SourcePathKind.SOURCE_RELATIVE.value,
        )
        if resolved is not None and resolved.is_file():
            return resolved
    return None


def _first_code_file_under_directory(directory: Path) -> Optional[Path]:
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in _CODE_FILE_EXTENSIONS:
            return path
    return None


def _extract_snippet(
    file_path: Path,
    line_start: Optional[int],
    line_end: Optional[int],
    symbol_name: Optional[str],
) -> Optional[dict]:
    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return None

    if not lines:
        return {
            "text": "",
            "truncated": False,
            "requested_line_start": line_start,
            "requested_line_end": line_end,
            "snippet_line_start": 1,
            "snippet_line_end": 1,
        }

    effective_line_start = line_start
    effective_line_end = line_end or line_start
    if effective_line_start is None and symbol_name:
        effective_line_start = _locate_symbol_line(lines, symbol_name)
        effective_line_end = effective_line_start

    if effective_line_start is None:
        snippet_line_start = 1
        snippet_line_end = min(len(lines), _MAX_SNIPPET_LINES)
    else:
        snippet_line_start = max(1, effective_line_start - _PRE_CONTEXT_LINES)
        snippet_line_end = min(len(lines), (effective_line_end or effective_line_start) + _POST_CONTEXT_LINES)
        if snippet_line_end - snippet_line_start + 1 > _MAX_SNIPPET_LINES:
            snippet_line_end = snippet_line_start + _MAX_SNIPPET_LINES - 1

    snippet_lines = lines[snippet_line_start - 1:snippet_line_end]
    truncated = snippet_line_end < len(lines)
    snippet_text = "".join(snippet_lines)
    if len(snippet_text) > _MAX_SNIPPET_CHARS:
        snippet_text = snippet_text[:_MAX_SNIPPET_CHARS]
        truncated = True

    return {
        "text": snippet_text,
        "truncated": truncated,
        "requested_line_start": effective_line_start,
        "requested_line_end": effective_line_end,
        "snippet_line_start": snippet_line_start,
        "snippet_line_end": min(snippet_line_end, snippet_line_start + len(snippet_lines) - 1),
    }


def _locate_symbol_line(lines: list[str], symbol_name: str) -> Optional[int]:
    pattern = re.compile(rf"\b{re.escape(symbol_name)}\b")
    for index, line in enumerate(lines, start=1):
        if pattern.search(line):
            return index
    return None


def _selection_reason_for_evidence(evidence) -> str:
    if evidence.symbol and evidence.line_start is not None:
        return "selected highest-quality evidence with explicit symbol and line range"
    if evidence.line_start is not None:
        return "selected evidence with an explicit line range"
    if evidence.symbol:
        return "selected evidence with an explicit symbol name"
    if evidence.file_path:
        return "selected evidence with a direct source path"
    return "selected the best available evidence reference"


def _confidence_from_value(confidence: Optional[Any]) -> Optional[dict]:
    if confidence is None:
        return None
    label = confidence.label.value if hasattr(confidence.label, "value") else str(confidence.label)
    return {
        "score": round(float(confidence.score), 3),
        "label": label,
        "reasons": list(confidence.reasons or ([confidence.rationale] if confidence.rationale else [])),
    }


def _confidence_from_graph_node(node: GraphNode) -> Optional[dict]:
    if node.confidence_score is None and node.confidence_label is None:
        return None
    return {
        "score": round(float(node.confidence_score or 0.0), 3),
        "label": node.confidence_label or "low",
        "reasons": ["retrieval is backed by persisted graph provenance"],
    }


def _detect_language(file_path: Path) -> Optional[str]:
    return _LANGUAGE_BY_EXTENSION.get(file_path.suffix.lower())


def _normalize_relative_path(path: Optional[str]) -> str:
    normalized = (path or ".").replace("\\", "/").strip()
    if not normalized:
        return "."
    return normalized.strip("/") or "."


def _to_workspace_relative(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix() or "."
    except ValueError:
        return path.as_posix()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _path_is_within_component_root(path: Path, workspace_root: Path, component_root: str) -> bool:
    relative_path = _to_workspace_relative(path, workspace_root)
    normalized_component_root = _normalize_relative_path(component_root)
    return relative_path == normalized_component_root or relative_path.startswith(f"{normalized_component_root}/")

