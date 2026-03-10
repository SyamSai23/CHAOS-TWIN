import { useState, useEffect, useMemo, useCallback } from "react";
import { Zap, GitBranch } from "lucide-react";
import type { RoutesResponse, RouteItem } from "../types";
import SequenceDiagram, { type SequenceData } from "../SequenceDiagram";

const API = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

/* ── Method colors ── */

const METHOD_COLORS: Record<string, string> = {
  GET: "#22c55e",
  POST: "#3b82f6",
  PUT: "#eab308",
  DELETE: "#ef4444",
  PATCH: "#a855f7",
  ANY: "#6b6b6b",
};

/* ── Rule-based route description ── */

function describeRoute(method: string, path: string): string | null {
  const segments = path
    .split("/")
    .filter(Boolean)
    .filter((s) => !s.startsWith("{") && !s.startsWith(":") && !s.startsWith("<"));

  if (segments.length === 0) return null;

  const lastSeg = segments[segments.length - 1];
  const noun = lastSeg.replace(/[-_]/g, " ");

  const endsWithParam =
    path.endsWith("}") || /\/:[^/]+$/.test(path) || /<[^>]+>\/?$/.test(path);

  const m = method.toUpperCase();

  if (m === "GET" && endsWithParam) return `Fetches a single ${noun} by ID`;
  if (m === "GET") return `Fetches list of ${noun}`;
  if (m === "POST") return `Creates a new ${noun}`;
  if (m === "PUT" || m === "PATCH") return `Updates a ${noun}`;
  if (m === "DELETE") return `Deletes a ${noun}`;

  return null;
}

/* ── Props ── */

type Props = {
  projectId: string;
};

/* ── Component ── */

