/* ── Shared types matching backend API responses ── */

export type Project = {
  id: string;
  name: string;
  path: string;
  created_at: string;
};

export type ScanComponent = {
  root_path: string;
  name: string;
  type: string;
  markers: string[];
  entry_points: string[];
};

export type ScanResult = {
  id: string;
  status: string;
  file_count: number;
  languages: string[];
  frameworks: string[];
  key_files: string[];
  top_level_dirs: string[];
  extension_counts: Record<string, number>;
  project_type: string;
  entry_points: string[];
  components: ScanComponent[];
  created_at: string;
};

export type GraphNode = {
  id: string;
  node_type: string;
  label: string;
  data: Record<string, unknown>;
};

export type GraphEdge = {
  id: string;
  source_node_id: string;
  target_node_id: string;
  edge_type: string;
};

export type GraphResponse = {
  project_id: string;
  scan_id: string;
  node_count: number;
  edge_count: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export type SimulationImpactedNode = {
  id: string;
  label: string;
  node_type: string;
  distance: number;
};

export type SimulationResult = {
  id: string;
  project_id: string;
  scan_id: string;
  failed_node_id: string;
  severity: string;
  summary: string;
  impacted_nodes: SimulationImpactedNode[];
  result: {
    failed_node_label: string;
    failed_node_type: string;
    impacted_count: number;
  };
  created_at: string;
};

export type DeepDiveModule = {
  name: string;
  file_count: number;
  dominant_role: string;
  roles: string[];
  files: string[];
};

export type DeepDiveFile = {
  path: string;
  role: string;
  score: number;
};

export type DeepDiveEdge = {
  source: string;
  target: string;
  type: string;
  weight: number;
};

export type DeepDiveModuleEdge = {
  source_module: string;
  target_module: string;
  edge_count: number;
};

export type DeepDiveFlowStep = {
  step: string;
  example_files: string[];
};

export type DeepDiveResult = {
  project_id: string;
  component_name: string;
  component_type: string;
  component_summary: string;
  internal_modules: DeepDiveModule[];
  important_files: DeepDiveFile[];
  internal_edges: DeepDiveEdge[];
  module_edges: DeepDiveModuleEdge[];
  probable_start_file: string | null;
  probable_flow_steps: DeepDiveFlowStep[];
  notes: string[];
};

/* ── API Routes (API Explorer) ── */

export type RouteItem = {
  id: string;
  method: string;
  path: string;
  file: string;
  component: string;
  has_sequence: boolean;
};

export type ComponentGroup = {
  component: string;
  component_type: string;
  routes: RouteItem[];
};

export type RoutesResponse = {
  total: number;
  by_component: ComponentGroup[];
  methods_summary: Record<string, number>;
};

/* ── Route Analysis (AST analyzer) ── */

export type AnalysisStep = {
  step_id: string;
  type: string;
  label: string;
  technical: string;
  line_number: number | null;
  is_error_path: boolean;
};

export type AnalysisPhase = {
  phase_id: string;
  name: string;
  description: string;
  steps: AnalysisStep[];
};

export type AnalysisErrorPath = {
  trigger: string;
  status_code: number | null;
  message: string | null;
};

export type AnalysisParameter = {
  name: string;
  type: string;
  source: string;
};

export type RouteAnalysis = {
  route_id: string;
  method: string;
  path: string;
  file: string;
  component: string;
  handler_function: string;
  parameters: AnalysisParameter[];
  return_type: string | null;
  phases: AnalysisPhase[];
  error_paths: AnalysisErrorPath[];
  participants: string[];
  has_database: boolean;
  has_filesystem: boolean;
  has_external: boolean;
  complexity: "simple" | "moderate" | "complex";
};

/* ── Utility ── */

export function shortenLabel(text: string): string {
  const trimmed = text.trim();
  if (trimmed.includes("/")) {
    const parts = trimmed.split("/").filter(Boolean);
    return parts[parts.length - 1] || trimmed;
  }
  return trimmed.length > 24 ? `${trimmed.slice(0, 21)}…` : trimmed;
}
