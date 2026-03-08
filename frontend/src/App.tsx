import { useEffect, useState, type FormEvent } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Edge as ReactFlowEdge,
  type Node as ReactFlowNode,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./App.css";

const API = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

type ApiStatus = {
  status: string;
};

type DbStatus = {
  status: string;
  database: string;
};

type Project = {
  id: string;
  name: string;
  path: string;
  created_at: string;
};

type ScanResult = {
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
  created_at: string;
};

type UploadResponse = {
  id: string;
  project_id: string;
  filename: string;
  storage_path: string;
  created_at: string;
};

type GraphNode = {
  id: string;
  node_type: string;
  label: string;
};

type GraphEdge = {
  id: string;
  source_node_id: string;
  target_node_id: string;
  edge_type: string;
};

type GraphResponse = {
  project_id: string;
  scan_id: string;
  node_count: number;
  edge_count: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
};

type SimulationImpactedNode = {
  id: string;
  label: string;
  node_type: string;
  distance: number;
};

type SimulationResult = {
  id: string;
  project_id: string;
  scan_id: string;
  failed_node_id: string;
  severity: string;
  summary: string;
  impacted_nodes: SimulationImpactedNode[];
  result: { failed_node_label: string; failed_node_type: string; impacted_count: number };
  created_at: string;
};

// Color palette per node type for the visual graph.
const NODE_COLORS: Record<string, { bg: string; border: string }> = {
  frontend: { bg: "#1e3a5f", border: "#60a5fa" },
  backend: { bg: "#1a3329", border: "#4ade80" },
  database: { bg: "#3b1f4a", border: "#c084fc" },
  runtime: { bg: "#2d2305", border: "#facc15" },
  tool: { bg: "#1e293b", border: "#94a3b8" },
  entry_point: { bg: "#3b1520", border: "#fb7185" },
};

function shortenLabel(text: string): string {
  const trimmed = text.trim();
  if (trimmed.includes("/")) {
    const parts = trimmed.split("/").filter(Boolean);
    return parts[parts.length - 1] || trimmed;
  }
  return trimmed.length > 24 ? `${trimmed.slice(0, 21)}…` : trimmed;
}

