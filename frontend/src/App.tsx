import {
  useEffect,
  useRef,
  useState,
} from "react";
import "./App.css";

import {
  FolderUp,
  GitBranch,
  Loader2,
  X,
  Zap,
} from "lucide-react";

import ProjectDashboard from "./views/ProjectDashboard";
import UnderstandingPage from "./views/UnderstandingPage";
import FeatureMapPage from "./pages/FeatureMapPage";
import ApiExplorerPage from "./pages/ApiExplorerPage";
import SequenceDiagramPage from "./pages/SequenceDiagramPage";
import GitHubReposPage from "./pages/GitHubReposPage";
import ProjectsPage from "./pages/ProjectsPage";
import TerraLandingView from "./views/TerraLandingView";
import { NAV_GROUPS, NAV_ITEMS, type NavItem } from "./app/navigation";
import { useChaosTwinApp } from "./app/useChaosTwinApp";
import { API_BASE } from "./api/client";

type AppView = NavItem | "sequence" | "github-repos";

const ACTIVE_ROUTE_VIEWS: NavItem[] = ["projects", "dashboard", "understanding", "feature-map", "api-explorer", "sequence-diagrams"];

function pathForView(view: AppView, projectId: string | null, routeId: string | null) {
  if (view === "projects") {
    return "/projects";
  }
  if (view === "github-repos") {
    return "/github/repos";
  }
  if (view === "sequence-diagrams") {
    return projectId ? `/projects/${projectId}/sequence` : "/";
  }
  if (view === "sequence") {
    if (!projectId) {
      return "/";
    }
    return routeId ? `/projects/${projectId}/sequence/${routeId}` : `/projects/${projectId}/sequence`;
  }
  if (!projectId || view === "landing") {
    return "/";
  }
  if (!ACTIVE_ROUTE_VIEWS.includes(view)) {
    return "/";
  }

  const segments: Record<"dashboard" | "understanding" | "feature-map" | "api-explorer" | "sequence-diagrams", string> = {
    dashboard: "dashboard",
    understanding: "understanding",
    "feature-map": "feature-map",
    "api-explorer": "api-explorer",
    "sequence-diagrams": "sequence",
  };

  return `/projects/${projectId}/${segments[view as "dashboard" | "understanding" | "feature-map" | "api-explorer" | "sequence-diagrams"]}`;
}

function parsePathname(pathname: string): { projectId: string | null; view: AppView; routeId: string | null } {
  if (pathname === "/projects" || pathname === "/projects/") {
    return { projectId: null, view: "projects", routeId: null };
  }
  if (pathname === "/github/repos" || pathname === "/github/repos/") {
    return { projectId: null, view: "github-repos", routeId: null };
  }
  const sequenceMatch = pathname.match(/^\/projects\/([^/]+)\/sequence\/([^/]+)\/?$/);
  if (sequenceMatch) {
    return { projectId: sequenceMatch[1], view: "sequence", routeId: sequenceMatch[2] };
  }
  const sequenceIndexMatch = pathname.match(/^\/projects\/([^/]+)\/sequence\/?$/);
  if (sequenceIndexMatch) {
    return { projectId: sequenceIndexMatch[1], view: "sequence-diagrams", routeId: null };
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
    sequence: "sequence-diagrams",
  };

  const view = segmentToView[segment];
  if (!view) {
    return { projectId: null, view: "landing", routeId: null };
  }

  return { projectId, view, routeId: null };
}

