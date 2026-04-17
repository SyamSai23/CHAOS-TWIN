import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";

import { API_BASE } from "../api/client";

type RouteParameter = {
  name?: string;
  type?: string;
  source?: string;
  location?: string;
  in?: string;
};

type BodyField = {
  field?: string;
  type?: string;
  required?: boolean;
  description?: string;
};

type RequestResponseSection = {
  description?: string;
  body?: BodyField[];
  notes?: string | null;
};

type RequestResponse = {
  request?: RequestResponseSection;
  response?: RequestResponseSection;
};

type UiField = {
  field?: string;
  type?: string;
  description?: string;
};

type UiAction = {
  action?: string;
  description?: string;
};

type UiSection = {
  description?: string;
};

type UiInputsSection = UiSection & {
  fields?: UiField[];
};

type UiInteractionsSection = UiSection & {
  actions?: UiAction[];
};

type UiAnalysis = {
  inputs?: UiInputsSection;
  interactions?: UiInteractionsSection;
  outputs?: UiSection;
};

type RouteStep = {
  label?: string;
  description?: string;
  action?: string;
  detail?: string;
};

type RoutePhase = {
  name?: string;
  title?: string;
  description?: string;
  steps?: RouteStep[];
};

type ApiRoute = {
  route_id?: string;
  method: string;
  path: string;
  file: string;
  handler: string | null;
  summary?: string;
  complexity: string;
  has_database: boolean;
  has_external: boolean;
  parameters: RouteParameter[];
  phases: RoutePhase[];
  participants: unknown[];
  request_response?: RequestResponse | null;
  analysis_data?: {
    phases?: RoutePhase[];
  } | null;
};

type FeatureGroup = {
  name: string;
  routes: ApiRoute[];
};

type ApiExplorerResponse = {
  mode?: "routes" | "entry_points";
  features?: FeatureGroup[];
};

type ApiExplorerPageProps = {
  projectId: string;
};

const METHOD_STYLES: Record<string, { background: string; color: string }> = {
  GET: { background: "#dbeafe", color: "#1d4ed8" },
  POST: { background: "#dcfce7", color: "#15803d" },
  PUT: { background: "#fef9c3", color: "#854d0e" },
  DELETE: { background: "#fee2e2", color: "#b91c1c" },
  PATCH: { background: "#f3e8ff", color: "#7e22ce" },
  ENTRY: { background: "#eef1ec", color: "#6f766d" },
};

const COMPLEXITY_STYLES: Record<string, { background: string; color: string }> = {
  simple: { background: "#e7f4eb", color: "#2f6b45" },
  moderate: { background: "#f7eed7", color: "#8a6422" },
  complex: { background: "#f7dfdc", color: "#a33b2f" },
};

function getMethodStyle(method: string) {
  return METHOD_STYLES[method.toUpperCase()] ?? { background: "#edf1ea", color: "#5f655b" };
}

function getComplexityStyle(complexity: string) {
  return COMPLEXITY_STYLES[complexity.toLowerCase()] ?? COMPLEXITY_STYLES.simple;
}

function methodColor(method: string) {
  return ({
    GET: "#16a34a",
    POST: "#2563eb",
    PUT: "#d97706",
    PATCH: "#7c3aed",
    DELETE: "#dc2626",
  }[method?.toUpperCase()] || "#74796e");
}

function routeKey(route: ApiRoute) {
  return `${route.method} ${route.path} ${route.file}`;
}

function traceRouteId(route: ApiRoute) {
  return `${route.method}-${route.path}`;
}

