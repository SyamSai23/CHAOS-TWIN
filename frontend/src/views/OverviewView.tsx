import { useEffect, useState } from "react";

import { AlertTriangle, FileCode2, LoaderCircle } from "lucide-react";

import { getCodePeek, getProjectInsights, getProjectSummary } from "../api/client";
import PageHeader from "../components/PageHeader";
import type {
  CodePeekResponse,
  Project,
  ProjectInsight,
  ProjectInsightsResponse,
  ScanResult,
  SystemIntelligenceSummaryResponse,
} from "../types";
import { shortenLabel } from "../types";

interface OverviewViewProps {
  project: Project;
  scan: ScanResult | null;
  refreshKey: number;
}

const LANG_EXT_MAP: Record<string, string[]> = {
  Python: [".py"],
  TypeScript: [".ts", ".tsx"],
  JavaScript: [".js", ".jsx"],
  Java: [".java"],
  "C#": [".cs"],
  Go: [".go"],
  Rust: [".rs"],
  Ruby: [".rb"],
  PHP: [".php"],
  HTML: [".html", ".htm"],
  CSS: [".css", ".scss", ".sass"],
};

function prettifyLabel(value: string): string {
  return value
    .replace(/[_:]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function summaryStatusText(summary: SystemIntelligenceSummaryResponse | null): string {
  if (!summary) {
    return "No summary available yet";
  }
  return `${prettifyLabel(summary.confidence_summary.overall_label)} confidence · ${summary.graph_provenance.replace(/_/g, " ")}`;
}

function confidenceTone(label: string): "high" | "medium" | "low" {
  if (label === "high") return "high";
  if (label === "medium") return "medium";
  return "low";
}

function severityTone(value: string): "high" | "medium" | "low" {
  if (value === "high") return "high";
  if (value === "medium") return "medium";
  return "low";
}

function formatProvenance(value: string | null | undefined): string {
  if (!value) {
    return "unknown provenance";
  }
  return value.replace(/[_-]+/g, " ");
}

function countSummaryEntries(values: Record<string, number>): number {
  return Object.values(values).reduce((sum, value) => sum + value, 0);
}

function isDegradedSummary(summary: SystemIntelligenceSummaryResponse | null): boolean {
  if (!summary) {
    return false;
  }
  return summary.confidence_summary.overall_label === "low"
    || formatProvenance(summary.graph_provenance).includes("fallback");
}

function sortFindings<T extends { severity: string }>(items: T[]): T[] {
  const order = { high: 0, medium: 1, low: 2 };
  return [...items].sort((left, right) => {
    const leftOrder = order[left.severity as keyof typeof order] ?? 3;
    const rightOrder = order[right.severity as keyof typeof order] ?? 3;
    return leftOrder - rightOrder;
  });
}

function topConfidenceReason(summary: SystemIntelligenceSummaryResponse | null): string | null {
  return summary?.confidence_summary.reasons?.[0] ?? null;
}

function insightSeverityClass(severity: string): string {
  if (severity === "high") return "intel-severity-high";
  if (severity === "medium") return "intel-severity-medium";
  return "intel-severity-low";
}

function confidenceClass(label: string): string {
  if (label === "high") return "intel-confidence-high";
  if (label === "medium") return "intel-confidence-medium";
  return "intel-confidence-low";
}

function isCodePeekAvailable(insight: ProjectInsight): boolean {
  return Boolean(
    insight.insight_id
      && (insight.evidence_refs.length > 0
        || insight.supporting_entity_ids.length > 0
        || insight.supporting_graph_node_ids.length > 0
        || insight.supporting_graph_edge_ids.length > 0),
  );
}

export default function OverviewView({ project, scan, refreshKey }: OverviewViewProps) {
  const [summary, setSummary] = useState<SystemIntelligenceSummaryResponse | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const [insights, setInsights] = useState<ProjectInsightsResponse | null>(null);
  const [insightsError, setInsightsError] = useState<string | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);

  const [activePeekInsightId, setActivePeekInsightId] = useState<string | null>(null);
  const [codePeek, setCodePeek] = useState<CodePeekResponse | null>(null);
  const [codePeekLoading, setCodePeekLoading] = useState(false);
  const [codePeekError, setCodePeekError] = useState<string | null>(null);

  useEffect(() => {
    if (!scan) {
      setSummary(null);
      setSummaryError(null);
      setSummaryLoading(false);
      setInsights(null);
      setInsightsError(null);
      setInsightsLoading(false);
      setActivePeekInsightId(null);
      setCodePeek(null);
      setCodePeekError(null);
      setCodePeekLoading(false);
      return;
    }

    let cancelled = false;
    setSummaryLoading(true);
    setSummaryError(null);
    setInsightsLoading(true);
    setInsightsError(null);
    setActivePeekInsightId(null);
    setCodePeek(null);
    setCodePeekError(null);
    setCodePeekLoading(false);

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

    return () => {
      cancelled = true;
    };
  }, [project.id, refreshKey, scan]);

  async function handleOpenCodePeek(insight: ProjectInsight) {
    if (activePeekInsightId === insight.insight_id) {
      setActivePeekInsightId(null);
      setCodePeek(null);
      setCodePeekError(null);
      setCodePeekLoading(false);
      return;
    }

    setActivePeekInsightId(insight.insight_id);
    setCodePeek(null);
    setCodePeekError(null);
    setCodePeekLoading(true);

    try {
      const payload = await getCodePeek(project.id, { insight_id: insight.insight_id });
      setCodePeek(payload);
    } catch (error) {
      setCodePeekError(error instanceof Error ? error.message : "Code peek unavailable");
    } finally {
      setCodePeekLoading(false);
    }
  }

  if (!scan) {
    return (
      <div className="page-shell">
        <PageHeader
          eyebrow="Project Overview"
          title={project.name}
          description="Deterministic summary, insights, and core scan metadata for the current project."
        />
        <div className="view-empty surface-panel">
          <p className="view-empty-title">No scan data yet</p>
          <p className="view-empty-sub">
            Upload a ZIP and run a scan from the sidebar to see the overview.
          </p>
        </div>
      </div>
    );
  }

  const langCounts = scan.languages.map((lang) => {
    const exts = LANG_EXT_MAP[lang] || [];
    const count = exts.reduce(
      (sum, ext) => sum + (scan.extension_counts[ext] || 0),
      0,
    );
    return { lang, count: count || 1 };
  });
  const maxLangCount = Math.max(...langCounts.map((l) => l.count), 1);
  const totalComponents = countSummaryEntries(summary?.component_counts ?? {});
  const insightsBySeverity = insights?.counts_by_severity ?? {};
  const topInsights = sortFindings(insights?.insights ?? []).slice(0, 6);
  const degraded = isDegradedSummary(summary);
  const runtimeHighlights = summary?.runtime_dependency_highlights ?? [];
  const findings = summary?.top_findings ?? [];
  const risks = summary?.top_risks ?? [];
  const criticalNodes = summary?.critical_nodes ?? [];
  const routeMethodPairs = Object.entries(summary?.route_counts.by_method ?? {});
  const confidenceReason = topConfidenceReason(summary);

  return (
    <div className="page-shell">
      <PageHeader
        eyebrow="Project Overview"
        title={project.name}
        description="Summary, confidence, and grounded intelligence signals across the current scan."
        meta={(
          <>
            <span className={`badge ${scan.status === "completed" ? "badge-success" : "badge-pending"}`}>
              {scan.status}
            </span>
            <span className="chip chip-muted">{scan.file_count} files</span>
            <span className="chip chip-muted">{scan.project_type}</span>
            {summary && (
              <span className={`badge ${confidenceClass(summary.confidence_summary.overall_label)}`}>
                {summary.confidence_summary.overall_label} confidence
              </span>
            )}
          </>
        )}
      />

      <section className="intel-hero surface-panel">
        <div className="intel-hero-main">
          <div className="intel-hero-copy">
            <div className="intel-section-kicker">System intelligence</div>
            <div className="intel-hero-title-row">
              <h2 className="intel-hero-title">
                {summary?.system_type_guess ? prettifyLabel(summary.system_type_guess) : "System profile pending"}
              </h2>
              {summary && (
                <span className={`badge ${confidenceClass(summary.confidence_summary.overall_label)}`}>
                  {summary.confidence_summary.overall_label} confidence
                </span>
              )}
            </div>
            <p className="intel-hero-summary">
              {summary?.overview_text ?? "Waiting on deterministic summary generation for this project."}
            </p>
            <div className="page-meta-row">
              {summary?.primary_stack.map((item) => (
                <span key={item} className="chip">{item}</span>
              ))}
              {!summary?.primary_stack.length && <span className="chip chip-muted">Stack still sparse</span>}
              {summary && <span className="chip chip-muted">{formatProvenance(summary.graph_provenance)}</span>}
              {summary?.generated_from.canonical_snapshot_used && <span className="chip chip-muted">canonical snapshot</span>}
            </div>
          </div>

          <div className="intel-hero-side">
            <div className={`intel-confidence-orb tone-${confidenceTone(summary?.confidence_summary.overall_label ?? "low")}`}>
              <div className="intel-confidence-orb-value">
                {summary ? `${Math.round(summary.confidence_summary.overall_score * 100)}%` : "--"}
              </div>
              <div className="intel-confidence-orb-label">summary confidence</div>
            </div>
            <div className="intel-hero-provenance">
              <span className="card-label">Source of truth</span>
              <span className="intel-hero-provenance-text">{summary ? formatProvenance(summary.graph_provenance) : "Waiting on summary"}</span>
              {confidenceReason && <p className="intel-hero-provenance-note">{confidenceReason}</p>}
            </div>
          </div>
        </div>

        {summaryLoading && (
          <div className="intel-loading-row">
            <LoaderCircle size={14} className="intel-spinner" />
            <span className="text-muted">Loading deterministic summary…</span>
          </div>
        )}

        {!summaryLoading && summaryError && (
          <div className="intel-empty-state">
            <p className="view-empty-title">Summary unavailable</p>
            <p className="view-empty-sub">{summaryError}</p>
          </div>
        )}

        {!summaryLoading && summary && degraded && (
          <div className="intel-warning-banner is-degraded">
            <AlertTriangle size={14} />
            <span>
              This overview is grounded but degraded. Confidence is {summary.confidence_summary.overall_label}, and the product is surfacing fallback-backed or sparse evidence rather than overstating certainty.
            </span>
          </div>
        )}

        {!summaryLoading && summary && !degraded && (
          <div className="intel-warning-banner is-grounded">
            <span>
              Grounded from current project artifacts with {summary.confidence_summary.overall_label} confidence and {formatProvenance(summary.graph_provenance)} provenance.
            </span>
          </div>
        )}
      </section>

      <section className="intel-metric-row">
        <div className="intel-metric-card surface-panel-muted">
          <span className="intel-metric-label">Routes mapped</span>
          <span className="intel-metric-value">{summary?.route_counts.total ?? 0}</span>
          <span className="intel-metric-sub">{routeMethodPairs.length > 0 ? routeMethodPairs.map(([method, count]) => `${method} ${count}`).join(" · ") : "No routed surface detected"}</span>
        </div>
        <div className="intel-metric-card surface-panel-muted">
          <span className="intel-metric-label">Components profiled</span>
          <span className="intel-metric-value">{totalComponents || scan.components.length}</span>
          <span className="intel-metric-sub">{scan.components.length} discovered by scan</span>
        </div>
        <div className="intel-metric-card surface-panel-muted">
          <span className="intel-metric-label">Critical nodes</span>
          <span className="intel-metric-value">{criticalNodes.length}</span>
          <span className="intel-metric-sub">{criticalNodes[0]?.label ?? "No critical nodes highlighted yet"}</span>
        </div>
        <div className="intel-metric-card surface-panel-muted">
          <span className="intel-metric-label">Deterministic insights</span>
          <span className="intel-metric-value">{insights?.insight_count ?? 0}</span>
          <span className="intel-metric-sub">{Object.entries(insightsBySeverity).filter(([, value]) => value > 0).map(([label, value]) => `${label} ${value}`).join(" · ") || "No insights emitted yet"}</span>
        </div>
      </section>

      <section className="intel-overview-layout">
        <div className="intel-primary-column">
          <div className="intel-section-card surface-panel">
            <div className="intel-section-head">
              <div>
                <div className="intel-section-kicker">System profile</div>
                <h3 className="intel-section-title">Stack, architecture, and coverage</h3>
              </div>
              {summary && <span className="chip chip-muted">{summaryStatusText(summary)}</span>}
            </div>

            <div className="intel-profile-grid">
              <div className="intel-profile-panel">
                <div className="card-label">Primary stack</div>
                <div className="chip-list intel-chip-list">
                  {summary?.primary_stack.length ? summary.primary_stack.map((item) => (
                    <span key={item} className="chip">{item}</span>
                  )) : <span className="text-muted">No stack confidently identified yet</span>}
                </div>
              </div>

              <div className="intel-profile-panel">
                <div className="card-label">Architecture hints</div>
                <div className="chip-list intel-chip-list">
                  {summary?.architecture_hints.length ? summary.architecture_hints.map((hint) => (
                    <span key={hint} className="chip chip-muted">{hint}</span>
                  )) : <span className="text-muted">No strong architecture hints yet</span>}
                </div>
              </div>

              <div className="intel-profile-panel">
                <div className="card-label">Component mix</div>
                <div className="intel-kv-list">
                  {summary ? Object.entries(summary.component_counts).map(([label, count]) => (
                    <div key={label} className="intel-kv-row">
                      <span>{prettifyLabel(label)}</span>
                      <span>{count}</span>
                    </div>
                  )) : <span className="text-muted">Component mix unavailable</span>}
                </div>
              </div>

              <div className="intel-profile-panel">
                <div className="card-label">Confidence and provenance</div>
                <div className="intel-kv-list">
                  <div className="intel-kv-row">
                    <span>Confidence</span>
                    <span>{summary?.confidence_summary.overall_label ?? "n/a"}</span>
                  </div>
                  <div className="intel-kv-row">
                    <span>Graph provenance</span>
                    <span>{summary ? prettifyLabel(summary.graph_provenance) : "n/a"}</span>
                  </div>
                  <div className="intel-kv-row">
                    <span>Canonical snapshot</span>
                    <span>{summary?.confidence_summary.canonical_snapshot_used ? "used" : "not used"}</span>
                  </div>
                  <div className="intel-kv-row">
                    <span>Simulation context</span>
                    <span>{summary?.confidence_summary.simulation_mode ?? "not used"}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="intel-dual-section">
            <div className="intel-section-card surface-panel">
              <div className="intel-section-head">
                <div>
                  <div className="intel-section-kicker">Critical surface</div>
                  <h3 className="intel-section-title">Critical nodes</h3>
                </div>
                <span className="chip chip-muted">{criticalNodes.length} highlighted</span>
              </div>

              <div className="intel-list intel-priority-list">
                {criticalNodes.length > 0 ? criticalNodes.map((node) => (
                  <div key={node.node_id} className="intel-priority-card tone-neutral">
                    <div className="intel-priority-topline">
                      <div>
                        <div className="intel-priority-title">{node.label}</div>
                        <div className="intel-priority-sub">{node.node_type} · score {node.criticality_score.toFixed(2)}</div>
                      </div>
                      <span className="chip chip-muted">critical node</span>
                    </div>
                    <p className="intel-list-detail">{node.reason}</p>
                  </div>
                )) : <span className="text-muted">No critical nodes identified yet</span>}
              </div>
            </div>

            <div className="intel-section-card surface-panel">
              <div className="intel-section-head">
                <div>
                  <div className="intel-section-kicker">Runtime signals</div>
                  <h3 className="intel-section-title">Dependency highlights</h3>
                </div>
                <span className="chip chip-muted">{runtimeHighlights.length} signals</span>
              </div>

              <div className="intel-list intel-priority-list">
                {runtimeHighlights.length > 0 ? runtimeHighlights.map((highlight, index) => (
                  <div key={`${highlight.category}-${index}`} className="intel-priority-card tone-neutral">
                    <div className="intel-priority-topline">
                      <div>
                        <div className="intel-priority-title">{highlight.label}</div>
                        <div className="intel-priority-sub">{prettifyLabel(highlight.category)} · {highlight.confidence} confidence</div>
                      </div>
                      <span className={`badge ${confidenceClass(highlight.confidence)}`}>{highlight.confidence}</span>
                    </div>
                    <p className="intel-list-detail">{highlight.detail}</p>
                  </div>
                )) : <span className="text-muted">No runtime dependency highlights surfaced yet</span>}
              </div>
            </div>
          </div>

          <div className="intel-dual-section">
            <div className="intel-section-card surface-panel">
              <div className="intel-section-head">
                <div>
                  <div className="intel-section-kicker">Findings</div>
                  <h3 className="intel-section-title">Top grounded findings</h3>
                </div>
                <span className="chip chip-muted">{findings.length} surfaced</span>
              </div>

              <div className="intel-list intel-priority-list">
                {findings.length > 0 ? findings.map((finding, index) => (
                  <div key={`${finding.category}-${index}`} className={`intel-priority-card tone-${severityTone(finding.severity)}`}>
                    <div className="intel-priority-topline">
                      <div className="intel-finding-meta">
                        <span className="chip chip-muted">{prettifyLabel(finding.category)}</span>
                        <span className={`badge ${confidenceClass(finding.confidence)}`}>{finding.confidence}</span>
                      </div>
                      <span className={`badge ${insightSeverityClass(finding.severity)}`}>{finding.severity}</span>
                    </div>
                    <p className="intel-list-detail">{finding.explanation}</p>
                  </div>
                )) : <span className="text-muted">No top findings yet</span>}
              </div>
            </div>

            <div className="intel-section-card surface-panel">
              <div className="intel-section-head">
                <div>
                  <div className="intel-section-kicker">Risks</div>
                  <h3 className="intel-section-title">Top risk highlights</h3>
                </div>
                <span className="chip chip-muted">{risks.length} surfaced</span>
              </div>

              <div className="intel-list intel-priority-list">
                {risks.length > 0 ? risks.map((risk, index) => (
                  <div key={`${risk.category}-${index}`} className={`intel-priority-card tone-${severityTone(risk.severity)}`}>
                    <div className="intel-priority-topline">
                      <div className="intel-finding-meta">
                        <span className="chip chip-muted">{prettifyLabel(risk.category)}</span>
                        <span className={`badge ${confidenceClass(risk.confidence)}`}>{risk.confidence}</span>
                      </div>
                      <span className={`badge ${insightSeverityClass(risk.severity)}`}>{risk.severity}</span>
                    </div>
                    <p className="intel-list-detail">{risk.explanation}</p>
                  </div>
                )) : <span className="text-muted">No top risks yet</span>}
              </div>
            </div>
          </div>

          <div className="intel-section-card surface-panel">
            <div className="intel-section-head">
              <div>
                <div className="intel-section-kicker">Deterministic insights</div>
                <h3 className="intel-section-title">Highlighted insight cards</h3>
              </div>
              {insights ? <span className="chip chip-muted">{insights.insight_count} total insights</span> : null}
            </div>

            {insightsLoading && (
              <div className="intel-loading-row">
                <LoaderCircle size={14} className="intel-spinner" />
                <span className="text-muted">Loading insights…</span>
              </div>
            )}

            {!insightsLoading && insightsError && (
              <div className="intel-empty-state">
                <p className="view-empty-title">Insights unavailable</p>
                <p className="view-empty-sub">{insightsError}</p>
              </div>
            )}

            {!insightsLoading && insights && insights.insights.length === 0 && (
              <div className="intel-empty-state">
                <p className="view-empty-title">No insights yet</p>
                <p className="view-empty-sub">The backend did not emit any deterministic insights for the current project state.</p>
              </div>
            )}

            {!insightsLoading && insights && insights.insights.length > 0 && (
              <div className="intel-insight-grid">
                {topInsights.map((insight) => (
                  <div key={insight.insight_id} className={`intel-insight-card tone-${severityTone(insight.severity)}`}>
                    <div className="intel-insight-top">
                      <div>
                        <div className="intel-finding-meta">
                          <span className={`badge ${insightSeverityClass(insight.severity)}`}>{insight.severity}</span>
                          <span className={`badge ${confidenceClass(insight.confidence.label)}`}>{insight.confidence.label}</span>
                          <span className="chip chip-muted">{prettifyLabel(insight.category)}</span>
                        </div>
                        <h3 className="intel-insight-title">{insight.title}</h3>
                      </div>
                      {isCodePeekAvailable(insight) && (
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={() => void handleOpenCodePeek(insight)}
                        >
                          <FileCode2 size={14} />
                          {activePeekInsightId === insight.insight_id ? "Hide code" : "View code"}
                        </button>
                      )}
                    </div>

                    <p className="intel-list-detail">{insight.explanation}</p>

                    {insight.tags.length > 0 && (
                      <div className="chip-list intel-chip-list">
                        {insight.tags.map((tag) => (
                          <span key={tag} className="chip chip-muted">{tag}</span>
                        ))}
                      </div>
                    )}

                    {activePeekInsightId === insight.insight_id && (
                      <div className="intel-codepeek-panel">
                        <div className="intel-codepeek-header">
                          <div>
                            <div className="card-label">Code Peek</div>
                            <div className="card-meta-text">
                              {codePeek ? `${codePeek.file_path}${codePeek.language ? ` · ${codePeek.language}` : ""}` : "Grounded source snippet for this insight"}
                            </div>
                          </div>
                        </div>

                        {codePeekLoading && (
                          <div className="intel-loading-row">
                            <LoaderCircle size={14} className="intel-spinner" />
                            <span className="text-muted">Resolving supporting code…</span>
                          </div>
                        )}

                        {!codePeekLoading && codePeekError && (
                          <div className="intel-empty-state intel-codepeek-empty">
                            <p className="view-empty-title">Code peek unavailable</p>
                            <p className="view-empty-sub">{codePeekError}</p>
                          </div>
                        )}

                        {!codePeekLoading && codePeek && (
                          <>
                            <div className="intel-codepeek-meta">
                              <span className="chip chip-muted">{prettifyLabel(codePeek.source_type)}</span>
                              {codePeek.confidence && (
                                <span className={`badge ${confidenceClass(codePeek.confidence.label)}`}>{codePeek.confidence.label}</span>
                              )}
                              {codePeek.generated_from.snippet_line_start && codePeek.generated_from.snippet_line_end && (
                                <span className="text-muted">
                                  lines {codePeek.generated_from.snippet_line_start}-{codePeek.generated_from.snippet_line_end}
                                </span>
                              )}
                            </div>
                            <pre className="intel-codepeek-snippet"><code>{codePeek.snippet_text}</code></pre>
                            <p className="intel-codepeek-reason">{codePeek.generated_from.selection_reason}</p>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <aside className="intel-secondary-column">
          <div className="intel-section-card surface-panel">
            <div className="intel-section-head">
              <div>
                <div className="intel-section-kicker">Repository signals</div>
                <h3 className="intel-section-title">Languages and frameworks</h3>
              </div>
            </div>

            <div className="intel-profile-panel">
              <div className="card-label">Languages</div>
              <div style={{ marginTop: 8 }}>
                {langCounts.length > 0 ? (
                  langCounts.map(({ lang, count }) => (
                    <div key={lang} className="lang-bar-row">
                      <span className="lang-bar-label">{lang}</span>
                      <div className="lang-bar-track">
                        <div
                          className="lang-bar-fill"
                          style={{
                            width: `${Math.max((count / maxLangCount) * 100, 8)}%`,
                          }}
                        />
                      </div>
                      <span className="lang-bar-count">{count}</span>
                    </div>
                  ))
                ) : (
                  <span className="text-muted">None detected</span>
                )}
              </div>
            </div>

            <div className="intel-profile-panel">
              <div className="card-label">Frameworks</div>
              <div className="chip-list intel-chip-list">
                {scan.frameworks.length > 0 ? (
                  scan.frameworks.map((framework) => (
                    <span key={framework} className="chip">{framework}</span>
                  ))
                ) : (
                  <span className="text-muted">None detected</span>
                )}
              </div>
            </div>
          </div>

          <div className="intel-section-card surface-panel">
            <div className="intel-section-head">
              <div>
                <div className="intel-section-kicker">File anchors</div>
                <h3 className="intel-section-title">Key files and entry points</h3>
              </div>
            </div>

            <div className="intel-profile-panel">
              <div className="card-label">Key files</div>
              <div className="mono-list">
                {scan.key_files.length > 0 ? (
                  scan.key_files.slice(0, 8).map((file) => (
                    <div key={file} className="mono-list-item">
                      <code>{shortenLabel(file)}</code>
                    </div>
                  ))
                ) : (
                  <span className="text-muted">None found</span>
                )}
              </div>
            </div>

            <div className="intel-profile-panel">
              <div className="card-label">Entry points</div>
              <div className="mono-list">
                {scan.entry_points.length > 0 ? (
                  scan.entry_points.slice(0, 8).map((entry) => (
                    <div key={entry} className="mono-list-item">
                      <code>{shortenLabel(entry)}</code>
                    </div>
                  ))
                ) : (
                  <span className="text-muted">None found</span>
                )}
              </div>
            </div>
          </div>
        </aside>
      </section>
    </div>
  );
}
