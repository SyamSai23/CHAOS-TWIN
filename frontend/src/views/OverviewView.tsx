import { useEffect, useState } from "react";

import { AlertTriangle, FileCode2, LoaderCircle } from "lucide-react";

import { getCodePeek, getProjectInsights, getProjectSummary } from "../api/client";
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
      <div className="view-empty">
        <p className="view-empty-title">No scan data yet</p>
        <p className="view-empty-sub">
          Upload a ZIP and run a scan from the sidebar to see the overview.
        </p>
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

  return (
    <div>
      <h1 className="view-title">{project.name}</h1>

      <div className="overview-grid">
        {/* Scan Status */}
        <div className="card">
          <div className="card-label">Scan Status</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
            <span
              className={`badge ${scan.status === "completed" ? "badge-success" : "badge-pending"}`}
            >
              {scan.status}
            </span>
          </div>
          <div className="card-meta-text">
            {new Date(scan.created_at).toLocaleString()}
          </div>
          <div className="card-meta-text">
            {scan.file_count} files &middot; {scan.project_type}
          </div>
        </div>

        {/* Languages */}
        <div className="card">
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

        {/* Components */}
        <div className="card">
          <div className="card-label">Components</div>
          <div className="card-big-number">{scan.components.length}</div>
          <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
            {scan.components.map((c) => (
              <div key={c.root_path} className="mini-row">
                <span className="text-primary">{c.name}</span>
                <span className="text-muted" style={{ fontSize: 12 }}>
                  {c.type}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Tech Stack */}
        <div className="card">
          <div className="card-label">Tech Stack</div>
          <div className="chip-list" style={{ marginTop: 8 }}>
            {scan.frameworks.length > 0 ? (
              scan.frameworks.map((f) => (
                <span key={f} className="chip">
                  {f}
                </span>
              ))
            ) : (
              <span className="text-muted">None detected</span>
            )}
          </div>
        </div>
      </div>

      {/* Key Files + Entry Points */}
      <div className="overview-two-col">
        <div className="card">
          <div className="card-label">Key Files</div>
          <div className="mono-list">
            {scan.key_files.length > 0 ? (
              scan.key_files.slice(0, 8).map((f) => (
                <div key={f} className="mono-list-item">
                  <code>{shortenLabel(f)}</code>
                </div>
              ))
            ) : (
              <span className="text-muted">None found</span>
            )}
            {scan.key_files.length > 8 && (
              <span className="text-muted">
                +{scan.key_files.length - 8} more
              </span>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-label">Entry Points</div>
          <div className="mono-list">
            {scan.entry_points.length > 0 ? (
              scan.entry_points.slice(0, 8).map((e) => (
                <div key={e} className="mono-list-item">
                  <code>{shortenLabel(e)}</code>
                </div>
              ))
            ) : (
              <span className="text-muted">None found</span>
            )}
            {scan.entry_points.length > 8 && (
              <span className="text-muted">
                +{scan.entry_points.length - 8} more
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="intel-section">
        <div className="card intel-summary-card">
          <div className="intel-header-row">
            <div>
              <div className="card-label">System Intelligence Summary</div>
              <div className="card-meta-text">{summaryStatusText(summary)}</div>
            </div>
            {summary && (
              <span className={`badge ${confidenceClass(summary.confidence_summary.overall_label)}`}>
                {summary.confidence_summary.overall_label} confidence
              </span>
            )}
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

          {!summaryLoading && summary && (
            <>
              {summary.confidence_summary.overall_label === "low" && (
                <div className="intel-warning-banner">
                  <AlertTriangle size={14} />
                  <span>
                    This summary is grounded but low-confidence. The backend is signaling degraded coverage or fallback analysis.
                  </span>
                </div>
              )}

              <p className="intel-overview-text">{summary.overview_text}</p>

              <div className="intel-metadata-grid">
                <div className="intel-stat-card">
                  <span className="intel-stat-label">System Type</span>
                  <span className="intel-stat-value">{summary.system_type_guess}</span>
                </div>
                <div className="intel-stat-card">
                  <span className="intel-stat-label">Primary Stack</span>
                  <span className="intel-stat-value">{summary.primary_stack.length > 0 ? summary.primary_stack.join(", ") : "Not enough evidence"}</span>
                </div>
                <div className="intel-stat-card">
                  <span className="intel-stat-label">Routes</span>
                  <span className="intel-stat-value">{summary.route_counts.total}</span>
                </div>
                <div className="intel-stat-card">
                  <span className="intel-stat-label">Graph Provenance</span>
                  <span className="intel-stat-value">{prettifyLabel(summary.graph_provenance)}</span>
                </div>
              </div>

              <div className="intel-two-col">
                <div className="intel-block">
                  <div className="card-label">Architecture Hints</div>
                  <div className="chip-list intel-chip-list">
                    {summary.architecture_hints.length > 0 ? (
                      summary.architecture_hints.map((hint) => (
                        <span key={hint} className="chip">{hint}</span>
                      ))
                    ) : (
                      <span className="text-muted">No strong architecture hints yet</span>
                    )}
                  </div>
                </div>

                <div className="intel-block">
                  <div className="card-label">Route Methods</div>
                  <div className="intel-kv-list">
                    {Object.entries(summary.route_counts.by_method).length > 0 ? (
                      Object.entries(summary.route_counts.by_method).map(([method, count]) => (
                        <div key={method} className="intel-kv-row">
                          <span>{method}</span>
                          <span>{count}</span>
                        </div>
                      ))
                    ) : (
                      <span className="text-muted">No routed surface detected</span>
                    )}
                  </div>
                </div>
              </div>

              <div className="intel-two-col">
                <div className="intel-block">
                  <div className="card-label">Component Counts</div>
                  <div className="intel-kv-list">
                    {Object.entries(summary.component_counts).map(([label, count]) => (
                      <div key={label} className="intel-kv-row">
                        <span>{prettifyLabel(label)}</span>
                        <span>{count}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="intel-block">
                  <div className="card-label">Critical Nodes</div>
                  <div className="intel-list">
                    {summary.critical_nodes.length > 0 ? (
                      summary.critical_nodes.map((node) => (
                        <div key={node.node_id} className="intel-list-item">
                          <div className="intel-list-main">
                            <span className="text-primary">{node.label}</span>
                            <span className="text-muted">{node.node_type} · score {node.criticality_score.toFixed(2)}</span>
                          </div>
                          <p className="intel-list-detail">{node.reason}</p>
                        </div>
                      ))
                    ) : (
                      <span className="text-muted">No critical nodes identified yet</span>
                    )}
                  </div>
                </div>
              </div>

              <div className="intel-two-col">
                <div className="intel-block">
                  <div className="card-label">Top Findings</div>
                  <div className="intel-list">
                    {summary.top_findings.length > 0 ? (
                      summary.top_findings.map((finding, index) => (
                        <div key={`${finding.category}-${index}`} className="intel-list-item">
                          <div className="intel-finding-meta">
                            <span className="chip chip-muted">{prettifyLabel(finding.category)}</span>
                            <span className={`badge ${confidenceClass(finding.confidence)}`}>{finding.confidence}</span>
                          </div>
                          <p className="intel-list-detail">{finding.explanation}</p>
                        </div>
                      ))
                    ) : (
                      <span className="text-muted">No findings yet</span>
                    )}
                  </div>
                </div>

                <div className="intel-block">
                  <div className="card-label">Top Risks</div>
                  <div className="intel-list">
                    {summary.top_risks.length > 0 ? (
                      summary.top_risks.map((risk, index) => (
                        <div key={`${risk.category}-${index}`} className="intel-list-item">
                          <div className="intel-finding-meta">
                            <span className={`badge ${insightSeverityClass(risk.severity)}`}>{risk.severity}</span>
                            <span className={`badge ${confidenceClass(risk.confidence)}`}>{risk.confidence}</span>
                          </div>
                          <p className="intel-list-detail">{risk.explanation}</p>
                        </div>
                      ))
                    ) : (
                      <span className="text-muted">No risks surfaced yet</span>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="intel-section">
        <div className="card intel-summary-card">
          <div className="intel-header-row">
            <div>
              <div className="card-label">Deterministic Insights</div>
              <div className="card-meta-text">
                {insights ? `${insights.insight_count} insights · ${prettifyLabel(insights.graph_provenance)}` : "Risk and diagnostic signals from current artifacts"}
              </div>
            </div>
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
            <div className="intel-insight-list">
              {insights.insights.map((insight) => (
                <div key={insight.insight_id} className="intel-insight-card">
                  <div className="intel-insight-top">
                    <div>
                      <h3 className="intel-insight-title">{insight.title}</h3>
                      <div className="intel-finding-meta">
                        <span className={`badge ${insightSeverityClass(insight.severity)}`}>{insight.severity}</span>
                        <span className={`badge ${confidenceClass(insight.confidence.label)}`}>{insight.confidence.label}</span>
                        <span className="chip chip-muted">{prettifyLabel(insight.category)}</span>
                      </div>
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
    </div>
  );
}
