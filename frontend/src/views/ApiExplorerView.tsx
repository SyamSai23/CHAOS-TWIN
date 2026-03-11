import { useState, useEffect, useMemo, useCallback } from "react";
import { Zap, GitBranch } from "lucide-react";
import type { RoutesResponse, RouteItem } from "../types";
import type { SequenceData } from "../SequenceDiagram";
import RequestJourney from "../components/RequestJourney";

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
            <RequestJourney
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

/* ── Route detail sub-component (now handled by RequestJourney) ── */