export default function ApiExplorerView({ projectId }: Props) {
  const [data, setData] = useState<RoutesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [methodFilter, setMethodFilter] = useState<string | null>(null);
  const [seqCache, setSeqCache] = useState<Record<string, SequenceData>>({});

  /* ── Fetch routes ── */

  useEffect(() => {
    setData(null);
    setError(null);
    setSelectedRouteId(null);
    setSearchQuery("");
    setMethodFilter(null);
    setSeqCache({});
    setLoading(true);

    fetch(`${API}/projects/${encodeURIComponent(projectId)}/routes`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load routes");
        return res.json();
      })
      .then((d: RoutesResponse) => setData(d))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [projectId]);

  /* ── Callback to mark route as having sequence ── */
  const onSequenceGenerated = useCallback(
    (routeId: string, seqData: SequenceData) => {
      setSeqCache((prev) => ({ ...prev, [routeId]: seqData }));
      // Update has_sequence in data
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          by_component: prev.by_component.map((g) => ({
            ...g,
            routes: g.routes.map((r) =>
              r.id === routeId ? { ...r, has_sequence: true } : r
            ),
          })),
        };
      });
    },
    []
  );

  /* ── Filtered data ── */

  const filteredGroups = useMemo(() => {
    if (!data) return [];
    return data.by_component
      .map((group) => {
        const filtered = group.routes.filter((r) => {
          if (methodFilter && r.method !== methodFilter) return false;
          if (searchQuery && !r.path.toLowerCase().includes(searchQuery.toLowerCase()))
            return false;
          return true;
        });
        return { ...group, routes: filtered };
      })
      .filter((g) => g.routes.length > 0);
  }, [data, methodFilter, searchQuery]);

  /* ── Find selected route ── */

  const selectedRoute = useMemo(() => {
    if (!selectedRouteId || !data) return null;
    for (const g of data.by_component) {
      const found = g.routes.find((r) => r.id === selectedRouteId);
      if (found) return found;
    }
    return null;
  }, [data, selectedRouteId]);

  /* ── Loading state ── */

  if (loading) {
    return (
      <div className="placeholder-view">
        <p className="text-muted">Loading routes…</p>
      </div>
    );
  }

  /* ── Error state ── */

  if (error) {
    return (
      <div className="placeholder-view">
        <Zap size={48} color="#6b6b6b" strokeWidth={1.5} />
        <h2 className="placeholder-title">Could not load routes</h2>
        <p className="placeholder-sub">{error}</p>
      </div>
    );
  }

  /* ── Empty / no routes ── */

  if (data && data.total === 0) {
    return (
      <div className="placeholder-view">
        <Zap size={48} color="#6b6b6b" strokeWidth={1.5} />
        <h2 className="placeholder-title">No API routes detected</h2>
        <p className="placeholder-sub">
          This repository does not appear to contain a detectable API layer. Routes are
          detected for FastAPI, Flask, Django, Express, Spring, Go, and Rails.
        </p>
      </div>
    );
  }

  if (!data) return null;

  /* ── Methods to show in summary bar ── */

  const methodOrder = ["GET", "POST", "PUT", "DELETE", "PATCH", "ANY"];
  const methodsToShow = methodOrder.filter((m) => (data.methods_summary[m] ?? 0) > 0);

  return (
    <div className="api-explorer">
      <h1 className="view-title">API Explorer</h1>

      <div className="api-explorer-layout">
        {/* ── LEFT PANEL ── */}
        <div className="api-left-panel">
          {/* Method summary badges */}
          <div className="api-method-bar">
            {methodsToShow.map((m) => (
              <button
                key={m}
                className={`api-method-badge${methodFilter === m ? " active" : ""}`}
                style={
                  {
                    "--method-color": METHOD_COLORS[m] || "#6b6b6b",
                  } as React.CSSProperties
                }
                onClick={() => setMethodFilter(methodFilter === m ? null : m)}
              >
                {m}{" "}
                <span className="api-method-count">{data.methods_summary[m]}</span>
              </button>
            ))}
          </div>

          {/* Search */}
          <input
            className="api-search"
            type="text"
            placeholder="Search routes…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />

          {/* Grouped route list */}
          <div className="api-route-list">
            {filteredGroups.map((group) => (
              <div key={group.component} className="api-route-group">
                <div className="api-group-header">
                  <span className="api-group-name">{group.component || "unknown"}</span>
                  <span className="chip chip-muted" style={{ fontSize: 10 }}>
                    {group.component_type}
                  </span>
                </div>
                {group.routes.map((route) => (
                  <RouteRow
                    key={route.id}
                    route={route}
                    selected={selectedRouteId === route.id}
                    onClick={() => setSelectedRouteId(route.id)}
                  />
                ))}
              </div>
            ))}

            {filteredGroups.length === 0 && (
              <p className="text-muted" style={{ padding: "16px 0", textAlign: "center" }}>
                No routes match filters
              </p>
            )}
          </div>
        </div>

        {/* ── RIGHT PANEL ── */}
        <div className="api-right-panel">
          {selectedRoute ? (
            <RouteDetail
              route={selectedRoute}
              projectId={projectId}
              seqData={seqCache[selectedRoute.id] ?? null}
              onSequenceGenerated={onSequenceGenerated}
            />
          ) : (
            <div className="api-empty-detail">
              <GitBranch size={48} color="#6b6b6b" strokeWidth={1.5} />
              <p className="api-empty-detail-title">Select a route to explore</p>
              <p className="api-empty-detail-sub">
                Click any route from the list to see its details
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Route row sub-component ── */

function RouteRow({
  route,
  selected,
  onClick,
}: {
  route: RouteItem;
  selected: boolean;
  onClick: () => void;
}) {
  const color = METHOD_COLORS[route.method] || "#6b6b6b";

  return (
    <button
      className={`api-route-row${selected ? " selected" : ""}`}
      onClick={onClick}
    >
      <span className="api-route-method" style={{ color, borderColor: color }}>
        {route.method}
      </span>
      <span className="api-route-path">{route.path}</span>
      {route.has_sequence && <span className="api-seq-dot" title="Sequence diagram generated" />}
      <span className="api-route-file">{route.file}</span>
    </button>
  );
}

/* ── Route detail sub-component ── */

function RouteDetail({
  route,
  projectId,
  seqData,
  onSequenceGenerated,
}: {
  route: RouteItem;
  projectId: string;
  seqData: SequenceData | null;
  onSequenceGenerated: (routeId: string, data: SequenceData) => void;
}) {
  const color = METHOD_COLORS[route.method] || "#6b6b6b";
  const description = describeRoute(route.method, route.path);
  const [generating, setGenerating] = useState(false);
  const [seqError, setSeqError] = useState<string | null>(null);
  const [localSeq, setLocalSeq] = useState<SequenceData | null>(null);
  const [checked, setChecked] = useState(false);

  // On mount / route change: try to fetch existing diagram
  useEffect(() => {
    setLocalSeq(null);
    setSeqError(null);
    setChecked(false);

    if (seqData) {
      setLocalSeq(seqData);
      setChecked(true);
      return;
    }

    if (!route.has_sequence) {
      setChecked(true);
      return;
    }

    // Route claims to have a diagram — fetch it
    fetch(
      `${API}/projects/${encodeURIComponent(projectId)}/sequence/route/${encodeURIComponent(route.id)}`
    )
      .then((res) => {
        if (!res.ok) return null;
        return res.json();
      })
      .then((d) => {
        if (d) {
          setLocalSeq(d as SequenceData);
          onSequenceGenerated(route.id, d as SequenceData);
        }
      })
      .catch(() => {})
      .finally(() => setChecked(true));
  }, [route.id, route.has_sequence, seqData, projectId, onSequenceGenerated]);

  const handleGenerate = () => {
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

  return (
    <div className="api-detail">
      {/* Main info card */}
      <div className="api-detail-card">
        <div className="api-detail-header">
          <span className="api-detail-method" style={{ background: color }}>
            {route.method}
          </span>
          <span className="api-detail-path">{route.path}</span>
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
        </div>

        <div className="api-detail-divider" />

        <div className="api-detail-section">
          <span className="api-detail-label">SEQUENCE DIAGRAM</span>
          {!displaySeq && checked && (
            <button
              className="btn btn-secondary btn-sm"
              style={{ marginTop: 8 }}
              disabled={generating}
              onClick={handleGenerate}
            >
              {generating ? "Generating…" : "Generate Sequence Diagram"}
            </button>
          )}
          {seqError && (
            <p style={{ color: "#ef4444", fontSize: 12, marginTop: 6 }}>{seqError}</p>
          )}
        </div>
      </div>

      {/* Description */}
      {description && (
        <div className="api-description-card">
          <span className="api-detail-label">WHAT THIS ROUTE LIKELY DOES</span>
          <p className="api-description-text">{description}</p>
        </div>
      )}

      {/* Inline sequence diagram */}
      {displaySeq && (
        <div className="api-seq-inline">
          <div className="api-seq-badge">
            <span
              className="api-detail-method"
              style={{ background: color, fontSize: 11, padding: "2px 8px" }}
            >
              {route.method}
            </span>
            <span style={{ color: "#e2e8f0", fontSize: 13, marginLeft: 8 }}>
              {route.path}
            </span>
          </div>
          <SequenceDiagram data={displaySeq} />
          <button
            className="btn btn-secondary btn-sm"
            style={{ marginTop: 8 }}
            disabled={generating}
            onClick={handleGenerate}
          >
            {generating ? "Regenerating…" : "Regenerate"}
          </button>
        </div>
      )}
    </div>
  );
}
