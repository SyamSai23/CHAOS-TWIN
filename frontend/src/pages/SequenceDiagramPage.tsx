import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { API_BASE } from "../api/client";
import AIChatBubble, { AskCopilotButton, requestAIChatPrompt } from "../components/AIChatBubble";

type Participant = {
  id?: string;
  label?: string;
  type?: string;
  file_path?: string | null;
  file_type?: string | null;
  summary?: string | null;
  metadata?: {
    file_path?: string | null;
    file_type?: string | null;
    summary?: string | null;
    [key: string]: unknown;
  } | null;
  [key: string]: unknown;
};

type PhaseStep = {
  type?: string;
  label?: string;
  description?: string;
  action?: string;
  technical?: string;
  is_error_path?: boolean;
  [key: string]: unknown;
} | string;

type Phase = {
  phase_id?: string;
  name?: string;
  description?: string;
  steps?: PhaseStep[];
  color?: string;
};

type ErrorPath = {
  condition?: string;
  status_code?: number | string;
  message?: string;
  [key: string]: unknown;
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
  error_paths?: ErrorPath[];
};

type SequenceDiagramPageProps = {
  projectId: string;
  routeId: string | null;
};

type Message = {
  id: number;
  from: string;
  to: string;
  label: string;
  type: "call" | "return" | "async" | "error";
  phase: string;
  phaseColor: string;
  stepDescription: string;
  technical: string;
  isErrorPath: boolean;
  stepType: string;
  sourceIndex: number;
};

type WalkthroughItem = {
  index: number;
  phaseName: string;
  phaseDescription: string;
  phaseColor: string;
  message: Message;
};

const PARTICIPANT_WIDTH = 120;
const PARTICIPANT_HEIGHT = 48;
const PARTICIPANT_SPACING = 180;
const ROW_HEIGHT = 60;
const DIAGRAM_PADDING = 40;
const PHASE_LABEL_WIDTH = 100;
const SELF_ARROW_WIDTH = 28;
const SELF_ARROW_HEIGHT = 22;

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

