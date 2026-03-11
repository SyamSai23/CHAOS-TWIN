import { useState, useEffect, useCallback } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import type { RouteItem, RouteAnalysis } from "../types";
import type { SequenceData } from "../SequenceDiagram";
import SequenceDiagram from "../SequenceDiagram";
import ModeToggle from "./ModeToggle";
import PhaseCard from "./PhaseCard";
import ErrorPathsSection from "./ErrorPathsSection";
import {
  analyzeRoute,
  fetchRouteAnalysis,
  fetchRouteSequence,
  generateRouteSequence,
} from "../api/client";

const COMPLEXITY_COLORS: Record<string, string> = {
  simple: "#6b7280",
  moderate: "#eab308",
  complex: "#ef4444",
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

function summarizeParticipants(participants: string[]): string {
  if (participants.length === 0) {
    return "Handler only";
  }
  if (participants.length <= 3) {
    return participants.join(" -> ");
  }
  return `${participants.slice(0, 3).join(" -> ")} +${participants.length - 3}`;
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
  const [analysis, setAnalysis] = useState<RouteAnalysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisCache, setAnalysisCache] = useState<Record<string, RouteAnalysis>>({});

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
    // Check cache first
    if (analysisCache[route.id]) {
      setAnalysis(analysisCache[route.id]);
      return;
    }

    setAnalysisLoading(true);
    setAnalysisError(null);
    setAnalysis(null);

    try {
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
  }, [route.id, route.method, route.path, route.file, route.component, projectId, analysisCache]);

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
            <span className="api-detail-label">COMPONENT</span>
            <span className="api-detail-value">{route.component || "unknown"}</span>
          </div>
          <div className="api-detail-row">
            <span className="api-detail-label">FILE</span>
            <span className="api-detail-value api-detail-mono">{route.file}</span>
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

          {analysis && !analysisLoading && (
            <>
              {/* Route description */}
              <p className="rj-route-description">
                {describeRoute(route.method, route.path)}
              </p>

              <div className="rj-analysis-overview">
                <div className="rj-overview-card">
                  <span className="rj-overview-label">PHASES</span>
                  <span className="rj-overview-value">{displayPhases.length}</span>
                </div>
                <div className="rj-overview-card">
                  <span className="rj-overview-label">PARTICIPANTS</span>
                  <span className="rj-overview-value">{summarizeParticipants(analysis.participants)}</span>
                </div>
                <div className="rj-overview-card">
                  <span className="rj-overview-label">COMPLEXITY</span>
                  <span
                    className="complexity-badge"
                    style={{ color: COMPLEXITY_COLORS[analysis.complexity] }}
                  >
                    {analysis.complexity}
                  </span>
                </div>
              </div>

              {analysis.parameters.length > 0 && (
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

              {/* Phases — preserve analyzer order, merge only adjacent duplicates */}
              <div className="rj-phases">
                <span className="rj-phases-label">REQUEST JOURNEY</span>
                {displayPhases.length > 0 ? (
                  displayPhases.map((phase, i) => (
                    <PhaseCard
                      key={`${phase.phase_id}-${i}`}
                      phase={{ ...phase, name: phaseLabel(analysis, phase.phase_id) }}
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

              {/* Error paths */}
              <ErrorPathsSection errorPaths={analysis.error_paths} />
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
              <SequenceDiagram data={visibleSeq} />
              <button
                className="btn btn-secondary btn-sm"
                style={{ marginTop: 8 }}
                disabled={generating}
                onClick={handleGenerateSeq}
              >
                {generating ? "Regenerating…" : "Regenerate"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
