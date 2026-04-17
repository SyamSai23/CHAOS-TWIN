import {
  useEffect,
  useRef,
  useState,
} from "react";
import "./App.css";

import {
  Zap,
} from "lucide-react";

import ProjectDashboard from "./views/ProjectDashboard";
import UnderstandingPage from "./views/UnderstandingPage";
import FeatureMapPage from "./pages/FeatureMapPage";
import ApiExplorerPage from "./pages/ApiExplorerPage";
import SequenceDiagramPage from "./pages/SequenceDiagramPage";
import ProjectsPage from "./pages/ProjectsPage";
import TerraLandingView from "./views/TerraLandingView";
import { NAV_GROUPS, NAV_ITEMS, type NavItem } from "./app/navigation";
import { useChaosTwinApp } from "./app/useChaosTwinApp";

type IntakeIntent = "zip" | "github" | null;
type AppView = NavItem | "sequence";

const ACTIVE_ROUTE_VIEWS: NavItem[] = ["projects", "dashboard", "understanding", "feature-map", "api-explorer"];

function pathForView(view: AppView, projectId: string | null, routeId: string | null) {
  if (view === "projects") {
    return "/projects";
  }
  if (!projectId || view === "landing") {
    return "/";
  }
  if (view === "sequence") {
    return routeId ? `/projects/${projectId}/sequence/${routeId}` : `/projects/${projectId}/api-explorer`;
  }
  if (!ACTIVE_ROUTE_VIEWS.includes(view)) {
    return "/";
  }

  const segments: Record<"dashboard" | "understanding" | "feature-map" | "api-explorer", string> = {
    dashboard: "dashboard",
    understanding: "understanding",
    "feature-map": "feature-map",
    "api-explorer": "api-explorer",
  };

  return `/projects/${projectId}/${segments[view as "dashboard" | "understanding" | "feature-map" | "api-explorer"]}`;
}

function parsePathname(pathname: string): { projectId: string | null; view: AppView; routeId: string | null } {
  if (pathname === "/projects" || pathname === "/projects/") {
    return { projectId: null, view: "projects", routeId: null };
  }
  const sequenceMatch = pathname.match(/^\/projects\/([^/]+)\/sequence\/([^/]+)\/?$/);
  if (sequenceMatch) {
    return { projectId: sequenceMatch[1], view: "sequence", routeId: sequenceMatch[2] };
  }

  const match = pathname.match(/^\/projects\/([^/]+)\/([^/]+)\/?$/);
  if (!match) {
    return { projectId: null, view: "landing", routeId: null };
  }

  const [, projectId, segment] = match;
  const segmentToView: Record<string, NavItem> = {
    dashboard: "dashboard",
    understanding: "understanding",
    "feature-map": "feature-map",
    "api-explorer": "api-explorer",
  };

  const view = segmentToView[segment];
  if (!view) {
    return { projectId: null, view: "landing", routeId: null };
  }

  return { projectId, view, routeId: null };
}