function toReactFlowGraph(
  graph: GraphResponse,
  simulationResult?: SimulationResult | null,
): {
  nodes: ReactFlowNode[];
  edges: ReactFlowEdge[];
} {
  // Build sets for fast lookup when a simulation is active
  const failedNodeId = simulationResult?.failed_node_id ?? null;
  const impactedNodeIds = new Set(
    simulationResult?.impacted_nodes.map((n) => n.id) ?? [],
  );
  const hasSimulation = failedNodeId !== null;
  function shortLabel(node: GraphNode): string {
    return shortenLabel(node.label);
  }

  // --- Build a map from entry_point node → its parent component node ---
  // An entry_point is "owned by" a component if there's a contains edge.
  const entryParentMap = new Map<string, string>(); // entryNodeId → parentNodeId
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  for (const edge of graph.edges) {
    const src = nodeById.get(edge.source_node_id);
    const tgt = nodeById.get(edge.target_node_id);
    if (edge.edge_type === "contains" && tgt?.node_type === "entry_point") {
      entryParentMap.set(edge.target_node_id, edge.source_node_id);
    }
    if (edge.edge_type === "contains" && src?.node_type === "entry_point") {
      entryParentMap.set(edge.source_node_id, edge.target_node_id);
    }
  }

  // --- Partition nodes into layout groups ---
  // Row 0: main components (frontend, backend, database)
  // Row 1: runtimes + tools
  // Entry points are placed on a sub-row below their parent component.
  const mainTypes = new Set(["frontend", "backend", "database"]);
  const auxTypes = new Set(["runtime", "tool"]);

  const mainNodes = graph.nodes.filter((n) => mainTypes.has(n.node_type));
  const auxNodes = graph.nodes.filter((n) => auxTypes.has(n.node_type));
  const entryNodes = graph.nodes.filter((n) => n.node_type === "entry_point");
  const otherNodes = graph.nodes.filter(
    (n) => !mainTypes.has(n.node_type) && !auxTypes.has(n.node_type) && n.node_type !== "entry_point",
  );

  const COL_W = 200; // horizontal spacing between columns
  const ROW_H = 90;  // vertical spacing between rows
  const NODE_W = 170;

  const rfNodes: ReactFlowNode[] = [];
  const componentColIndex = new Map<string, number>(); // nodeId → column

  // Helper: compute simulation-aware style overrides for a node
  function simStyle(nodeId: string, baseStyle: Record<string, unknown>): Record<string, unknown> {
    if (!hasSimulation) return baseStyle;
    if (nodeId === failedNodeId) {
      return {
        ...baseStyle,
        border: "2.5px solid #ef4444",
        boxShadow: "0 0 14px 4px rgba(239,68,68,0.45)",
        background: "#2a0a0a",
        opacity: 1,
      };
    }
    if (impactedNodeIds.has(nodeId)) {
      return {
        ...baseStyle,
        border: "2px solid #f59e0b",
        boxShadow: "0 0 10px 2px rgba(245,158,11,0.35)",
        background: "#2a1a00",
        opacity: 1,
      };
    }
    // Unaffected — dim it out
    return { ...baseStyle, opacity: 0.25 };
  }

  // Place main component nodes in a horizontal row
  mainNodes.forEach((node, i) => {
    componentColIndex.set(node.id, i);
    const colors = NODE_COLORS[node.node_type] || NODE_COLORS.tool;
    rfNodes.push({
      id: node.id,
      position: { x: i * COL_W, y: 0 },
      data: { label: shortLabel(node) },
      style: simStyle(node.id, {
        border: `2px solid ${colors.border}`,
        borderRadius: "10px",
        padding: "8px 10px",
        background: colors.bg,
        color: "#e5e7eb",
        width: NODE_W,
        fontSize: "13px",
        fontWeight: 700,
        textAlign: "center",
      }),
    });
  });

  // Place entry points directly below their parent component
  const entryCountPerParent = new Map<string, number>();
  entryNodes.forEach((node) => {
    const parentId = entryParentMap.get(node.id);
    const parentCol = parentId != null ? componentColIndex.get(parentId) : undefined;
    const col = parentCol ?? (componentColIndex.size + (entryCountPerParent.size || 0));
    const subIdx = entryCountPerParent.get(String(col)) ?? 0;
    entryCountPerParent.set(String(col), subIdx + 1);

    const colors = NODE_COLORS.entry_point;
    rfNodes.push({
      id: node.id,
      position: { x: col * COL_W + 10, y: ROW_H + subIdx * (ROW_H - 10) },
      data: { label: shortLabel(node) },
      style: simStyle(node.id, {
        border: `1.5px dashed ${colors.border}`,
        borderRadius: "6px",
        padding: "5px 8px",
        background: colors.bg,
        color: "#e5e7eb",
        width: NODE_W - 20,
        fontSize: "11px",
        fontWeight: 500,
        textAlign: "center",
      }),
    });
  });

  // Determine the Y start for the aux row (below all entry points)
  const maxEntries = Math.max(1, ...Array.from(entryCountPerParent.values()));
  const auxY = ROW_H + maxEntries * (ROW_H - 10) + 30;

  // Place runtimes + tools in a row below
  auxNodes.forEach((node, i) => {
    const colors = NODE_COLORS[node.node_type] || NODE_COLORS.tool;
    rfNodes.push({
      id: node.id,
      position: { x: i * COL_W, y: auxY },
      data: { label: shortLabel(node) },
      style: simStyle(node.id, {
        border: `1.5px solid ${colors.border}`,
        borderRadius: "8px",
        padding: "6px 8px",
        background: colors.bg,
        color: "#e5e7eb",
        width: NODE_W - 10,
        fontSize: "11px",
        fontWeight: 600,
        textAlign: "center",
      }),
    });
  });

  // Place any other unclassified nodes after aux
  otherNodes.forEach((node, i) => {
    const colors = NODE_COLORS.tool;
    rfNodes.push({
      id: node.id,
      position: { x: (auxNodes.length + i) * COL_W, y: auxY },
      data: { label: shortLabel(node) },
      style: simStyle(node.id, {
        border: `1px solid ${colors.border}`,
        borderRadius: "8px",
        padding: "6px 8px",
        background: colors.bg,
        color: "#e5e7eb",
        width: NODE_W - 10,
        fontSize: "11px",
        fontWeight: 600,
        textAlign: "center",
      }),
    });
  });

  // Build a set of node IDs involved in the simulation (failed + impacted)
  const simNodeIds = new Set<string>();
  if (hasSimulation) {
    simNodeIds.add(failedNodeId!);
    for (const n of simulationResult!.impacted_nodes) simNodeIds.add(n.id);
  }

  const rfEdges: ReactFlowEdge[] = graph.edges.map((edge) => {
    const srcInSim = simNodeIds.has(edge.source_node_id);
    const tgtInSim = simNodeIds.has(edge.target_node_id);
    const bothInSim = srcInSim && tgtInSim;

    return {
      id: edge.id,
      source: edge.source_node_id,
      target: edge.target_node_id,
      animated: bothInSim,
      style: hasSimulation
        ? bothInSim
          ? { stroke: "#f59e0b", strokeWidth: 2 }
          : { stroke: "#475569", strokeWidth: 1.2, opacity: 0.2 }
        : { stroke: "#475569", strokeWidth: 1.2 },
    };
  });

  return { nodes: rfNodes, edges: rfEdges };
}

