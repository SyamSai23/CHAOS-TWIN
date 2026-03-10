import { useEffect, useState, useRef, type FormEvent, type ChangeEvent } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./App.css";

import {
  Zap,
  GitBranch,
  LayoutDashboard,
  Search,
  Activity,
  GitCommitHorizontal,
  Plus,
  Upload,
  Play,
  Trash2,
} from "lucide-react";

import type {
  Project,
  ScanResult,
  GraphResponse,
  SimulationResult,
  DeepDiveResult,
} from "./types";
import { shortenLabel } from "./types";

import OverviewView from "./views/OverviewView";
import ArchitectureView from "./views/ArchitectureView";
import ApiExplorerView from "./views/ApiExplorerView";
import SequenceDiagramsView from "./views/SequenceDiagramsView";
import DeepDiveView from "./views/DeepDiveView";
import SimulationView from "./views/SimulationView";

const API = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

/* ── Navigation config ── */

type NavItem =
  | "overview"
  | "architecture"
  | "api-explorer"
  | "sequence-diagrams"
  | "deep-dive"
  | "simulation";

const NAV_ITEMS: { key: NavItem; label: string; icon: typeof LayoutDashboard }[] = [
  { key: "overview", label: "Overview", icon: LayoutDashboard },
  { key: "architecture", label: "Architecture", icon: GitBranch },
  { key: "api-explorer", label: "API Explorer", icon: Zap },
  { key: "sequence-diagrams", label: "Sequence Diagrams", icon: GitCommitHorizontal },
  { key: "deep-dive", label: "Deep Dive", icon: Search },
  { key: "simulation", label: "Simulation", icon: Activity },
];

/* ── Unused type placeholders (kept for API response parsing) ── */

type UploadResponse = {
  id: string;
  project_id: string;
  filename: string;
  storage_path: string;
  created_at: string;
};

/* ── App ── */