function App() {
  const newProjectFileInputRef = useRef<HTMLInputElement>(null);
  const [entryIntent, setEntryIntent] = useState<IntakeIntent>(null);
  const [sequenceRouteId, setSequenceRouteId] = useState<string | null>(null);

  const {
    activeView,
    apiStatus,
    apiStatusDetail,
    createError,
    dbStatus,
    dbStatusDetail,
    duplicateProjectPrompt,
    handleNewProjectFileSelected,
    name,
    isCreatingProjectFromZip,
    newProjectUploadError,
    path,
    resolveDuplicateProjectChoice,
    selectedProject,
    selectedProjectId,
    showCreateForm,
    cancelCreateForm,
    handleSubmit,
    setActiveView,
    setName,
    setPath,
    setSelectedProjectId,
    statusDotClass,
    switchProject,
  } = useChaosTwinApp();

  const effectiveView: AppView = sequenceRouteId
    ? "sequence"
    : ACTIVE_ROUTE_VIEWS.includes(activeView)
      ? activeView
      : "landing";
  const activeNavItem = NAV_ITEMS.find((item) => item.key === (effectiveView === "sequence" ? "api-explorer" : effectiveView));
  const projectId = selectedProjectId ?? "";

  useEffect(() => {
    const parsed = parsePathname(window.location.pathname);
    setSelectedProjectId(parsed.projectId);
    setSequenceRouteId(parsed.routeId);
    setActiveView(parsed.view === "sequence" ? "api-explorer" : parsed.view);
  }, [setActiveView, setSelectedProjectId]);

  useEffect(() => {
    const handlePopState = () => {
      const parsed = parsePathname(window.location.pathname);
      setSelectedProjectId(parsed.projectId);
      setSequenceRouteId(parsed.routeId);
      setActiveView(parsed.view === "sequence" ? "api-explorer" : parsed.view);
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [setActiveView, setSelectedProjectId]);

  useEffect(() => {
    const nextPath = pathForView(effectiveView, selectedProjectId, sequenceRouteId);
    if (window.location.pathname !== nextPath) {
      window.history.replaceState({}, "", nextPath);
    }
  }, [effectiveView, selectedProjectId, sequenceRouteId]);

  function handleCancelCreate() {
    cancelCreateForm();
    setEntryIntent(null);
  }

  function navigateTo(view: NavItem) {
    setSequenceRouteId(null);
    setActiveView(view);
  }

  function handleUploadNewProject() {
    setEntryIntent("zip");
    newProjectFileInputRef.current?.click();
  }

  function renderView() {
    switch (effectiveView) {
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
      case "feature-map":
        return (
          <FeatureMapPage
            projectId={projectId}
          />
        );
      case "api-explorer":
        return (
          <ApiExplorerPage
            projectId={projectId}
          />
        );
      case "projects":
        return <ProjectsPage />;
      case "sequence":
        return sequenceRouteId ? (
          <SequenceDiagramPage
            projectId={projectId}
            routeId={sequenceRouteId}
          />
        ) : null;
      default:
        return null;
    }
  }

  const uploadInput = (
    <input
      ref={newProjectFileInputRef}
      type="file"
      accept=".zip"
      onChange={(event) => {
        void handleNewProjectFileSelected(event);
      }}
      style={{ display: "none" }}
    />
  );

  if (effectiveView === "landing" || (effectiveView !== "projects" && (!selectedProject || !selectedProjectId))) {
    return (
      <>
        {uploadInput}
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
          uploadError={newProjectUploadError}
          entryIntent={entryIntent}
          onUploadZip={handleUploadNewProject}
          onManageProjects={() => navigateTo("projects")}
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
      {uploadInput}
      <header className="topbar">
        <div className="topbar-left">
          <span className="topbar-page-name">{activeNavItem?.label ?? "Dashboard"}</span>
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
          <div style={{ padding: "20px 8px 16px", borderBottom: "1px solid rgba(196,200,188,0.3)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 36, height: 36, borderRadius: 10, background: "#4a7c59", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Zap size={18} color="#fff" />
              </div>
              <span style={{ fontFamily: "'Literata', serif", fontWeight: 700, fontSize: "1.15rem", color: "#2c332e" }}>
                Chaos Twin
              </span>
            </div>
          </div>

          <nav style={{ padding: "12px 8px", display: "flex", flexDirection: "column", gap: 4 }}>
            {NAV_GROUPS.flatMap((group) => group.items)
              .filter((item) => ACTIVE_ROUTE_VIEWS.includes(item.key))
              .map((item) => {
                const isDisabled = item.key !== "projects" && !selectedProjectId;
                return (
                  <button
                    key={item.key}
                    className={`sidebar-nav-item${effectiveView === item.key ? " active" : ""}`}
                    onClick={() => navigateTo(item.key)}
                    disabled={isDisabled}
                    style={{
                      opacity: !selectedProjectId ? 0.4 : 1,
                    }}
                  >
                    <item.icon size={16} />
                    <span>{item.label}</span>
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
