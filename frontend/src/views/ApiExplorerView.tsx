import { useState, useEffect, useMemo, useCallback, type CSSProperties } from "react";
import { AlertTriangle, GitBranch, Search, ShieldCheck, Workflow, Zap } from "lucide-react";

import type { RouteItem, RoutesResponse } from "../types";
import type { SequenceData } from "../SequenceDiagram";
import RequestJourney from "../components/RequestJourney";
import PageHeader from "../components/PageHeader";
import { fetchRoutes } from "../api/client";

const METHOD_COLORS: Record<string, string> = {
  GET: "#22c55e",
  POST: "#3b82f6",
  PUT: "#eab308",
  DELETE: "#ef4444",
  PATCH: "#a855f7",
  ANY: "#6b6b6b",
};

type Props = {
  projectId: string;
  refreshKey: number;
};

export default function ApiExplorerView({ projectId, refreshKey }: Props) {
  const [data, setData] = useState<RoutesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [methodFilter, setMethodFilter] = useState<string | null>(null);
  const [seqCache, setSeqCache] = useState<Record<string, SequenceData>>({});

  useEffect(() => {
    setData(null);
    setError(null);
    setSelectedRouteId(null);
    setSearchQuery("");
    setMethodFilter(null);
    setSeqCache({});
    setLoading(true);

    fetchRoutes(projectId)
      .then((payload: RoutesResponse) => setData(payload))
      .catch((fetchError) => setError(fetchError.message))
      .finally(() => setLoading(false));
  }, [projectId, refreshKey]);

  const onSequenceGenerated = useCallback((routeId: string, seqData: SequenceData) => {
    setSeqCache((prev) => ({ ...prev, [routeId]: seqData }));
    setData((prev) => {
      if (!prev) {
        return prev;
      }
      return {
        ...prev,
        by_component: prev.by_component.map((group) => ({
          ...group,
          routes: group.routes.map((route) => (
            route.id === routeId ? { ...route, has_sequence: true } : route
          )),
        })),
      };
    });
  }, []);

  const filteredGroups = useMemo(() => {
    if (!data) {
      return [];
    }

    return data.by_component
      .map((group) => {
        const routes = group.routes.filter((route) => {
          if (methodFilter && route.method !== methodFilter) {
            return false;
          }

          if (searchQuery) {
            const haystack = [
              route.path,
              route.file,
              route.component,
              route.controller_name,
              route.handler_function,
            ]
              .filter(Boolean)
              .join(" ")
              .toLowerCase();
            if (!haystack.includes(searchQuery.toLowerCase())) {
              return false;
            }
          }

          return true;
        });

        return { ...group, routes };
      })
      .filter((group) => group.routes.length > 0);
  }, [data, methodFilter, searchQuery]);

  useEffect(() => {
    if (!filteredGroups.length) {
      setSelectedRouteId(null);
      return;
    }

    const stillVisible = filteredGroups.some((group) =>
      group.routes.some((route) => route.id === selectedRouteId),
    );

    if (!stillVisible) {
      setSelectedRouteId(filteredGroups[0].routes[0]?.id ?? null);
    }
  }, [filteredGroups, selectedRouteId]);

  const selectedRoute = useMemo(() => {
    if (!selectedRouteId || !data) {
      return null;
    }

    for (const group of data.by_component) {
      const found = group.routes.find((route) => route.id === selectedRouteId);
      if (found) {
        return found;
      }
    }

    return null;
  }, [data, selectedRouteId]);

  if (loading) {
    return (
      <div className="page-shell">
        <PageHeader
          eyebrow="Routes"
          title="API Explorer"
          description="Browse detected endpoints, inspect deterministic request flow, and generate route sequences."
        />
        <div className="placeholder-view surface-panel">
          <p className="text-muted">Loading routes…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page-shell">
        <PageHeader
          eyebrow="Routes"
          title="API Explorer"
          description="Browse detected endpoints, inspect deterministic request flow, and generate route sequences."
        />
        <div className="placeholder-view surface-panel">
          <Zap size={48} color="#6b6b6b" strokeWidth={1.5} />
          <h2 className="placeholder-title">Could not load routes</h2>
          <p className="placeholder-sub">{error}</p>
        </div>
      </div>
    );
  }

  if (data && data.total === 0) {
    return (
      <div className="page-shell">
        <PageHeader
          eyebrow="Routes"
          title="API Explorer"
          description="Browse detected endpoints, inspect deterministic request flow, and generate route sequences."
        />
        <div className="placeholder-view surface-panel">
          <Zap size={48} color="#6b6b6b" strokeWidth={1.5} />
          <h2 className="placeholder-title">No API routes detected</h2>
          <p className="placeholder-sub">
            This repository does not appear to contain a detectable API layer. Routes are
            detected for FastAPI, Flask, Django, Express, Spring, Go, and Rails.
          </p>
        </div>
      </div>
    );
  }

  if (!data) {
    return null;
  }

  const methodOrder = ["GET", "POST", "PUT", "DELETE", "PATCH", "ANY"];
  const methodsToShow = methodOrder.filter((method) => (data.methods_summary[method] ?? 0) > 0);
  const allRoutes = data.by_component.flatMap((group) => group.routes);
  const groundedRoutes = allRoutes.filter((route) => route.request_flow_summary?.has_request_flow).length;
  const degradedRoutes = allRoutes.filter((route) => isRouteDegraded(route)).length;
  const sequenceReadyRoutes = allRoutes.filter((route) => route.has_sequence).length;
  const selectedSource = selectedRoute ? sourceSummary(selectedRoute) : null;

  return (
    <div className="page-shell api-explorer">
      <PageHeader
        eyebrow="Routes"
        title="API Explorer"
        description="Inspect route coverage, deterministic request flow, and grounded sequence generation from one surface."
        meta={(
          <>
            <span className="chip chip-muted">{data.total} routes</span>
            <span className="chip chip-muted">{filteredGroups.length} component groups</span>
            <span className="chip chip-muted">{groundedRoutes} grounded</span>
            <span className="chip chip-muted">{degradedRoutes} degraded</span>
            {methodsToShow.map((method) => (
              <span key={method} className="chip chip-muted">{method} {data.methods_summary[method]}</span>
            ))}
          </>
        )}
      />

      <div className="api-explorer-layout">
        <section className="api-left-panel">
          <div className="api-left-header">
            <div className="api-panel-kicker">Route explorer</div>
            <h2 className="api-panel-title">Browse the routed surface</h2>
            <p className="api-panel-subtitle">
              Select an endpoint to inspect grounded request flow, trust signals, and sequence readiness.
            </p>

            <div className="api-summary-grid">
              <div className="api-summary-card">
                <span className="api-summary-label">Grounded flow</span>
                <span className="api-summary-value">{groundedRoutes}</span>
                <span className="api-summary-sub">Routes with direct request flow</span>
              </div>
              <div className="api-summary-card">
                <span className="api-summary-label">Degraded</span>
                <span className="api-summary-value">{degradedRoutes}</span>
                <span className="api-summary-sub">Fallback-backed or lower-confidence</span>
              </div>
              <div className="api-summary-card">
                <span className="api-summary-label">Sequence ready</span>
                <span className="api-summary-value">{sequenceReadyRoutes}</span>
                <span className="api-summary-sub">Saved sequence diagrams available</span>
              </div>
            </div>
          </div>

          <div className="api-controls-shell">
            <label className="api-search-shell">
              <Search size={14} />
              <input
                className="api-search"
                type="text"
                placeholder="Search path, owner, file, or component"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </label>

            <div className="api-method-bar">
              <button
                className={`api-method-badge api-method-badge-neutral${methodFilter === null ? " active" : ""}`}
                onClick={() => setMethodFilter(null)}
              >
                All <span className="api-method-count">{data.total}</span>
              </button>
              {methodsToShow.map((method) => (
                <button
                  key={method}
                  className={`api-method-badge${methodFilter === method ? " active" : ""}`}
                  style={{ "--method-color": METHOD_COLORS[method] || "#6b6b6b" } as CSSProperties}
                  onClick={() => setMethodFilter(methodFilter === method ? null : method)}
                >
                  {method} <span className="api-method-count">{data.methods_summary[method]}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="api-route-list">
            {filteredGroups.map((group) => (
              <div key={group.component} className="api-route-group">
                <div className="api-group-header">
                  <div>
                    <span className="api-group-name">{group.component || "unknown"}</span>
                    <span className="api-group-count">{group.routes.length} routes</span>
                  </div>
                  <span className="chip chip-muted api-group-chip">{group.component_type}</span>
                </div>
                <div className="api-route-group-list">
                  {group.routes.map((route) => (
                    <RouteRow
                      key={route.id}
                      route={route}
                      selected={selectedRouteId === route.id}
                      onClick={() => setSelectedRouteId(route.id)}
                    />
                  ))}
                </div>
              </div>
            ))}

            {filteredGroups.length === 0 && (
              <div className="api-route-empty-state">
                <Search size={18} />
                <p className="api-route-empty-title">No routes match the current filters</p>
                <p className="api-route-empty-sub">Clear the search or method filter to restore the full routed surface.</p>
              </div>
            )}
          </div>
        </section>

        <section className="api-right-panel">
          {selectedRoute ? (
            <>
              <div className="api-selection-strip">
                <div className="api-selection-copy">
                  <span className="api-panel-kicker">Selected route</span>
                  <div className="api-selection-title-row">
                    <span className="api-detail-method" style={{ background: METHOD_COLORS[selectedRoute.method] || "#6b6b6b" }}>
                      {selectedRoute.method}
                    </span>
                    <h2 className="api-selection-title">{selectedRoute.path}</h2>
                  </div>
                  <p className="api-selection-subtitle">
                    {selectedSource?.detail ?? "Inspect the grounded request journey, compatibility fallback, and sequence coverage for this route."}
                  </p>
                </div>

                <div className="api-selection-badges">
                  <span className={`api-trust-pill ${selectedSource?.tone === "fallback" ? "is-fallback" : selectedSource?.tone === "caution" ? "is-caution" : "is-grounded"}`}>
                    {selectedSource?.label ?? "Route detail"}
                  </span>
                  {selectedRoute.has_sequence ? <span className="api-trust-pill is-sequence">Sequence ready</span> : null}
                </div>
              </div>

              <RequestJourney
                route={selectedRoute}
                projectId={projectId}
                seqData={seqCache[selectedRoute.id] ?? null}
                onSequenceGenerated={onSequenceGenerated}
              />
            </>
          ) : (
            <div className="api-empty-detail surface-panel">
              <div className="api-empty-detail-illustration">
                <Workflow size={28} />
              </div>
              <p className="api-empty-detail-title">Select a route to inspect its journey</p>
              <p className="api-empty-detail-sub">
                Route detail opens here with request-flow grounding, trust signals, and sequence access. The list stays as the source-of-truth explorer rail.
              </p>
              <div className="api-empty-checklist">
                <span><ShieldCheck size={14} /> Honest degraded and confidence signaling</span>
                <span><GitBranch size={14} /> Grounded request flow when available</span>
                <span><AlertTriangle size={14} /> Compatibility fallback when direct flow is weak</span>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function RouteRow({ route, selected, onClick }: { route: RouteItem; selected: boolean; onClick: () => void }) {
  const color = METHOD_COLORS[route.method] || "#6b6b6b";
  const flowSummary = route.request_flow_summary;
  const owner = route.controller_name && route.handler_function
    ? `${route.controller_name}.${route.handler_function}`
    : route.handler_function || route.controller_name || route.component || "unknown";
  const degraded = isRouteDegraded(route);
  const badges = routeCapabilityBadges(route);

  return (
    <button className={`api-route-row${selected ? " selected" : ""}`} onClick={onClick}>
      <div className="api-route-row-topline">
        <span className="api-route-method" style={{ color, borderColor: color }}>
          {route.method}
        </span>
        <span className="api-route-path">{route.path}</span>
        {route.has_sequence ? <span className="api-seq-dot" title="Sequence diagram generated" /> : null}
      </div>

      <div className="api-route-row-meta">
        <span className="api-route-owner">{owner}</span>
        <span className="api-route-file">{route.file}</span>
      </div>

      <div className="api-route-row-badges">
        <span className={`api-route-flow-badge ${flowSummary?.has_request_flow ? "is-grounded" : "is-fallback"}`}>
          {flowSummary?.has_request_flow ? `${flowSummary.stage_count} steps` : "Compatibility only"}
        </span>
        {typeof flowSummary?.confidence === "number" ? (
          <span className="api-route-flow-badge is-confidence">{Math.round(flowSummary.confidence * 100)}% confidence</span>
        ) : null}
        {degraded ? <span className="api-route-flow-badge is-warning">Degraded</span> : null}
        {badges.slice(0, 2).map((badge) => (
          <span key={badge} className="api-route-flow-badge is-capability">{badge}</span>
        ))}
      </div>
    </button>
  );
}

function isRouteDegraded(route: RouteItem): boolean {
  const summary = route.request_flow_summary;
  if (!summary?.has_request_flow) {
    return true;
  }
  return typeof summary.confidence === "number" && summary.confidence < 0.75;
}

function routeCapabilityBadges(route: RouteItem): string[] {
  const summary = route.request_flow_summary;
  if (!summary) {
    return [];
  }
  const badges: string[] = [];
  if (summary.has_service) badges.push("Service");
  if (summary.has_repository || summary.has_data_access) badges.push("Data");
  if (summary.has_external) badges.push("External");
  return badges;
}

function sourceSummary(route: RouteItem): { label: string; detail: string; tone: "grounded" | "caution" | "fallback" } {
  const summary = route.request_flow_summary;
  if (!summary?.has_request_flow) {
    return {
      label: "Compatibility fallback",
      tone: "fallback",
      detail: "Direct request flow is not available for this route, so the detail panel stays usable through honest compatibility analysis.",
    };
  }
  if (typeof summary.confidence === "number" && summary.confidence < 0.75) {
    return {
      label: "Grounded with caution",
      tone: "caution",
      detail: `Request flow is grounded, but confidence is ${Math.round(summary.confidence * 100)}% so lower-certainty steps stay explicitly marked.`,
    };
  }
  return {
    label: "Grounded request flow",
    tone: "grounded",
    detail: `This route has a direct ${summary.stage_count}-stage request flow from the backend source of truth.`,
  };
}
