import {
  useRef,
} from "react";
import { ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./App.css";

import {
  Plus,
  Upload,
  Play,
  Trash2,
  Zap,
} from "lucide-react";

import OverviewView from "./views/OverviewView";
import ArchitectureView from "./views/ArchitectureView";
import ApiExplorerView from "./views/ApiExplorerView";
import SequenceDiagramsView from "./views/SequenceDiagramsView";
import DeepDiveView from "./views/DeepDiveView";
import SimulationView from "./views/SimulationView";
import { NAV_ITEMS } from "./app/navigation";
import { useChaosTwinApp } from "./app/useChaosTwinApp";

/* ── App ── */

function App() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const {
    activeView,
    apiStatus,
    createError,
    dbStatus,
    ddErrors,
    ddExpandEdges,
    ddLoading,
    ddResults,
    ddSelectedRoot,
    generatingGraph,
    graphMessages,
    graphs,
    name,
    path,
    projectRefreshKeys,
    projects,
    scanErrors,
    scanning,
    scans,
    selectedProject,
    selectedProjectId,
    showCreateForm,
    simErrors,
    simResults,
    simSelectedNode,
    simulating,
    uploadedFilenames,
    uploading,
    uploadMessages,
    cancelCreateForm,
    clearSimulationResult,
    handleDeleteProject,
    handleFileSelected,
    handleGenerateGraph,
    handleGraphNodeClick,
    handleScan,
    handleSimulate,
    handleSubmit,
    openDeepDive,
    selectProject,
    setActiveView,
    setName,
    setPath,
    setShowCreateForm,
    setSimulationNode,
    statusDotClass,
    toggleDeepDiveEdges,
  } = useChaosTwinApp();

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
        return (
          <OverviewView
            project={selectedProject}
            scan={scans[selectedProjectId] || null}
            refreshKey={projectRefreshKeys[selectedProjectId] || 0}
          />
        );

      case "architecture":
        return (
          <ReactFlowProvider>
            <ArchitectureView
              graph={graphs[selectedProjectId] || null}
              scan={scans[selectedProjectId] || null}
              simResult={simResults[selectedProjectId] || null}
              ddSelectedRoot={ddSelectedRoot[selectedProjectId] || null}
              onNodeClick={(nodeId) => handleGraphNodeClick(selectedProjectId, nodeId)}
              onDeepDive={(root) => void openDeepDive(selectedProjectId, root)}
              generatingGraph={generatingGraph[selectedProjectId] || false}
              graphMessage={graphMessages[selectedProjectId] || null}
              onGenerateGraph={() => handleGenerateGraph(selectedProjectId)}
            />
          </ReactFlowProvider>
        );

      case "api-explorer":
        return (
          <ApiExplorerView
            projectId={selectedProjectId}
            refreshKey={projectRefreshKeys[selectedProjectId] || 0}
          />
        );

      case "sequence-diagrams":
        return (
          <SequenceDiagramsView
            projectId={selectedProjectId}
            refreshKey={projectRefreshKeys[selectedProjectId] || 0}
          />
        );

      case "deep-dive":
        return (
          <DeepDiveView
            scan={scans[selectedProjectId] || null}
            ddSelectedRoot={ddSelectedRoot[selectedProjectId] || null}
            ddResult={ddResults[selectedProjectId] || null}
            ddLoading={ddLoading[selectedProjectId] || false}
            ddError={ddErrors[selectedProjectId] || null}
            ddExpandEdges={ddExpandEdges[selectedProjectId] || false}
            onDeepDive={(root) => void openDeepDive(selectedProjectId, root)}
            onToggleExpandEdges={() => toggleDeepDiveEdges(selectedProjectId)}
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
            onSelectNode={(nodeId) => setSimulationNode(selectedProjectId, nodeId)}
            onSimulate={() => handleSimulate(selectedProjectId)}
            onClear={() => clearSimulationResult(selectedProjectId)}
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
                    onClick={cancelCreateForm}
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
