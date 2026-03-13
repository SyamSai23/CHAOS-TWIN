import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  FileCode2,
  FolderUp,
  GitBranch,
  Layers3,
  LoaderCircle,
  Play,
  ShieldCheck,
  Sparkles,
  Waypoints,
  Zap,
} from "lucide-react";

import { getProjectInsights, getProjectSummary } from "../api/client";
import type { NavItem } from "../app/navigation";
import PageHeader from "../components/PageHeader";
import type {
  GraphResponse,
  Project,
  ProjectInsight,
  ProjectInsightsResponse,
  ScanResult,
  ScanComponent,
  SystemIntelligenceSummaryResponse,
} from "../types";

type IntakeIntent = "zip" | "github" | null;

interface WorkspaceLandingViewProps {
  project: Project;
  scan: ScanResult | null;
  graph: GraphResponse | null;
  refreshKey: number;
  uploadMessage: string | null;
  uploadedFilename: string | null;
  uploading: boolean;
  scanning: boolean;
  generatingGraph: boolean;
  graphMessage: string | null;
  entryIntent: IntakeIntent;
  onNavigate: (view: NavItem) => void;
  onOpenComponent: (componentRoot: string) => void;
  onUploadZip: () => void;
  onConnectGithub: () => void;
  onRunScan: () => void;
  onGenerateGraph: () => void;
}

