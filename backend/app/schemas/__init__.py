from datetime import datetime

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
