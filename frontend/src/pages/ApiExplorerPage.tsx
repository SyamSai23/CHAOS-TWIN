import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";

import { API_BASE } from "../api/client";
import AIChatBubble, { AskCopilotButton, requestAIChatPrompt } from "../components/AIChatBubble";

type SchemaFieldData = {
  name?: string;
  field?: string;
  type?: string;
  required?: boolean | "required";
  description?: string;
  fields?: SchemaFieldData[];
};

type RouteParameter = SchemaFieldData & {
  source?: string;
  location?: string;
  in?: string;
};

type RequestResponseSection = {
  description?: string;
  body?: SchemaFieldData[];
  fields?: SchemaFieldData[];
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
  request_body?: SchemaFieldData[];
  response_fields?: SchemaFieldData[];
  request_description?: string;
  response_description?: string;
  response?: {
    fields?: SchemaFieldData[];
  } | null;
  analysis_data?: {
    phases?: RoutePhase[];
  } | null;
  analysis?: {
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

type RouteWithFeature = {
  route: ApiRoute;
  featureName: string;
};

type ConnectedRoute = {
  route: ApiRoute;
  featureName: string;
  reason: "same resource" | "same feature";
};

type RouteCallerFile = {
  file: string;
  file_type: string;
  summary?: string;
  match_reason?: string;
};

type RouteCallerChainLayer = {
  layer: string;
  label: string;
  icon?: string;
  description?: string;
  files: RouteCallerFile[];
};

type RouteCallerChainResponse = {
  route?: string;
  chain: RouteCallerChainLayer[];
  found: boolean;
};

type SequencePreviewPayload = {
  method: string;
  path: string;
  handler?: string | null;
  complexity: string;
  participants: unknown[];
  phases: RoutePhase[];
  has_database: boolean;
  has_external: boolean;
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

function sequencePreviewStorageKey(projectId: string) {
  return `chaos-twin:sequence-preview:${projectId}`;
}

function buildSequencePreview(route: ApiRoute, phases: RoutePhase[]): SequencePreviewPayload {
  return {
    method: route.method,
    path: route.path,
    handler: route.handler,
    complexity: route.complexity,
    participants: Array.isArray(route.participants) ? route.participants : [],
    phases,
    has_database: route.has_database,
    has_external: route.has_external,
  };
}

function fileName(filePath: string) {
  return filePath.split("/").pop() || filePath;
}

function routeHasPathParam(path: string) {
  return path.split("/").some((segment) => segment.startsWith(":") || (segment.startsWith("{") && segment.endsWith("}")));
}

function routeSortRank(route: ApiRoute) {
  const method = route.method.toUpperCase();
  if (method === "GET") {
    return routeHasPathParam(route.path) ? 1 : 0;
  }
  if (method === "POST") return 2;
  if (method === "PUT" || method === "PATCH") return 3;
  if (method === "DELETE") return 4;
  return 5;
}

function baseResource(path: string) {
  const segments = path
    .split("/")
    .map((segment) => segment.trim())
    .filter(Boolean)
    .filter((segment) => segment !== "api" && !/^v\d+$/i.test(segment));

  return segments.find((segment) => !segment.startsWith(":") && !(segment.startsWith("{") && segment.endsWith("}"))) || null;
}

function callerTypeStyle(fileType: string) {
  const normalized = fileType.toLowerCase();
  if (normalized === "page") return { color: "#f97316", background: "#fff7ed" };
  if (normalized === "component") return { color: "#2563eb", background: "#eff6ff" };
  if (normalized === "service") return { color: "#4a7c59", background: "#eef4f1" };
  if (normalized === "hook") return { color: "#7c3aed", background: "#f5f3ff" };
  if (normalized === "store") return { color: "#d97706", background: "#fffbeb" };
  return { color: "#74796e", background: "#f3f4f6" };
}

function callChainConnectorLabel(layer: string) {
  if (layer === "entry") return "calls";
  if (layer === "direct") return "used by";
  return "";
}

const CallChainLayer = ({
  layer,
  isLast,
}: {
  layer: { layer: string; label: string; icon?: string; description?: string; files: RouteCallerFile[] };
  isLast: boolean;
}) => {
  const connectorLabel = callChainConnectorLabel(layer.layer);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
      <div
        style={{
          width: "100%",
          background: "#faf8f5",
          border: "1px solid #e8e4dc",
          borderRadius: 10,
          padding: "12px 16px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: layer.description ? 6 : 10 }}>
          <span style={{ fontSize: 18, lineHeight: 1 }}>{layer.icon || "📄"}</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#2e3230" }}>{layer.label}</span>
        </div>
        {layer.description && (
          <div style={{ fontSize: 11, color: "#74796e", fontStyle: "italic", marginBottom: 10 }}>
            {layer.description}
          </div>
        )}

        <div style={{ display: "grid", gap: 0 }}>
          {layer.files.map((file, index) => {
            const badgeStyle = callerTypeStyle(file.file_type);
            return (
              <div
                key={`${file.file}-${index}`}
                style={{
                  paddingTop: index === 0 ? 0 : 10,
                  marginTop: index === 0 ? 0 : 10,
                  borderTop: index === 0 ? "none" : "1px solid #f0ede8",
                }}
              >
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "minmax(0, 1fr) auto",
                    gap: 10,
                    alignItems: "center",
                  }}
                >
                  <div
                    style={{
                      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                      fontSize: 12,
                      color: "#2e3230",
                      minWidth: 0,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {file.file}
                  </div>
                  <span
                    style={{
                      ...badgeStyle,
                      borderRadius: 999,
                      padding: "3px 8px",
                      fontSize: 10,
                      fontWeight: 700,
                      textTransform: "lowercase",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {file.file_type}
                  </span>
                </div>
                {file.summary && (
                  <div style={{ marginTop: 6, fontSize: 11, color: "#74796e", lineHeight: 1.5 }}>
                    {file.summary}
                  </div>
                )}
                {file.match_reason && (
                  <div style={{ marginTop: 6, fontSize: 10, color: "#9ca3af" }}>
                    {file.match_reason}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {!isLast && (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", margin: "10px 0" }}>
          <div style={{ width: 2, height: 20, background: "#e8e4dc" }} />
          <div style={{ fontSize: 10, color: "#9ca3af", marginTop: 4 }}>{connectorLabel}</div>
          <div style={{ fontSize: 14, color: "#c4c8bc", lineHeight: 1 }}>▼</div>
        </div>
      )}
    </div>
  );
};

const CallChainSkeleton = () => (
  <div style={{ display: "grid", gap: 12 }}>
    <style>
      {`@keyframes api-call-chain-pulse { 0% { opacity: 0.55; } 50% { opacity: 1; } 100% { opacity: 0.55; } }`}
    </style>
    {[0, 1, 2].map((index) => (
      <div
        key={index}
        style={{
          background: "#faf8f5",
          border: "1px solid #e8e4dc",
          borderRadius: 10,
          padding: "12px 16px",
          animation: `api-call-chain-pulse 1.4s ease-in-out ${index * 0.12}s infinite`,
        }}
      >
        <div style={{ width: 140, height: 14, borderRadius: 999, background: "#ece6dc", marginBottom: 10 }} />
        <div style={{ width: "78%", height: 12, borderRadius: 999, background: "#f0ede8", marginBottom: 8 }} />
        <div style={{ width: "62%", height: 12, borderRadius: 999, background: "#f0ede8" }} />
      </div>
    ))}
  </div>
);

function sectionFields(section?: RequestResponseSection) {
  if (Array.isArray(section?.body)) {
    return section.body;
  }
  if (Array.isArray(section?.fields)) {
    return section.fields;
  }
  return [];
}

function inputFields(section?: UiInputsSection) {
  return Array.isArray(section?.fields) ? section?.fields ?? [] : [];
}

function interactionActions(section?: UiInteractionsSection) {
  return Array.isArray(section?.actions) ? section?.actions ?? [] : [];
}

const SchemaField = ({
  field,
  depth = 0,
}: {
  field: SchemaFieldData;
  depth?: number;
}) => {
  const [expanded, setExpanded] = React.useState(true);
  const isRequired = field.required === true || field.required === "required";
  const hasNested = Array.isArray(field.fields) && field.fields.length > 0;
  const fieldType = field.type || "any";

  return (
    <div style={{ marginLeft: depth * 16, marginBottom: 6 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 10px",
          background: depth === 0 ? "#faf8f5" : "#f5f1ea",
          borderRadius: 8,
          border: `1px solid ${isRequired ? "#4a7c59" : "#e8e4dc"}`,
          cursor: hasNested ? "pointer" : "default",
          transition: "background 0.1s",
        }}
        onClick={() => hasNested && setExpanded((current) => !current)}
      >
        {hasNested && (
          <span style={{ fontSize: 10, color: "#74796e", width: 12 }}>
            {expanded ? "▾" : "▸"}
          </span>
        )}

        <span style={{ fontFamily: "monospace", fontSize: 13, fontWeight: 700, color: "#2e3230" }}>
          {field.name || field.field || "field"}
        </span>

        {isRequired && (
          <span style={{ color: "#dc2626", fontSize: 13, fontWeight: 900, lineHeight: 1 }}>*</span>
        )}

        <span
          style={{
            fontSize: 10,
            color: "#fff",
            background:
              fieldType === "string"
                ? "#4a7c59"
                : fieldType === "number" || fieldType === "integer"
                  ? "#2563eb"
                  : fieldType === "boolean"
                    ? "#7c3aed"
                    : fieldType === "array"
                      ? "#d97706"
                      : fieldType === "object"
                        ? "#0891b2"
                        : "#74796e",
            borderRadius: 5,
            padding: "2px 7px",
            fontFamily: "monospace",
            fontWeight: 600,
          }}
        >
          {fieldType}
        </span>

        {!isRequired && (
          <span style={{ fontSize: 10, color: "#9ca3af", fontStyle: "italic", marginLeft: "auto" }}>
            optional
          </span>
        )}
      </div>

      {field.description && (
        <div
          style={{
            fontSize: 11,
            color: "#74796e",
            marginTop: 3,
            marginLeft: depth * 16 + (hasNested ? 20 : 10),
            paddingLeft: 4,
          }}
        >
          {field.description}
        </div>
      )}

      {hasNested && expanded && (
        <div style={{ marginTop: 4, paddingLeft: 8, borderLeft: "2px solid #e8e4dc" }}>
          {field.fields?.map((nestedField, index) => (
            <SchemaField key={`${nestedField.name || nestedField.field || "field"}-${index}`} field={nestedField} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
};

const ExampleJsonBlock = ({ fields, title }: { fields: SchemaFieldData[]; title: string }) => {
  const [visible, setVisible] = React.useState(false);
  const [copied, setCopied] = React.useState(false);

  const buildExample = (schemaFields: SchemaFieldData[]): Record<string, unknown> => {
    const obj: Record<string, unknown> = {};
    schemaFields.slice(0, 12).forEach((field) => {
      const name = (field.name || field.field || "").toLowerCase();
      const type = (field.type || "").toLowerCase();
      if (!name) return;

      if (field.fields?.length) {
        obj[name] = buildExample(field.fields);
      } else if (type === "array") {
        obj[name] = [];
      } else if (type === "boolean") {
        obj[name] = true;
      } else if (type === "number" || type === "integer" || type === "int") {
        obj[name] =
          name.includes("count") || name.includes("total")
            ? 42
            : name.includes("price") || name.includes("amount")
              ? 29.99
              : 1;
      } else {
        if (name.includes("id")) obj[name] = "usr_01HXYZ123";
        else if (name.includes("email")) obj[name] = "jane@example.com";
        else if (name.includes("password")) obj[name] = "••••••••";
        else if (name.includes("username") || name === "user") obj[name] = "jane_doe";
        else if (name.includes("name") && name.includes("first")) obj[name] = "Jane";
        else if (name.includes("name") && name.includes("last")) obj[name] = "Doe";
        else if (name.includes("name")) obj[name] = "Jane Doe";
        else if (name.includes("token") || name.includes("jwt") || name.includes("access")) {
          obj[name] = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c3JfMDEifQ.abc123";
        } else if (name.includes("refresh")) {
          obj[name] = "eyJhbGciOiJIUzI1NiJ9.refresh.xyz789";
        } else if (name.includes("url") || name.includes("image") || name.includes("avatar")) {
          obj[name] = "https://example.com/avatar.jpg";
        } else if (name.includes("phone")) {
          obj[name] = "+1-555-0123";
        } else if (name.includes("address")) {
          obj[name] = "123 Main St, Seattle WA";
        } else if (name.includes("created") || name.includes("updated") || name.includes("at")) {
          obj[name] = "2024-03-15T10:30:00Z";
        } else if (name.includes("date")) {
          obj[name] = "2024-03-15";
        } else if (name.includes("status")) {
          obj[name] = "active";
        } else if (name.includes("message") || name.includes("description")) {
          obj[name] = "Operation successful";
        } else if (name.includes("role")) {
          obj[name] = "user";
        } else if (name.includes("title")) {
          obj[name] = "Example Title";
        } else if (name.includes("body") || name.includes("content")) {
          obj[name] = "Lorem ipsum content here";
        } else if (name.includes("tags")) {
          obj[name] = ["tag1", "tag2"];
        } else {
          obj[name] = `example_${name}`;
        }
      }
    });
    return obj;
  };

  if (fields.length === 0) return null;
  const example = buildExample(fields);
  const jsonStr = JSON.stringify(example, null, 2);

  const colorizeJson = (json: string) =>
    json
      .replace(/("[\w]+")\s*:/g, '<span style="color:#86b89a">$1</span>:')
      .replace(/:\s*(".*?")/g, ': <span style="color:#fbbf24">$1</span>')
      .replace(/:\s*(true|false)/g, ': <span style="color:#a78bfa">$1</span>')
      .replace(/:\s*(\d+\.?\d*)/g, ': <span style="color:#60a5fa">$1</span>');

  return (
    <div style={{ marginTop: 12 }}>
      <button
        onClick={() => setVisible((current) => !current)}
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: "#4a7c59",
          background: "transparent",
          border: "1px solid #4a7c59",
          borderRadius: 6,
          padding: "4px 12px",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <span>{visible ? "▾" : "▸"}</span>
        {visible ? "Hide" : "Show"} example {title.toLowerCase()}
      </button>

      {visible && (
        <div
          style={{
            marginTop: 8,
            background: "#0f1a14",
            borderRadius: 10,
            border: "1px solid #2d4a35",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "8px 14px",
              borderBottom: "1px solid #1a2e1f",
            }}
          >
            <span style={{ fontSize: 11, color: "#86b89a", fontFamily: "monospace", fontWeight: 600 }}>
              {title} · application/json
            </span>
            <button
              onClick={() => {
                void navigator.clipboard.writeText(jsonStr);
                setCopied(true);
                window.setTimeout(() => setCopied(false), 2000);
              }}
              style={{
                fontSize: 10,
                color: copied ? "#4ade80" : "#86b89a",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                fontWeight: 600,
              }}
            >
              {copied ? "✓ Copied" : "Copy"}
            </button>
          </div>

          <pre
            style={{
              margin: 0,
              padding: "14px 16px",
              fontSize: 12,
              lineHeight: 1.7,
              fontFamily: "monospace",
              color: "#e8f5ee",
              overflowX: "auto",
            }}
            dangerouslySetInnerHTML={{ __html: colorizeJson(jsonStr) }}
          />
        </div>
      )}
    </div>
  );
};

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
  const [callersCache, setCallersCache] = useState<Record<string, RouteCallerChainResponse>>({});
  const [callersLoading, setCallersLoading] = useState<Record<string, boolean>>({});
  const [visibleCallers, setVisibleCallers] = useState<Record<string, boolean>>({});

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
    setCallersCache({});
    setCallersLoading({});
    setVisibleCallers({});

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

  function openSequenceDiagram(route: ApiRoute, phases: RoutePhase[]) {
    try {
      const payload = buildSequencePreview(route, phases);
      window.sessionStorage.setItem(
        sequencePreviewStorageKey(projectId),
        JSON.stringify(payload),
      );
    } catch (error) {
      console.warn("Failed to persist sequence preview payload:", error);
    }

    if (route.route_id) {
      navigateTo(`/projects/${projectId}/sequence/${route.route_id}`);
      return;
    }

    navigateTo(`/projects/${projectId}/sequence`);
  }

  async function handleWhoCalls(route: ApiRoute) {
    const routeId = traceRouteId(route);
    setVisibleCallers((current) => ({ ...current, [routeId]: true }));

    if (Object.prototype.hasOwnProperty.call(callersCache, routeId) || callersLoading[routeId]) {
      return;
    }

    setCallersLoading((current) => ({ ...current, [routeId]: true }));
    try {
      const search = new URLSearchParams({
        method: route.method,
        path: route.path,
      });
      const response = await fetch(
        `${API_BASE}/projects/${projectId}/analyze/callers?${search.toString()}`,
      );
      const body = await response.json().catch(() => null);
      const payload =
        body && typeof body === "object" && Array.isArray((body as RouteCallerChainResponse).chain)
          ? (body as RouteCallerChainResponse)
          : { chain: [], found: false };
      setCallersCache((current) => ({ ...current, [routeId]: payload }));
    } catch (error) {
      console.error("Failed to trace callers:", error);
      setCallersCache((current) => ({ ...current, [routeId]: { chain: [], found: false } }));
    } finally {
      setCallersLoading((current) => ({ ...current, [routeId]: false }));
    }
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

  const allRoutes = useMemo<RouteWithFeature[]>(
    () =>
      features.flatMap((feature) =>
        feature.routes.map((route) => ({
          route,
          featureName: feature.name,
        })),
      ),
    [features],
  );

  const connectedRoutesByKey = useMemo<Record<string, ConnectedRoute[]>>(() => {
    const map: Record<string, ConnectedRoute[]> = {};

    allRoutes.forEach((current) => {
      const currentKey = routeKey(current.route);
      const currentBase = baseResource(current.route.path);

      map[currentKey] = allRoutes
        .map((candidate) => {
          if (routeKey(candidate.route) === currentKey) {
            return null;
          }

          const candidateBase = baseResource(candidate.route.path);

          let reason: ConnectedRoute["reason"] | null = null;
          if (currentBase && candidateBase && currentBase === candidateBase) {
            reason = "same resource";
          } else if (current.featureName === candidate.featureName) {
            reason = "same feature";
          }

          if (!reason) {
            return null;
          }

          return {
            route: candidate.route,
            featureName: candidate.featureName,
            reason,
          };
        })
        .filter((connection): connection is ConnectedRoute => Boolean(connection))
        .sort((a, b) => {
          const rankDiff = routeSortRank(a.route) - routeSortRank(b.route);
          if (rankDiff !== 0) return rankDiff;
          return a.route.path.localeCompare(b.route.path);
        })
        .slice(0, 6);
    });

    return map;
  }, [allRoutes]);
  const expandedRoute = useMemo(() => {
    if (!openRouteKey) {
      return null;
    }

    return allRoutes.find((item) => routeKey(item.route) === openRouteKey)?.route ?? null;
  }, [allRoutes, openRouteKey]);
  const apiExplorerSuggestedQuestions = useMemo(() => {
    if (expandedRoute) {
      return [
        "What validates the input for this route?",
        "What database tables does this route touch?",
        "What happens if this route fails?",
        "Which frontend components call this route?",
      ];
    }

    return [
      "Which route is most complex?",
      "Which routes touch the database?",
      "Are there any routes without authentication?",
    ];
  }, [expandedRoute]);
  const apiExplorerPageContext = useMemo(() => {
    if (expandedRoute) {
      return {
        page: "api_explorer",
        route_method: expandedRoute.method,
        route_path: expandedRoute.path,
        route_handler: expandedRoute.handler || expandedRoute.file,
      };
    }

    return { page: "api_explorer" };
  }, [expandedRoute]);

  function askAboutRoute(route: ApiRoute) {
    requestAIChatPrompt({
      question: `Explain the ${route.method.toUpperCase()} ${route.path} route. What does it do, what validates the input, and what are the failure cases?`,
      pageContext: {
        page: "api_explorer",
        entity_type: "route",
        route_method: route.method,
        route_path: route.path,
        route_handler: route.handler || route.file,
      },
    });
  }

  function askAboutApiFile(filePath: string) {
    const fileLabel = fileName(filePath);
    requestAIChatPrompt({
      question: `Tell me about ${fileLabel}. What is its role, what does it export, and what depends on it?`,
      pageContext: {
        page: "api_explorer",
        entity_type: "file",
        entity_name: fileLabel,
        entity_path: filePath,
      },
    });
  }

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
    <>
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
                const requestFields = Array.isArray(route.request_body)
                  ? route.request_body
                  : sectionFields(requestResponse?.request).length > 0
                    ? sectionFields(requestResponse?.request)
                    : route.parameters;
                const responseFields = Array.isArray(route.response_fields)
                  ? route.response_fields
                  : Array.isArray(route.response?.fields)
                    ? route.response.fields
                    : sectionFields(requestResponse?.response);
                const requestDescription = route.request_description || requestResponse?.request?.description;
                const responseDescription = route.response_description || requestResponse?.response?.description;
                const requestNotes = requestResponse?.request?.notes;
                const responseNotes = requestResponse?.response?.notes;
                const connectedRoutes = connectedRoutesByKey[key] ?? [];
                const connectedResource = baseResource(route.path);
                const callersData = callersCache[routeId] ?? { chain: [], found: false };
                const callersVisible = visibleCallers[routeId] === true;
                const isLoadingCallers = callersLoading[routeId] === true;
                return (
                  <div key={key}>
                    <div
                      className="ask-copilot-anchor"
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
                        <AskCopilotButton inline onAsk={() => askAboutRoute(route)} />
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
                            {route.file && (
                              <div
                                className="ask-copilot-anchor"
                                style={{
                                  display: "flex",
                                  alignItems: "center",
                                  gap: 8,
                                  marginTop: 8,
                                  color: "#74796e",
                                  fontSize: 12,
                                  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                                }}
                              >
                                <span>{route.handler || fileName(route.file)}</span>
                                <AskCopilotButton inline onAsk={() => askAboutApiFile(route.file)} />
                              </div>
                            )}
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

                              <button
                                type="button"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  openSequenceDiagram(route, phases);
                                }}
                                style={{
                                  fontSize: 11,
                                  color: "#4a7c59",
                                  background: "#eef4f1",
                                  border: "1px solid #c9ddd1",
                                  borderRadius: 999,
                                  padding: "6px 10px",
                                  cursor: "pointer",
                                  fontWeight: 700,
                                }}
                              >
                                Open Sequence Diagram →
                              </button>
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

                        {!isEntryRoute && (
                          <>
                            <div style={{ marginBottom: 20 }}>
                              <div
                                style={{
                                  fontSize: 11,
                                  fontWeight: 700,
                                  letterSpacing: "0.08em",
                                  color: "#4a7c59",
                                  textTransform: "uppercase",
                                  marginBottom: 10,
                                }}
                              >
                                Request
                              </div>

                              {requestDescription && (
                                <p style={{ fontSize: 13, color: "#74796e", fontStyle: "italic", marginBottom: 10 }}>
                                  {requestDescription}
                                </p>
                              )}

                              {requestFields.length > 0 ? (
                                <>
                                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                    {requestFields.map((field, index) => (
                                      <SchemaField key={`${field.name || field.field || "field"}-${index}`} field={field} depth={0} />
                                    ))}
                                  </div>
                                  <ExampleJsonBlock fields={requestFields} title="Request Body" />
                                </>
                              ) : (
                                <div style={{ fontSize: 12, color: "#9ca3af", fontStyle: "italic" }}>
                                  {route.method === "GET" || route.method === "DELETE"
                                    ? "No request body — parameters passed via URL"
                                    : "No request body schema available"}
                                </div>
                              )}

                              {requestNotes && (
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
                                  {requestNotes}
                                </div>
                              )}
                            </div>

                            <div style={{ marginBottom: 20 }}>
                              <div
                                style={{
                                  fontSize: 11,
                                  fontWeight: 700,
                                  letterSpacing: "0.08em",
                                  color: "#4a7c59",
                                  textTransform: "uppercase",
                                  marginBottom: 10,
                                }}
                              >
                                Response
                              </div>

                              {responseDescription && (
                                <p style={{ fontSize: 13, color: "#74796e", fontStyle: "italic", marginBottom: 10 }}>
                                  {responseDescription}
                                </p>
                              )}

                              {responseFields.length > 0 ? (
                                <>
                                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                    {responseFields.map((field, index) => (
                                      <SchemaField key={`${field.name || field.field || "field"}-${index}`} field={field} depth={0} />
                                    ))}
                                  </div>
                                  <ExampleJsonBlock fields={responseFields} title="Response" />
                                </>
                              ) : (
                                <div style={{ fontSize: 12, color: "#9ca3af", fontStyle: "italic" }}>
                                  No response schema available
                                </div>
                              )}

                              {responseNotes && (
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
                                  {responseNotes}
                                </div>
                              )}
                            </div>
                          </>
                        )}

                        {!isEntryRoute && !requestResponse ? (
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

                        {!isEntryRoute && connectedRoutes.length > 0 && (
                          <div style={{ marginBottom: 20 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                              <div
                                style={{
                                  fontSize: 11,
                                  fontWeight: 700,
                                  letterSpacing: "0.08em",
                                  color: "#4a7c59",
                                  textTransform: "uppercase",
                                }}
                              >
                                Connected Routes
                              </div>
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
                                {connectedRoutes.length}
                              </span>
                              {connectedResource && (
                                <span
                                  style={{
                                    fontSize: 11,
                                    color: "#74796e",
                                  }}
                                >
                                  · {connectedResource} resource
                                </span>
                              )}
                            </div>

                            <div
                              style={{
                                background: "#f5f1ea",
                                border: "1px solid #e8e4dc",
                                borderRadius: 10,
                                overflow: "hidden",
                              }}
                            >
                              <div
                                style={{
                                  display: "grid",
                                  gridTemplateColumns: "52px minmax(0, 1fr) auto",
                                  gap: 12,
                                  alignItems: "center",
                                  padding: "8px 12px",
                                  borderBottom: "1px solid #e8e4dc",
                                  fontSize: 11,
                                  color: "#9ca3af",
                                  textTransform: "uppercase",
                                  letterSpacing: "0.06em",
                                  background: "#f8f4ed",
                                }}
                              >
                                <span>Method</span>
                                <span>Path</span>
                                <span>Relationship</span>
                              </div>
                              {connectedRoutes.map((connectedRoute, index) => {
                                const connectedKey = routeKey(connectedRoute.route);
                                const connectedMethodStyle = getMethodStyle(connectedRoute.route.method);
                                const relationBadgeStyle =
                                  connectedRoute.reason === "same resource"
                                    ? {
                                        color: "#4a7c59",
                                        background: "#eef4f1",
                                        border: "1px solid #d9e9df",
                                      }
                                    : {
                                        color: "#2563eb",
                                        background: "#eff6ff",
                                        border: "1px solid #dbeafe",
                                      };
                                return (
                                  <div
                                    key={connectedKey}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      setOpenRouteKey(connectedKey);
                                    }}
                                    style={{
                                      display: "grid",
                                      gridTemplateColumns: "52px minmax(0, 1fr) auto",
                                      alignItems: "center",
                                      gap: 12,
                                      padding: "10px 12px",
                                      cursor: "pointer",
                                      borderBottom: index < connectedRoutes.length - 1 ? "1px solid #e8e4dc" : "none",
                                      transition: "background 0.15s ease",
                                    }}
                                    onMouseEnter={(event) => {
                                      event.currentTarget.style.background = "#eee8de";
                                    }}
                                    onMouseLeave={(event) => {
                                      event.currentTarget.style.background = "transparent";
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
                                        ...connectedMethodStyle,
                                      }}
                                    >
                                      {connectedRoute.route.method.toUpperCase()}
                                    </div>
                                    <div style={{ minWidth: 0 }}>
                                      <div
                                        style={{
                                          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                                          fontSize: 13,
                                          color: "#2e3230",
                                          overflow: "hidden",
                                          textOverflow: "ellipsis",
                                          whiteSpace: "nowrap",
                                        }}
                                      >
                                        {connectedRoute.route.path}
                                      </div>
                                    </div>
                                    <span
                                      style={{
                                        fontSize: 11,
                                        ...relationBadgeStyle,
                                        borderRadius: 999,
                                        padding: "4px 8px",
                                        textTransform: "lowercase",
                                        whiteSpace: "nowrap",
                                      }}
                                    >
                                      {connectedRoute.reason}
                                    </span>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {!isEntryRoute && (
                          <div style={{ marginBottom: 20 }}>
                            {!callersVisible ? (
                              <button
                                type="button"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void handleWhoCalls(route);
                                }}
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: 6,
                                  padding: "6px 12px",
                                  background: "transparent",
                                  color: "#4a7c59",
                                  border: "1px solid #4a7c59",
                                  borderRadius: 8,
                                  fontSize: 12,
                                  fontWeight: 600,
                                  cursor: "pointer",
                                }}
                              >
                                🔍 Who calls this route?
                              </button>
                            ) : (
                              <div>
                                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                                  <div
                                    style={{
                                      fontSize: 11,
                                      fontWeight: 700,
                                      letterSpacing: "0.08em",
                                      color: "#4a7c59",
                                      textTransform: "uppercase",
                                    }}
                                  >
                                    Who calls this
                                  </div>
                                  {!isLoadingCallers && (
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
                                      {callersData.chain.reduce((count, layer) => count + layer.files.length, 0)}
                                    </span>
                                  )}
                                </div>

                                {isLoadingCallers ? (
                                  <CallChainSkeleton />
                                ) : callersData.found && callersData.chain.length > 0 ? (
                                  <div style={{ display: "grid", gap: 0 }}>
                                    {callersData.chain.map((layer, index) => (
                                      <CallChainLayer key={`${layer.layer}-${index}`} layer={layer} isLast={index === callersData.chain.length - 1} />
                                    ))}
                                  </div>
                                ) : (
                                  <div
                                    style={{
                                      background: "#faf8f5",
                                      border: "1px solid #e8e4dc",
                                      borderRadius: 10,
                                      padding: "14px 16px",
                                      color: "#74796e",
                                    }}
                                  >
                                    <div style={{ fontSize: 14, fontWeight: 700, color: "#2e3230", marginBottom: 6 }}>
                                      🔍 No callers found
                                    </div>
                                    <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                                      This route may be called externally or the codebase
                                      <br />
                                      hasn&apos;t been fully indexed yet.
                                    </div>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )}

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
      <AIChatBubble
        projectId={projectId}
        context={{
          page: "api_explorer",
          pageContext: apiExplorerPageContext,
          resetKey: expandedRoute ? routeKey(expandedRoute) : "api-explorer",
        }}
        suggestedQuestions={apiExplorerSuggestedQuestions}
      />
    </>
  );
}
