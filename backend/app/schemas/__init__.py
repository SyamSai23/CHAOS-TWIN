from datetime import datetime
from typing import Optional

from pydantic import BaseModel


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
    components: list[dict] = []
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
