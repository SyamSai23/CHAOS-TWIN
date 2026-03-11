import { useState, useEffect, useCallback } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import type { RouteItem, RouteAnalysis } from "../types";
import type { SequenceData } from "../SequenceDiagram";
import SequenceDiagram from "../SequenceDiagram";
import ModeToggle from "./ModeToggle";
import PhaseCard from "./PhaseCard";
import ErrorPathsSection from "./ErrorPathsSection";

const API = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

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

    const pid = encodeURIComponent(projectId);
    const rid = encodeURIComponent(route.id);

    try {
      // Try GET first (already analyzed)
      const getRes = await fetch(`${API}/projects/${pid}/analyze/route/${rid}`);
      if (getRes.ok) {
        const a = (await getRes.json()) as RouteAnalysis;
        setAnalysis(a);
        setAnalysisCache((prev) => ({ ...prev, [route.id]: a }));
        return;
      }

      // Not found — trigger analysis via POST
      const postRes = await fetch(`${API}/projects/${pid}/analyze/route`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          method: route.method,
          path: route.path,
          file: route.file,
          component: route.component,
        }),
      });

      if (!postRes.ok) throw new Error("Analysis failed");
      const a = (await postRes.json()) as RouteAnalysis;
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

    fetch(
      `${API}/projects/${encodeURIComponent(projectId)}/sequence/route/${encodeURIComponent(route.id)}`
    )
      .then((res) => (res.ok ? res.json() : null))
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

    fetch(
      `${API}/projects/${encodeURIComponent(projectId)}/sequence/route`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          method: route.method,
          path: route.path,
          file: route.file,
          component: route.component,
        }),
      }
    )
      .then((res) => {
        if (!res.ok) throw new Error("Failed to generate sequence diagram");
        return res.json();
      })
      .then((d: SequenceData) => {
        setLocalSeq(d);
        onSequenceGenerated(route.id, d);
      })
      .catch((e) => setSeqError(e.message))
      .finally(() => setGenerating(false));
  };

  const displaySeq = localSeq || seqData;

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

              {/* Phases — deduplicate, filter, enforce canonical order */}
              <div className="rj-phases">
                <span className="rj-phases-label">REQUEST JOURNEY</span>
                {(() => {
                  const VALID = ["validation", "processing", "database", "response"];
                  const seen = new Set<string>();
                  const cleaned = analysis.phases.filter((p) => {
                    if (!VALID.includes(p.phase_id) || seen.has(p.phase_id)) return false;
                    seen.add(p.phase_id);
                    return true;
                  });
                  cleaned.sort(
                    (a, b) => VALID.indexOf(a.phase_id) - VALID.indexOf(b.phase_id)
                  );
                  return cleaned.length > 0 ? (
                    cleaned.map((phase, i) => (
                      <PhaseCard key={phase.phase_id} phase={phase} index={i} mode="story" />
                    ))
                  ) : (
                    <p className="text-muted" style={{ fontSize: 13 }}>
                      No phases detected — handler may be too simple to decompose.
                    </p>
                  );
                })()}
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
          {!displaySeq && seqChecked && (
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
          {displaySeq && (
            <div className="api-seq-inline">
              <SequenceDiagram data={displaySeq} />
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
