import {
  useState,
  useRef,
} from "react";
import { ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./App.css";

import {
  Zap,
} from "lucide-react";

import ProjectDashboard from "./views/ProjectDashboard";
import UnderstandingPage from "./views/UnderstandingPage";
import TerraLandingView from "./views/TerraLandingView";
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
  const newProjectFileInputRef = useRef<HTMLInputElement>(null);
  const [entryIntent, setEntryIntent] = useState<IntakeIntent>(null);
  const {
    activeView,
    apiStatus,
    apiStatusDetail,
    createError,
    dbStatus,
    dbStatusDetail,
    duplicateProjectPrompt,
    ddErrors,
    ddExpandEdges,
    ddLoading,
    ddResults,
    ddSelectedRoot,
    generatingGraph,
    graphMessages,
    graphs,
    handleNewProjectFileSelected,
    name,
    isCreatingProjectFromZip,
    newProjectUploadError,
    path,
    projectRefreshKeys,
    projects,
    resolveDuplicateProjectChoice,
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
    switchProject,
    toggleDeepDiveEdges,
  } = useChaosTwinApp();
  const activeNavItem = NAV_ITEMS.find((item) => item.key === activeView);
  const projectId = selectedProjectId ?? "";
  const selectedScan = projectId ? scans[projectId] || null : null;

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

  function navigateTo(view: NavItem) {
    setActiveView(view);
  }

  function handleUploadNewProject() {
    setEntryIntent("zip");
    newProjectFileInputRef.current?.click();
  }

  /* ── Render active view ── */

  function renderView() {
    switch (activeView) {
      case "workspace":
        return (
          <WorkspaceLandingView
            project={selectedProject!}
            scan={selectedScan}
            graph={graphs[projectId] || null}
            refreshKey={projectRefreshKeys[projectId] || 0}
            uploadMessage={uploadMessages[projectId] || null}
            uploadedFilename={uploadedFilenames[projectId] || null}
            uploading={uploading[projectId] || false}
            scanning={scanning[projectId] || false}
            generatingGraph={generatingGraph[projectId] || false}
            graphMessage={graphMessages[projectId] || null}
            entryIntent={entryIntent}
            onNavigate={navigateTo}
            onOpenComponent={(componentRoot) => void openDeepDive(projectId, componentRoot)}
            onUploadZip={handleStartZipIntake}
            onConnectGithub={handleStartGithubIntake}
            onRunScan={() => void handleScan(projectId)}
            onGenerateGraph={() => handleGenerateGraph(projectId)}
          />
        );


      case "dashboard":
        return (
          <ProjectDashboard 
            projectId={projectId} 
            onNavigate={setActiveView} 
          />
        );

      case "understanding":
        return (
          <UnderstandingPage 
            projectId={projectId} 
          />
        );

      case "architecture":
        return (
          <ReactFlowProvider>
            <ArchitectureView
              graph={graphs[projectId] || null}
              scan={selectedScan}
              simResult={simResults[projectId] || null}
              ddSelectedRoot={ddSelectedRoot[projectId] || null}
              onNodeClick={(nodeId) => handleGraphNodeClick(projectId, nodeId)}
              onDeepDive={(root) => void openDeepDive(projectId, root)}
              generatingGraph={generatingGraph[projectId] || false}
              graphMessage={graphMessages[projectId] || null}
              onGenerateGraph={() => handleGenerateGraph(projectId)}
            />
          </ReactFlowProvider>
        );

      case "api-explorer":
        return (
          <ApiExplorerView
            projectId={projectId}
            refreshKey={projectRefreshKeys[projectId] || 0}
          />
        );

      case "sequence-diagrams":
        return (
          <SequenceDiagramsView
            projectId={projectId}
            refreshKey={projectRefreshKeys[projectId] || 0}
          />
        );

      case "deep-dive":
        return (
          <DeepDiveView
            scan={selectedScan}
            ddSelectedRoot={ddSelectedRoot[projectId] || null}
            ddResult={ddResults[projectId] || null}
            ddLoading={ddLoading[projectId] || false}
            ddError={ddErrors[projectId] || null}
            ddExpandEdges={ddExpandEdges[projectId] || false}
            onDeepDive={(root) => void openDeepDive(projectId, root)}
            onToggleExpandEdges={() => toggleDeepDiveEdges(projectId)}
            projectName={selectedProject!.name}
          />
        );

      case "simulation":
        return (
          <SimulationView
            graph={graphs[projectId] || null}
            simSelectedNode={simSelectedNode[projectId] || ""}
            simulating={simulating[projectId] || false}
            simResult={simResults[projectId] || null}
            simError={simErrors[projectId] || null}
            onSelectNode={(nodeId) => setSimulationNode(projectId, nodeId)}
            onSimulate={() => handleSimulate(projectId)}
            onClear={() => clearSimulationResult(projectId)}
          />
        );
    }
  }

  /* ── Render ── */

  if (!selectedProject || !selectedProjectId) {
    return (
      <>
        <TerraLandingView
          showCreateForm={showCreateForm}
          name={name}
          setName={setName}
          path={path}
          setPath={setPath}
          handleSubmit={handleSubmit}
          handleCancelCreate={handleCancelCreate}
          createError={createError}
          isUploading={isCreatingProjectFromZip}
          projects={projects}
          uploadError={newProjectUploadError}
          entryIntent={entryIntent}
          onSelectProject={selectProject}
          onUploadZip={handleUploadNewProject}
        />
        {duplicateProjectPrompt && (
          <div style={{ position: "fixed", inset: 0, background: "rgba(42, 47, 43, 0.32)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 120 }}>
            <div style={{ width: "100%", maxWidth: 440, background: "#fff", borderRadius: 20, boxShadow: "0 18px 48px rgba(46,50,48,0.16)", padding: 28 }}>
              <h3 style={{ margin: "0 0 10px", fontFamily: "'Literata', serif", color: "#2e3230" }}>
                Duplicate project name
              </h3>
              <p style={{ margin: "0 0 20px", color: "#545e57", lineHeight: 1.6 }}>
                A project named <strong>{duplicateProjectPrompt.projectName}</strong> already exists. Replace it or create a new project?
              </p>
              <div style={{ display: "flex", gap: 12 }}>
                <button
                  className="topbar-upload-btn"
                  onClick={() => {
                    void resolveDuplicateProjectChoice("replace");
                  }}
                  style={{ flex: 1 }}
                >
                  Replace
                </button>
                <button
                  className="sidebar-nav-item"
                  onClick={() => {
                    void resolveDuplicateProjectChoice("create_new");
                  }}
                  style={{ flex: 1, justifyContent: "center" }}
                >
                  Create New
                </button>
              </div>
            </div>
          </div>
        )}
      </>
    );
  }

  return (
    <div className="layout">
      <header className="topbar">
        <div className="topbar-left">
          <span className="topbar-page-name">{activeNavItem?.label ?? "Workspace"}</span>
        </div>
        <div className="topbar-center">
          {selectedProject && (
            <span className="topbar-project-title">{selectedProject.name}</span>
          )}
        </div>
        <div className="topbar-right">
          <div className="topbar-status-rail">
            <div className={`topbar-status-badge is-${statusDotClass(apiStatus)}`} title={apiStatusDetail}>
              <span className={`topbar-dot ${statusDotClass(apiStatus)}`} />
              API {apiStatus}
            </div>
            <div className={`topbar-status-badge is-${statusDotClass(dbStatus)}`} title={dbStatusDetail}>
              <span className={`topbar-dot ${statusDotClass(dbStatus)}`} />
              DB {dbStatus}
            </div>
          </div>
          <button className="topbar-upload-btn" onClick={handleUploadNewProject}>
            {isCreatingProjectFromZip ? "Uploading..." : "Upload New Project"}
          </button>
        </div>
      </header>

      <div className="layout-body">
        <aside className="sidebar">
          {/* Logo / brand */}
          <div style={{ padding: '20px 8px 16px', borderBottom: '1px solid rgba(196,200,188,0.3)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 36, height: 36, borderRadius: 10, background: '#4a7c59', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Zap size={18} color="#fff" />
              </div>
              <span style={{ fontFamily: "'Literata', serif", fontWeight: 700, fontSize: '1.15rem', color: '#2c332e' }}>
                Chaos Twin
              </span>
            </div>
          </div>

          {/* Hidden file input still needed for internal scan actions */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip"
            onChange={handleFileSelected}
            style={{ display: "none" }}
          />
          <input
            ref={newProjectFileInputRef}
            type="file"
            accept=".zip"
            onChange={(event) => {
              void handleNewProjectFileSelected(event);
            }}
            style={{ display: "none" }}
          />

          {/* Navigation items */}
          <nav style={{ padding: '12px 8px', display: 'flex', flexDirection: 'column', gap: 4 }}>
            {NAV_GROUPS.flatMap(g => g.items)
              .filter(item => !item.requiresScan || Boolean(selectedScan))
              .map((item) => {
                const isComingSoon = item.comingSoon;
                const isDisabled = !selectedProjectId || isComingSoon;
                return (
                  <button
                    key={item.key}
                    className={`sidebar-nav-item${!isComingSoon && activeView === item.key ? " active" : ""}`}
                    onClick={isComingSoon ? undefined : () => navigateTo(item.key)}
                    disabled={isDisabled}
                    title={isComingSoon ? "Coming soon" : undefined}
                    style={{
                      opacity: isComingSoon ? 0.38 : (!selectedProjectId ? 0.4 : 1),
                      cursor: isComingSoon ? "default" : undefined,
                    }}
                  >
                    <item.icon size={16} />
                    <span>{item.label}</span>
                    {isComingSoon && (
                      <span style={{
                        marginLeft: 'auto',
                        fontSize: '0.6rem',
                        fontWeight: 600,
                        letterSpacing: '0.04em',
                        color: '#7a8a7e',
                        textTransform: 'uppercase',
                        opacity: 0.7,
                      }}>Soon</span>
                    )}
                  </button>
                );
              })}
          </nav>
          <div style={{ marginTop: "auto", padding: "12px 8px 20px", borderTop: "1px solid rgba(196,200,188,0.3)" }}>
            <button
              className="sidebar-nav-item"
              onClick={switchProject}
              style={{ opacity: 0.72, fontSize: "0.92rem" }}
            >
              <span style={{ fontSize: "1rem" }}>⇄</span>
              <span>Switch Project</span>
            </button>
          </div>
        </aside>

        <main className="main-canvas">
          <div className="main-canvas-inner">{renderView()}</div>
        </main>
      </div>
      {duplicateProjectPrompt && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(42, 47, 43, 0.32)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 120 }}>
          <div style={{ width: "100%", maxWidth: 440, background: "#fff", borderRadius: 20, boxShadow: "0 18px 48px rgba(46,50,48,0.16)", padding: 28 }}>
            <h3 style={{ margin: "0 0 10px", fontFamily: "'Literata', serif", color: "#2e3230" }}>
              Duplicate project name
            </h3>
            <p style={{ margin: "0 0 20px", color: "#545e57", lineHeight: 1.6 }}>
              A project named <strong>{duplicateProjectPrompt.projectName}</strong> already exists. Replace it or create a new project?
            </p>
            <div style={{ display: "flex", gap: 12 }}>
              <button
                className="topbar-upload-btn"
                onClick={() => {
                  void resolveDuplicateProjectChoice("replace");
                }}
                style={{ flex: 1 }}
              >
                Replace
              </button>
              <button
                className="sidebar-nav-item"
                onClick={() => {
                  void resolveDuplicateProjectChoice("create_new");
                }}
                style={{ flex: 1, justifyContent: "center" }}
              >
                Create New
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
