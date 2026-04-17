from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str
    path: str


class ProjectResponse(BaseModel):
    id: str
    name: str
    path: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UploadResponse(BaseModel):
    id: str
    project_id: str
    filename: str
    storage_path: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ScanResponse(BaseModel):
    id: str
    project_id: str
    upload_id: str
    status: str
    file_count: int
    files: list[dict]
    languages: list[str]
    frameworks: list[str]
    key_files: list[str]
    top_level_dirs: list[str]
    extension_counts: dict[str, int]
    project_type: str
    entry_points: list[str]
    components: list[dict] = Field(default_factory=list)
    # ── Scanner V3 fields ──
    confidence_scores: Optional[dict] = None
    dependencies: Optional[dict] = None
    service_graph: Optional[list] = None
    routes: Optional[list] = None
    import_graph: Optional[dict] = None
    execution_flow: Optional[list] = None
    env_variables: Optional[list] = None
    docker_services: Optional[list] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class GraphNodeResponse(BaseModel):
    id: str
    project_id: str
    scan_id: str
    node_type: str
    label: str
    data: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class GraphEdgeResponse(BaseModel):
    id: str
    project_id: str
    scan_id: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectGraphResponse(BaseModel):
    project_id: str
    scan_id: str
    node_count: int
    edge_count: int
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


class SimulationRunResponse(BaseModel):
    id: str
    project_id: str
    scan_id: str
    failed_node_id: str
    severity: str
    summary: str
    impacted_nodes: list[dict]
    result: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class InsightEvidenceRef(BaseModel):
    ref_type: str
    artifact: str
    ref_id: str
    label: str
    file_path: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InsightConfidence(BaseModel):
    score: float
    label: str
    reasons: list[str] = Field(default_factory=list)


class ProjectInsight(BaseModel):
    insight_id: str
    category: str
    subtype: str
    severity: str
    confidence: InsightConfidence
    title: str
    explanation: str
    evidence_refs: list[InsightEvidenceRef] = Field(default_factory=list)
    supporting_entity_ids: list[str] = Field(default_factory=list)
    supporting_graph_node_ids: list[str] = Field(default_factory=list)
    supporting_graph_edge_ids: list[str] = Field(default_factory=list)
    scan_id: str
    snapshot_id: Optional[str] = None
    graph_scan_id: Optional[str] = None
    graph_provenance: Optional[str] = None
    source_modes: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class InsightsGeneratedFrom(BaseModel):
    generated_at: datetime
    latest_scan_created_at: datetime
    canonical_snapshot_used: bool
    graph_used: bool
    graph_provenance: str
    simulation_used: bool
    simulation_mode: Optional[str] = None
    source_modes: list[str] = Field(default_factory=list)
    detectors_run: list[str] = Field(default_factory=list)
    detectors_skipped: list[str] = Field(default_factory=list)


class ProjectInsightsResponse(BaseModel):
    project_id: str
    scan_id: str
    snapshot_id: Optional[str] = None
    graph_scan_id: Optional[str] = None
    graph_provenance: str
    insight_count: int
    counts_by_severity: dict[str, int] = Field(default_factory=dict)
    counts_by_category: dict[str, int] = Field(default_factory=dict)
    insights: list[ProjectInsight] = Field(default_factory=list)
    generated_from: InsightsGeneratedFrom


class CodePeekConfidence(BaseModel):
    score: float
    label: str
    reasons: list[str] = Field(default_factory=list)


class CodePeekGeneratedFrom(BaseModel):
    generated_at: datetime
    retrieval_mode: str
    resolved_via: list[str] = Field(default_factory=list)
    selection_reason: str
    file_hit: bool
    workspace_root_resolved: bool
    snippet_line_start: Optional[int] = None
    snippet_line_end: Optional[int] = None


class CodePeekResponse(BaseModel):
    project_id: str
    scan_id: str
    snapshot_id: Optional[str] = None
    source_type: str
    source_id: str
    file_path: str
    source_root_kind: str
    symbol_name: Optional[str] = None
    symbol_kind: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    column_start: Optional[int] = None
    column_end: Optional[int] = None
    snippet_text: str
    snippet_truncated: bool
    language: Optional[str] = None
    evidence_id: Optional[str] = None
    canonical_entity_id: Optional[str] = None
    graph_provenance: Optional[str] = None
    confidence: Optional[CodePeekConfidence] = None
    generated_from: CodePeekGeneratedFrom


class RouteCountSummary(BaseModel):
    total: int
    by_method: dict[str, int]


class SummaryHighlight(BaseModel):
    category: str
    label: str
    detail: str
    confidence: str
    supporting_ids: list[str] = Field(default_factory=list)


