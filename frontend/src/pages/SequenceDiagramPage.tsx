import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";

import { API_BASE } from "../api/client";

declare global {
  interface Window {
    mermaid?: {
      initialize: (config: Record<string, unknown>) => void;
      render: (id: string, definition: string) => Promise<{ svg: string }>;
    };
  }
}

type Participant = {
  id?: string;
  label?: string;
  type?: string;
};

type Step = {
  type?: string;
  label?: string;
  technical?: string;
  is_error_path?: boolean;
};

type Phase = {
  phase_id?: string;
  name?: string;
  description?: string;
  steps?: Step[];
  color?: string;
};

type SequencePayload = {
  method: string;
  path: string;
  handler?: string | null;
  complexity: string;
  participants: Participant[];
  phases: Phase[];
  has_database: boolean;
  has_external: boolean;
};

type SequenceDiagramPageProps = {
  projectId: string;
  routeId: string;
};

const METHOD_STYLES: Record<string, { background: string; color: string }> = {
  GET: { background: "#dbeafe", color: "#1d4ed8" },
  POST: { background: "#dcfce7", color: "#15803d" },
  PUT: { background: "#fef9c3", color: "#854d0e" },
  DELETE: { background: "#fee2e2", color: "#b91c1c" },
  PATCH: { background: "#f3e8ff", color: "#7e22ce" },
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

function sanitizeLabel(value?: string) {
  return value || "Unknown";
}

function mermaidSafeId(value: string, fallback: string) {
  const cleaned = value.replace(/[^a-zA-Z0-9_]/g, "_");
  return cleaned || fallback;
}

function escapeMermaidLabel(value: string) {
  return value.replace(/"/g, '\\"');
}

function plainMermaidLabel(value: string) {
  return value.replace(/"/g, "");
}

function orderedParticipants(participants: Participant[]) {
  const order = { client: 0, component: 1, service: 1, database: 2, external: 3 };
  return [...participants].sort((a, b) => {
    const left = order[(a.type || "component") as keyof typeof order] ?? 1;
    const right = order[(b.type || "component") as keyof typeof order] ?? 1;
    return left - right;
  });
}

function getSourceParticipant(step: Step, participants: Participant[]) {
  const client = participants.find((participant) => participant.type === "client")?.id;
  const component = participants.find((participant) => participant.type === "component" || participant.type === "service")?.id;

  switch (step.type) {
    case "db_read":
    case "db_write":
    case "service_call":
    case "conditional":
    case "external":
      return component || client || "client";
    case "response":
      return component || client || "client";
    default:
      return component || client || "client";
  }
}

function getTargetParticipant(step: Step, participants: Participant[]) {
  const client = participants.find((participant) => participant.type === "client")?.id;
  const component = participants.find((participant) => participant.type === "component" || participant.type === "service")?.id;
  const database = participants.find((participant) => participant.type === "database")?.id;
  const external = participants.find((participant) => participant.type === "external")?.id;

  switch (step.type) {
    case "db_read":
    case "db_write":
      return database || component || client || "client";
    case "external":
      return external || component || client || "client";
    case "response":
      return client || component || "client";
    case "conditional":
    case "service_call":
      return component || client || "client";
    default:
      return component || client || "client";
  }
}

function buildMermaidDiagram(route: SequencePayload) {
  const ordered = orderedParticipants(route.participants || []).map((participant, index) => ({
    ...participant,
    id: mermaidSafeId(String(participant.id || participant.label || `participant_${index}`), `participant_${index}`),
  }));

  const lines = ["sequenceDiagram"];
  ordered.forEach((participant) => {
    const safeLabel = plainMermaidLabel(sanitizeLabel(participant.label));
    lines.push(`  participant ${participant.id} as ${safeLabel}`);
  });

  const clientId = ordered.find((participant) => participant.type === "client")?.id;
  const componentId = ordered.find((participant) => participant.type === "component")?.id;
  if (clientId && componentId) {
    lines.push(`  ${clientId}->>${componentId}: ${escapeMermaidLabel(`${route.method} ${route.path}`)}`);
  }

  route.phases.forEach((phase, phaseIndex) => {
    const firstParticipant = ordered[0]?.id;
    const lastParticipant = ordered[ordered.length - 1]?.id;
    if (firstParticipant && lastParticipant) {
      lines.push(`  Note over ${firstParticipant},${lastParticipant}: ${escapeMermaidLabel(sanitizeLabel(phase.name || `Phase ${phaseIndex + 1}`))}`);
    }

    (phase.steps || []).forEach((step) => {
      const source = getSourceParticipant(step, ordered);
      const target = getTargetParticipant(step, ordered);
      if (step.type === "db_read") {
        lines.push(`  ${source}->>${target}: ${escapeMermaidLabel(step.label || "Step")}`);
        lines.push(`  ${target}-->>${source}: result`);
      } else if (step.type === "db_write") {
        lines.push(`  ${source}->>${target}: ${escapeMermaidLabel(step.label || "Step")}`);
        lines.push(`  ${target}-->>${source}: saved`);
      } else {
        const arrow = step.is_error_path ? "-->>" : (step.type === "response" ? "-->>" : "->>");
        lines.push(`  ${source}${arrow}${target}: ${escapeMermaidLabel(step.label || "Step")}`);
      }
    });
  });

  return lines.join("\n");
}

function navigateTo(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export default function SequenceDiagramPage({ projectId, routeId }: SequenceDiagramPageProps) {
  const [data, setData] = useState<SequencePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [diagramError, setDiagramError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetch(`${API_BASE}/projects/${projectId}/sequence/${routeId}`)
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok) {
          throw new Error(body?.detail || "Failed to load sequence diagram");
        }
        return body as SequencePayload;
      })
      .then((body) => {
        if (!cancelled) {
          setData(body);
        }
      })
      .catch((fetchError) => {
        if (!cancelled) {
          setError(fetchError instanceof Error ? fetchError.message : "Failed to load sequence diagram");
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
  }, [projectId, routeId]);

  const participants = useMemo(() => (Array.isArray(data?.participants) ? data?.participants : []), [data]);
  const phases = useMemo(() => (Array.isArray(data?.phases) ? data?.phases : []), [data]);

  useEffect(() => {
    if (!data || participants.length === 0 || phases.length === 0) {
      const container = document.getElementById("mermaid-container");
      if (container) {
        container.innerHTML = "";
      }
      setDiagramError(null);
      return;
    }

    let cancelled = false;

    async function renderDiagram() {
      try {
        const mermaid = window.mermaid;
        const route = data;
        if (!mermaid || !route) {
          return;
        }
        const diagramStr = buildMermaidDiagram(route);
        const container = document.getElementById("mermaid-container");
        if (!container) {
          return;
        }
        const renderId = `sequence_diagram_${routeId.replace(/[^a-zA-Z0-9_]/g, "_")}`;
        const { svg } = await mermaid.render(renderId, diagramStr);
        if (!cancelled) {
          container.innerHTML = svg;
          const svgEl = container.querySelector("svg");
          if (svgEl) {
            const actors = svgEl.querySelectorAll<SVGGraphicsElement>(".actor");
            const total = actors.length;
            const half = Math.floor(total / 2);
            for (let index = half; index < total; index += 1) {
              actors[index].style.display = "none";
            }
          }
          setDiagramError(null);
        }
      } catch (renderError) {
        if (!cancelled) {
          setDiagramError(renderError instanceof Error ? renderError.message : "Failed to render Mermaid diagram");
        }
      }
    }

    if (window.mermaid) {
      void renderDiagram();
      return () => {
        cancelled = true;
      };
    }

    const existingScript = document.querySelector('script[data-mermaid-sequence="true"]') as HTMLScriptElement | null;
    if (existingScript) {
      existingScript.addEventListener("load", () => {
        if (window.mermaid) {
          window.mermaid.initialize({
            startOnLoad: false,
            theme: "base",
            themeVariables: {
              primaryColor: "#f5f1ea",
              primaryTextColor: "#2e3230",
              primaryBorderColor: "#c4c8bc",
              lineColor: "#2e3230",
              secondaryColor: "#faf6f0",
              tertiaryColor: "#f5f1ea",
              fontFamily: "Nunito Sans, sans-serif",
              fontSize: "14px",
            },
          });
          void renderDiagram();
        }
      }, { once: true });
      return () => {
        cancelled = true;
      };
    }

    const script = document.createElement("script");
    script.src = "https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.6.1/mermaid.min.js";
    script.async = true;
    script.dataset.mermaidSequence = "true";
    script.onload = () => {
      if (!window.mermaid || cancelled) {
        return;
      }
      window.mermaid.initialize({
        startOnLoad: false,
        theme: "base",
        themeVariables: {
          primaryColor: "#f5f1ea",
          primaryTextColor: "#2e3230",
          primaryBorderColor: "#c4c8bc",
          lineColor: "#2e3230",
          secondaryColor: "#faf6f0",
          tertiaryColor: "#f5f1ea",
          fontFamily: "Nunito Sans, sans-serif",
          fontSize: "14px",
        },
      });
      void renderDiagram();
    };
    script.onerror = () => {
      if (!cancelled) {
        setDiagramError("Failed to load Mermaid");
      }
    };
    document.head.appendChild(script);

    return () => {
      cancelled = true;
    };
  }, [data, participants, phases, routeId]);

  if (loading) {
    return (
      <div style={{ minHeight: "calc(100vh - 120px)", display: "grid", placeItems: "center", background: "#faf6f0", borderRadius: 18, color: "#2e3230", fontFamily: "'Nunito Sans', sans-serif" }}>
        <div style={{ display: "grid", placeItems: "center", gap: 12 }}>
          <Loader2 size={28} style={{ color: "#4a7c59", animation: "terra-spin 1s linear infinite" }} />
          <div style={{ fontSize: 15, color: "#74796e" }}>Loading sequence diagram...</div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ minHeight: "calc(100vh - 120px)", background: "#faf6f0", borderRadius: 18, padding: 24, color: "#c0392b", fontFamily: "'Nunito Sans', sans-serif" }}>
        {error || "Sequence diagram not available"}
      </div>
    );
  }

  const methodStyle = getMethodStyle(data.method);
  const complexityStyle = getComplexityStyle(data.complexity);

  return (
    <div style={{ minHeight: "calc(100vh - 120px)", background: "#faf6f0", borderRadius: 18, padding: 24, color: "#2e3230", fontFamily: "'Nunito Sans', sans-serif" }}>
      <div style={{ marginBottom: 24 }}>
        <button
          type="button"
          onClick={() => navigateTo(`/projects/${projectId}/api-explorer`)}
          style={{ border: "none", background: "transparent", padding: 0, marginBottom: 18, color: "#4a7c59", fontSize: 14, fontWeight: 700, cursor: "pointer", fontFamily: "'Nunito Sans', sans-serif" }}
        >
          ← API Explorer
        </button>

        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span style={{ borderRadius: 6, padding: "6px 12px", fontSize: 11, fontWeight: 700, letterSpacing: "0.04em", ...methodStyle }}>
            {data.method}
          </span>
          <span style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 20, color: "#2e3230" }}>
            {data.path}
          </span>
        </div>
        <div style={{ marginTop: 8, color: "#74796e", fontSize: 14 }}>
          {data.handler || "Unknown handler"}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
          <span style={{ borderRadius: 999, padding: "4px 8px", fontSize: 11, textTransform: "capitalize", ...complexityStyle }}>
            {data.complexity}
          </span>
          {data.has_database && (
            <span style={{ background: "#f5f1ea", color: "#74796e", borderRadius: 999, padding: "4px 8px", fontSize: 11, border: "1px solid #d8d4cc" }}>
              DB
            </span>
          )}
          {data.has_external && (
            <span style={{ background: "#f5f1ea", color: "#74796e", borderRadius: 999, padding: "4px 8px", fontSize: 11, border: "1px solid #d8d4cc" }}>
              External
            </span>
          )}
        </div>
      </div>

      <div style={{ display: "grid", gap: 28 }}>
        <section style={{ background: "#fffdf9", border: "1px solid #ddd8ce", borderRadius: 16, padding: 20, overflowX: "auto" }}>
          {participants.length === 0 || phases.length === 0 ? (
            <div style={{ color: "#74796e", fontSize: 14 }}>No participant or phase data available for this route yet.</div>
          ) : (
            <>
              <div
                id="mermaid-container"
                style={{
                  background: "white",
                  borderRadius: "12px",
                  border: "1px solid #c4c8bc",
                  padding: "32px",
                  overflowX: "auto",
                  minHeight: "300px",
                }}
              />
              {diagramError && (
                <div style={{ marginTop: 12, color: "#c0392b", fontSize: 13 }}>
                  {diagramError}
                </div>
              )}
            </>
          )}
        </section>

        <section style={{ background: "#fffdf9", border: "1px solid #ddd8ce", borderRadius: 16, padding: 20 }}>
          <h2 style={{ margin: "0 0 18px", fontFamily: "'Literata', serif", fontSize: 18, color: "#2e3230" }}>
            What happens, step by step
          </h2>
          {phases.length === 0 ? (
            <div style={{ color: "#74796e", fontSize: 14 }}>No phase walkthrough is available for this route yet.</div>
          ) : (
            <div style={{ display: "grid", gap: 18 }}>
              {phases.map((phase, phaseIndex) => (
                <div key={`${phase.phase_id || phase.name || phaseIndex}`}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#2e3230" }}>
                    {phaseIndex + 1}. {sanitizeLabel(phase.name)}
                  </div>
                  {phase.description && (
                    <div style={{ marginTop: 4, fontSize: 13, color: "#74796e", lineHeight: 1.6 }}>
                      {phase.description}
                    </div>
                  )}
                  <div style={{ display: "grid", gap: 8, marginTop: 10, paddingLeft: 14 }}>
                    {(phase.steps || []).map((step, stepIndex) => (
                      <div key={`${phase.phase_id || phaseIndex}-walk-${stepIndex}`} style={{ color: step.is_error_path ? "#b91c1c" : "#2e3230" }}>
                        <div style={{ fontSize: 12, fontWeight: 700 }}>
                          {step.is_error_path ? "⚠️ " : ""}{step.label || "Step"}
                        </div>
                        {step.technical && (
                          <div style={{ marginTop: 2, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 11, color: "#74796e" }}>
                            {step.technical}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
