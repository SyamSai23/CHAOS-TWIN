/* ── Shared types matching backend API responses ── */

export type Project = {
  id: string;
  name: string;
  path: string;
  created_at: string;
};

export type ScanComponent = {
  component_key: string;
  root_path: string;
  name: string;
  type: string;
  entry_file?: string | null;
  file_count?: number;
  languages?: string[];
  markers: string[];
  entry_points: string[];
};

export type ScanResult = {
  id: string;
  project_id: string;
  upload_id: string;
  status: string;
  file_count: number;
  files: Array<Record<string, unknown>>;
  languages: string[];
  frameworks: string[];
  key_files: string[];
  top_level_dirs: string[];
  extension_counts: Record<string, number>;
  project_type: string;
  entry_points: string[];
  components: ScanComponent[];
  confidence_scores?: Record<string, number> | null;
  dependencies?: Record<string, Array<Record<string, unknown>>> | null;
  service_graph?: Array<Record<string, unknown>> | null;
  routes?: Array<Record<string, unknown>> | null;
  import_graph?: Record<string, unknown> | null;
  execution_flow?: Array<Record<string, unknown>> | null;
  env_variables?: string[] | null;
  docker_services?: Array<Record<string, unknown>> | null;
  created_at: string;
};

export type GraphNodeData = {
  component_key?: string;
  component_type?: string;
  root_path?: string;
  entry_file?: string | null;
  language?: string | null;
  file_count?: number | null;
} & Record<string, unknown>;

export type GraphNode = {
  id: string;
  project_id: string;
  scan_id: string;
  node_type: string;
  label: string;
  data: GraphNodeData;
  created_at?: string;
};

export type GraphEdge = {
  id: string;
  project_id: string;
  scan_id: string;
  source_node_id: string;
  target_node_id: string;
  edge_type: string;
  created_at?: string;
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

export type InsightEvidenceRef = {
  ref_type: string;
  artifact: string;
  ref_id: string;
  label: string;
  file_path?: string | null;
  metadata: Record<string, unknown>;
};

export type InsightConfidence = {
  score: number;
  label: string;
  reasons: string[];
};

export type ProjectInsight = {
  insight_id: string;
  category: string;
  subtype: string;
  severity: string;
  confidence: InsightConfidence;
  title: string;
  explanation: string;
  evidence_refs: InsightEvidenceRef[];
  supporting_entity_ids: string[];
  supporting_graph_node_ids: string[];
  supporting_graph_edge_ids: string[];
  scan_id: string;
  snapshot_id?: string | null;
  graph_scan_id?: string | null;
  graph_provenance?: string | null;
  source_modes: string[];
  tags: string[];
};

export type InsightsGeneratedFrom = {
  generated_at: string;
  latest_scan_created_at: string;
  canonical_snapshot_used: boolean;
  graph_used: boolean;
  graph_provenance: string;
  simulation_used: boolean;
  simulation_mode?: string | null;
  source_modes: string[];
  detectors_run: string[];
  detectors_skipped: string[];
};

export type ProjectInsightsResponse = {
  project_id: string;
  scan_id: string;
  snapshot_id?: string | null;
  graph_scan_id?: string | null;
  graph_provenance: string;
  insight_count: number;
  counts_by_severity: Record<string, number>;
  counts_by_category: Record<string, number>;
  insights: ProjectInsight[];
  generated_from: InsightsGeneratedFrom;
};

export type CodePeekConfidence = {
  score: number;
  label: string;
  reasons: string[];
};

export type CodePeekGeneratedFrom = {
  generated_at: string;
  retrieval_mode: string;
  resolved_via: string[];
  selection_reason: string;
  file_hit: boolean;
  workspace_root_resolved: boolean;
  snippet_line_start?: number | null;
  snippet_line_end?: number | null;
};

export type CodePeekResponse = {
  project_id: string;
  scan_id: string;
  snapshot_id?: string | null;
  source_type: string;
  source_id: string;
  file_path: string;
  source_root_kind: string;
  symbol_name?: string | null;
  symbol_kind?: string | null;
  line_start?: number | null;
  line_end?: number | null;
  column_start?: number | null;
  column_end?: number | null;
  snippet_text: string;
  snippet_truncated: boolean;
  language?: string | null;
  evidence_id?: string | null;
  canonical_entity_id?: string | null;
  graph_provenance?: string | null;
  confidence?: CodePeekConfidence | null;
  generated_from: CodePeekGeneratedFrom;
};

export type SummaryHighlight = {
  category: string;
  label: string;
  detail: string;
  confidence: string;
  supporting_ids: string[];
};

export type CriticalNodeSummary = {
  node_id: string;
  label: string;
  node_type: string;
  criticality_score: number;
  graph_source?: string | null;
  canonical_entity_id?: string | null;
  reason: string;
};

export type SummaryFinding = {
  category: string;
  severity: string;
  confidence: string;
  explanation: string;
  supporting_ids: string[];
  evidence_refs: string[];
};

export type SummaryConfidence = {
  overall_score: number;
  overall_label: string;
  reasons: string[];
  canonical_snapshot_used: boolean;
  graph_used: boolean;
  graph_provenance: string;
  simulation_mode?: string | null;
};

export type SummaryGeneratedFrom = {
  generated_at: string;
  latest_scan_created_at: string;
  canonical_snapshot_used: boolean;
  graph_used: boolean;
  graph_provenance: string;
  simulation_used: boolean;
  simulation_mode?: string | null;
};

export type SystemIntelligenceSummaryResponse = {
  project_id: string;
  scan_id: string;
  snapshot_id?: string | null;
  graph_scan_id?: string | null;
  graph_provenance: string;
  system_type_guess: string;
  primary_stack: string[];
  architecture_hints: string[];
  component_counts: Record<string, number>;
  route_counts: {
    total: number;
    by_method: Record<string, number>;
  };
  runtime_dependency_highlights: SummaryHighlight[];
  critical_nodes: CriticalNodeSummary[];
  top_findings: SummaryFinding[];
  top_risks: SummaryFinding[];
  confidence_summary: SummaryConfidence;
  overview_text: string;
  generated_from: SummaryGeneratedFrom;
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
  analysis_signature?: string;
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