function prettifyLabel(value: string): string {
  return value
    .replace(/[_:]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatProvenance(value: string | null | undefined): string {
  if (!value) {
    return "unknown provenance";
  }
  return value.replace(/[_-]+/g, " ");
}

function confidenceClass(label: string): string {
  if (label === "high") return "intel-confidence-high";
  if (label === "medium") return "intel-confidence-medium";
  return "intel-confidence-low";
}

function findingTone(severity: string): string {
  if (severity === "high") return "intel-severity-high";
  if (severity === "medium") return "intel-severity-medium";
  return "intel-severity-low";
}

function isDegradedSummary(summary: SystemIntelligenceSummaryResponse | null): boolean {
  if (!summary) {
    return false;
  }
  return summary.confidence_summary.overall_label === "low"
    || formatProvenance(summary.graph_provenance).includes("fallback");
}

function sortInsights(items: ProjectInsight[]): ProjectInsight[] {
  const order = { high: 0, medium: 1, low: 2 };
  return [...items].sort((left, right) => {
    const leftOrder = order[left.severity as keyof typeof order] ?? 3;
    const rightOrder = order[right.severity as keyof typeof order] ?? 3;
    return leftOrder - rightOrder;
  });
}

function normalizeToken(value: string | null | undefined): string {
  return (value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

type ImportantComponent = {
  key: string;
  label: string;
  kind: string;
  reason: string;
  component: ScanComponent | null;
};

function matchComponentFromNode(components: ScanComponent[], label: string): ScanComponent | null {
  const normalizedLabel = normalizeToken(label);
  if (!normalizedLabel) {
    return null;
  }

  return components.find((component) => normalizeToken(component.name) === normalizedLabel)
    || components.find((component) => normalizeToken(component.component_key) === normalizedLabel)
    || components.find((component) => normalizeToken(component.root_path).endsWith(normalizedLabel))
    || components.find((component) => normalizeToken(component.root_path).includes(normalizedLabel))
    || null;
}

export default function WorkspaceLandingView({
  project,
  scan,
  graph,
  refreshKey,
  uploadMessage,
  uploadedFilename,
  uploading,
  scanning,
  generatingGraph,
  graphMessage,
  entryIntent,
  onNavigate,
  onOpenComponent,
  onUploadZip,
  onConnectGithub,
  onRunScan,
  onGenerateGraph,
}: WorkspaceLandingViewProps) {
  const [summary, setSummary] = useState<SystemIntelligenceSummaryResponse | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [insights, setInsights] = useState<ProjectInsightsResponse | null>(null);
  const [insightsError, setInsightsError] = useState<string | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);

  useEffect(() => {
    if (!scan) {
      return;
    }

    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) {
        return;
      }

      setSummaryLoading(true);
      setSummaryError(null);
      setInsightsLoading(true);
      setInsightsError(null);

      void getProjectSummary(project.id)
        .then((payload) => {
          if (!cancelled) {
            setSummary(payload);
          }
        })
        .catch((error) => {
          if (!cancelled) {
            setSummary(null);
            setSummaryError(error instanceof Error ? error.message : "Summary unavailable");
          }
        })
        .finally(() => {
          if (!cancelled) {
            setSummaryLoading(false);
          }
        });

      void getProjectInsights(project.id)
        .then((payload) => {
          if (!cancelled) {
            setInsights(payload);
          }
        })
        .catch((error) => {
          if (!cancelled) {
            setInsights(null);
            setInsightsError(error instanceof Error ? error.message : "Insights unavailable");
          }
        })
        .finally(() => {
          if (!cancelled) {
            setInsightsLoading(false);
          }
        });
    });

    return () => {
      cancelled = true;
    };
  }, [project.id, refreshKey, scan]);

  const degraded = isDegradedSummary(summary);
  const topFindings = useMemo(() => summary?.top_findings.slice(0, 2) ?? [], [summary]);
  const topRisks = useMemo(() => summary?.top_risks.slice(0, 2) ?? [], [summary]);
  const highlightedInsights = useMemo(() => sortInsights(insights?.insights ?? []).slice(0, 3), [insights]);
  const importantComponents = useMemo<ImportantComponent[]>(() => {
    const components = (scan?.components ?? []).filter((component) => ["frontend", "backend", "service"].includes(component.type));

    const seen = new Set<string>();
    const featuredFromSummary = (summary?.critical_nodes ?? [])
      .filter((node) => ["frontend", "backend", "component", "service"].includes(node.node_type))
      .map((node) => {
        const matchedComponent = matchComponentFromNode(components, node.label);
        const key = matchedComponent?.root_path ?? node.node_id;
        if (seen.has(key)) {
          return null;
        }
        seen.add(key);
        return {
          key,
          label: matchedComponent?.name === "root" ? project.name : matchedComponent?.name ?? node.label,
          kind: matchedComponent?.type ?? node.node_type,
          reason: node.reason,
          component: matchedComponent,
        };
      })
      .filter((item): item is ImportantComponent => Boolean(item));

    if (featuredFromSummary.length > 0) {
      return featuredFromSummary.slice(0, 4);
    }

    return [...components]
      .sort((left, right) => (right.file_count ?? 0) - (left.file_count ?? 0))
      .slice(0, 4)
      .map((component) => ({
        key: component.root_path,
        label: component.name === "root" ? project.name : component.name,
        kind: component.type,
        reason: component.file_count
          ? `${component.file_count} files in this ${component.type} component`
          : `Discovered ${component.type} component from current scan evidence`,
        component,
      }));
  }, [project.name, scan, summary]);

  if (!scan) {
    const stagedCopy = entryIntent === "github"
      ? "GitHub is now a first-class intake path in the product framing, but the backend repo connection flow is still staged. Use this project shell as the future connection target, or continue with ZIP import today."
      : "The project shell exists, but the workspace has no source evidence yet. Import first, then run a scan so the product can reveal grounded intelligence instead of placeholders.";

    return (
      <div className="page-shell workspace-landing-page">
        <PageHeader
          eyebrow="Workspace Setup"
          title={project.name}
          description="This project shell is ready for intake. Import source and run a scan before the workspace opens into summary, architecture, components, or deeper intelligence surfaces."
          meta={(
            <>
              <span className="chip chip-muted">Project shell ready</span>
              <span className="chip chip-muted">No scan evidence yet</span>
            </>
          )}
        />

        <section className="workspace-stage-hero surface-panel">
          <div className="workspace-stage-copy">
            <div className="intel-section-kicker">Start here</div>
            <h2 className="workspace-stage-title">Import source first. The workspace should only open up after the scan has something grounded to reveal.</h2>
            <p className="workspace-stage-subtitle">This stage is intentionally light: choose an intake path, run the scan, then move into a summary-first workspace rather than landing in six equally loud tools.</p>
          </div>

          <div className="workspace-stage-actions">
            <button type="button" className="workspace-stage-action is-primary" onClick={onUploadZip}>
              <div className="workspace-stage-action-topline">
                <span className="workspace-stage-action-label">Available now</span>
                <span className="badge badge-success">ZIP import</span>
              </div>
              <div className="workspace-stage-action-title"><FolderUp size={16} /> Upload ZIP</div>
              <p>Attach a repository snapshot to this project shell and use the scan to light up the intelligence workspace.</p>
            </button>

            <button type="button" className="workspace-stage-action" onClick={onConnectGithub}>
              <div className="workspace-stage-action-topline">
                <span className="workspace-stage-action-label">Staged path</span>
                <span className="chip chip-muted">GitHub</span>
              </div>
              <div className="workspace-stage-action-title"><GitBranch size={16} /> Connect GitHub</div>
              <p>Keep the GitHub entry point visible and intentional now, without pretending the deeper repo-connection backend is already finished.</p>
            </button>

            <button type="button" className="workspace-stage-action" onClick={onRunScan} disabled={scanning}>
              <div className="workspace-stage-action-topline">
                <span className="workspace-stage-action-label">After import</span>
                <span className="chip chip-muted">Grounded scan</span>
              </div>
              <div className="workspace-stage-action-title"><Play size={16} /> {scanning ? "Scanning…" : "Run Scan"}</div>
              <p>The scan is the transition point from intake into the actual workspace. Without it, the product should stay honest and restrained.</p>
            </button>
          </div>
        </section>

        <section className="workspace-stage-grid">
          <div className="workspace-stage-card surface-panel">
            <div className="intel-section-kicker">Intake state</div>
            <div className="workspace-stage-card-body">
              <p className="workspace-stage-note">{stagedCopy}</p>
              {uploadedFilename ? <div className="chip chip-muted">Latest upload: {uploadedFilename}</div> : null}
              {uploadMessage ? <div className={uploadMessage === "Uploaded successfully" ? "text-success" : "text-error"}>{uploadMessage}</div> : null}
            </div>
          </div>

          <div className="workspace-stage-card surface-panel">
            <div className="intel-section-kicker">What unlocks after scan</div>
            <div className="workspace-stage-unlock-list">
              <div className="workspace-stage-unlock-item"><Sparkles size={15} /><span>Summary-first workspace and trust state</span></div>
              <div className="workspace-stage-unlock-item"><Layers3 size={15} /><span>Architecture workspace and graph controls</span></div>
                <div className="workspace-stage-unlock-item"><Boxes size={15} /><span>Important components and focused deep dives</span></div>
                <div className="workspace-stage-unlock-item"><Zap size={15} /><span>Routes, request flow, sequences, and simulation when you intentionally go deeper</span></div>
            </div>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page-shell workspace-landing-page">
      <PageHeader
        eyebrow="Workspace Summary"
        title={project.name}
        description="Start with the plain-language summary. Then move into architecture, important components, and deeper tools only when you need them."
        meta={(
          <>
            <span className={`badge ${scan.status === "completed" ? "badge-success" : "badge-pending"}`}>{scan.status}</span>
            <span className="chip chip-muted">{scan.file_count} files</span>
            {summary ? <span className={`badge ${confidenceClass(summary.confidence_summary.overall_label)}`}>{summary.confidence_summary.overall_label} confidence</span> : null}
            {summary ? <span className="chip chip-muted">{formatProvenance(summary.graph_provenance)}</span> : null}
          </>
        )}
      />

      <section className="workspace-summary-hero surface-panel">
        <div className="workspace-summary-copy">
          <div className="intel-section-kicker">Summary-first workspace</div>
          <h2 className="workspace-summary-title">{summary?.system_type_guess ? prettifyLabel(summary.system_type_guess) : "Workspace ready"}</h2>
          <p className="workspace-summary-subtitle">{summary?.overview_text ?? "The project has been scanned. Summary and insights are still loading, so the workspace is staying focused on identity, readiness, and the next drill-downs."}</p>
          <div className="workspace-summary-banner-row">
            {summaryLoading ? (
              <div className="workspace-inline-banner is-loading">
                <LoaderCircle size={14} className="intel-spinner" />
                <span>Loading deterministic summary…</span>
              </div>
            ) : summary ? (
              <div className={`workspace-inline-banner ${degraded ? "is-caution" : "is-grounded"}`}>
                {degraded ? <AlertTriangle size={14} /> : <ShieldCheck size={14} />}
                <span>
                  {degraded
                    ? `This workspace is grounded but degraded. Confidence is ${summary.confidence_summary.overall_label}, and fallback or sparse evidence is being surfaced explicitly.`
                    : `Grounded from current project artifacts with ${summary.confidence_summary.overall_label} confidence and ${formatProvenance(summary.graph_provenance)} provenance.`}
                </span>
              </div>
            ) : null}
            {summaryError ? <div className="workspace-inline-note">{summaryError}</div> : null}
          </div>
        </div>

        <div className="workspace-summary-stats">
          <div className="workspace-summary-stat">
            <span className="workspace-summary-stat-label">Components</span>
            <span className="workspace-summary-stat-value">{(scan.components || []).length}</span>
            <span className="workspace-summary-stat-copy">Discovered from current scan evidence</span>
          </div>
          <div className="workspace-summary-stat">
            <span className="workspace-summary-stat-label">Routes</span>
            <span className="workspace-summary-stat-value">{summary?.route_counts.total ?? 0}</span>
            <span className="workspace-summary-stat-copy">Mapped request entry points</span>
          </div>
          <div className="workspace-summary-stat">
            <span className="workspace-summary-stat-label">Important nodes</span>
            <span className="workspace-summary-stat-value">{summary?.critical_nodes.length ?? 0}</span>
            <span className="workspace-summary-stat-copy">High-signal parts of the system right now</span>
          </div>
          <div className="workspace-summary-stat">
            <span className="workspace-summary-stat-label">Architecture</span>
            <span className="workspace-summary-stat-value">{graph ? graph.node_count : 0}</span>
            <span className="workspace-summary-stat-copy">{graph ? `${graph.edge_count} mapped edges` : "Graph not built yet"}</span>
          </div>
        </div>
      </section>

      <section className="workspace-primary-grid">
        <div className="workspace-primary-card surface-panel">
          <div className="workspace-signal-head">
            <div>
              <div className="intel-section-kicker">Step 2</div>
              <h3 className="workspace-signal-title">Read the architecture next</h3>
            </div>
            {graph ? (
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => onNavigate("architecture")}>Open architecture</button>
            ) : (
              <button type="button" className="btn btn-secondary btn-sm" onClick={onGenerateGraph} disabled={generatingGraph}>{generatingGraph ? "Building..." : "Build graph"}</button>
            )}
          </div>
          <p className="workspace-stage-note">
            {graph
              ? `The structural map is ready with ${graph.node_count} nodes and ${graph.edge_count} edges.`
              : "Use architecture after the summary when you want topology, boundaries, and system shape instead of more text."}
          </p>
          <div className="workspace-finding-list">
            <div className="workspace-finding-item">
              <span className="badge badge-muted">Why next</span>
              <p>Architecture gives the cleanest high-level answer to how the system is organized before you dive into individual routes or modules.</p>
            </div>
            <div className="workspace-finding-item">
              <span className="badge badge-muted">Trust</span>
              <p>{summary ? `Graph provenance is ${formatProvenance(summary.graph_provenance)} and confidence is ${summary.confidence_summary.overall_label}.` : "Trust state will stay visible here when the summary finishes loading."}</p>
            </div>
          </div>
          {graphMessage ? <div className="workspace-inline-note">{graphMessage}</div> : null}
        </div>

        <div className="workspace-primary-card surface-panel">
          <div className="workspace-signal-head">
            <div>
              <div className="intel-section-kicker">Step 3</div>
              <h3 className="workspace-signal-title">Focus the important components</h3>
            </div>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => onNavigate("deep-dive")}>Open components</button>
          </div>
          <div className="workspace-component-list">
            {importantComponents.length > 0 ? importantComponents.map((item) => (
              <div key={item.key} className="workspace-component-item">
                <div className="workspace-component-copy">
                  <div className="workspace-component-head">
                    <h4 className="workspace-component-title">{item.label}</h4>
                    <span className="chip chip-muted">{prettifyLabel(item.kind)}</span>
                  </div>
                  <p>{item.reason}</p>
                </div>
                <div className="workspace-component-actions">
                  {item.component ? (
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => onOpenComponent(item.component!.root_path)}>
                      Inspect
                    </button>
                  ) : null}
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => onNavigate("architecture")}>Locate</button>
                </div>
              </div>
            )) : (
              <div className="workspace-finding-empty">No important components are surfaced yet. Run the architecture graph or deep dive once more scan evidence is available.</div>
            )}
          </div>
        </div>
      </section>

      <section className="workspace-signal-grid">
        <div className="workspace-signal-card surface-panel">
          <div className="workspace-signal-head">
            <div>
              <div className="intel-section-kicker">Keep in mind</div>
              <h3 className="workspace-signal-title">Important findings and cautions</h3>
            </div>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => onNavigate("overview")}>Open evidence</button>
          </div>
          <div className="workspace-signal-columns">
            <div className="workspace-finding-list">
              <div className="workspace-signal-column-title">Findings</div>
              {topFindings.length > 0 ? topFindings.map((item) => (
                <div key={`${item.category}-${item.explanation}`} className="workspace-finding-item">
                  <span className={`badge ${findingTone(item.severity)}`}>{item.severity}</span>
                  <p>{item.explanation}</p>
                </div>
              )) : highlightedInsights.length > 0 ? highlightedInsights.map((item) => (
                <div key={item.insight_id} className="workspace-finding-item">
                  <span className={`badge ${findingTone(item.severity)}`}>{item.severity}</span>
                  <p>{item.explanation}</p>
                </div>
              )) : (
                <div className="workspace-finding-empty">{insightsLoading ? "Loading grounded findings..." : insightsError ?? "No top findings surfaced yet."}</div>
              )}
            </div>

            <div className="workspace-finding-list">
              <div className="workspace-signal-column-title">Risks</div>
              {topRisks.length > 0 ? topRisks.map((item) => (
                <div key={`${item.category}-${item.explanation}`} className="workspace-finding-item is-risk">
                  <span className={`badge ${findingTone(item.severity)}`}>{item.severity}</span>
                  <p>{item.explanation}</p>
                </div>
              )) : (
                <div className="workspace-finding-empty">No top risks surfaced yet.</div>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="workspace-secondary-grid">
        <div className="workspace-secondary-card surface-panel">
          <div className="intel-section-kicker">Step 4</div>
          <h3 className="workspace-signal-title">Go deeper only when needed</h3>
          <p className="workspace-stage-note">Routes, sequences, evidence review, simulation, and fresh intake are still here. They just no longer compete with the first understanding steps.</p>
          <div className="workspace-secondary-actions">
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => onNavigate("api-explorer")}><Zap size={14} /> View Routes</button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => onNavigate("sequence-diagrams")}><Waypoints size={14} /> View Sequences</button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => onNavigate("overview")}><Sparkles size={14} /> Review Evidence</button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => onNavigate("simulation")}><Play size={14} /> Run Simulation</button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onUploadZip} disabled={uploading}><FileCode2 size={14} /> {uploading ? "Uploading…" : "Refresh with ZIP"}</button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onConnectGithub}><GitBranch size={14} /> Connect GitHub</button>
          </div>
          {entryIntent === "github" ? (
            <p className="workspace-stage-note">GitHub remains visible as a first-class intake path here too. The UI is reserving the connection story without pretending repo auth and sync are already complete.</p>
          ) : null}
        </div>
      </section>
    </div>
  );
}