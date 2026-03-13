import { ArrowRight, FolderUp, GitBranch, Sparkles } from "lucide-react";

import PageHeader from "../components/PageHeader";

type IntakeIntent = "zip" | "github" | null;

interface HomeIntakeViewProps {
  entryIntent: IntakeIntent;
  projectCount: number;
  showCreateForm: boolean;
  onCreateProject: () => void;
  onStartZip: () => void;
  onStartGithub: () => void;
}

export default function HomeIntakeView({
  entryIntent,
  projectCount,
  showCreateForm,
  onCreateProject,
  onStartZip,
  onStartGithub,
}: HomeIntakeViewProps) {
  const stagedCopy = entryIntent === "github"
    ? "GitHub intake is staged honestly. Start by creating the project shell in the workspace rail, then this entry point becomes the connection target once repo auth and import are enabled."
    : entryIntent === "zip"
      ? "ZIP intake starts by creating the project shell in the workspace rail so the uploaded source has a grounded workspace to attach to."
      : "Choose an intake path first. Summary, architecture, components, and deeper tools only appear after scanned project evidence exists.";

  return (
    <div className="page-shell home-intake-page">
      <PageHeader
        eyebrow="Home / Intake"
        title="Start with code intake. The workspace opens only after the scan has real evidence."
        description="Bring in a codebase first. After that, CHAOS-TWIN explains it in order: plain summary, architecture, important components, then deeper route and simulation tools."
        meta={(
          <>
            <span className="chip chip-muted">{projectCount} projects in workspace</span>
            <span className="chip chip-muted">ZIP import live</span>
            <span className="chip chip-muted">GitHub staged honestly</span>
          </>
        )}
      />

      <section className="home-intake-hero surface-panel">
        <div className="home-intake-copy">
          <div className="intel-section-kicker">Intake first</div>
          <h2 className="home-intake-title">Choose how the codebase comes in.</h2>
          <p className="home-intake-subtitle">This first page stays focused on intake. The product only shifts into explanation once upload and scan give it something grounded to work from.</p>
        </div>

        <div className="home-intake-actions-grid">
          <button type="button" className="home-intake-action-card is-primary" onClick={onStartZip}>
            <div className="home-intake-action-topline">
              <span className="home-intake-action-kicker">Primary intake</span>
              <span className="badge badge-success">Available now</span>
            </div>
            <div className="home-intake-action-title-row">
              <FolderUp size={18} />
              <span className="home-intake-action-title">Upload ZIP</span>
            </div>
            <p className="home-intake-action-copy">Bring in a repository snapshot today. After upload and scan, the workspace starts with a plain-language summary and opens into architecture and components only when needed.</p>
            <span className="home-intake-action-cta">Start ZIP intake <ArrowRight size={14} /></span>
          </button>

          <button type="button" className="home-intake-action-card" onClick={onStartGithub}>
            <div className="home-intake-action-topline">
              <span className="home-intake-action-kicker">Staged entry</span>
              <span className="chip chip-muted">Real place in product</span>
            </div>
            <div className="home-intake-action-title-row">
              <GitBranch size={18} />
              <span className="home-intake-action-title">Connect GitHub</span>
            </div>
            <p className="home-intake-action-copy">GitHub stays visible as the next intake path. The backend connection flow is still staged, so the UI keeps that explicit instead of pretending the import already works.</p>
            <span className="home-intake-action-cta">Prepare GitHub path <ArrowRight size={14} /></span>
          </button>
        </div>
      </section>

      <section className="home-intake-story-grid">
        <div className="home-intake-story-card surface-panel">
          <div className="intel-section-kicker">What happens next</div>
          <div className="home-intake-steps">
            <div className="home-intake-step">
              <span className="home-intake-step-number">1</span>
              <div>
                <p className="home-intake-step-title">Create the project shell</p>
                <p className="home-intake-step-copy">A project record anchors intake, scan history, graph state, and the deeper analysis surfaces that follow.</p>
              </div>
            </div>
            <div className="home-intake-step">
              <span className="home-intake-step-number">2</span>
              <div>
                <p className="home-intake-step-title">Import and scan</p>
                <p className="home-intake-step-copy">Only scanned evidence lights up the workspace. No architecture, route, or sequence detail is invented client-side.</p>
              </div>
            </div>
            <div className="home-intake-step">
              <span className="home-intake-step-number">3</span>
              <div>
                <p className="home-intake-step-title">Enter the workspace</p>
                <p className="home-intake-step-copy">The first post-scan layer is simple on purpose: summary first, then architecture, then important components, with deeper tools held back until you ask for them.</p>
              </div>
            </div>
          </div>
        </div>

        <div className="home-intake-story-card surface-panel">
          <div className="intel-section-kicker">What the workspace will show</div>
          <div className="home-intake-reveal-list">
            <div className="home-intake-reveal-item">
              <Sparkles size={16} />
              <span>A short plain-language summary instead of a dashboard full of equal-weight panels.</span>
            </div>
            <div className="home-intake-reveal-item">
              <GitBranch size={16} />
              <span>Architecture and important components become the next two understanding steps.</span>
            </div>
            <div className="home-intake-reveal-item">
              <ArrowRight size={16} />
              <span>Trust state stays explicit when the evidence is sparse, degraded, fallback-backed, or still pending.</span>
            </div>
          </div>
          <div className={`home-intake-inline-note${showCreateForm ? " is-open" : ""}`}>
            <p>{stagedCopy}</p>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onCreateProject}>
              {showCreateForm ? "Project shell form open" : "Create project shell"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}