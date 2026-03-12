import type {
  CodePeekResponse,
  DeepDiveResult,
  GraphResponse,
  Project,
  ProjectInsightsResponse,
  RouteAnalysis,
  RouteDetail,
  RoutesResponse,
  ScanResult,
  SimulationResult,
  SystemIntelligenceSummaryResponse,
} from "../types";
import type { SequenceData } from "../SequenceDiagram";

export type CodePeekParams = {
  evidence_id?: string;
  entity_id?: string;
  insight_id?: string;
  graph_node_id?: string;
  graph_edge_id?: string;
  file_path?: string;
  component_root?: string;
};

export type UploadResponse = {
  id: string;
  project_id: string;
  filename: string;
  storage_path: string;
  created_at: string;
};

export type RouteSequenceRecord = {
  route_id: string;
  diagram_data: SequenceData;
  created_at: string | null;
};

export const API_BASE =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function parseResponse<T>(response: Response, fallbackMessage: string): Promise<T> {
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.detail || body?.message || fallbackMessage);
  }
  return body as T;
}

export async function fetchHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/health`);
  return parseResponse(response, "Failed to load API health");
}

export async function fetchDbHealth(): Promise<{ status: string; database: string }> {
  const response = await fetch(`${API_BASE}/health/db`);
  return parseResponse(response, "Failed to load DB health");
}

export async function listProjects(): Promise<Project[]> {
  const response = await fetch(`${API_BASE}/projects`);
  return parseResponse(response, "Failed to load projects");
}

export async function createProject(payload: { name: string; path: string }): Promise<Project> {
  const response = await fetch(`${API_BASE}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response, "Failed to create project");
}

export async function deleteProject(projectId: string): Promise<{ deleted: boolean }> {
  const response = await fetch(`${API_BASE}/projects/${projectId}`, {
    method: "DELETE",
  });
  return parseResponse(response, "Failed to delete project");
}

export async function uploadProjectZip(projectId: string, file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE}/projects/${projectId}/upload`, {
    method: "POST",
    body: formData,
  });
  return parseResponse(response, "Upload failed");
}

export async function runProjectScan(projectId: string): Promise<ScanResult> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/scan`, {
    method: "POST",
  });
  return parseResponse(response, "Scan failed");
}

export async function fetchLatestProjectScan(projectId: string): Promise<ScanResult> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/scan`);
  return parseResponse(response, "Failed to load latest scan");
}

export async function generateProjectGraph(projectId: string): Promise<GraphResponse> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/graph`, {
    method: "POST",
  });
  return parseResponse(response, "Graph generation failed");
}

export async function runProjectSimulation(projectId: string, nodeId: string): Promise<SimulationResult> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ node_id: nodeId }),
  });
  return parseResponse(response, "Simulation failed");
}

export async function fetchComponentDeepDive(projectId: string, componentRoot: string): Promise<DeepDiveResult> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/components/deep-dive`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ component_root: componentRoot }),
  });
  return parseResponse(response, "Deep dive failed");
}

export async function getProjectSummary(projectId: string): Promise<SystemIntelligenceSummaryResponse> {
  const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/summary`);
  return parseResponse(response, "Failed to load project summary");
}

export async function getProjectInsights(projectId: string): Promise<ProjectInsightsResponse> {
  const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/insights`);
  return parseResponse(response, "Failed to load project insights");
}

export async function getCodePeek(projectId: string, params: CodePeekParams): Promise<CodePeekResponse> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) {
      search.set(key, value);
    }
  }
  const response = await fetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/code-peek?${search.toString()}`,
  );
  return parseResponse(response, "Failed to load code peek");
}

export async function fetchRoutes(projectId: string): Promise<RoutesResponse> {
  const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/routes`);
  return parseResponse(response, "Failed to load routes");
}

export async function fetchRouteDetail(projectId: string, routeId: string): Promise<RouteDetail> {
  const response = await fetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/routes/${encodeURIComponent(routeId)}`,
  );
  return parseResponse(response, "Failed to load route detail");
}

export async function fetchRouteAnalysis(projectId: string, routeId: string): Promise<RouteAnalysis> {
  const response = await fetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/analyze/route/${encodeURIComponent(routeId)}`,
  );
  return parseResponse(response, "Could not analyze this route");
}

export async function analyzeRoute(
  projectId: string,
  payload: { method: string; path: string; file: string; component: string },
): Promise<RouteAnalysis> {
  const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/analyze/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response, "Could not analyze this route");
}

export async function fetchRouteSequence(projectId: string, routeId: string): Promise<SequenceData> {
  const response = await fetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/sequence/route/${encodeURIComponent(routeId)}`,
  );
  return parseResponse(response, "Failed to load route sequence");
}

export async function generateRouteSequence(
  projectId: string,
  payload: { method: string; path: string; file: string; component: string },
): Promise<SequenceData> {
  const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/sequence/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response, "Failed to generate sequence diagram");
}

export async function fetchRouteSequences(projectId: string): Promise<RouteSequenceRecord[]> {
  const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/sequence/routes`);
  return parseResponse(response, "Failed to load route diagrams");
}

export async function generateAllRouteSequences(
  projectId: string,
): Promise<{ generated: number; failed: number; route_ids: string[] }> {
  const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/sequence/all`, {
    method: "POST",
  });
  return parseResponse(response, "Batch generation failed");
}