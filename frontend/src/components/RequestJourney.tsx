import { useState, useEffect, useCallback } from "react";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Code2,
  Cpu,
  Database,
  GitBranch,
  Globe,
  RefreshCw,
  Send,
  Shield,
} from "lucide-react";
import type { RouteItem, RouteAnalysis, RouteDetail, AnalysisParticipant, RequestFlow, RequestFlowStage } from "../types";
import type { SequenceData } from "../SequenceDiagram";
import SequenceDiagram from "../SequenceDiagram";
import ModeToggle from "./ModeToggle";
import PhaseCard from "./PhaseCard";
import ErrorPathsSection from "./ErrorPathsSection";
import InlineCodePeek, { type InlineCodePeekAnchor } from "./InlineCodePeek";
import {
  analyzeRoute,
  fetchRouteDetail,
  fetchRouteAnalysis,
  fetchRouteSequence,
  generateRouteSequence,
} from "../api/client";

const COMPLEXITY_COLORS: Record<string, string> = {
  simple: "#6b7280",
  moderate: "#eab308",
  complex: "#ef4444",
};

const STAGE_STYLES: Record<string, { icon: typeof ArrowRight; accent: string; label: string }> = {
  dispatch: { icon: GitBranch, accent: "#f97316", label: "Dispatch" },
  middleware: { icon: ArrowRight, accent: "#94a3b8", label: "Middleware" },
  auth: { icon: Shield, accent: "#0ea5e9", label: "Auth" },
  validation: { icon: CheckCircle2, accent: "#f59e0b", label: "Validation" },
  handler: { icon: Code2, accent: "#f8fafc", label: "Handler" },
  service: { icon: Cpu, accent: "#8b5cf6", label: "Service" },
  repository: { icon: Database, accent: "#a855f7", label: "Repository" },
  data_access: { icon: Database, accent: "#a855f7", label: "Data Access" },
  external: { icon: Globe, accent: "#22c55e", label: "External" },
  response: { icon: Send, accent: "#14b8a6", label: "Response" },
};

/* ── Route description from method + path ── */

function describeRoute(method: string, path: string): string {
  const segments = path
    .split("/")
    .filter(Boolean)
    .filter((s) => !s.startsWith("{") && !s.startsWith(":") && !s.startsWith("<"));

  const lastSeg = segments[segments.length - 1] || "resource";
  const noun = lastSeg.replace(/[-_]/g, " ");

  const endsWithParam =
    path.endsWith("}") || /\/:[^/]+$/.test(path) || /<[^>]+>\/?$/.test(path);

  const m = method.toUpperCase();
  if (m === "GET" && endsWithParam) return `Fetches a single ${noun} by ID`;
  if (m === "GET") return `Fetches a list of ${noun}`;
  if (m === "POST") return `Creates or generates ${noun}`;
  if (m === "PUT" || m === "PATCH") return `Updates a ${noun}`;
  if (m === "DELETE") return `Deletes a ${noun} and related data`;
  return `Handles ${noun} request`;
}