function navigateTo(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function fileName(filePath: string) {
  return filePath.split("/").pop() || filePath;
}

function parameterSource(param: RouteParameter) {
  return param.source || param.location || param.in || "unknown";
}

function bodyFields(section?: RequestResponseSection) {
  return Array.isArray(section?.body) ? section?.body ?? [] : [];
}

function inputFields(section?: UiInputsSection) {
  return Array.isArray(section?.fields) ? section?.fields ?? [] : [];
}

function interactionActions(section?: UiInteractionsSection) {
  return Array.isArray(section?.actions) ? section?.actions ?? [] : [];
}

function renderSchemaSection(
  label: string,
  section: RequestResponseSection | undefined,
  includeRequired: boolean,
) {
  const rows = bodyFields(section);

  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ fontSize: 11, letterSpacing: "0.08em", color: "#4a7c59", marginBottom: 10 }}>
        {label}
      </div>
      {section?.description && (
        <div style={{ marginBottom: 10, fontSize: 13, color: "#74796e", fontStyle: "italic", lineHeight: 1.6 }}>
          {section.description}
        </div>
      )}
      {rows.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, color: "#2e3230" }}>
          <thead>
            <tr style={{ background: "#f0ece4", textAlign: "left" }}>
              <th style={{ padding: "6px 8px", fontWeight: 700 }}>Field</th>
              <th style={{ padding: "6px 8px", fontWeight: 700 }}>Type</th>
              {includeRequired && <th style={{ padding: "6px 8px", fontWeight: 700 }}>Required</th>}
              <th style={{ padding: "6px 8px", fontWeight: 700 }}>Description</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${row.field || "field"}-${index}`} style={{ borderBottom: "1px solid #e8e4dc" }}>
                <td style={{ padding: "6px 8px", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}>
                  {row.field || "field"}
                </td>
                <td style={{ padding: "6px 8px" }}>{row.type || "unknown"}</td>
                {includeRequired && (
                  <td style={{ padding: "6px 8px" }}>
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        borderRadius: 999,
                        padding: "2px 8px",
                        fontSize: 11,
                        background: row.required ? "#e7f4eb" : "#eef1ec",
                        color: row.required ? "#2f6b45" : "#6f766d",
                      }}
                    >
                      {row.required ? "required" : "optional"}
                    </span>
                  </td>
                )}
                <td style={{ padding: "6px 8px", color: "#74796e" }}>{row.description || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {section?.notes && (
        <div
          style={{
            marginTop: 10,
            padding: "10px 12px",
            borderRadius: 8,
            background: "#f0ece4",
            color: "#74796e",
            fontSize: 12,
            lineHeight: 1.6,
          }}
        >
          {section.notes}
        </div>
      )}
    </div>
  );
}

export default function ApiExplorerPage({ projectId }: ApiExplorerPageProps) {
  const [features, setFeatures] = useState<FeatureGroup[]>([]);
  const [mode, setMode] = useState<"routes" | "entry_points">("routes");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [openRouteKey, setOpenRouteKey] = useState<string | null>(null);
  const [generatedDetails, setGeneratedDetails] = useState<Record<string, RequestResponse>>({});
  const [generatingRouteKey, setGeneratingRouteKey] = useState<string | null>(null);
  const [routeErrors, setRouteErrors] = useState<Record<string, string>>({});
  const [generatedUiAnalyses, setGeneratedUiAnalyses] = useState<Record<string, UiAnalysis>>({});
  const [generatingFileKey, setGeneratingFileKey] = useState<string | null>(null);
  const [fileErrors, setFileErrors] = useState<Record<string, string>>({});
  const [tracingRouteId, setTracingRouteId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setOpenRouteKey(null);
    setMode("routes");
    setGeneratedDetails({});
    setGeneratingRouteKey(null);
    setRouteErrors({});
    setGeneratedUiAnalyses({});
    setGeneratingFileKey(null);
    setFileErrors({});
    setTracingRouteId(null);

    fetch(`${API_BASE}/projects/${projectId}/api-explorer`)
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok) {
          throw new Error(body?.detail || "Failed to load API explorer");
        }
        return body;
      })
      .then((body: ApiExplorerResponse) => {
        if (!cancelled) {
          setFeatures(Array.isArray(body?.features) ? body.features : []);
          setMode(body?.mode === "entry_points" ? "entry_points" : "routes");
        }
      })
      .catch((fetchError) => {
        if (!cancelled) {
          setError(fetchError instanceof Error ? fetchError.message : "Failed to load API explorer");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function enrichRoute(route: ApiRoute) {
    const key = routeKey(route);
    if (!route.route_id) {
      setRouteErrors((current) => ({ ...current, [key]: "Failed to generate details. Try again." }));
      return;
    }

    setGeneratingRouteKey(key);
    setRouteErrors((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });

    try {
      const response = await fetch(`${API_BASE}/projects/${projectId}/api-explorer/routes/${route.route_id}/enrich`, {
        method: "POST",
      });
      const body = await response.json().catch(() => null);
      if (!response.ok || !body || typeof body !== "object") {
        throw new Error(body?.detail || "Failed to generate details. Try again.");
      }
      setGeneratedDetails((current) => ({ ...current, [key]: body as RequestResponse }));
    } catch (enrichError) {
      setRouteErrors((current) => ({
        ...current,
        [key]: enrichError instanceof Error ? enrichError.message : "Failed to generate details. Try again.",
      }));
    } finally {
      setGeneratingRouteKey((current) => (current === key ? null : current));
    }
  }

  async function enrichFile(route: ApiRoute) {
    const key = routeKey(route);

    setGeneratingFileKey(key);
    setFileErrors((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });

    try {
      const response = await fetch(`${API_BASE}/projects/${projectId}/api-explorer/files/enrich`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ file_path: route.path }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok || !body || typeof body !== "object") {
        throw new Error(body?.detail || "Failed to analyze file. Try again.");
      }
      setGeneratedUiAnalyses((current) => ({ ...current, [key]: body as UiAnalysis }));
    } catch (enrichError) {
      setFileErrors((current) => ({
        ...current,
        [key]: enrichError instanceof Error ? enrichError.message : "Failed to analyze file. Try again.",
      }));
    } finally {
      setGeneratingFileKey((current) => (current === key ? null : current));
    }
  }

  function handleTrace(route: ApiRoute) {
    const routeId = traceRouteId(route);
    setTracingRouteId((current) => (current === routeId ? null : routeId));
  }

  const filteredFeatures = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) {
      return features;
    }

    return features
      .map((feature) => ({
        ...feature,
        routes: feature.routes.filter((route) => {
          const haystack = `${route.path} ${route.handler ?? ""}`.toLowerCase();
          return haystack.includes(normalizedQuery);
        }),
      }))
      .filter((feature) => feature.routes.length > 0);
  }, [features, query]);

  if (loading) {
    return (
      <div
        style={{
          minHeight: "calc(100vh - 120px)",
          display: "grid",
          placeItems: "center",
          background: "#faf6f0",
          borderRadius: 18,
          color: "#2e3230",
          fontFamily: "'Nunito Sans', sans-serif",
        }}
      >
        <div style={{ display: "grid", placeItems: "center", gap: 12 }}>
          <Loader2 size={28} style={{ color: "#4a7c59", animation: "terra-spin 1s linear infinite" }} />
          <div style={{ fontSize: 15, color: "#74796e" }}>Loading API explorer...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        style={{
          minHeight: "calc(100vh - 120px)",
          background: "#faf6f0",
          borderRadius: 18,
          padding: 24,
          color: "#c0392b",
          fontFamily: "'Nunito Sans', sans-serif",
        }}
      >
        {error}
      </div>
    );
  }

  return (
    <div
      style={{
        minHeight: "calc(100vh - 120px)",
        background: "#faf6f0",
        borderRadius: 18,
        padding: 24,
        color: "#2e3230",
        fontFamily: "'Nunito Sans', sans-serif",
      }}
    >
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontFamily: "'Literata', serif", fontSize: 28, color: "#2e3230" }}>API Explorer</h1>
        <p style={{ margin: "8px 0 0", color: "#74796e", fontSize: 14 }}>
          {mode === "entry_points"
            ? "No API routes detected — showing key entry points instead."
            : "Every entry point into this codebase, grouped by feature."}
        </p>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search by route path or handler..."
          style={{
            width: "100%",
            maxWidth: 480,
            marginTop: 16,
            border: "1px solid #c4c8bc",
            borderRadius: 8,
            padding: "10px 14px",
            background: "#fffdf9",
            color: "#2e3230",
            fontSize: 14,
            fontFamily: "'Nunito Sans', sans-serif",
            outline: "none",
          }}
        />
      </div>

      <div style={{ display: "grid", gap: 28 }}>
        {filteredFeatures.map((feature) => (
          <section key={feature.name}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#2e3230" }}>{feature.name}</h2>
              <span
                style={{
                  background: "#f5f1ea",
                  border: "1px solid #c4c8bc",
                  borderRadius: 20,
                  padding: "2px 10px",
                  fontSize: 12,
                  color: "#74796e",
                }}
              >
                {feature.routes.length}
              </span>
            </div>
            <div style={{ borderTop: "1px solid #c4c8bc", paddingTop: 12 }}>
              {feature.routes.map((route) => {
                const key = routeKey(route);
                const routeId = traceRouteId(route);
                const open = openRouteKey === key;
                const isEntryRoute = route.method.toUpperCase() === "ENTRY";
                const methodStyle = getMethodStyle(route.method);
                const complexityStyle = route.complexity === "unknown" ? null : getComplexityStyle(route.complexity);
                const requestResponse = generatedDetails[key] ?? route.request_response ?? null;
                const routeError = routeErrors[key];
                const isGenerating = generatingRouteKey === key;
                const uiAnalysis = generatedUiAnalyses[key] ?? null;
                const fileError = fileErrors[key];
                const isGeneratingFile = generatingFileKey === key;
                const phases =
                  route.analysis_data?.phases ||
                  route.phases ||
                  (route as ApiRoute & { analysis?: { phases?: RoutePhase[] } }).analysis?.phases ||
                  [];
                return (
                  <div key={key}>
                    <div
                      onClick={() => setOpenRouteKey(open ? null : key)}
                      style={{
                        padding: "12px 16px",
                        borderRadius: 8,
                        marginBottom: 4,
                        display: "grid",
                        gridTemplateColumns: "52px minmax(0, 1fr) auto",
                        alignItems: "center",
                        gap: 16,
                        background: open ? "#f5f1ea" : "transparent",
                        cursor: "pointer",
                      }}
                    >
                      <div
                        style={{
                          width: 52,
                          textAlign: "center",
                          borderRadius: 6,
                          padding: "6px 0",
                          fontSize: 11,
                          fontWeight: 700,
                          letterSpacing: "0.04em",
                          ...methodStyle,
                        }}
                      >
                        {route.method.toUpperCase() === "ENTRY" ? "FILE" : route.method.toUpperCase()}
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <div
                          style={{
                            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                            fontSize: 14,
                            color: "#2e3230",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {route.path}
                        </div>
                        <div style={{ marginTop: 4, fontSize: 12, color: "#74796e" }}>
                          {route.handler || fileName(route.file)}
                        </div>
                        {mode === "entry_points" && route.summary && (
                          <div style={{ marginTop: 4, fontSize: 12, color: "#74796e", lineHeight: 1.5 }}>
                            {route.summary}
                          </div>
                        )}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                        {route.has_database && (
                          <span
                            style={{
                              background: "#f5f1ea",
                              color: "#74796e",
                              borderRadius: 999,
                              padding: "4px 8px",
                              fontSize: 11,
                              border: "1px solid #d8d4cc",
                            }}
                          >
                            DB
                          </span>
                        )}
                        {route.has_external && (
                          <span
                            style={{
                              background: "#f5f1ea",
                              color: "#74796e",
                              borderRadius: 999,
                              padding: "4px 8px",
                              fontSize: 11,
                              border: "1px solid #d8d4cc",
                            }}
                          >
                            Ext
                          </span>
                        )}
                        {complexityStyle && (
                          <span
                            style={{
                              borderRadius: 999,
                              padding: "4px 8px",
                              fontSize: 11,
                              textTransform: "capitalize",
                              ...complexityStyle,
                            }}
                          >
                            {route.complexity}
                          </span>
                        )}
                      </div>
                    </div>

                    {open && (
                      <div
                        style={{
                          background: "#f5f1ea",
                          borderRadius: 8,
                          padding: 16,
                          margin: "4px 0 8px 68px",
                        }}
                      >
                        {!isEntryRoute && (
                          <div style={{ marginBottom: 16 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                              <span
                                style={{
                                  background: methodColor(route.method),
                                  color: "#fff",
                                  padding: "2px 7px",
                                  borderRadius: 4,
                                  fontSize: 10,
                                  fontWeight: 700,
                                }}
                              >
                                {route.method.toUpperCase()}
                              </span>
                              <span
                                style={{
                                  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                                  fontSize: 13,
                                  color: "#2e3230",
                                }}
                              >
                                {route.path}
                              </span>
                            </div>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 12 }}>
                              <button
                                type="button"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  handleTrace(route);
                                }}
                                style={{
                                  display: "flex",
                                  alignItems: "center",
                                  gap: 6,
                                  padding: "6px 14px",
                                  background: tracingRouteId === routeId ? "#4a7c59" : "#eef4f1",
                                  color: tracingRouteId === routeId ? "#fff" : "#4a7c59",
                                  border: "1.5px solid #4a7c59",
                                  borderRadius: 8,
                                  fontSize: 12,
                                  fontWeight: 600,
                                  cursor: "pointer",
                                  transition: "all 0.15s",
                                }}
                              >
                                {tracingRouteId === routeId ? "✕ Close trace" : "▶ Trace this route"}
                              </button>

                              <span
                                onClick={(event) => {
                                  event.stopPropagation();
                                  navigateTo(`/projects/${projectId}/sequence`);
                                }}
                                style={{
                                  fontSize: 11,
                                  color: "#74796e",
                                  cursor: "pointer",
                                  textDecoration: "underline",
                                }}
                              >
                                Full page →
                              </span>
                            </div>

                            {tracingRouteId === routeId && (
                              <div
                                style={{
                                  marginTop: 14,
                                  background: "#0f1a14",
                                  borderRadius: 12,
                                  padding: "16px 20px",
                                  border: "1px solid #2d4a35",
                                }}
                              >
                                <div
                                  style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 8,
                                    marginBottom: 14,
                                    fontSize: 11,
                                    color: "#86b89a",
                                    fontWeight: 600,
                                    textTransform: "uppercase",
                                    letterSpacing: "0.06em",
                                  }}
                                >
                                  <span
                                    style={{
                                      background: methodColor(route.method),
                                      color: "#fff",
                                      padding: "2px 7px",
                                      borderRadius: 4,
                                      fontSize: 10,
                                    }}
                                  >
                                    {route.method}
                                  </span>
                                  {route.path}
                                </div>

                                {(() => {
                                  if (phases.length === 0) {
                                    return (
                                      <div style={{ color: "#74796e", fontSize: 12 }}>
                                        No trace data available. This route may not have been deeply analyzed yet.
                                      </div>
                                    );
                                  }

                                  return (
                                    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                                      {(() => {
                                        console.log("[Trace] phases data:", JSON.stringify(phases.slice(0, 2), null, 2));
                                        return null;
                                      })()}
                                      {phases.map((phase: RoutePhase, idx: number) => (
                                        <div key={idx} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                                          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 20 }}>
                                            <div
                                              style={{
                                                width: 8,
                                                height: 8,
                                                borderRadius: "50%",
                                                background: "#4a7c59",
                                                flexShrink: 0,
                                                marginTop: 4,
                                              }}
                                            />
                                            {idx < phases.length - 1 && (
                                              <div style={{ width: 1, flexGrow: 1, background: "#2d4a35", minHeight: 24 }} />
                                            )}
                                          </div>
                                          <div style={{ paddingBottom: 16 }}>
                                            <div style={{ fontSize: 12, fontWeight: 600, color: "#e8f5ee" }}>
                                              {phase.name || (phase as RoutePhase & { phase?: string }).phase || `Step ${idx + 1}`}
                                            </div>
                                            {((phase.steps || (phase as RoutePhase & { actions?: any[] }).actions || []) as any[]).slice(0, 4).map((step: any, si: number) => {
                                              const text =
                                                typeof step === "string"
                                                  ? step
                                                  : step.description ??
                                                    step.action ??
                                                    step.text ??
                                                    step.label ??
                                                    step.name ??
                                                    (step.actor && step.message ? `${step.actor}: ${step.message}` : null) ??
                                                    "";
                                              if (!text) return null;
                                              return (
                                                <div
                                                  key={si}
                                                  style={{
                                                    fontSize: 11,
                                                    color: "#86b89a",
                                                    marginTop: 4,
                                                    fontFamily: "monospace",
                                                    borderLeft: "2px solid #2d4a35",
                                                    paddingLeft: 8,
                                                  }}
                                                >
                                                  {text}
                                                </div>
                                              );
                                            })}
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                  );
                                })()}
                              </div>
                            )}
                          </div>
                        )}

                        {isEntryRoute && route.summary && (
                          <div
                            style={{
                              marginBottom: 14,
                              fontSize: 14,
                              color: "#74796e",
                              fontStyle: "italic",
                              lineHeight: 1.7,
                            }}
                          >
                            {route.summary}
                          </div>
                        )}

                        {isEntryRoute && uiAnalysis ? (
                          <>
                            <div style={{ marginBottom: 18 }}>
                              <div style={{ fontSize: 11, letterSpacing: "0.08em", color: "#4a7c59", marginBottom: 10 }}>
                                NEEDS
                              </div>
                              {uiAnalysis.inputs?.description && (
                                <div style={{ marginBottom: 10, fontSize: 13, color: "#74796e", fontStyle: "italic", lineHeight: 1.6 }}>
                                  {uiAnalysis.inputs.description}
                                </div>
                              )}
                              {inputFields(uiAnalysis.inputs).length > 0 && (
                                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, color: "#2e3230" }}>
                                  <thead>
                                    <tr style={{ background: "#f0ece4", textAlign: "left" }}>
                                      <th style={{ padding: "6px 8px", fontWeight: 700 }}>Field</th>
                                      <th style={{ padding: "6px 8px", fontWeight: 700 }}>Type</th>
                                      <th style={{ padding: "6px 8px", fontWeight: 700 }}>Description</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {inputFields(uiAnalysis.inputs).map((field, index) => (
                                      <tr key={`${field.field || "field"}-${index}`} style={{ borderBottom: "1px solid #e8e4dc" }}>
                                        <td style={{ padding: "6px 8px", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}>
                                          {field.field || "field"}
                                        </td>
                                        <td style={{ padding: "6px 8px" }}>{field.type || "unknown"}</td>
                                        <td style={{ padding: "6px 8px", color: "#74796e" }}>{field.description || ""}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              )}
                            </div>

                            <div style={{ marginBottom: 18 }}>
                              <div style={{ fontSize: 11, letterSpacing: "0.08em", color: "#4a7c59", marginBottom: 10 }}>
                                INTERACTIONS
                              </div>
                              {uiAnalysis.interactions?.description && (
                                <div style={{ marginBottom: 10, fontSize: 13, color: "#74796e", fontStyle: "italic", lineHeight: 1.6 }}>
                                  {uiAnalysis.interactions.description}
                                </div>
                              )}
                              {interactionActions(uiAnalysis.interactions).length > 0 && (
                                <div style={{ display: "grid", gap: 10 }}>
                                  {interactionActions(uiAnalysis.interactions).map((action, index) => (
                                    <div key={`${action.action || "action"}-${index}`} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                                      <span
                                        style={{
                                          width: 6,
                                          height: 6,
                                          borderRadius: "50%",
                                          background: "#c4c8bc",
                                          marginTop: 7,
                                          flexShrink: 0,
                                        }}
                                      />
                                      <div>
                                        <div style={{ fontSize: 13, color: "#2e3230", fontWeight: 700 }}>
                                          {action.action || "Interaction"}
                                        </div>
                                        {action.description && (
                                          <div style={{ marginTop: 2, fontSize: 12, color: "#74796e", lineHeight: 1.5 }}>
                                            {action.description}
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>

                            <div style={{ marginBottom: 8 }}>
                              <div style={{ fontSize: 11, letterSpacing: "0.08em", color: "#4a7c59", marginBottom: 10 }}>
                                LEADS TO
                              </div>
                              <div style={{ fontSize: 13, color: "#74796e", lineHeight: 1.6 }}>
                                {uiAnalysis.outputs?.description || "No output details available."}
                              </div>
                            </div>
                          </>
                        ) : isEntryRoute ? (
                          <div style={{ marginBottom: route.summary ? 8 : 18 }}>
                            {fileError && (
                              <div
                                style={{
                                  marginBottom: 10,
                                  color: "#c0392b",
                                  fontSize: 12,
                                }}
                              >
                                {fileError}
                              </div>
                            )}
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                void enrichFile(route);
                              }}
                              disabled={isGeneratingFile}
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 8,
                                background: "#4a7c59",
                                color: "#ffffff",
                                border: "none",
                                borderRadius: 8,
                                padding: "8px 16px",
                                fontSize: 13,
                                fontFamily: "'Nunito Sans', sans-serif",
                                cursor: isGeneratingFile ? "wait" : "pointer",
                                opacity: isGeneratingFile ? 0.85 : 1,
                              }}
                            >
                              {isGeneratingFile ? (
                                <>
                                  <Loader2 size={14} style={{ animation: "terra-spin 1s linear infinite" }} />
                                  Analyzing...
                                </>
                              ) : (
                                "Analyze this screen →"
                              )}
                            </button>
                          </div>
                        ) : null}

                        {!isEntryRoute && route.parameters.length > 0 && (
                          <div style={{ marginBottom: 18 }}>
                            <div style={{ fontSize: 11, letterSpacing: "0.08em", color: "#4a7c59", marginBottom: 10 }}>
                              PARAMETERS
                            </div>
                            <div style={{ display: "grid", gap: 8 }}>
                              {route.parameters.map((param, index) => (
                                <div key={`${param.name || "param"}-${index}`} style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                                  <span style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 13, color: "#2e3230" }}>
                                    {param.name || "parameter"}
                                  </span>
                                  {param.type && (
                                    <span style={{ border: "1px solid #c4c8bc", borderRadius: 999, padding: "2px 8px", fontSize: 11, color: "#5f655b", background: "#fffdf9" }}>
                                      {param.type}
                                    </span>
                                  )}
                                  <span style={{ border: "1px solid #c4c8bc", borderRadius: 999, padding: "2px 8px", fontSize: 11, color: "#5f655b", background: "#fffdf9", textTransform: "lowercase" }}>
                                    {parameterSource(param)}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {!isEntryRoute && requestResponse ? (
                          <>
                            {renderSchemaSection("REQUEST", requestResponse.request, true)}
                            {renderSchemaSection("RESPONSE", requestResponse.response, false)}
                          </>
                        ) : !isEntryRoute ? (
                          <div style={{ marginBottom: 18 }}>
                            {routeError && (
                              <div
                                style={{
                                  marginBottom: 10,
                                  color: "#c0392b",
                                  fontSize: 12,
                                }}
                              >
                                {routeError}
                              </div>
                            )}
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                void enrichRoute(route);
                              }}
                              disabled={isGenerating}
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 8,
                                background: "#4a7c59",
                                color: "#ffffff",
                                border: "none",
                                borderRadius: 8,
                                padding: "8px 16px",
                                fontSize: 13,
                                fontFamily: "'Nunito Sans', sans-serif",
                                cursor: isGenerating ? "wait" : "pointer",
                                opacity: isGenerating ? 0.85 : 1,
                              }}
                            >
                              {isGenerating ? (
                                <>
                                  <Loader2 size={14} style={{ animation: "terra-spin 1s linear infinite" }} />
                                  Analyzing...
                                </>
                              ) : (
                                "Generate Request/Response Details"
                              )}
                            </button>
                          </div>
                        ) : null}

                        {!isEntryRoute && phases.length > 0 && (
                          <div style={{ marginBottom: 16 }}>
                            <div style={{ fontSize: 11, letterSpacing: "0.08em", color: "#4a7c59", marginBottom: 10 }}>
                              HOW IT WORKS
                            </div>
                            <div style={{ display: "grid", gap: 14 }}>
                              {phases.map((phase, phaseIndex) => (
                                <div key={`${phase.name || phase.title || "phase"}-${phaseIndex}`}>
                                  <div style={{ fontSize: 13, fontWeight: 700, color: "#2e3230" }}>
                                    {phaseIndex + 1}. {phase.name || phase.title || `Phase ${phaseIndex + 1}`}
                                  </div>
                                  {phase.description && (
                                    <div style={{ marginTop: 4, fontSize: 13, color: "#74796e", lineHeight: 1.6 }}>
                                      {phase.description}
                                    </div>
                                  )}
                                  {(phase.steps || []).map((step, stepIndex) => (
                                    <div
                                      key={`${step.label || step.action || "step"}-${stepIndex}`}
                                      style={{
                                        marginTop: 8,
                                        marginLeft: 14,
                                        display: "flex",
                                        gap: 10,
                                        alignItems: "flex-start",
                                      }}
                                    >
                                      <span
                                        style={{
                                          width: 6,
                                          height: 6,
                                          borderRadius: "50%",
                                          background: "#c4c8bc",
                                          marginTop: 7,
                                          flexShrink: 0,
                                        }}
                                      />
                                      <div style={{ minWidth: 0 }}>
                                        <div style={{ fontSize: 13, color: "#2e3230" }}>
                                          {step.label || step.action || "Step"}
                                        </div>
                                        {(step.description || step.detail) && (
                                          <div style={{ marginTop: 2, fontSize: 12, color: "#74796e", lineHeight: 1.5 }}>
                                            {step.description || step.detail}
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