function navigateTo(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function sequencePreviewStorageKey(projectId: string) {
  return `chaos-twin:sequence-preview:${projectId}`;
}

function isSequencePayload(value: unknown): value is SequencePayload {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Partial<SequencePayload>;
  return (
    typeof candidate.method === "string" &&
    typeof candidate.path === "string" &&
    typeof candidate.complexity === "string" &&
    Array.isArray(candidate.participants) &&
    Array.isArray(candidate.phases) &&
    typeof candidate.has_database === "boolean" &&
    typeof candidate.has_external === "boolean"
  );
}

function sanitizeLabel(value?: string | null) {
  return value?.trim() || "Unknown";
}

function safeStepText(step: PhaseStep, fallback: string) {
  if (typeof step === "string") {
    return step;
  }
  return step.description || step.action || step.label || fallback;
}

function safeStepTechnical(step: PhaseStep) {
  return typeof step === "string" ? "" : String(step.technical || "");
}

function safeStepType(step: PhaseStep) {
  return typeof step === "string" ? "internal" : String(step.type || "internal");
}

function participantFillColor(type?: string) {
  const normalized = String(type || "").toLowerCase();
  if (normalized === "client") return "#e8f5ee";
  if (normalized === "database") return "#fef3c7";
  if (normalized === "external") return "#ede9fe";
  return "#f0f9ff";
}

function phaseColor(phaseName?: string) {
  const normalized = String(phaseName || "").toLowerCase();
  if (normalized.includes("validation")) return "#f97316";
  if (normalized.includes("processing")) return "#3b82f6";
  if (normalized.includes("database")) return "#a855f7";
  if (normalized.includes("response")) return "#22c55e";
  if (normalized.includes("error")) return "#dc2626";
  return "#74796e";
}

function normalizeParticipants(route: SequencePayload) {
  const seenIds = new Set<string>();
  const participants: Participant[] = [];

  const pushParticipant = (participant: Participant) => {
    const baseId =
      sanitizeLabel(String(participant.id || participant.label || participant.type || "participant"))
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_") || "participant";
    let nextId = baseId;
    let suffix = 1;
    while (seenIds.has(nextId)) {
      nextId = `${baseId}_${suffix}`;
      suffix += 1;
    }
    seenIds.add(nextId);
    participants.push({
      ...participant,
      id: nextId,
      label: sanitizeLabel(participant.label || participant.id),
    });
  };

  (route.participants || []).forEach((participant) => {
    if (participant && typeof participant === "object") {
      pushParticipant(participant);
    }
  });

  const hasType = (type: string) =>
    participants.some((participant) => String(participant.type || "").toLowerCase() === type);

  const hasHandler = participants.some((participant) => {
    const type = String(participant.type || "").toLowerCase();
    return !["client", "database", "external"].includes(type);
  });

  if (!hasType("client")) {
    pushParticipant({ id: "client", label: "Client", type: "client" });
  }

  if (!hasHandler) {
    pushParticipant({
      id: "handler",
      label: sanitizeLabel(route.handler || "Backend"),
      type: "component",
    });
  }

  if (route.has_database && !hasType("database")) {
    pushParticipant({ id: "database", label: "Database", type: "database" });
  }

  if (route.has_external && !hasType("external")) {
    pushParticipant({ id: "external", label: "External", type: "external" });
  }

  const order = { client: 0, component: 1, service: 1, route: 1, controller: 1, database: 2, external: 3 };
  return [...participants].sort((left, right) => {
    const leftOrder = order[String(left.type || "component").toLowerCase() as keyof typeof order] ?? 1;
    const rightOrder = order[String(right.type || "component").toLowerCase() as keyof typeof order] ?? 1;
    return leftOrder - rightOrder;
  });
}

function getClientParticipant(participants: Participant[]) {
  return participants.find((participant) => String(participant.type || "").toLowerCase() === "client") || participants[0];
}

function getHandlerParticipant(participants: Participant[]) {
  return (
    participants.find((participant) => {
      const type = String(participant.type || "").toLowerCase();
      return !["client", "database", "external"].includes(type);
    }) || participants[0]
  );
}

function getDatabaseParticipant(participants: Participant[]) {
  return participants.find((participant) => String(participant.type || "").toLowerCase() === "database");
}

function getExternalParticipant(participants: Participant[]) {
  return participants.find((participant) => String(participant.type || "").toLowerCase() === "external");
}

function buildMessages(route: SequencePayload, participants: Participant[]) {
  if (participants.length === 0) {
    return { happyPath: [] as Message[], errorPath: [] as Message[] };
  }

  const client = getClientParticipant(participants);
  const handler = getHandlerParticipant(participants);
  const database = getDatabaseParticipant(participants) || handler;
  const external = getExternalParticipant(participants) || handler;

  const firstPhase = route.phases[0];
  const firstPhaseName = sanitizeLabel(firstPhase?.name || "Request");
  const firstPhaseColor = phaseColor(firstPhase?.name || "request");

  const requestMessage: Message = {
    id: 0,
    from: String(client?.id || "client"),
    to: String(handler?.id || "handler"),
    label: `${route.method.toUpperCase()} ${route.path}`,
    type: "call",
    phase: firstPhaseName,
    phaseColor: firstPhaseColor,
    stepDescription: `Client sends ${route.method.toUpperCase()} ${route.path}`,
    technical: route.handler || "",
    isErrorPath: false,
    stepType: "request",
    sourceIndex: 0,
  };

  const stepMessages: Message[] = [];
  let nextId = 1;

  route.phases.forEach((phase, phaseIndex) => {
    const currentPhaseName = sanitizeLabel(phase.name || `Phase ${phaseIndex + 1}`);
    const currentPhaseColor = phase.color || phaseColor(phase.name);

    (phase.steps || []).forEach((step, stepIndex) => {
      const stepType = safeStepType(step);
      const label = safeStepText(step, `Step ${stepIndex + 1}`);
      const stepDescription = typeof step === "string" ? label : String(step.description || label);
      const technical = safeStepTechnical(step);
      const isErrorPath = typeof step === "string" ? false : Boolean(step.is_error_path);

      let from = String(handler?.id || "handler");
      let to = String(handler?.id || "handler");
      let type: Message["type"] = "call";

      if (stepType === "db_read" || stepType === "db_write") {
        to = String(database?.id || from);
        type = "call";
      } else if (stepType === "response") {
        to = String(client?.id || from);
        type = "return";
      } else if (stepType === "external") {
        to = String(external?.id || from);
        type = "async";
      } else if (stepType === "conditional") {
        to = from;
        type = "call";
      } else if (isErrorPath) {
        to = String(client?.id || from);
        type = "error";
      }

      stepMessages.push({
        id: nextId,
        from,
        to,
        label,
        type: isErrorPath ? "error" : type,
        phase: currentPhaseName,
        phaseColor: currentPhaseColor,
        stepDescription,
        technical,
        isErrorPath,
        stepType,
        sourceIndex: stepMessages.length + 1,
      });
      nextId += 1;
    });
  });

  const derivedErrorMessages = (route.error_paths || []).map((errorPath, index) => ({
    id: nextId + index,
    from: String(handler?.id || "handler"),
    to: String(client?.id || "client"),
    label: `${errorPath.status_code || "Error"} ${sanitizeLabel(errorPath.condition || errorPath.message || "Failure path")}`,
    type: "error" as const,
    phase: "Error Paths",
    phaseColor: "#dc2626",
    stepDescription: sanitizeLabel(errorPath.message || errorPath.condition || "An error response is returned to the client."),
    technical: String(errorPath.condition || errorPath.message || ""),
    isErrorPath: true,
    stepType: "error",
    sourceIndex: stepMessages.length + index + 1,
  }));

  return {
    happyPath: [requestMessage, ...stepMessages.filter((message) => !message.isErrorPath)],
    errorPath: [requestMessage, ...stepMessages.filter((message) => message.isErrorPath), ...derivedErrorMessages],
  };
}

function participantX(index: number) {
  return DIAGRAM_PADDING + PHASE_LABEL_WIDTH + index * PARTICIPANT_SPACING + PARTICIPANT_WIDTH / 2;
}

function messageY(index: number) {
  return DIAGRAM_PADDING + PARTICIPANT_HEIGHT + 36 + index * ROW_HEIGHT;
}

function truncateLabel(value: string, maxLength = 35) {
  return value.length > maxLength ? `${value.slice(0, maxLength - 1)}…` : value;
}

function participantMeta(participant?: Participant) {
  if (!participant) {
    return { filePath: null, fileType: null, summary: null };
  }

  return {
    filePath: String(participant.file_path || participant.metadata?.file_path || "") || null,
    fileType: String(participant.file_type || participant.metadata?.file_type || participant.type || "") || null,
    summary: String(participant.summary || participant.metadata?.summary || "") || null,
  };
}

function renderArrowHead(x: number, y: number, direction: 1 | -1, open: boolean, color: string) {
  if (open) {
    return (
      <g>
        <line x1={x} y1={y} x2={x - direction * 10} y2={y - 5} stroke={color} strokeWidth={2} />
        <line x1={x} y1={y} x2={x - direction * 10} y2={y + 5} stroke={color} strokeWidth={2} />
      </g>
    );
  }

  const points = direction === 1
    ? `${x},${y} ${x - 10},${y - 6} ${x - 10},${y + 6}`
    : `${x},${y} ${x + 10},${y - 6} ${x + 10},${y + 6}`;
  return <polygon points={points} fill={color} />;
}

export default function SequenceDiagramPage({ projectId, routeId }: SequenceDiagramPageProps) {
  const [data, setData] = useState<SequencePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState<number>(-1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1500);
  const [selectedParticipant, setSelectedParticipant] = useState<string | null>(null);
  const [hoveredMessage, setHoveredMessage] = useState<number | null>(null);
  const [showErrorPaths, setShowErrorPaths] = useState(false);
  const [selectedStep, setSelectedStep] = useState<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeStepRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!routeId) {
      try {
        const previewRaw = window.sessionStorage.getItem(sequencePreviewStorageKey(projectId));
        const preview = previewRaw ? JSON.parse(previewRaw) : null;
        setData(isSequencePayload(preview) ? preview : null);
      } catch {
        setData(null);
      }
      setLoading(false);
      setError(null);
      return;
    }

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

  const participants = useMemo(() => (data ? normalizeParticipants(data) : []), [data]);
  const participantIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    participants.forEach((participant, index) => {
      map.set(String(participant.id || `participant_${index}`), index);
    });
    return map;
  }, [participants]);
  const messageSets = useMemo(() => (data ? buildMessages(data, participants) : { happyPath: [] as Message[], errorPath: [] as Message[] }), [data, participants]);
  const visibleMessages = useMemo(
    () => (showErrorPaths ? messageSets.errorPath : messageSets.happyPath),
    [messageSets, showErrorPaths],
  );
  const walkthroughItems = useMemo<WalkthroughItem[]>(() => {
    const items: WalkthroughItem[] = [];
    visibleMessages.forEach((message, index) => {
      items.push({
        index,
        phaseName: message.phase,
        phaseDescription:
          data?.phases.find((phase) => sanitizeLabel(phase.name) === message.phase)?.description || "",
        phaseColor: message.phaseColor,
        message,
      });
    });
    return items;
  }, [data?.phases, visibleMessages]);

  const phaseBands = useMemo(() => {
    const bands: Array<{ phase: string; color: string; start: number; end: number }> = [];
    visibleMessages.forEach((message, index) => {
      const previous = bands[bands.length - 1];
      if (previous && previous.phase === message.phase) {
        previous.end = index;
      } else {
        bands.push({
          phase: message.phase,
          color: message.phaseColor,
          start: index,
          end: index,
        });
      }
    });
    return bands;
  }, [visibleMessages]);

  useEffect(() => {
    setIsPlaying(false);
    setCurrentStep(-1);
    setSelectedStep(null);
    setHoveredMessage(null);
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, [showErrorPaths, data?.method, data?.path]);

  useEffect(() => {
    if (currentStep >= visibleMessages.length) {
      setCurrentStep(visibleMessages.length > 0 ? visibleMessages.length - 1 : -1);
    }
    if (selectedStep !== null && selectedStep >= visibleMessages.length) {
      setSelectedStep(visibleMessages.length > 0 ? visibleMessages.length - 1 : null);
    }
  }, [currentStep, selectedStep, visibleMessages.length]);

  useEffect(() => {
    if (!isPlaying || visibleMessages.length === 0) {
      return undefined;
    }

    if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }

    intervalRef.current = setInterval(() => {
      setCurrentStep((previous) => {
        if (previous >= visibleMessages.length - 1) {
          setIsPlaying(false);
          if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
          return previous;
        }
        return previous + 1;
      });
    }, playbackSpeed);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [isPlaying, playbackSpeed, visibleMessages.length]);

  useEffect(() => {
    if (currentStep >= 0 && activeStepRef.current) {
      activeStepRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [currentStep]);

  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, []);
  const sequenceSuggestedQuestions = useMemo(
    () => [
      "What error handling exists in this flow?",
      "Which step is most likely to fail?",
      "How many database calls does this route make?",
      "What would a junior developer misunderstand about this flow?",
    ],
    [],
  );
  const sequencePageContext = useMemo(
    () => ({
      page: "sequence_diagram",
      route_method: data?.method ?? null,
      route_path: data?.path ?? null,
      phase_count: data?.phases.length ?? 0,
      step_count: visibleMessages.length,
    }),
    [data?.method, data?.path, data?.phases.length, visibleMessages.length],
  );

  function askAboutSequenceStep(stepLabel: string, stepPhase: string) {
    requestAIChatPrompt({
      question: `In the ${(data?.method || "route").toUpperCase()} ${data?.path || ""} route, tell me more about this step: ${stepLabel}. Which file handles this, and what could go wrong here?`,
      pageContext: {
        page: "sequence_diagram",
        entity_type: "step",
        route_method: data?.method ?? null,
        route_path: data?.path ?? null,
        step_label: stepLabel,
        step_phase: stepPhase,
      },
    });
  }

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

  if (!routeId && !data) {
    return (
      <>
        <div style={{ minHeight: "calc(100vh - 120px)", background: "#faf6f0", borderRadius: 18, padding: 24, color: "#2e3230", fontFamily: "'Nunito Sans', sans-serif" }}>
          <div style={{ marginBottom: 24 }}>
            <button
              type="button"
              onClick={() => navigateTo(`/projects/${projectId}/api-explorer`)}
              style={{ border: "none", background: "transparent", padding: 0, marginBottom: 18, color: "#4a7c59", fontSize: 14, fontWeight: 700, cursor: "pointer", fontFamily: "'Nunito Sans', sans-serif" }}
            >
              ← API Explorer
            </button>
            <h1 style={{ margin: 0, fontFamily: "'Literata', serif", fontSize: 28, color: "#2e3230" }}>Sequence Diagrams</h1>
            <p style={{ margin: "10px 0 0", color: "#74796e", fontSize: 14, lineHeight: 1.7, maxWidth: 720 }}>
              Sequence diagrams are available per route. Open a route from API Explorer and use the full-page sequence view to inspect the request flow step by step.
            </p>
          </div>

          <div style={{ background: "#fffdf9", border: "1px solid #ddd8ce", borderRadius: 16, padding: 24, maxWidth: 760 }}>
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 8 }}>No route selected yet</div>
            <div style={{ color: "#74796e", fontSize: 14, lineHeight: 1.7, marginBottom: 18 }}>
              This page exists, but it needs a specific route to render a diagram. Choose a route in API Explorer, then open its full sequence view.
            </div>
            <button
              type="button"
              onClick={() => navigateTo(`/projects/${projectId}/api-explorer`)}
              style={{
                background: "#4a7c59",
                color: "#fff",
                border: "none",
                borderRadius: 8,
                padding: "10px 16px",
                fontSize: 13,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              Open API Explorer
            </button>
          </div>
        </div>
        <AIChatBubble
          projectId={projectId}
          context={{
            page: "sequence_diagram",
            pageContext: sequencePageContext,
            resetKey: "sequence-empty",
          }}
          suggestedQuestions={sequenceSuggestedQuestions}
        />
      </>
    );
  }

  if (error || !data) {
    return (
      <>
        <div style={{ minHeight: "calc(100vh - 120px)", background: "#faf6f0", borderRadius: 18, padding: 24, color: "#c0392b", fontFamily: "'Nunito Sans', sans-serif" }}>
          {error || "Sequence diagram not available"}
        </div>
        <AIChatBubble
          projectId={projectId}
          context={{
            page: "sequence_diagram",
            pageContext: sequencePageContext,
            resetKey: "sequence-error",
          }}
          suggestedQuestions={sequenceSuggestedQuestions}
        />
      </>
    );
  }

  const methodStyle = getMethodStyle(data.method);
  const complexityStyle = getComplexityStyle(data.complexity);
  const totalWidth = Math.max(
    760,
    DIAGRAM_PADDING * 2 + PHASE_LABEL_WIDTH + Math.max(participants.length - 1, 0) * PARTICIPANT_SPACING + PARTICIPANT_WIDTH,
  );
  const totalHeight = DIAGRAM_PADDING * 2 + PARTICIPANT_HEIGHT + Math.max(visibleMessages.length, 1) * ROW_HEIGHT + 60;
  const selectedMessageIndex = selectedStep ?? currentStep;
  const selectedMessage = selectedMessageIndex >= 0 ? visibleMessages[selectedMessageIndex] : null;
  const selectedParticipantLabel = selectedParticipant
    ? participants.find((participant) => participant.id === selectedParticipant)?.label || selectedParticipant
    : null;
  const selectedParticipantMessageCount = selectedParticipant
    ? visibleMessages.filter((message) => message.from === selectedParticipant || message.to === selectedParticipant).length
    : 0;

  const togglePlay = () => {
    if (isPlaying) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      setIsPlaying(false);
      return;
    }

    if (visibleMessages.length === 0) {
      return;
    }

    if (currentStep >= visibleMessages.length - 1) {
      setCurrentStep(0);
    } else if (currentStep === -1) {
      setCurrentStep(0);
    }
    setIsPlaying(true);
  };

  const stepForward = () => {
    if (currentStep < visibleMessages.length - 1) {
      setCurrentStep((previous) => previous + 1);
    }
  };

  const stepBack = () => {
    if (currentStep > 0) {
      setCurrentStep((previous) => previous - 1);
    }
  };

  const reset = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setIsPlaying(false);
    setCurrentStep(-1);
    setSelectedStep(null);
  };

  return (
    <>
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

      {visibleMessages.length === 0 ? (
        <div style={{ background: "#fffdf9", border: "1px solid #ddd8ce", borderRadius: 16, padding: 24, color: "#74796e", fontSize: 14 }}>
          No phases or execution steps are available for this route yet.
        </div>
      ) : (
        <div style={{ display: "grid", gap: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() => setShowErrorPaths(false)}
              style={{
                border: "1px solid #c4c8bc",
                background: !showErrorPaths ? "#4a7c59" : "#fffdf9",
                color: !showErrorPaths ? "#fff" : "#4a7c59",
                borderRadius: 999,
                padding: "8px 14px",
                fontSize: 12,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              Happy Path ✓
            </button>
            <button
              type="button"
              onClick={() => setShowErrorPaths(true)}
              style={{
                border: "1px solid #e4b8b8",
                background: showErrorPaths ? "#dc2626" : "#fffdf9",
                color: showErrorPaths ? "#fff" : "#dc2626",
                borderRadius: 999,
                padding: "8px 14px",
                fontSize: 12,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              Show Error Paths
            </button>
            {selectedParticipant && (
              <span style={{ fontSize: 12, color: "#4a7c59", fontWeight: 700 }}>
                Showing {selectedParticipantLabel} interactions only — {selectedParticipantMessageCount} arrows
              </span>
            )}
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 1.6fr) minmax(320px, 1fr)",
              gap: 20,
              alignItems: "start",
            }}
          >
            <div style={{ display: "grid", gap: 16 }}>
              <section style={{ background: "#fffdf9", border: "1px solid #ddd8ce", borderRadius: 16, padding: 20, overflowX: "auto" }}>
                <svg width={totalWidth} height={totalHeight} viewBox={`0 0 ${totalWidth} ${totalHeight}`} role="img" aria-label="Interactive sequence diagram">
                  {phaseBands.map((band) => {
                    const startY = messageY(band.start) - ROW_HEIGHT / 2 + 6;
                    const bandHeight = (band.end - band.start + 1) * ROW_HEIGHT - 12;
                    const labelX = DIAGRAM_PADDING + 18;
                    const labelY = startY + bandHeight / 2;
                    return (
                      <g key={`${band.phase}-${band.start}`}>
                        <rect
                          x={DIAGRAM_PADDING}
                          y={startY}
                          width={totalWidth - DIAGRAM_PADDING * 2}
                          height={bandHeight}
                          fill={band.color}
                          fillOpacity={0.08}
                          rx={4}
                        />
                        <text
                          x={labelX}
                          y={labelY}
                          fontSize={10}
                          fontWeight={700}
                          fill={band.color}
                          textAnchor="start"
                          transform={`rotate(-90, ${labelX}, ${labelY})`}
                        >
                          {band.phase}
                        </text>
                      </g>
                    );
                  })}

                  {participants.map((participant, index) => {
                    const centerX = participantX(index);
                    const isSelected = selectedParticipant === participant.id;
                    const isDimmed = Boolean(selectedParticipant && !isSelected);
                    return (
                      <g
                        key={String(participant.id || index)}
                        onClick={() => setSelectedParticipant(isSelected ? null : String(participant.id || ""))}
                        style={{ cursor: "pointer", opacity: isDimmed ? 0.45 : 1 }}
                      >
                        <rect
                          x={centerX - PARTICIPANT_WIDTH / 2}
                          y={DIAGRAM_PADDING}
                          width={PARTICIPANT_WIDTH}
                          height={PARTICIPANT_HEIGHT}
                          rx={8}
                          fill={selectedParticipant && !isSelected ? "#f0ede8" : participantFillColor(participant.type)}
                          stroke={isSelected ? "#4a7c59" : "#c4c8bc"}
                          strokeWidth={isSelected ? 2.5 : 1.5}
                        />
                        <text
                          x={centerX}
                          y={DIAGRAM_PADDING + PARTICIPANT_HEIGHT / 2 + 5}
                          textAnchor="middle"
                          fontSize={13}
                          fontWeight={600}
                          fill="#2e3230"
                        >
                          {sanitizeLabel(participant.label)}
                        </text>
                        <line
                          x1={centerX}
                          y1={DIAGRAM_PADDING + PARTICIPANT_HEIGHT}
                          x2={centerX}
                          y2={totalHeight - DIAGRAM_PADDING}
                          stroke="#d1d5db"
                          strokeWidth={1.5}
                          strokeDasharray="6,4"
                        />
                      </g>
                    );
                  })}

                  {visibleMessages.map((message, index) => {
                    const fromIndex = participantIndexMap.get(message.from) ?? 0;
                    const toIndex = participantIndexMap.get(message.to) ?? fromIndex;
                    const fromX = participantX(fromIndex);
                    const toX = participantX(toIndex);
                    const y = messageY(index);
                    const isSelf = fromIndex === toIndex;
                    const isActive = currentStep === index;
                    const isHovered = hoveredMessage === index;
                    const isDimmed = Boolean(
                      selectedParticipant &&
                      message.from !== selectedParticipant &&
                      message.to !== selectedParticipant,
                    );
                    const arrowColor = isActive ? "#4a7c59" : message.isErrorPath ? "#dc2626" : "#2e3230";
                    const arrowOpacity = isDimmed ? 0.15 : 1;
                    const arrowWidth = isActive || isHovered ? 2.5 : 1.5;
                    const dashed = message.type === "return" || message.type === "error";
                    const openArrow = message.type === "return" || message.type === "async";
                    const label = truncateLabel(message.label);

                    return (
                      <g key={message.id}>
                        {isSelf ? (
                          <>
                            <path
                              d={`M ${fromX} ${y} h ${SELF_ARROW_WIDTH} v ${SELF_ARROW_HEIGHT} h -${SELF_ARROW_WIDTH}`}
                              fill="none"
                              stroke={arrowColor}
                              strokeWidth={arrowWidth}
                              strokeDasharray={dashed ? "6,4" : undefined}
                              opacity={arrowOpacity}
                            />
                            {renderArrowHead(fromX, y + SELF_ARROW_HEIGHT, -1, openArrow, arrowColor)}
                            <text
                              x={fromX + SELF_ARROW_WIDTH / 2}
                              y={y - 8}
                              textAnchor="middle"
                              fontSize={11}
                              fill={arrowColor}
                              opacity={arrowOpacity}
                            >
                              {label}
                            </text>
                            <rect
                              x={fromX - 8}
                              y={y - 20}
                              width={SELF_ARROW_WIDTH + 20}
                              height={SELF_ARROW_HEIGHT + 32}
                              fill="transparent"
                              onClick={() => {
                                setSelectedStep(index);
                                setCurrentStep(index);
                              }}
                              onMouseEnter={() => setHoveredMessage(index)}
                              onMouseLeave={() => setHoveredMessage(null)}
                              style={{ cursor: "pointer" }}
                            />
                          </>
                        ) : (
                          <>
                            <line
                              x1={fromX}
                              y1={y}
                              x2={toX}
                              y2={y}
                              stroke={arrowColor}
                              strokeWidth={arrowWidth}
                              strokeDasharray={dashed ? "6,4" : undefined}
                              opacity={arrowOpacity}
                            />
                            {renderArrowHead(toX, y, toX > fromX ? 1 : -1, openArrow, arrowColor)}
                            <text
                              x={(fromX + toX) / 2}
                              y={y - 8}
                              textAnchor="middle"
                              fontSize={11}
                              fill={arrowColor}
                              opacity={arrowOpacity}
                            >
                              {label}
                            </text>
                            <rect
                              x={Math.min(fromX, toX) - 14}
                              y={y - 20}
                              width={Math.abs(toX - fromX) + 28}
                              height={40}
                              fill="transparent"
                              onClick={() => {
                                setSelectedStep(index);
                                setCurrentStep(index);
                              }}
                              onMouseEnter={() => setHoveredMessage(index)}
                              onMouseLeave={() => setHoveredMessage(null)}
                              style={{ cursor: "pointer" }}
                            />
                          </>
                        )}
                      </g>
                    );
                  })}
                </svg>
              </section>

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "12px 16px",
                  background: "#f5f1ea",
                  borderRadius: 12,
                  border: "1px solid #e8e4dc",
                }}
              >
                <button
                  type="button"
                  onClick={stepBack}
                  disabled={currentStep <= 0}
                  style={{
                    border: "1px solid #d8d4cc",
                    background: currentStep <= 0 ? "#f5f1ea" : "#fffdf9",
                    color: currentStep <= 0 ? "#b3b1aa" : "#2e3230",
                    borderRadius: 8,
                    padding: "8px 12px",
                    fontSize: 13,
                    cursor: currentStep <= 0 ? "not-allowed" : "pointer",
                  }}
                >
                  ⏮
                </button>

                <button
                  type="button"
                  onClick={togglePlay}
                  style={{
                    background: isPlaying ? "#dc2626" : "#4a7c59",
                    color: "#fff",
                    border: "none",
                    borderRadius: 8,
                    padding: "8px 20px",
                    fontWeight: 700,
                    fontSize: 13,
                    cursor: "pointer",
                  }}
                >
                  {currentStep === -1 ? "▶ Play" : isPlaying ? "⏸ Pause" : "▶ Resume"}
                </button>

                <button
                  type="button"
                  onClick={stepForward}
                  disabled={currentStep >= visibleMessages.length - 1}
                  style={{
                    border: "1px solid #d8d4cc",
                    background: currentStep >= visibleMessages.length - 1 ? "#f5f1ea" : "#fffdf9",
                    color: currentStep >= visibleMessages.length - 1 ? "#b3b1aa" : "#2e3230",
                    borderRadius: 8,
                    padding: "8px 12px",
                    fontSize: 13,
                    cursor: currentStep >= visibleMessages.length - 1 ? "not-allowed" : "pointer",
                  }}
                >
                  ⏭
                </button>

                {currentStep >= 0 && (
                  <button
                    type="button"
                    onClick={reset}
                    style={{ fontSize: 12, color: "#74796e", background: "transparent", border: "none", cursor: "pointer" }}
                  >
                    ↺ Reset
                  </button>
                )}

                {currentStep >= 0 && visibleMessages.length > 0 && (
                  <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{ flex: 1, height: 4, background: "#e8e4dc", borderRadius: 2, overflow: "hidden" }}>
                      <div
                        style={{
                          height: "100%",
                          width: `${((currentStep + 1) / visibleMessages.length) * 100}%`,
                          background: "#4a7c59",
                          transition: "width 0.3s ease",
                          borderRadius: 2,
                        }}
                      />
                    </div>
                    <span style={{ fontSize: 12, color: "#74796e", whiteSpace: "nowrap" }}>
                      Step {currentStep + 1} of {visibleMessages.length}
                    </span>
                  </div>
                )}

                <select
                  value={playbackSpeed}
                  onChange={(event) => setPlaybackSpeed(Number(event.target.value))}
                  style={{ fontSize: 11, padding: "4px 8px", borderRadius: 6, border: "1px solid #e8e4dc", background: "#fff", color: "#2e3230" }}
                >
                  <option value={2500}>0.5×</option>
                  <option value={1500}>1×</option>
                  <option value={800}>2×</option>
                  <option value={400}>4×</option>
                </select>
              </div>
            </div>

            <div style={{ display: "grid", gap: 16 }}>
              {selectedMessage && (
                <section style={{ background: "#fffdf9", border: "1px solid #ddd8ce", borderRadius: 16, padding: 18 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: 12, marginBottom: 12 }}>
                    <div>
                      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: selectedMessage.phaseColor, marginBottom: 6 }}>
                        Step {selectedMessageIndex + 1} · {selectedMessage.phase}
                      </div>
                      <div style={{ fontSize: 16, fontWeight: 700, color: "#2e3230" }}>
                        {selectedMessage.label}
                      </div>
                    </div>
                    {selectedStep !== null && (
                      <button
                        type="button"
                        onClick={() => setSelectedStep(null)}
                        style={{
                          border: "none",
                          background: "transparent",
                          color: "#74796e",
                          fontSize: 18,
                          cursor: "pointer",
                          lineHeight: 1,
                        }}
                      >
                        ×
                      </button>
                    )}
                  </div>

                  <div style={{ fontSize: 13, color: "#545e57", lineHeight: 1.7 }}>
                    {selectedMessage.stepDescription || "No description available."}
                  </div>

                  {selectedMessage.technical && (
                    <div
                      style={{
                        marginTop: 10,
                        background: "#f5f1ea",
                        borderRadius: 8,
                        padding: "8px 10px",
                        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                        fontSize: 11,
                        color: "#2e3230",
                      }}
                    >
                      {selectedMessage.technical}
                    </div>
                  )}

                  <div style={{ display: "grid", gap: 6, marginTop: 14, fontSize: 12, color: "#74796e" }}>
                    <div><strong style={{ color: "#2e3230" }}>Type:</strong> {selectedMessage.stepType}</div>
                    <div>
                      <strong style={{ color: "#2e3230" }}>From:</strong>{" "}
                      {sanitizeLabel(participants[participantIndexMap.get(selectedMessage.from) ?? 0]?.label)}
                      {" → "}
                      {sanitizeLabel(participants[participantIndexMap.get(selectedMessage.to) ?? 0]?.label)}
                    </div>
                  </div>

                  {(() => {
                    const sourceParticipant = participants[participantIndexMap.get(selectedMessage.from) ?? 0];
                    const meta = participantMeta(sourceParticipant);
                    if (!meta.filePath && !meta.summary) {
                      return null;
                    }

                    return (
                      <div style={{ marginTop: 14, borderTop: "1px solid #eee7db", paddingTop: 12 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
                          {meta.fileType && (
                            <span
                              style={{
                                background: "#eef4f1",
                                color: "#4a7c59",
                                borderRadius: 999,
                                padding: "4px 8px",
                                fontSize: 10,
                                fontWeight: 700,
                                textTransform: "uppercase",
                              }}
                            >
                              {meta.fileType}
                            </span>
                          )}
                          {meta.filePath && (
                            <span style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 11, color: "#2e3230" }}>
                              {meta.filePath}
                            </span>
                          )}
                        </div>
                        {meta.summary && (
                          <div style={{ fontSize: 12, color: "#74796e", lineHeight: 1.6 }}>
                            {meta.summary}
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </section>
              )}

              <section style={{ background: "#fffdf9", border: "1px solid #ddd8ce", borderRadius: 16, padding: 20 }}>
                <h2 style={{ margin: "0 0 18px", fontFamily: "'Literata', serif", fontSize: 18, color: "#2e3230" }}>
                  Walkthrough
                </h2>
                <div style={{ maxHeight: totalHeight, overflowY: "auto", paddingRight: 6, display: "grid", gap: 14 }}>
                  {walkthroughItems.map((item, index) => {
                    const isActive = currentStep === index;
                    const isHovered = hoveredMessage === index;
                    return (
                      <div key={`${item.phaseName}-${item.message.id}`}>
                        {(index === 0 || walkthroughItems[index - 1]?.phaseName !== item.phaseName) && (
                          <div style={{ marginBottom: 8 }}>
                            <div style={{ fontSize: 14, fontWeight: 700, color: "#2e3230" }}>
                              {item.phaseName}
                            </div>
                            {item.phaseDescription && (
                              <div style={{ marginTop: 4, fontSize: 12, color: "#74796e", lineHeight: 1.6 }}>
                                {item.phaseDescription}
                              </div>
                            )}
                          </div>
                        )}
                        <div
                          className="ask-copilot-anchor"
                          ref={isActive ? activeStepRef : null}
                          onClick={() => {
                            setCurrentStep(index);
                            setSelectedStep(index);
                          }}
                          onMouseEnter={() => setHoveredMessage(index)}
                          onMouseLeave={() => setHoveredMessage(null)}
                          style={{
                            background: isActive || isHovered ? "#eef4f1" : "transparent",
                            borderLeft: isActive ? "3px solid #4a7c59" : "3px solid transparent",
                            padding: "8px 12px",
                            cursor: "pointer",
                            transition: "all 0.15s",
                            borderRadius: 8,
                          }}
                        >
                          <div style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "space-between" }}>
                            <div style={{ fontSize: 12, fontWeight: 700, color: item.message.isErrorPath ? "#b91c1c" : "#2e3230" }}>
                              {item.message.label}
                            </div>
                            <AskCopilotButton
                              inline
                              onAsk={() => askAboutSequenceStep(item.message.label, item.phaseName)}
                            />
                          </div>
                          <div style={{ marginTop: 4, fontSize: 12, color: "#74796e", lineHeight: 1.6 }}>
                            {item.message.stepDescription}
                          </div>
                          {item.message.technical && (
                            <div style={{ marginTop: 4, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 11, color: "#5f655b" }}>
                              {item.message.technical}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            </div>
          </div>
        </div>
      )}
      </div>
      <AIChatBubble
        projectId={projectId}
        context={{
          page: "sequence_diagram",
          pageContext: sequencePageContext,
          resetKey: `${data.method}:${data.path}:${showErrorPaths ? "error" : "happy"}`,
        }}
        suggestedQuestions={sequenceSuggestedQuestions}
      />
    </>
  );
}
