import {
  useState,
  useRef,
} from "react";
import { ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./App.css";

import {
  ArrowRight,
  GitBranch,
  Plus,
  Upload,
  Play,
  Trash2,
  Zap,
} from "lucide-react";

import OverviewView from "./views/OverviewView";
import HomeIntakeView from "./views/HomeIntakeView";
import ArchitectureView from "./views/ArchitectureView";
import ApiExplorerView from "./views/ApiExplorerView";
import SequenceDiagramsView from "./views/SequenceDiagramsView";
import DeepDiveView from "./views/DeepDiveView";
import SimulationView from "./views/SimulationView";
import WorkspaceLandingView from "./views/WorkspaceLandingView";
import { NAV_GROUPS, NAV_ITEMS, type NavItem } from "./app/navigation";
import { useChaosTwinApp } from "./app/useChaosTwinApp";

type IntakeIntent = "zip" | "github" | null;

/* ── App ── */

function App() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [entryIntent, setEntryIntent] = useState<IntakeIntent>(null);
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
  const activeNavItem = NAV_ITEMS.find((item) => item.key === activeView);
  const selectedScan = selectedProjectId ? scans[selectedProjectId] || null : null;

  function openCreateFormForIntent(intent: IntakeIntent) {
    setEntryIntent(intent);
    setShowCreateForm(true);
  }

  function handleStartZipIntake() {
    setEntryIntent("zip");
    if (selectedProjectId) {
      fileInputRef.current?.click();
      return;
    }
    setShowCreateForm(true);
  }

  function handleStartGithubIntake() {
    setEntryIntent("github");
    if (!selectedProjectId) {
      setShowCreateForm(true);
      return;
    }
    setActiveView("workspace");
  }

  function handleCancelCreate() {
    cancelCreateForm();
    setEntryIntent(null);
  }

  function handleSelectProject(projectId: string) {
    setEntryIntent(null);
    selectProject(projectId);
  }

  function navigateTo(view: NavItem) {
    setActiveView(view);
  }

  /* ── Render active view ── */

  function renderView() {
    if (!selectedProject || !selectedProjectId) {
      return (
        <HomeIntakeView
          entryIntent={entryIntent}
          projectCount={projects.length}
          showCreateForm={showCreateForm}
          onCreateProject={() => openCreateFormForIntent(entryIntent)}
          onStartZip={handleStartZipIntake}
          onStartGithub={handleStartGithubIntake}
        />
      );
    }

    switch (activeView) {
      case "workspace":
        return (
          <WorkspaceLandingView
            project={selectedProject}
            scan={selectedScan}
            graph={graphs[selectedProjectId] || null}
            refreshKey={projectRefreshKeys[selectedProjectId] || 0}
            uploadMessage={uploadMessages[selectedProjectId] || null}
            uploadedFilename={uploadedFilenames[selectedProjectId] || null}
            uploading={uploading[selectedProjectId] || false}
            scanning={scanning[selectedProjectId] || false}
            generatingGraph={generatingGraph[selectedProjectId] || false}
            graphMessage={graphMessages[selectedProjectId] || null}
            entryIntent={entryIntent}
            onNavigate={navigateTo}
            onOpenComponent={(componentRoot) => void openDeepDive(selectedProjectId, componentRoot)}
            onUploadZip={handleStartZipIntake}
            onConnectGithub={handleStartGithubIntake}
            onRunScan={() => void handleScan(selectedProjectId)}
            onGenerateGraph={() => handleGenerateGraph(selectedProjectId)}
          />
        );

      case "overview":
        return (
          <OverviewView
            project={selectedProject}
            scan={selectedScan}
            refreshKey={projectRefreshKeys[selectedProjectId] || 0}
          />
        );

      case "architecture":
        return (
          <ReactFlowProvider>
            <ArchitectureView
              graph={graphs[selectedProjectId] || null}
              scan={selectedScan}
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
            scan={selectedScan}
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
      <header className="topbar">
        <div className="topbar-left">
          <div className="topbar-mark">
            <Zap size={18} />
          </div>
          <div className="topbar-brand-copy">
            <span className="topbar-kicker">Intelligence Workspace</span>
            <span className="topbar-title">Chaos Twin</span>
          </div>
        </div>
        <div className="topbar-right">
          <div className="topbar-status-rail">
            <div className={`topbar-status-pill is-${statusDotClass(apiStatus)}`} title={`API: ${apiStatus}`}>
              <span className={`topbar-dot ${statusDotClass(apiStatus)}`} />
              <span>API {apiStatus}</span>
            </div>
            <div className={`topbar-status-pill is-${statusDotClass(dbStatus)}`} title={`DB: ${dbStatus}`}>
              <span className={`topbar-dot ${statusDotClass(dbStatus)}`} />
              <span>DB {dbStatus}</span>
            </div>
          </div>
          {selectedProject && (
            <div className="topbar-project-pill">
              <span className="topbar-project-context">{activeNavItem?.label ?? "Workspace"}</span>
              <span className="topbar-project-name">{selectedProject.name}</span>
            </div>
          )}
        </div>
      </header>

      <div className="layout-body">
        <aside className="sidebar">
          <div className="sidebar-section">
            <div className="sidebar-section-head">
              <div className="sidebar-label">Workspace</div>
              <span className="chip chip-muted">{projects.length} projects</span>
            </div>
            <p className="sidebar-section-copy">
              Start with a project shell, then attach source artifacts and run grounded scans.
            </p>
            <div className="sidebar-project-list">
              {projects.map((p) => (
                <button
                  key={p.id}
                  className={`sidebar-project-item${p.id === selectedProjectId ? " active" : ""}`}
                  onClick={() => handleSelectProject(p.id)}
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
              {projects.length === 0 && (
                <div className="sidebar-list-empty">
                  No projects yet. Create one to start the intake flow.
                </div>
              )}
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
                    onClick={handleCancelCreate}
                  >
                    Cancel
                  </button>
                </div>
                <p className="sidebar-form-note">
                  {entryIntent === "github"
                    ? "This creates the project shell for the staged GitHub intake path. Repo auth and import are intentionally deferred until the backend flow is ready."
                    : entryIntent === "zip"
                      ? "This creates the project shell for ZIP intake. Attach the ZIP and run a scan from the intake section below."
                      : "This creates the project shell only. Source import and scanning happen in the intake section below."}
                </p>
                {createError && (
                  <p className="text-error" style={{ fontSize: 12, marginTop: 2 }}>
                    {createError}
                  </p>
                )}
              </form>
            ) : (
              <button className="sidebar-new-project" onClick={() => openCreateFormForIntent(null)}>
                <Plus size={14} />
                New Project
              </button>
            )}
          </div>

          {selectedProjectId && (
            <div className="sidebar-section sidebar-nav">
              <div className="sidebar-section-head">
                <div className="sidebar-label">Understanding Flow</div>
              </div>
              {NAV_GROUPS.map((group) => {
                const visibleItems = group.items.filter((item) => !item.requiresScan || Boolean(selectedScan));
                if (!visibleItems.length) {
                  return null;
                }
                return (
                  <div key={group.label} className="sidebar-nav-group">
                    <div className="sidebar-nav-group-label">{group.label}</div>
                    {visibleItems.map((item) => (
                      <button
                        key={item.key}
                        className={`sidebar-nav-item${activeView === item.key ? " active" : ""}${item.key === "workspace" ? " is-primary" : ""}`}
                        onClick={() => navigateTo(item.key)}
                      >
                        <item.icon size={16} />
                        <span>{item.label}</span>
                      </button>
                    ))}
                  </div>
                );
              })}
            </div>
          )}

          {selectedProjectId && (
            <div className="sidebar-section sidebar-actions">
              <div className="sidebar-section-head">
                <div>
                  <div className="sidebar-label">Intake</div>
                  <p className="sidebar-section-copy sidebar-section-copy-tight">
                    Import source, then scan. GitHub remains visible as the next intake path.
                  </p>
                </div>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip"
                onChange={handleFileSelected}
                style={{ display: "none" }}
              />
              <div className="sidebar-action-stack">
                <button
                  className="btn btn-secondary btn-full"
                  onClick={handleStartZipIntake}
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
                <button type="button" className="sidebar-future-action" onClick={handleStartGithubIntake}>
                  <span className="sidebar-future-action-main">
                    <GitBranch size={14} />
                    Connect GitHub
                  </span>
                  <span className="chip chip-muted">Staged</span>
                </button>
              </div>

              <div className="sidebar-status-stack">
                <div className="sidebar-status-card">
                  <div className="sidebar-status-label-row">
                    <span className="sidebar-status-label">Current flow</span>
                    <ArrowRight size={12} />
                    <span className="sidebar-status-value">Create project, upload ZIP, run scan</span>
                  </div>
                  <p className="sidebar-status-copy">
                      After scan, the app opens into summary first, then architecture and components.
                  </p>
                </div>

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
                    Latest upload: {uploadedFilenames[selectedProjectId]}
                  </p>
                )}
                {entryIntent === "github" && (
                  <p className="text-muted" style={{ fontSize: 11 }}>
                    GitHub intake is staged honestly. Keep using the project shell and ZIP import until repo connection and sync are enabled.
                  </p>
                )}
                {scanErrors[selectedProjectId] && (
                  <p className="text-error" style={{ fontSize: 12 }}>
                    {scanErrors[selectedProjectId]}
                  </p>
                )}
              </div>
            </div>
          )}
        </aside>

        <main className="main-canvas">
          <div className="main-canvas-inner">{renderView()}</div>
        </main>
      </div>
    </div>
  );
}

export default App;