class CriticalNodeSummary(BaseModel):
    node_id: str
    label: str
    node_type: str
    criticality_score: float
    graph_source: Optional[str] = None
    canonical_entity_id: Optional[str] = None
    reason: str


class SummaryFinding(BaseModel):
    category: str
    severity: str
    confidence: str
    explanation: str
    supporting_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class SummaryConfidence(BaseModel):
    overall_score: float
    overall_label: str
    reasons: list[str]
    canonical_snapshot_used: bool
    graph_used: bool
    graph_provenance: str
    simulation_mode: Optional[str] = None


class SummaryGeneratedFrom(BaseModel):
    generated_at: datetime
    latest_scan_created_at: datetime
    canonical_snapshot_used: bool
    graph_used: bool
    graph_provenance: str
    simulation_used: bool
    simulation_mode: Optional[str] = None


class SystemIntelligenceSummaryResponse(BaseModel):
    project_id: str
    scan_id: str
    snapshot_id: Optional[str] = None
    graph_scan_id: Optional[str] = None
    graph_provenance: str
    system_type_guess: str
    primary_stack: list[str]
    architecture_hints: list[str]
    component_counts: dict[str, int]
    route_counts: RouteCountSummary
    runtime_dependency_highlights: list[SummaryHighlight]
    critical_nodes: list[CriticalNodeSummary]
    top_findings: list[SummaryFinding]
    top_risks: list[SummaryFinding]
    confidence_summary: SummaryConfidence
    overview_text: str
    generated_from: SummaryGeneratedFrom


class BriefComponentDetail(BaseModel):
    name: str
    type: str
    description: str


class RepoBriefResponse(BaseModel):
    project_id: str
    repo_summary: str
    main_components: list[BriefComponentDetail]
    architecture_explanation: str
    reading_order: list[str]
    risk_notes: list[str]
    simulation_insight: Optional[str] = None


# ── Component Deep Dive schemas ──────────────────────────────────────

class DeepDiveRequest(BaseModel):
    component_root: str  # e.g. "backend", "frontend", "." for root


class InternalModule(BaseModel):
    name: str
    file_count: int
    dominant_role: str
    roles: list[str]
    files: list[str]


class ImportantFile(BaseModel):
    path: str
    role: str
    score: int


class InternalEdge(BaseModel):
    source: str
    target: str
    type: str
    weight: int = 1


class ModuleEdge(BaseModel):
    source_module: str
    target_module: str
    edge_count: int


class FlowStep(BaseModel):
    step: str
    example_files: list[str]


class DeepDiveResponse(BaseModel):
    project_id: str
    component_name: str
    component_type: str
    component_summary: str
    internal_modules: list[InternalModule]
    important_files: list[ImportantFile]
    internal_edges: list[InternalEdge]
    module_edges: list[ModuleEdge]
    probable_start_file: Optional[str] = None
    probable_flow_steps: list[FlowStep]
    notes: list[str]


class RoutePreview(BaseModel):
    method: str
    path: str
    summary: str


class LanguageStat(BaseModel):
    name: str
    percentage: float


class ProjectInsights(BaseModel):
    complexity: str
    complexity_reason: str
    entry_points: str
    entry_points_detail: str
    external_services: list[str]
    external_services_detail: str
    auth_summary: str


class ProjectDashboardResponse(BaseModel):
    project_name: str
    executive_summary: str
    languages: list[LanguageStat]
    dependencies: list[str]
    total_routes: int
    total_files: int
    components: list[str]
    routes_preview: list[RoutePreview]
    insights: Optional[ProjectInsights] = None


class DashboardChatRequest(BaseModel):
    messages: list[dict[str, str]]


class DashboardChatResponse(BaseModel):
    response: str


class ProjectUnderstandingResponse(BaseModel):
    id: str
    project_id: str
    status: str
    project_story: Optional[str] = None
    project_story_beginner: Optional[str] = None
    project_story_intermediate: Optional[str] = None
    project_story_advanced: Optional[str] = None
    system_map: Optional[list[dict]] = None
    data_journey: Optional[list[dict]] = None
    key_decisions: Optional[list[dict]] = None
    key_decisions_beginner: Optional[list[dict]] = None
    key_decisions_intermediate: Optional[list[dict]] = None
    key_decisions_advanced: Optional[list[dict]] = None
    gotchas: Optional[list[dict]] = None
    gotchas_beginner: Optional[list[dict]] = None
    gotchas_intermediate: Optional[list[dict]] = None
    gotchas_advanced: Optional[list[dict]] = None
    glossary: Optional[list[dict]] = None
    generated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UnderstandingChatRequest(BaseModel):
    section: str
    message: str
    history: Optional[list[dict[str, str]]] = None


class UnderstandingChatResponse(BaseModel):
    response: str