function App() {
  /* ── Navigation state ── */
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<NavItem>("overview");
  const [showCreateForm, setShowCreateForm] = useState(false);

  /* ── File upload ref ── */
  const fileInputRef = useRef<HTMLInputElement>(null);

  /* ── Health check state ── */
  const [apiStatus, setApiStatus] = useState<string>("loading...");
  const [dbStatus, setDbStatus] = useState<string>("loading...");

  /* ── Project state ── */
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);

  /* ── Scan state ── */
  const [scans, setScans] = useState<Record<string, ScanResult | null>>({});
  const [scanning, setScanning] = useState<Record<string, boolean>>({});
  const [scanErrors, setScanErrors] = useState<Record<string, string | null>>({});

  /* ── Upload state ── */
  const [uploading, setUploading] = useState<Record<string, boolean>>({});
  const [uploadMessages, setUploadMessages] = useState<Record<string, string | null>>({});
  const [uploadedFilenames, setUploadedFilenames] = useState<Record<string, string | null>>({});

  /* ── Graph state ── */
  const [graphs, setGraphs] = useState<Record<string, GraphResponse | null>>({});
  const [generatingGraph, setGeneratingGraph] = useState<Record<string, boolean>>({});
  const [graphMessages, setGraphMessages] = useState<Record<string, string | null>>({});

  /* ── Simulation state ── */
  const [simSelectedNode, setSimSelectedNode] = useState<Record<string, string>>({});
  const [simulating, setSimulating] = useState<Record<string, boolean>>({});
  const [simResults, setSimResults] = useState<Record<string, SimulationResult | null>>({});
  const [simErrors, setSimErrors] = useState<Record<string, string | null>>({});

  /* ── Deep dive state ── */
  const [ddSelectedRoot, setDdSelectedRoot] = useState<Record<string, string | null>>({});
  const [ddLoading, setDdLoading] = useState<Record<string, boolean>>({});
  const [ddResults, setDdResults] = useState<Record<string, DeepDiveResult | null>>({});
  const [ddErrors, setDdErrors] = useState<Record<string, string | null>>({});
  const [ddExpandEdges, setDdExpandEdges] = useState<Record<string, boolean>>({});

  /* ── Initialization ── */

  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => r.json())
      .then((d: { status: string }) => setApiStatus(d.status))
      .catch(() => setApiStatus("error"));

    fetch(`${API}/health/db`)
      .then((r) => r.json())
      .then((d: { database: string }) => setDbStatus(d.database))
      .catch(() => setDbStatus("error"));

    fetchProjects();
  }, []);

  // Auto-select first project
  useEffect(() => {
    if (projects.length > 0 && !selectedProjectId) {
      setSelectedProjectId(projects[0].id);
    }
    // If selected project was deleted, pick next
    if (selectedProjectId && !projects.find((p) => p.id === selectedProjectId)) {
      setSelectedProjectId(projects.length > 0 ? projects[0].id : null);
    }
  }, [projects, selectedProjectId]);

  const selectedProject = projects.find((p) => p.id === selectedProjectId) || null;

  /* ── API handlers ── */

  async function fetchProjects() {
    try {
      const res = await fetch(`${API}/projects`);
      const data: Project[] = await res.json();
      setProjects(data);
    } catch {
      console.error("Failed to fetch projects");
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setCreateError(null);
    try {
      const res = await fetch(`${API}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, path }),
      });
      if (!res.ok) {
        setCreateError("Failed to create project");
        return;
      }
      const newProject: Project = await res.json();
      setName("");
      setPath("");
      setShowCreateForm(false);
      setProjects((prev) => [...prev, newProject]);
      setSelectedProjectId(newProject.id);
      setActiveView("overview");
    } catch {
      setCreateError("Failed to create project");
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

  async function handleFileSelected(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    const projectId = selectedProjectId;
    if (!file || !projectId) return;
    e.target.value = "";

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
    } catch {
      setUploadMessages((prev) => ({ ...prev, [projectId]: "Upload failed" }));
    } finally {
      setUploading((prev) => ({ ...prev, [projectId]: false }));
    }
  }

  async function handleScan(projectId: string) {
    setScanning((prev) => ({ ...prev, [projectId]: true }));
    setScanErrors((prev) => ({ ...prev, [projectId]: null }));

    try {
      const res = await fetch(`${API}/projects/${projectId}/scan`, { method: "POST" });
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

  async function handleGenerateGraph(projectId: string) {
    setGeneratingGraph((prev) => ({ ...prev, [projectId]: true }));
    setGraphMessages((prev) => ({ ...prev, [projectId]: null }));

    try {
      const res = await fetch(`${API}/projects/${projectId}/graph`, { method: "POST" });
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

  async function handleDeepDive(projectId: string, componentRoot: string) {
    // Toggle off if same component clicked again
    if (ddSelectedRoot[projectId] === componentRoot) {
      setDdSelectedRoot((prev) => ({ ...prev, [projectId]: null }));
      setDdResults((prev) => ({ ...prev, [projectId]: null }));
      setDdErrors((prev) => ({ ...prev, [projectId]: null }));
      return;
    }

    setDdSelectedRoot((prev) => ({ ...prev, [projectId]: componentRoot }));
    setDdLoading((prev) => ({ ...prev, [projectId]: true }));
    setDdErrors((prev) => ({ ...prev, [projectId]: null }));
    setDdResults((prev) => ({ ...prev, [projectId]: null }));

    try {
      const res = await fetch(`${API}/projects/${projectId}/components/deep-dive`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ component_root: componentRoot }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setDdErrors((prev) => ({ ...prev, [projectId]: body?.detail || "Deep dive failed" }));
        return;
      }
      const data: DeepDiveResult = await res.json();
      setDdResults((prev) => ({ ...prev, [projectId]: data }));
    } catch {
      setDdErrors((prev) => ({ ...prev, [projectId]: "Deep dive failed" }));
    } finally {
      setDdLoading((prev) => ({ ...prev, [projectId]: false }));
    }
  }

  /* ── Graph node click → navigate to deep dive ── */

  function handleGraphNodeClick(projectId: string, nodeId: string) {
    const graph = graphs[projectId];
    const scan = scans[projectId];
    if (!graph || !scan) return;

    const node = graph.nodes.find((n) => n.id === nodeId);
    if (!node) return;

    if (!["frontend", "backend", "component"].includes(node.node_type)) return;

    const components = scan.components || [];
    const comp = components.find(
      (c) =>
        c.name.toLowerCase().replace("_", " ") === node.label.toLowerCase() ||
        c.name.toLowerCase() === node.label.toLowerCase() ||
        c.type === node.node_type,
    );
    if (comp) {
      // Always select (don't toggle) when coming from architecture
      if (ddSelectedRoot[projectId] !== comp.root_path) {
        handleDeepDive(projectId, comp.root_path);
      }
      setActiveView("deep-dive");
    }
  }

  /* ── Select project ── */

  function selectProject(projectId: string) {
    setSelectedProjectId(projectId);
    setActiveView("overview");
  }

  /* ── Status helpers ── */

  function statusDotClass(value: string) {
    if (value === "loading...") return "loading";
    if (value === "ok" || value === "connected" || value === "running") return "ok";
    return "err";
  }

  /* ── Render active view ── */

  function renderView() {
    if (!selectedProject || !selectedProjectId) {
      return (
        <div className="view-empty">
          <p className="view-empty-title">No project selected</p>
          <p className="view-empty-sub">Select or create a project to get started.</p>
        </div>
      );
    }

    switch (activeView) {
      case "overview":
        return <OverviewView project={selectedProject} scan={scans[selectedProjectId] || null} />;

      case "architecture":
        return (
          <ReactFlowProvider>
            <ArchitectureView
              graph={graphs[selectedProjectId] || null}
              scan={scans[selectedProjectId] || null}
              simResult={simResults[selectedProjectId] || null}
              ddSelectedRoot={ddSelectedRoot[selectedProjectId] || null}
              onNodeClick={(nodeId) => handleGraphNodeClick(selectedProjectId, nodeId)}
              onDeepDive={(root) => {
                if (ddSelectedRoot[selectedProjectId] !== root) {
                  handleDeepDive(selectedProjectId, root);
                }
                setActiveView("deep-dive");
              }}
              generatingGraph={generatingGraph[selectedProjectId] || false}
              graphMessage={graphMessages[selectedProjectId] || null}
              onGenerateGraph={() => handleGenerateGraph(selectedProjectId)}
            />
          </ReactFlowProvider>
        );

      case "api-explorer":
        return <ApiExplorerView projectId={selectedProjectId} />;

      case "sequence-diagrams":
        return <SequenceDiagramsView projectId={selectedProjectId} />;

      case "deep-dive":
        return (
          <DeepDiveView
            scan={scans[selectedProjectId] || null}
            ddSelectedRoot={ddSelectedRoot[selectedProjectId] || null}
            ddResult={ddResults[selectedProjectId] || null}
            ddLoading={ddLoading[selectedProjectId] || false}
            ddError={ddErrors[selectedProjectId] || null}
            ddExpandEdges={ddExpandEdges[selectedProjectId] || false}
            onDeepDive={(root) => handleDeepDive(selectedProjectId, root)}
            onToggleExpandEdges={() =>
              setDdExpandEdges((prev) => ({
                ...prev,
                [selectedProjectId]: !(prev[selectedProjectId] ?? false),
              }))
            }
            projectName={selectedProject.name}
          />
        );

      case "simulation":
        return (
          <SimulationView
            graph={graphs[selectedProjectId] || null}
            simSelectedNode={simSelectedNode[selectedProjectId] || ""}
            simulating={simulating[selectedProjectId] || false}
            simResult={simResults[selectedProjectId] || null}
            simError={simErrors[selectedProjectId] || null}
            onSelectNode={(nodeId) =>
              setSimSelectedNode((prev) => ({ ...prev, [selectedProjectId]: nodeId }))
            }
            onSimulate={() => handleSimulate(selectedProjectId)}
            onClear={() => setSimResults((prev) => ({ ...prev, [selectedProjectId]: null }))}
          />
        );
    }
  }

  /* ── Render ── */

  return (
    <div className="layout">
      {/* ── Topbar ── */}
      <header className="topbar">
        <div className="topbar-left">
          <Zap size={18} color="#f97316" />
          <span className="topbar-title">Chaos Twin</span>
        </div>
        <div className="topbar-right">
          <div className="topbar-status">
            <span className={`topbar-dot ${statusDotClass(apiStatus)}`} title={`API: ${apiStatus}`} />
            <span className={`topbar-dot ${statusDotClass(dbStatus)}`} title={`DB: ${dbStatus}`} />
          </div>
          {selectedProject && (
            <span className="topbar-breadcrumb">{selectedProject.name}</span>
          )}
        </div>
      </header>

      <div className="layout-body">
        {/* ── Sidebar ── */}
        <aside className="sidebar">
          {/* Section 1: Projects */}
          <div className="sidebar-section">
            <div className="sidebar-label">Your Projects</div>
            <div className="sidebar-project-list">
              {projects.map((p) => (
                <button
                  key={p.id}
                  className={`sidebar-project-item${p.id === selectedProjectId ? " active" : ""}`}
                  onClick={() => selectProject(p.id)}
                >
                  <span className="sidebar-project-name">{p.name}</span>
                  <span className="sidebar-project-date">
                    {new Date(p.created_at).toLocaleDateString()}
                  </span>
                  <span
                    className="sidebar-project-delete"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteProject(p.id);
                    }}
                    role="button"
                    tabIndex={0}
                  >
                    <Trash2 size={12} />
                  </span>
                </button>
              ))}
            </div>

            {showCreateForm ? (
              <form onSubmit={handleSubmit} className="sidebar-create-form">
                <input
                  type="text"
                  placeholder="Project name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="sidebar-input"
                  required
                />
                <input
                  type="text"
                  placeholder="Path (e.g. /projects/my-api)"
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                  className="sidebar-input"
                  required
                />
                <div style={{ display: "flex", gap: 6 }}>
                  <button type="submit" className="btn btn-primary btn-sm" style={{ flex: 1 }}>
                    Create
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      setShowCreateForm(false);
                      setCreateError(null);
                    }}
                  >
                    Cancel
                  </button>
                </div>
                {createError && (
                  <p className="text-error" style={{ fontSize: 12, marginTop: 2 }}>
                    {createError}
                  </p>
                )}
              </form>
            ) : (
              <button className="sidebar-new-project" onClick={() => setShowCreateForm(true)}>
                <Plus size={14} />
                New Project
              </button>
            )}
          </div>

          {/* Section 2: Navigation */}
          {selectedProjectId && (
            <div className="sidebar-section sidebar-nav">
              {NAV_ITEMS.map((item) => (
                <button
                  key={item.key}
                  className={`sidebar-nav-item${activeView === item.key ? " active" : ""}`}
                  onClick={() => setActiveView(item.key)}
                >
                  <item.icon size={16} />
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          )}

          {/* Section 3: Actions */}
          {selectedProjectId && (
            <div className="sidebar-section sidebar-actions">
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip"
                onChange={handleFileSelected}
                style={{ display: "none" }}
              />
              <button
                className="btn btn-secondary btn-full"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading[selectedProjectId]}
              >
                <Upload size={14} />
                {uploading[selectedProjectId] ? "Uploading…" : "Upload ZIP"}
              </button>
              <button
                className="btn btn-primary btn-full"
                onClick={() => handleScan(selectedProjectId)}
                disabled={scanning[selectedProjectId]}
              >
                <Play size={14} />
                {scanning[selectedProjectId] ? "Scanning…" : "Run Scan"}
              </button>

              {uploadMessages[selectedProjectId] && (
                <p
                  className={
                    uploadMessages[selectedProjectId] === "Uploaded successfully"
                      ? "text-success"
                      : "text-error"
                  }
                  style={{ fontSize: 12 }}
                >
                  {uploadMessages[selectedProjectId]}
                </p>
              )}
              {uploadedFilenames[selectedProjectId] && (
                <p className="text-muted" style={{ fontSize: 11 }}>
                  {uploadedFilenames[selectedProjectId]}
                </p>
              )}
              {scanErrors[selectedProjectId] && (
                <p className="text-error" style={{ fontSize: 12 }}>
                  {scanErrors[selectedProjectId]}
                </p>
              )}
            </div>
          )}
        </aside>

        {/* ── Main Canvas ── */}
        <main className="main-canvas">{renderView()}</main>
      </div>
    </div>
  );
}

export default App;

// Re-export shortenLabel for any legacy usage
export { shortenLabel };