function humanizePhaseName(phaseId: string, fallbackName: string): string {
  if (fallbackName?.trim()) {
    return fallbackName;
  }
  return phaseId
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function phaseLabel(analysis: RouteAnalysis, phaseId: string): string {
  const phase = analysis.phases.find((item) => item.phase_id === phaseId);
  return humanizePhaseName(phaseId, phase?.name ?? phaseId);
}

function summarizeParticipants(participants: AnalysisParticipant[]): string {
  if (participants.length === 0) {
    return "Handler only";
  }
  const labels = participants.map((participant) => participant.label || participant.id);
  if (labels.length <= 3) {
    return labels.join(" -> ");
  }
  return `${labels.slice(0, 3).join(" -> ")} +${labels.length - 3}`;
}

function formatAnchor(detail: RouteDetail | null, route: RouteItem): string {
  const anchor = detail?.best_target;
  if (!anchor?.file_path) {
    return route.file;
  }
  const line = anchor.line_start ? `:${anchor.line_start}` : "";
  const symbol = anchor.symbol_name ? ` • ${anchor.symbol_name}` : "";
  return `${anchor.file_path}${line}${symbol}`;
}

function formatConfidence(value: number | null | undefined): string {
  if (typeof value !== "number") {
    return "n/a";
  }
  return value.toFixed(2);
}

function formatOwner(detail: RouteDetail | null, analysis: RouteAnalysis | null, route: RouteItem): string {
  const controller = detail?.controller_name ?? route.controller_name;
  const handler = detail?.handler_function ?? analysis?.handler_function ?? route.handler_function;
  if (controller && handler) {
    return `${controller}.${handler}`;
  }
  if (handler) {
    return handler;
  }
  return "unknown";
}

function formatStageAnchor(stage: RequestFlowStage): string | null {
  const filePath = stage.file_path || stage.code_anchor?.file_path || stage.evidence?.file_path;
  if (!filePath) {
    return null;
  }
  const line = stage.line_start ?? stage.code_anchor?.line_start ?? stage.evidence?.line_start;
  const className = stage.class_name || stage.code_anchor?.class_name || stage.evidence?.class_name;
  const symbolName = stage.symbol_name || stage.code_anchor?.symbol_name || stage.evidence?.symbol_name;
  const owner = className && symbolName ? `${className}.${symbolName}` : className || symbolName;
  const lineLabel = line ? `:${line}` : "";
  return owner ? `${filePath}${lineLabel} • ${owner}` : `${filePath}${lineLabel}`;
}

function summarizeRequestFlow(flow: RequestFlow | null): string | null {
  if (!flow || flow.stages.length === 0) {
    return null;
  }
  const stageTypes = Array.from(new Set(flow.stages.map((stage) => stage.stage_type)));
  const important = stageTypes.filter((stageType) => !["dispatch", "response"].includes(stageType));
  if (important.length === 0) {
    return "This route is grounded to its entrypoint and response, with no additional internal steps confidently identified.";
  }
  const labels = important.slice(0, 4).map((stageType) => STAGE_STYLES[stageType]?.label.toLowerCase() ?? stageType.replace(/_/g, " "));
  return `This route moves through ${labels.join(", ")} before returning a response. Only grounded steps are shown.`;
}

function sourceLabel(detail: RouteDetail | null, flow: RequestFlow | null, hasFallbackFlow: boolean): string {
  if (flow && !hasFallbackFlow) {
    return detail?.analysis_source === "derived_from_request_flow"
      ? "Deterministic flow"
      : "Direct request flow";
  }
  if (hasFallbackFlow) {
    return "Compatibility fallback";
  }
  return "Compatibility analysis";
}

function flowStatusMessage(flow: RequestFlow | null, hasFallbackFlow: boolean): { tone: "fallback" | "caution" | "info"; text: string } | null {
  if (!flow) {
    return {
      tone: "fallback",
      text: "Detailed request flow is unavailable for this route, so the panel is using compatibility analysis only.",
    };
  }
  if (hasFallbackFlow) {
    return {
      tone: "fallback",
      text: "Showing compatibility-derived request flow because the direct route detail flow is unavailable.",
    };
  }
  const lowConfidence = typeof flow.confidence === "number" && flow.confidence < 0.75;
  const inferredSteps = flow.stages.some((stage) => stage.is_inferred);
  if (lowConfidence || inferredSteps) {
    return {
      tone: "caution",
      text: "Some steps are inferred or lower-confidence. Missing internal stages are intentionally omitted rather than guessed.",
    };
  }
  return {
    tone: "info",
    text: "Request flow is grounded directly from deterministic backend evidence.",
  };
}

function stageTone(stage: RequestFlowStage): string {
  if (stage.stage_type === "external") return "external";
  if (stage.stage_type === "repository" || stage.stage_type === "data_access") return "data";
  if (stage.stage_type === "auth" || stage.stage_type === "validation") return "guard";
  if (stage.is_inferred) return "inferred";
  return "default";
}

function requestFlowStageAnchor(stage: RequestFlowStage): InlineCodePeekAnchor | null {
  const primary = stage.code_anchor ?? stage.evidence ?? null;
  return {
    file_path: stage.file_path ?? primary?.file_path ?? null,
    symbol_name: stage.symbol_name ?? primary?.symbol_name ?? null,
    class_name: stage.class_name ?? primary?.class_name ?? null,
    line_start: stage.line_start ?? primary?.line_start ?? null,
    line_end: stage.line_end ?? primary?.line_end ?? null,
    selection_reason: stage.selection_reason ?? primary?.selection_reason ?? null,
  };
}

function RequestFlowStageCard({ stage, index, projectId }: { stage: RequestFlowStage; index: number; projectId: string }) {
  const stageStyle = STAGE_STYLES[stage.stage_type] ?? { icon: ArrowRight, accent: "#6b7280", label: stage.stage_type.replace(/_/g, " ") };
  const StageIcon = stageStyle.icon;
  const anchor = formatStageAnchor(stage);
  const codePeekAnchor = requestFlowStageAnchor(stage);
  const hints = stage.hints?.filter(Boolean) ?? [];
  const showReason = Boolean(stage.selection_reason) && (stage.is_inferred || (stage.confidence ?? 1) < 0.75);

  return (
    <article className={`rj-stage-card rj-stage-tone-${stageTone(stage)}`}>
      <div className="rj-stage-rail">
        <span className="rj-stage-number">{index + 1}</span>
        <span className="rj-stage-icon" style={{ color: stageStyle.accent, borderColor: `${stageStyle.accent}33` }}>
          <StageIcon size={14} />
        </span>
      </div>

      <div className="rj-stage-content">
        <div className="rj-stage-topline">
          <div className="rj-stage-badges">
            <span className="rj-stage-kind" style={{ color: stageStyle.accent }}>{stageStyle.label}</span>
            <span className={`rj-stage-grounding ${stage.is_inferred ? "is-inferred" : "is-direct"}`}>
              {stage.is_inferred ? "Inferred" : "Direct"}
            </span>
            <span className="rj-stage-confidence">{formatConfidence(stage.confidence)}</span>
          </div>
        </div>

        <h3 className="rj-stage-title">{stage.label}</h3>

        {anchor && <p className="rj-stage-anchor">{anchor}</p>}

        {hints.length > 0 && (
          <div className="rj-stage-hints">
            {hints.slice(0, 4).map((hint) => (
              <span key={`${stage.step}:${hint}`} className="rj-stage-hint-chip">
                {hint}
              </span>
            ))}
          </div>
        )}

        {showReason && <p className="rj-stage-reason">{stage.selection_reason}</p>}

        <InlineCodePeek
          projectId={projectId}
          anchor={codePeekAnchor}
          isInferred={Boolean(stage.is_inferred)}
          confidence={stage.confidence}
          sourceLabel={stageStyle.label}
          unavailableReason={stage.is_inferred
            ? "This inferred step has no grounded file anchor for Code Peek."
            : "No grounded file anchor was detected for this step."}
        />
      </div>
    </article>
  );
}

function isSequenceCompatible(seq: SequenceData | null, analysis: RouteAnalysis | null): boolean {
  if (!seq) {
    return false;
  }
  const analysisSignature = analysis?.analysis_signature;
  if (!analysisSignature) {
    return true;
  }
  return seq.metadata.analysis_signature === analysisSignature;
}

function buildDisplayPhases(analysis: RouteAnalysis) {
  const merged: RouteAnalysis["phases"] = [];

  for (const phase of analysis.phases) {
    const previous = merged[merged.length - 1];
    if (previous && previous.phase_id === phase.phase_id) {
      previous.steps = [...previous.steps, ...phase.steps];
      if (!previous.description && phase.description) {
        previous.description = phase.description;
      }
      continue;
    }

    merged.push({
      ...phase,
      name: humanizePhaseName(phase.phase_id, phase.name),
      description: phase.description || "",
      steps: [...phase.steps],
    });
  }

  return merged;
}

function buildAnalysisTags(analysis: RouteAnalysis) {
  const tags: { className: string; label: string }[] = [];
  if (analysis.has_database) {
    tags.push({ className: "rj-tag-db", label: "Database" });
  }
  if (analysis.has_filesystem) {
    tags.push({ className: "rj-tag-fs", label: "Filesystem" });
  }
  if (analysis.has_external) {
    tags.push({ className: "rj-tag-ext", label: "External Calls" });
  }
  return tags;
}

type Props = {
  route: RouteItem;
  projectId: string;
  seqData: SequenceData | null;
  onSequenceGenerated: (routeId: string, data: SequenceData) => void;
};

export default function RequestJourney({
  route,
  projectId,
  seqData,
  onSequenceGenerated,
}: Props) {
  const [mode, setMode] = useState<"story" | "technical">("story");
  const [routeDetail, setRouteDetail] = useState<RouteDetail | null>(null);
  const [analysis, setAnalysis] = useState<RouteAnalysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisCache, setAnalysisCache] = useState<Record<string, RouteAnalysis>>({});
  const [detailCache, setDetailCache] = useState<Record<string, RouteDetail>>({});

  // Sequence diagram state (for technical mode)
  const [localSeq, setLocalSeq] = useState<SequenceData | null>(null);
  const [seqChecked, setSeqChecked] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [seqError, setSeqError] = useState<string | null>(null);

  const methodColor = ({
    GET: "#22c55e", POST: "#3b82f6", PUT: "#eab308",
    DELETE: "#ef4444", PATCH: "#a855f7",
  } as Record<string, string>)[route.method] || "#6b6b6b";

  /* ── Fetch analysis (story mode) ── */

  const fetchAnalysis = useCallback(async () => {
    if (detailCache[route.id]) {
      const cachedDetail = detailCache[route.id];
      setRouteDetail(cachedDetail);
      setAnalysis(cachedDetail.route_analysis ?? analysisCache[route.id] ?? null);
      return;
    }

    if (analysisCache[route.id]) {
      setAnalysis(analysisCache[route.id]);
    }

    setAnalysisLoading(true);
    setAnalysisError(null);
    setAnalysis(null);
    setRouteDetail(null);

    try {
      try {
        const detail = await fetchRouteDetail(projectId, route.id);
        setRouteDetail(detail);
        setDetailCache((prev) => ({ ...prev, [route.id]: detail }));
        if (detail.route_analysis) {
          setAnalysis(detail.route_analysis);
          setAnalysisCache((prev) => ({ ...prev, [route.id]: detail.route_analysis as RouteAnalysis }));
          return;
        }
      } catch {
        // Fall through to legacy route-analysis endpoints below.
      }

      try {
        const a = await fetchRouteAnalysis(projectId, route.id);
        setAnalysis(a);
        setAnalysisCache((prev) => ({ ...prev, [route.id]: a }));
        return;
      } catch {
        // Fall through to on-demand analysis below.
      }

      const a = await analyzeRoute(projectId, {
        method: route.method,
        path: route.path,
        file: route.file,
        component: route.component,
      });
      setAnalysis(a);
      setAnalysisCache((prev) => ({ ...prev, [route.id]: a }));
    } catch {
      setAnalysisError("Could not analyze this route");
    } finally {
      setAnalysisLoading(false);
    }
  }, [route.id, route.method, route.path, route.file, route.component, projectId, analysisCache, detailCache]);

  useEffect(() => {
    fetchAnalysis();
  }, [fetchAnalysis]);

  /* ── Fetch sequence diagram (technical mode) ── */

  useEffect(() => {
    setLocalSeq(null);
    setSeqError(null);
    setSeqChecked(false);

    if (seqData) {
      setLocalSeq(seqData);
      setSeqChecked(true);
      return;
    }

    if (!route.has_sequence) {
      setSeqChecked(true);
      return;
    }

    fetchRouteSequence(projectId, route.id)
      .then((d) => d ?? null)
      .then((d) => {
        if (d) {
          setLocalSeq(d as SequenceData);
          onSequenceGenerated(route.id, d as SequenceData);
        }
      })
      .catch(() => {})
      .finally(() => setSeqChecked(true));
  }, [route.id, route.has_sequence, seqData, projectId, onSequenceGenerated]);

  const handleGenerateSeq = () => {
    setGenerating(true);
    setSeqError(null);

    generateRouteSequence(projectId, {
      method: route.method,
      path: route.path,
      file: route.file,
      component: route.component,
    })
      .then((d: SequenceData) => {
        setLocalSeq(d);
        onSequenceGenerated(route.id, d);
      })
      .catch((e) => setSeqError(e.message))
      .finally(() => setGenerating(false));
  };

  const displayPhases = analysis ? buildDisplayPhases(analysis) : [];
  const analysisTags = analysis ? buildAnalysisTags(analysis) : [];
  const sequenceCandidate = localSeq || seqData;
  const sequenceIsCompatible = isSequenceCompatible(sequenceCandidate, analysis);
  const sequenceIsStale = Boolean(sequenceCandidate) && Boolean(analysis) && !sequenceIsCompatible;
  const visibleSeq = sequenceIsCompatible ? sequenceCandidate : null;
  const directRequestFlow = routeDetail?.request_flow ?? null;
  const fallbackRequestFlow = !directRequestFlow ? analysis?.request_flow ?? null : null;
  const activeRequestFlow = directRequestFlow ?? fallbackRequestFlow;
  const hasFallbackFlow = Boolean(!directRequestFlow && fallbackRequestFlow?.stages.length);
  const hasRequestFlow = Boolean(activeRequestFlow?.stages.length);
  const flowSource = sourceLabel(routeDetail, activeRequestFlow, hasFallbackFlow);
  const flowStatus = flowStatusMessage(activeRequestFlow, hasFallbackFlow);
  const routeOwner = formatOwner(routeDetail, analysis, route);
  const routeSummary = summarizeRequestFlow(activeRequestFlow) ?? describeRoute(route.method, route.path);
  const flowStageCount = routeDetail?.request_flow?.stage_count ?? route.request_flow_summary?.stage_count ?? displayPhases.length;
  const flowConfidence = routeDetail?.request_flow?.confidence ?? route.request_flow_summary?.confidence ?? null;
  const activeFile = routeDetail?.file || route.file;
  const activeComponent = routeDetail?.component || route.component;

  /* ── Render ── */

  return (
    <div className="request-journey">
      {/* Header card */}
      <div className="rj-header-card">
        <div className="rj-header-top">
          <div className="rj-route-info">
            <span className="api-detail-method" style={{ background: methodColor }}>
              {route.method}
            </span>
            <span className="api-detail-path">{route.path}</span>
          </div>
          <ModeToggle mode={mode} onChange={setMode} />
        </div>

        <div className="api-detail-divider" />

        <div className="api-detail-grid">
          <div className="api-detail-row">
            <span className="api-detail-label">SOURCE</span>
            <span className="api-detail-value">{flowSource}</span>
          </div>
          <div className="api-detail-row">
            <span className="api-detail-label">OWNER</span>
            <span className="api-detail-value api-detail-mono">{routeOwner}</span>
          </div>
          <div className="api-detail-row">
            <span className="api-detail-label">COMPONENT</span>
            <span className="api-detail-value">{activeComponent || "unknown"}</span>
          </div>
          <div className="api-detail-row">
            <span className="api-detail-label">FILE</span>
            <span className="api-detail-value api-detail-mono">{activeFile}</span>
          </div>
          <div className="api-detail-row">
            <span className="api-detail-label">FLOW STAGES</span>
            <span className="api-detail-value">{flowStageCount || 0}</span>
          </div>
          <div className="api-detail-row">
            <span className="api-detail-label">CODE ANCHOR</span>
            <span className="api-detail-value api-detail-mono">{formatAnchor(routeDetail, route)}</span>
          </div>
          {mode === "technical" && analysis && (
            <div className="api-detail-row">
              <span className="api-detail-label">COMPLEXITY</span>
              <span
                className="complexity-badge"
                style={{ color: COMPLEXITY_COLORS[analysis.complexity] }}
              >
                {analysis.complexity}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ── Story Mode ── */}
      {mode === "story" && (
        <div className="rj-story">
          {analysisLoading && (
            <div className="rj-skeleton">
              <div className="rj-skeleton-card" />
              <div className="rj-skeleton-card" />
              <div className="rj-skeleton-card" />
            </div>
          )}

          {analysisError && (
            <div className="rj-error">
              <AlertCircle size={32} />
              <p>{analysisError}</p>
              <button className="btn btn-secondary btn-sm" onClick={fetchAnalysis}>
                <RefreshCw size={14} /> Retry
              </button>
            </div>
          )}

          {(routeDetail || analysis) && !analysisLoading && (
            <>
              <p className="rj-route-description">{routeSummary}</p>

              {flowStatus && (
                <div className={`rj-flow-banner rj-flow-banner-${flowStatus.tone}`}>
                  <AlertCircle size={14} />
                  <span>{flowStatus.text}</span>
                </div>
              )}

              <div className="rj-analysis-overview">
                <div className="rj-overview-card">
                  <span className="rj-overview-label">STAGES</span>
                  <span className="rj-overview-value">{flowStageCount || 0}</span>
                </div>
                <div className="rj-overview-card">
                  <span className="rj-overview-label">FLOW CONFIDENCE</span>
                  <span className="rj-overview-value">{flowConfidence ?? "n/a"}</span>
                </div>
                <div className="rj-overview-card">
                  <span className="rj-overview-label">FLOW SOURCE</span>
                  <span className="rj-overview-value">{flowSource}</span>
                </div>
                <div className="rj-overview-card">
                  <span className="rj-overview-label">PARTICIPANTS</span>
                  <span className="rj-overview-value">{analysis ? summarizeParticipants(analysis.participants) : routeOwner}</span>
                </div>
              </div>

              {hasRequestFlow && activeRequestFlow ? (
                <div className="rj-journey-shell">
                  <div className="rj-phases">
                    <span className="rj-phases-label">REQUEST FLOW</span>
                    <div className="rj-stage-list">
                      {activeRequestFlow.stages.map((stage, index) => (
                        <RequestFlowStageCard
                          key={`${stage.step ?? index}:${stage.stage_type}:${stage.label}`}
                          stage={stage}
                          index={index}
                          projectId={projectId}
                        />
                      ))}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="rj-phases">
                  <span className="rj-phases-label">COMPATIBILITY JOURNEY</span>
                  {displayPhases.length > 0 ? (
                    displayPhases.map((phase, i) => (
                      <PhaseCard
                        key={`${phase.phase_id}-${i}`}
                        phase={{ ...phase, name: analysis ? phaseLabel(analysis, phase.phase_id) : humanizePhaseName(phase.phase_id, phase.name) }}
                        index={i}
                        mode="story"
                      />
                    ))
                  ) : (
                    <p className="text-muted" style={{ fontSize: 13 }}>
                      No phases detected — handler may be too simple to decompose.
                    </p>
                  )}
                </div>
              )}

              {analysis && analysis.parameters.length > 0 && (
                <div className="params-section">
                  <span className="params-label">Parameters</span>
                  <div className="params-list">
                    {analysis.parameters.map((parameter) => (
                      <div key={`${parameter.name}:${parameter.source}`} className="params-item">
                        <span className="params-name">{parameter.name}</span>
                        <span className="params-type">{parameter.type || "unknown"}</span>
                        <span className="params-source">{parameter.source}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {analysisTags.length > 0 && (
                <div className="rj-tags">
                  {analysisTags.map((tag) => (
                    <span key={tag.label} className={`rj-tag ${tag.className}`}>
                      {tag.label}
                    </span>
                  ))}
                </div>
              )}

              {/* Error paths */}
              {analysis && analysis.error_paths.length > 0 && (
                <ErrorPathsSection errorPaths={analysis.error_paths} />
              )}
            </>
          )}
        </div>
      )}

      {/* ── Sequence Mode ── */}
      {mode === "technical" && (
        <div className="rj-technical">
          {sequenceIsStale && (
            <div className="rj-seq-stale">
              <p>Stored sequence is out of sync with the latest route analysis.</p>
              <button
                className="btn btn-secondary btn-sm"
                disabled={generating}
                onClick={handleGenerateSeq}
              >
                {generating ? "Regenerating…" : "Regenerate Sequence Diagram"}
              </button>
            </div>
          )}
          {!visibleSeq && seqChecked && !sequenceIsStale && (
            <div className="rj-tech-empty">
              <button
                className="btn btn-secondary btn-sm"
                disabled={generating}
                onClick={handleGenerateSeq}
              >
                {generating ? "Generating…" : "Generate Sequence Diagram"}
              </button>
            </div>
          )}
          {!seqChecked && (
            <div className="rj-skeleton">
              <div className="rj-skeleton-card" />
            </div>
          )}
          {seqError && (
            <p style={{ color: "#ef4444", fontSize: 12, marginTop: 6 }}>{seqError}</p>
          )}
          {visibleSeq && (
            <div className="api-seq-inline">
              <SequenceDiagram
                data={visibleSeq}
                actions={(
                  <button
                    className="btn btn-secondary btn-sm"
                    disabled={generating}
                    onClick={handleGenerateSeq}
                  >
                    {generating ? "Regenerating…" : "Regenerate"}
                  </button>
                )}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