function App() {
  const [apiStatus, setApiStatus] = useState<string>("loading...");
  const [dbStatus, setDbStatus] = useState<string>("loading...");

  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [scans, setScans] = useState<Record<string, ScanResult | null>>({});
  const [scanning, setScanning] = useState<Record<string, boolean>>({});
  const [scanErrors, setScanErrors] = useState<Record<string, string | null>>({});
  const [selectedFiles, setSelectedFiles] = useState<Record<string, File | null>>({});
  const [uploading, setUploading] = useState<Record<string, boolean>>({});
  const [uploadMessages, setUploadMessages] = useState<Record<string, string | null>>({});
  const [uploadedFilenames, setUploadedFilenames] = useState<Record<string, string | null>>({});
  const [graphs, setGraphs] = useState<Record<string, GraphResponse | null>>({});
  const [generatingGraph, setGeneratingGraph] = useState<Record<string, boolean>>({});
  const [graphMessages, setGraphMessages] = useState<Record<string, string | null>>({});

  const [simSelectedNode, setSimSelectedNode] = useState<Record<string, string>>({});
  const [simulating, setSimulating] = useState<Record<string, boolean>>({});
  const [simResults, setSimResults] = useState<Record<string, SimulationResult | null>>({});
  const [simErrors, setSimErrors] = useState<Record<string, string | null>>({});

  useEffect(() => {
    const fetchStatuses = async () => {
      try {
        const apiResponse = await fetch(`${API}/health`);
        const apiData: ApiStatus = await apiResponse.json();
        setApiStatus(apiData.status);
      } catch {
        setApiStatus("error");
      }

      try {
        const dbResponse = await fetch(`${API}/health/db`);
        const dbData: DbStatus = await dbResponse.json();
        setDbStatus(dbData.database);
      } catch {
        setDbStatus("error");
      }
    };

    fetchStatuses();
    fetchProjects();
  }, []);

  async function fetchProjects() {
    try {
      const res = await fetch(`${API}/projects`);
      const data: Project[] = await res.json();
      setProjects(data);
    } catch {
      console.error("Failed to fetch projects");
    }
  }

  async function handleScan(projectId: string) {
    setScanning((prev) => ({ ...prev, [projectId]: true }));
    setScanErrors((prev) => ({ ...prev, [projectId]: null }));

    try {
      const res = await fetch(`${API}/projects/${projectId}/scan`, {
        method: "POST",
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setScanErrors((prev) => ({
          ...prev,
          [projectId]: body?.detail || "Scan failed",
        }));
        return;
      }

      const data: ScanResult = await res.json();
      setScans((prev) => ({ ...prev, [projectId]: data }));
    } catch {
      setScanErrors((prev) => ({ ...prev, [projectId]: "Scan failed" }));
    } finally {
      setScanning((prev) => ({ ...prev, [projectId]: false }));
    }
  }

  function handleFileChange(projectId: string, file: File | null) {
    setSelectedFiles((prev) => ({ ...prev, [projectId]: file }));
    setUploadMessages((prev) => ({ ...prev, [projectId]: null }));
  }

  async function handleUpload(projectId: string) {
    const file = selectedFiles[projectId];

    if (!file) {
      setUploadMessages((prev) => ({
        ...prev,
        [projectId]: "Select a .zip file first",
      }));
      return;
    }

    setUploading((prev) => ({ ...prev, [projectId]: true }));
    setUploadMessages((prev) => ({ ...prev, [projectId]: null }));

    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`${API}/projects/${projectId}/upload`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setUploadMessages((prev) => ({
          ...prev,
          [projectId]: body?.detail || "Upload failed",
        }));
        return;
      }

      const data: UploadResponse = await res.json();
      setUploadMessages((prev) => ({ ...prev, [projectId]: "Uploaded successfully" }));
      setUploadedFilenames((prev) => ({ ...prev, [projectId]: data.filename }));
      setSelectedFiles((prev) => ({ ...prev, [projectId]: null }));
    } catch {
      setUploadMessages((prev) => ({ ...prev, [projectId]: "Upload failed" }));
    } finally {
      setUploading((prev) => ({ ...prev, [projectId]: false }));
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    try {
      const res = await fetch(`${API}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, path }),
      });

      if (!res.ok) {
        setError("Failed to create project");
        return;
      }

      setName("");
      setPath("");
      fetchProjects();
    } catch {
      setError("Failed to create project");
    }
  }

  async function handleDeleteProject(projectId: string) {
    if (!window.confirm("Delete this project and all its data? This cannot be undone.")) return;

    try {
      const res = await fetch(`${API}/projects/${projectId}`, { method: "DELETE" });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        alert(body?.detail || "Failed to delete project");
        return;
      }
      setProjects((prev) => prev.filter((p) => p.id !== projectId));
    } catch {
      alert("Failed to delete project");
    }
  }

  async function handleGenerateGraph(projectId: string) {
    setGeneratingGraph((prev) => ({ ...prev, [projectId]: true }));
    setGraphMessages((prev) => ({ ...prev, [projectId]: null }));

    try {
      const res = await fetch(`${API}/projects/${projectId}/graph`, {
        method: "POST",
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setGraphMessages((prev) => ({
          ...prev,
          [projectId]: body?.detail || "Graph generation failed",
        }));
        return;
      }

      const data: GraphResponse = await res.json();
      setGraphs((prev) => ({ ...prev, [projectId]: data }));
      setGraphMessages((prev) => ({ ...prev, [projectId]: "Graph ready" }));
    } catch {
      setGraphMessages((prev) => ({ ...prev, [projectId]: "Failed to build graph" }));
    } finally {
      setGeneratingGraph((prev) => ({ ...prev, [projectId]: false }));
    }
  }

  async function handleSimulate(projectId: string) {
    const nodeId = simSelectedNode[projectId];
    if (!nodeId) return;

    setSimulating((prev) => ({ ...prev, [projectId]: true }));
    setSimErrors((prev) => ({ ...prev, [projectId]: null }));
    setSimResults((prev) => ({ ...prev, [projectId]: null }));

    try {
      const res = await fetch(`${API}/projects/${projectId}/simulate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_id: nodeId }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setSimErrors((prev) => ({
          ...prev,
          [projectId]: body?.detail || "Simulation failed",
        }));
        return;
      }

      const data: SimulationResult = await res.json();
      setSimResults((prev) => ({ ...prev, [projectId]: data }));
    } catch {
      setSimErrors((prev) => ({ ...prev, [projectId]: "Simulation failed" }));
    } finally {
      setSimulating((prev) => ({ ...prev, [projectId]: false }));
    }
  }

  function statusDot(value: string) {
    if (value === "loading...") return "loading";
    if (value === "ok" || value === "connected" || value === "running") return "ok";
    return "err";
  }

  return (
    <div className="app-shell">
      {/* ── Header ── */}
      <header className="app-header">
        <h1><span className="accent">⬡</span> Chaos Twin</h1>
        <p>Understand your codebase. Simulate failures. Ship with confidence.</p>
      </header>

      {/* ── Status bar ── */}
      <div className="status-bar">
        <span className="status-pill">
          <span className={`status-dot ok`} /> Frontend
        </span>
        <span className="status-pill">
          <span className={`status-dot ${statusDot(apiStatus)}`} /> API: {apiStatus}
        </span>
        <span className="status-pill">
          <span className={`status-dot ${statusDot(dbStatus)}`} /> DB: {dbStatus}
        </span>
      </div>

      {/* ── Create project ── */}
      <div className="create-form-card">
        <div className="section-title">Create a Project</div>
        <form onSubmit={handleSubmit} className="create-form">
          <div className="form-field">
            <label>Name</label>
            <input
              type="text"
              placeholder="e.g. my-api"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="form-field">
            <label>Path</label>
            <input
              type="text"
              placeholder="e.g. /projects/my-api"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              required
            />
          </div>
          <button type="submit" className="btn btn-primary">
            Create
          </button>
        </form>
        {error && <p className="msg-error">{error}</p>}
      </div>

      {/* ── Projects ── */}
      <div className="section-title">Your Projects</div>

      {projects.length === 0 ? (
        <div className="empty-state">No projects yet — create one above to get started.</div>
      ) : (
        projects.map((p) => (
          <div key={p.id} className="project-card">
            {/* Card header */}
            <div className="card-header">
              <div className="card-header-row">
                <h3>{p.name}</h3>
                <button
                  className="btn btn-danger btn-sm"
                  onClick={() => handleDeleteProject(p.id)}
                >
                  Delete
                </button>
              </div>
              <div className="card-meta">
                <span>Path: <code>{p.path}</code></span>
                <span>Created: {new Date(p.created_at).toLocaleString()}</span>
              </div>
            </div>

            {/* Upload section */}
            <div className="card-section">
              <div className="card-section-label">Source Code</div>
              <div className="upload-row">
                <div className="file-input-wrap">
                  <input
                    type="file"
                    accept=".zip"
                    onChange={(e) => handleFileChange(p.id, e.target.files?.[0] || null)}
                  />
                </div>
                <button
                  onClick={() => handleUpload(p.id)}
                  disabled={uploading[p.id]}
                  className="btn btn-secondary btn-sm"
                >
                  {uploading[p.id] ? "Uploading…" : "Upload .zip"}
                </button>
              </div>
              {uploadMessages[p.id] && (
                <p className={uploadMessages[p.id] === "Uploaded successfully" ? "msg-success" : "msg-error"}>
                  {uploadMessages[p.id]}
                </p>
              )}
              {uploadedFilenames[p.id] && (
                <p className="msg-info">Current file: <code>{uploadedFilenames[p.id]}</code></p>
              )}
            </div>

            {/* Scan section */}
            <div className="card-section">
              <div className="card-section-label">Analysis</div>
              <button
                onClick={() => handleScan(p.id)}
                disabled={scanning[p.id]}
                className="btn btn-secondary btn-sm"
              >
                {scanning[p.id] ? "Analyzing…" : "Run Scan"}
              </button>

              {scanErrors[p.id] && <p className="msg-error">{scanErrors[p.id]}</p>}

              {scans[p.id] && (() => {
                const scan = scans[p.id]!;
                const extensionEntries = Object.entries(scan.extension_counts || {});
                const visibleExtensions = extensionEntries.slice(0, 6);
                const remainingExtensions = extensionEntries.length - visibleExtensions.length;
                const visibleKeyFiles = scan.key_files.slice(0, 6);
                const remainingKeyFiles = scan.key_files.length - visibleKeyFiles.length;
                const visibleDirs = scan.top_level_dirs.slice(0, 8);
                const remainingDirs = scan.top_level_dirs.length - visibleDirs.length;
                const visibleEntryPoints = scan.entry_points.slice(0, 6);
                const remainingEntryPoints = scan.entry_points.length - visibleEntryPoints.length;
                return (
                  <div className="scan-summary">
                    <div className="scan-grid">
                      <div className="scan-stat">
                        <span className="scan-stat-label">Status</span>
                        <span className="scan-stat-value">{scan.status}</span>
                      </div>
                      <div className="scan-stat">
                        <span className="scan-stat-label">Type</span>
                        <span className="scan-stat-value">{scan.project_type}</span>
                      </div>
                      <div className="scan-stat">
                        <span className="scan-stat-label">Files</span>
                        <span className="scan-stat-value">{scan.file_count}</span>
                      </div>
                    </div>

                    <div className="scan-detail-section">
                      <div className="scan-detail-title">Languages</div>
                      <div className="tag-list">
                        {scan.languages.length > 0
                          ? scan.languages.map((l) => <span key={l} className="tag">{l}</span>)
                          : <span className="empty-hint">None found</span>}
                      </div>
                    </div>

                    <div className="scan-detail-section">
                      <div className="scan-detail-title">File Types</div>
                      <div className="tag-list">
                        {visibleExtensions.length > 0
                          ? visibleExtensions.map(([ext, count]) => (
                              <span key={ext} className="tag tag-muted">{ext} ({count})</span>
                            ))
                          : <span className="empty-hint">None found</span>}
                        {remainingExtensions > 0 && (
                          <span className="tag tag-muted">+{remainingExtensions} more</span>
                        )}
                      </div>
                    </div>

                    <div className="scan-detail-section">
                      <div className="scan-detail-title">Frameworks</div>
                      <div className="tag-list">
                        {scan.frameworks.length > 0
                          ? scan.frameworks.map((f) => <span key={f} className="tag">{f}</span>)
                          : <span className="empty-hint">None found</span>}
                      </div>
                    </div>

                    <div className="scan-detail-section">
                      <div className="scan-detail-title">Key Files</div>
                      <div className="scan-detail-body">
                        {visibleKeyFiles.length > 0 ? (
                          <ul>
                            {visibleKeyFiles.map((file) => (
                              <li key={file}><code>{shortenLabel(file)}</code></li>
                            ))}
                          </ul>
                        ) : (
                          <span className="empty-hint">None found</span>
                        )}
                        {remainingKeyFiles > 0 && <div className="msg-info">+{remainingKeyFiles} more</div>}
                      </div>
                    </div>

                    <div className="scan-detail-section">
                      <div className="scan-detail-title">Folders</div>
                      <div className="tag-list">
                        {visibleDirs.length > 0
                          ? visibleDirs.map((d) => <span key={d} className="tag tag-muted">{d}</span>)
                          : <span className="empty-hint">None found</span>}
                        {remainingDirs > 0 && (
                          <span className="tag tag-muted">+{remainingDirs} more</span>
                        )}
                      </div>
                    </div>

                    <div className="scan-detail-section">
                      <div className="scan-detail-title">Entry Points</div>
                      <div className="scan-detail-body">
                        {visibleEntryPoints.length > 0 ? (
                          <ul>
                            {visibleEntryPoints.map((entry) => (
                              <li key={entry}><code>{shortenLabel(entry)}</code></li>
                            ))}
                          </ul>
                        ) : (
                          <span className="empty-hint">None found</span>
                        )}
                        {remainingEntryPoints > 0 && <div className="msg-info">+{remainingEntryPoints} more</div>}
                      </div>
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* Graph section */}
            <div className="card-section">
              <div className="card-section-label">Architecture</div>
              <button
                onClick={() => handleGenerateGraph(p.id)}
                disabled={generatingGraph[p.id]}
                className="btn btn-secondary btn-sm"
              >
                {generatingGraph[p.id] ? "Building…" : "Build Graph"}
              </button>

              {graphMessages[p.id] && (
                <p className={graphMessages[p.id] === "Graph ready" ? "msg-success" : "msg-error"}>
                  {graphMessages[p.id]}
                </p>
              )}

              {graphs[p.id] && (() => {
                const graph = graphs[p.id]!;
                const nodeLabelById = Object.fromEntries(
                  graph.nodes.map((node) => [node.id, node.label]),
                );
                const flowGraph = toReactFlowGraph(graph, simResults[p.id]);

                return (
                  <div className="graph-debug">
                    <div className="graph-stats">
                      <span className="tag">{graph.node_count} {graph.node_count === 1 ? "node" : "nodes"}</span>
                      <span className="tag">{graph.edge_count} {graph.edge_count === 1 ? "connection" : "connections"}</span>
                    </div>

                    <div className="graph-container">
                      <ReactFlow
                        nodes={flowGraph.nodes}
                        edges={flowGraph.edges}
                        fitView
                        fitViewOptions={{ padding: 0.18, minZoom: 0.3, maxZoom: 1.4 }}
                        proOptions={{ hideAttribution: true }}
                        nodesDraggable={false}
                        nodesConnectable={false}
                        elementsSelectable={false}
                        panOnDrag
                        zoomOnScroll={false}
                        zoomOnPinch
                        onInit={(instance: ReactFlowInstance) => {
                          setTimeout(() => {
                            instance.fitView({
                              padding: 0.18,
                              minZoom: 0.3,
                              maxZoom: 1.4,
                            });
                          }, 50);
                        }}
                      >
                        <MiniMap
                          pannable
                          zoomable
                          style={{ background: "#080c14" }}
                        />
                        <Controls />
                        <Background gap={20} color="#1a1f2e" />
                      </ReactFlow>
                    </div>

                    {graph.nodes.length > 0 && (
                      <div className="scan-detail-section">
                        <div className="scan-detail-title">Components</div>
                        <div className="tag-list">
                          {graph.nodes.map((node) => (
                            <span key={node.id} className="tag tag-muted">
                              {shortenLabel(node.label)} <span className="tag-dim">&middot; {node.node_type}</span>
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {graph.edges.length > 0 && (
                      <div className="scan-detail-section">
                        <div className="scan-detail-title">Connections</div>
                        <div className="tag-list">
                          {graph.edges.map((edge) => (
                            <span key={edge.id} className="tag tag-muted">
                              {shortenLabel(nodeLabelById[edge.source_node_id] || "?")} &rarr; {shortenLabel(nodeLabelById[edge.target_node_id] || "?")}
                              <span className="tag-dim"> &middot; {edge.edge_type}</span>
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>

            {/* Simulation section — only visible when a graph exists */}
            {graphs[p.id] && (() => {
              const graph = graphs[p.id]!;
              const selected = simSelectedNode[p.id] || "";
              const sim = simResults[p.id];
              return (
                <div className="card-section">
                  <div className="card-section-label">Chaos Simulation</div>

                  <div className="sim-controls">
                    <select
                      className="sim-select"
                      value={selected}
                      onChange={(e) =>
                        setSimSelectedNode((prev) => ({ ...prev, [p.id]: e.target.value }))
                      }
                    >
                      <option value="">Choose a component…</option>
                      {graph.nodes.map((node) => (
                        <option key={node.id} value={node.id}>
                          {shortenLabel(node.label)} ({node.node_type})
                        </option>
                      ))}
                    </select>
                    <button
                      className="btn btn-primary btn-sm"
                      disabled={!selected || simulating[p.id]}
                      onClick={() => handleSimulate(p.id)}
                    >
                      {simulating[p.id] ? "Running…" : "Run Simulation"}
                    </button>
                    {sim && (
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => setSimResults((prev) => ({ ...prev, [p.id]: null }))}
                      >
                        Clear
                      </button>
                    )}
                  </div>

                  {!sim && !simErrors[p.id] && (
                    <p className="empty-hint" style={{ marginTop: 10 }}>
                      Pick a component and run a simulation to see what breaks.
                    </p>
                  )}

                  {simErrors[p.id] && <p className="msg-error">{simErrors[p.id]}</p>}

                  {sim && (
                    <div className="sim-result">
                      <div className="sim-summary-row">
                        <span className={`sim-severity sim-severity-${sim.severity}`}>
                          {sim.severity === "high" ? "High Risk" : sim.severity === "medium" ? "Med Risk" : "Low Risk"}
                        </span>
                        <span className="sim-summary-text">{sim.summary}</span>
                      </div>

                      <div className="sim-stats">
                        <div className="sim-stat">
                          <span className="sim-stat-label">Failed Component</span>
                          <span className="sim-stat-value">
                            {shortenLabel(sim.result.failed_node_label)} <span className="tag-dim">&middot; {sim.result.failed_node_type}</span>
                          </span>
                        </div>
                        <div className="sim-stat">
                          <span className="sim-stat-label">Components Affected</span>
                          <span className="sim-stat-value">{sim.result.impacted_count}</span>
                        </div>
                      </div>

                      {sim.impacted_nodes.length > 0 && (
                        <div className="sim-impacted">
                          <div className="scan-detail-title">Blast Radius</div>
                          <div className="sim-impacted-list">
                            {sim.impacted_nodes.map((node) => (
                              <div key={node.id} className="sim-impacted-item">
                                <span className="sim-impacted-label">{shortenLabel(node.label)}</span>
                                <span className="tag tag-muted">{node.node_type}</span>
                                <span className="sim-distance">{node.distance === 1 ? "1 hop away" : `${node.distance} hops away`}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        ))
      )}
    </div>
  );
}

export default App;