function App() {
  const initialRoute = parsePathname(window.location.pathname);
  const newProjectFileInputRef = useRef<HTMLInputElement>(null);
  const [sequenceRouteId, setSequenceRouteId] = useState<string | null>(initialRoute.routeId);
  const [standaloneView, setStandaloneView] = useState<"github-repos" | null>(
    initialRoute.view === "github-repos" ? "github-repos" : null,
  );
  const [routeHydrated, setRouteHydrated] = useState(false);
  const [projectEntryOpen, setProjectEntryOpen] = useState(false);

  const {
    activeView,
    apiStatus,
    apiStatusDetail,
    dbStatus,
    dbStatusDetail,
    duplicateProjectPrompt,
    handleNewProjectFileSelected,
    isCreatingProjectFromZip,
    newProjectUploadError,
    projectsLoaded,
    resolveDuplicateProjectChoice,
    selectedProject,
    selectedProjectId,
    setActiveView,
    setSelectedProjectId,
    statusDotClass,
  } = useChaosTwinApp();

  const effectiveView: AppView = standaloneView
    ? standaloneView
    : sequenceRouteId
      ? "sequence"
      : ACTIVE_ROUTE_VIEWS.includes(activeView)
        ? activeView
        : "landing";
  const activeNavItem = NAV_ITEMS.find((item) => item.key === (effectiveView === "sequence" ? "sequence-diagrams" : effectiveView));
  const projectId = selectedProjectId ?? "";

  useEffect(() => {
    const parsed = parsePathname(window.location.pathname);
    setSelectedProjectId(parsed.projectId);
    setSequenceRouteId(parsed.routeId);
    setStandaloneView(parsed.view === "github-repos" ? "github-repos" : null);
    setActiveView(parsed.view === "sequence" || parsed.view === "github-repos" ? "api-explorer" : parsed.view);
    setRouteHydrated(true);
  }, [setActiveView, setSelectedProjectId]);

  useEffect(() => {
    const handlePopState = () => {
      const parsed = parsePathname(window.location.pathname);
      setSelectedProjectId(parsed.projectId);
      setSequenceRouteId(parsed.routeId);
      setStandaloneView(parsed.view === "github-repos" ? "github-repos" : null);
      setActiveView(parsed.view === "sequence" || parsed.view === "github-repos" ? "api-explorer" : parsed.view);
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [setActiveView, setSelectedProjectId]);

  useEffect(() => {
    if (!routeHydrated) {
      return;
    }
    const nextPath = pathForView(effectiveView, selectedProjectId, sequenceRouteId);
    if (window.location.pathname !== nextPath) {
      window.history.replaceState({}, "", nextPath);
    }
  }, [effectiveView, routeHydrated, selectedProjectId, sequenceRouteId]);

  function navigateTo(view: NavItem) {
    setSequenceRouteId(null);
    setActiveView(view);
  }

  function handleUploadNewProject() {
    setProjectEntryOpen(true);
  }

  function triggerZipUpload() {
    newProjectFileInputRef.current?.click();
  }

  function handleConnectGitHub() {
    window.location.href = `${API_BASE}/auth/github`;
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
      case "github-repos":
        return <GitHubReposPage />;
      case "sequence-diagrams":
        return (
          <SequenceDiagramPage
            projectId={projectId}
            routeId={null}
          />
        );
      case "sequence":
        return (
          <SequenceDiagramPage
            projectId={projectId}
            routeId={sequenceRouteId}
          />
        );
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

  if (effectiveView === "github-repos") {
    return <GitHubReposPage />;
  }

  if (effectiveView !== "landing" && effectiveView !== "projects" && selectedProjectId && !selectedProject) {
    if (!projectsLoaded) {
      return (
        <div style={{ minHeight: "100vh", background: "#faf6f0", display: "grid", placeItems: "center", color: "#2e3230", fontFamily: "'Nunito Sans', sans-serif" }}>
          <div style={{ display: "grid", placeItems: "center", gap: 12 }}>
            <Loader2 size={28} style={{ color: "#4a7c59", animation: "terra-spin 1s linear infinite" }} />
            <div style={{ fontSize: 15, color: "#74796e" }}>Loading project...</div>
          </div>
        </div>
      );
    }

    window.history.replaceState({}, "", "/projects");
    window.dispatchEvent(new PopStateEvent("popstate"));
    return null;
  }

  if (effectiveView === "landing" || (effectiveView !== "projects" && !selectedProjectId)) {
    return (
      <>
        {uploadInput}
        <TerraLandingView
          onAddProject={() => setProjectEntryOpen(true)}
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
            Add Project
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

      {projectEntryOpen && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(42, 47, 43, 0.36)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 130, padding: 24 }}>
          <div style={{ width: "100%", maxWidth: 520, background: "#fffdf9", borderRadius: 22, boxShadow: "0 22px 54px rgba(46,50,48,0.18)", border: "1px solid rgba(196,200,188,0.5)", padding: 26 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 18 }}>
              <div>
                <div style={{ fontFamily: "'Literata', serif", fontSize: 28, color: "#2e3230" }}>Add Project</div>
                <div style={{ marginTop: 8, color: "#74796e", fontSize: 14, lineHeight: 1.6 }}>
                  Choose how you want to bring a repository into Chaos Twin. This is the single entry point for new projects.
                </div>
              </div>
              <button
                type="button"
                onClick={() => setProjectEntryOpen(false)}
                style={{ width: 34, height: 34, borderRadius: 999, border: "1px solid #d8d4cc", background: "#fff", color: "#74796e", display: "grid", placeItems: "center", cursor: "pointer" }}
                aria-label="Close add project dialog"
              >
                <X size={16} />
              </button>
            </div>

            <div style={{ display: "grid", gap: 14 }}>
              <button
                type="button"
                onClick={handleConnectGitHub}
                style={{ textAlign: "left", background: "#eef4f1", border: "1px solid #c8ddd1", borderRadius: 16, padding: "18px 18px", cursor: "pointer" }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 16, fontWeight: 700, color: "#2e3230" }}>
                  <GitBranch size={18} color="#4a7c59" />
                  Import from GitHub
                </div>
                <div style={{ marginTop: 8, color: "#5f655b", fontSize: 13, lineHeight: 1.6 }}>
                  Connect your GitHub account, choose a repository and branch, and run the normal import pipeline.
                </div>
              </button>

              <button
                type="button"
                onClick={triggerZipUpload}
                disabled={isCreatingProjectFromZip}
                style={{ textAlign: "left", background: "#f7f3ec", border: "1px solid #d8d4cc", borderRadius: 16, padding: "18px 18px", cursor: isCreatingProjectFromZip ? "wait" : "pointer", opacity: isCreatingProjectFromZip ? 0.8 : 1 }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 16, fontWeight: 700, color: "#2e3230" }}>
                  {isCreatingProjectFromZip ? <Loader2 size={18} className="terra-spinner" color="#4a7c59" /> : <FolderUp size={18} color="#4a7c59" />}
                  {isCreatingProjectFromZip ? "Uploading codebase..." : "Upload ZIP codebase"}
                </div>
                <div style={{ marginTop: 8, color: "#5f655b", fontSize: 13, lineHeight: 1.6 }}>
                  Upload a repository ZIP directly and let Chaos Twin run the same scan and indexing pipeline.
                </div>
              </button>
            </div>

            {newProjectUploadError && (
              <div style={{ marginTop: 14, color: "#b91c1c", fontSize: 13, lineHeight: 1.5 }}>
                {newProjectUploadError}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
