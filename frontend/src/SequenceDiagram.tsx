import { type ReactNode } from "react";
import InlineCodePeek, { type InlineCodePeekAnchor } from "./components/InlineCodePeek";

/* ── Types matching the API response ── */

export type Participant = {
  id: string;
  label: string;
  type: "client" | "component" | "database" | "external" | "queue";
  order: number;
  metadata?: {
    role?: string;
    file_path?: string | null;
    symbol_name?: string | null;
    class_name?: string | null;
    line_start?: number | null;
    line_end?: number | null;
    anchor_kind?: string | null;
    target_rank?: number | null;
    selection_reason?: string | null;
  };
};

export type SequenceCodeAnchor = {
  file_path?: string | null;
  symbol_name?: string | null;
  class_name?: string | null;
  line_start?: number | null;
  line_end?: number | null;
  anchor_kind?: string | null;
  target_rank?: number | null;
  selection_reason?: string | null;
};

export type Message = {
  id: string;
  from_participant: string;
  to_participant: string;
  label: string;
  message_type: "call" | "return" | "async";
  step: number;
  order: number;
  sequence_source?: string;
  source_stage_step?: number | null;
  source_stage_type?: string | null;
  file_path?: string | null;
  symbol_name?: string | null;
  class_name?: string | null;
  line_start?: number | null;
  line_end?: number | null;
  confidence?: number | null;
  is_inferred?: boolean;
  provenance?: string | null;
  code_anchor?: SequenceCodeAnchor | null;
  best_target?: SequenceCodeAnchor | null;
};

export type Flow = {
  flow_id: string;
  flow_name: string;
  route_example: string | null;
  message_ids: string[];
};

export type SequenceData = {
  project_id: string;
  route_id?: string;
  route_method?: string;
  route_path?: string;
  participants: Participant[];
  messages: Message[];
  flows: Flow[];
  metadata: {
    analysis_signature?: string | null;
    component_count: number;
    step_count: number;
    has_external_calls: boolean;
    has_database: boolean;
    is_multi_component: boolean;
    sequence_source?: string;
    request_flow_stage_count?: number;
    request_flow_confidence?: number | null;
    degraded?: boolean;
    warnings?: string[];
  };
};

/* ── Color palette (matches existing dark theme) ── */

const PARTICIPANT_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  client: { bg: "#1f2937", border: "#64748b", text: "#e2e8f0" },
  component: { bg: "#172554", border: "#60a5fa", text: "#e2e8f0" },
  database: { bg: "#3b2507", border: "#f59e0b", text: "#fef3c7" },
  external: { bg: "#052e2b", border: "#2dd4bf", text: "#ccfbf1" },
  queue: { bg: "#3f3f46", border: "#facc15", text: "#fef9c3" },
};

const MESSAGE_TONES: Record<string, { line: string; label: string; badge: string }> = {
  business: { line: "#7dd3fc", label: "#e0f2fe", badge: "is-business" },
  guard: { line: "#38bdf8", label: "#e0f2fe", badge: "is-guard" },
  data: { line: "#f59e0b", label: "#fef3c7", badge: "is-data" },
  external: { line: "#2dd4bf", label: "#ccfbf1", badge: "is-external" },
  response: { line: "#34d399", label: "#d1fae5", badge: "is-response" },
  neutral: { line: "#94a3b8", label: "#cbd5e1", badge: "is-neutral" },
};

/* ── Layout constants ── */

const COL_W = 176;     // horizontal spacing between participants
const HEADER_H = 72;   // participant header height
const MSG_H = 38;      // vertical spacing per message
const TOP_PAD = 20;    // top padding
const BOT_PAD = 30;    // bottom padding
const HEAD_W = 132;    // participant box width
const HEAD_H = 44;     // participant box height

type SequenceDiagramProps = {
  data: SequenceData;
  actions?: ReactNode;
  onMessageSelect?: (message: Message) => void;
};

/* ── Component ── */

export default function SequenceDiagram({ data, actions, onMessageSelect }: SequenceDiagramProps) {
  const { participants, messages, flows, metadata } = data;

  if (participants.length < 2) {
    return (
      <p className="empty-hint">
        Not enough data to generate sequence diagram for this repository.
      </p>
    );
  }

  // Sort participants by order
  const sortedP = [...participants].sort((a, b) => a.order - b.order);
  const pIndex = new Map(sortedP.map((p, i) => [p.id, i]));

  // Use only the first flow's messages (max 20)
  const primaryFlow = flows[0];
  const flowMsgIds = new Set(primaryFlow?.message_ids ?? messages.map((m) => m.id));
  const visibleMsgs = messages
    .filter((m) => flowMsgIds.has(m.id))
    .sort((a, b) => a.order - b.order)
    .slice(0, 20);
  const participantById = new Map(sortedP.map((participant) => [participant.id, participant]));
  const primaryFlowName = primaryFlow?.flow_name ?? routeTitle(data);
  const source = sequenceSourceLabel(metadata.sequence_source);
  const requestFlowStageCount = metadata.request_flow_stage_count ?? null;
  const directCount = visibleMsgs.filter((message) => !message.is_inferred).length;
  const inferredCount = visibleMsgs.filter((message) => Boolean(message.is_inferred)).length;
  const warnings = metadata.warnings?.filter(Boolean) ?? [];
  const degraded = Boolean(metadata.degraded);

  // SVG dimensions
  const svgW = sortedP.length * COL_W + 40;
  const msgAreaTop = TOP_PAD + HEADER_H + 20;
  const svgH = msgAreaTop + visibleMsgs.length * MSG_H + BOT_PAD;

  // x position for a participant
  const px = (pid: string) => {
    const idx = pIndex.get(pid) ?? 0;
    return 20 + idx * COL_W + COL_W / 2;
  };

  return (
    <div className="sequence-panel">
      <div className="sequence-panel-header">
        <div className="sequence-panel-copy">
          <span className="sequence-panel-eyebrow">Route sequence</span>
          <div className="sequence-panel-title-row">
            {data.route_method && (
              <span className={`sequence-method-badge method-${data.route_method.toLowerCase()}`}>
                {data.route_method}
              </span>
            )}
            <h3 className="sequence-panel-title">{data.route_path ?? primaryFlowName}</h3>
          </div>
          <p className="sequence-panel-subtitle">
            {buildSequenceNarrative(data, visibleMsgs, source, degraded)}
          </p>
        </div>
        {actions ? <div className="sequence-panel-actions">{actions}</div> : null}
      </div>

      <div className="sequence-meta-row">
        <span className={`sequence-meta-chip ${degraded ? "is-fallback" : "is-direct"}`}>
          {source}
        </span>
        {requestFlowStageCount !== null && (
          <span className="sequence-meta-chip">{requestFlowStageCount} request-flow stages</span>
        )}
        {typeof metadata.request_flow_confidence === "number" && (
          <span className="sequence-meta-chip">confidence {formatConfidence(metadata.request_flow_confidence)}</span>
        )}
        <span className="sequence-meta-chip">{directCount} direct</span>
        {inferredCount > 0 && <span className="sequence-meta-chip is-inferred">{inferredCount} inferred</span>}
      </div>

      {(degraded || warnings.length > 0) && (
        <div className={`sequence-banner ${degraded ? "is-warning" : "is-info"}`}>
          <div className="sequence-banner-copy">
            <strong>{degraded ? "Fallback-backed sequence" : "Sequence guidance"}</strong>
            <span>
              {warnings[0] ?? "This sequence includes inferred detail and intentionally avoids pretending unsupported steps are precise."}
            </span>
          </div>
          {warnings.length > 1 && (
            <span className="sequence-banner-count">+{warnings.length - 1} more note{warnings.length > 2 ? "s" : ""}</span>
          )}
        </div>
      )}

      <div className="sequence-participant-strip">
        {sortedP.map((participant) => (
          <div
            key={participant.id}
            className={`sequence-participant-pill type-${participant.type}`}
            title={formatAnchorSummary(participant.metadata) ?? undefined}
          >
            <span className="sequence-participant-kind">{participantTypeLabel(participant.type)}</span>
            <span className="sequence-participant-name">{participant.label}</span>
          </div>
        ))}
      </div>

      {primaryFlow && (
        <div className="sequence-flow-row">
          <span className="sequence-flow-name">{primaryFlow.flow_name}</span>
          {primaryFlow.route_example && (
            <span className="sequence-flow-route">{primaryFlow.route_example}</span>
          )}
        </div>
      )}

      <div className="sequence-canvas-shell">
        <svg
          width={svgW}
          height={svgH}
          className="sequence-svg"
          style={{ minWidth: svgW }}
        >
        {/* Defs for arrowheads */}
        <defs>
          <marker id="arrow-call" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
            <polygon points="0 0, 8 3, 0 6" fill="#94a3b8" />
          </marker>
          <marker id="arrow-return" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
            <polygon points="0 0, 8 3, 0 6" fill="#64748b" />
          </marker>
          <marker id="arrow-async" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
            <polyline points="0 0, 8 3, 0 6" fill="none" stroke="#facc15" strokeWidth="1.5" />
          </marker>
        </defs>

        {/* Participant headers + lifelines */}
        {sortedP.map((p) => {
          const x = px(p.id);
          const colors = PARTICIPANT_COLORS[p.type] || PARTICIPANT_COLORS.component;
          return (
            <g key={p.id}>
              {/* Lifeline */}
              <line
                x1={x} y1={TOP_PAD + HEADER_H}
                x2={x} y2={svgH - 10}
                stroke="#334155"
                strokeWidth={1}
                strokeDasharray="4 3"
              />
              {/* Header box */}
              <rect
                x={x - HEAD_W / 2}
                y={TOP_PAD}
                width={HEAD_W}
                height={HEAD_H}
                rx={6}
                fill={colors.bg}
                stroke={colors.border}
                strokeWidth={1.5}
              />
              {/* Label */}
              <text
                x={x}
                y={TOP_PAD + 17}
                textAnchor="middle"
                fill={colors.text}
                fontSize={11}
                fontWeight={600}
                fontFamily="system-ui, -apple-system, sans-serif"
              >
                {truncate(p.label, 18)}
              </text>
              <text
                x={x}
                y={TOP_PAD + 31}
                textAnchor="middle"
                fill={colors.border}
                fontSize={8}
                fontWeight={700}
                fontFamily="system-ui, -apple-system, sans-serif"
                style={{ textTransform: "uppercase", letterSpacing: "0.08em" }}
              >
                {participantTypeLabel(p.type)}
              </text>
            </g>
          );
        })}

        {/* Messages */}
        {visibleMsgs.map((msg, i) => {
          const y = msgAreaTop + i * MSG_H + MSG_H / 2;
          const fromX = px(msg.from_participant);
          const toX = px(msg.to_participant);
          const tone = messageTone(msg);
          const toneStyle = MESSAGE_TONES[tone];
          const inferredOpacity = msg.is_inferred ? 0.72 : 1;

          if (fromX === toX) {
            // Self-call: draw a small loop
            return (
              <g key={msg.id}>
                <path
                  d={`M ${fromX} ${y} C ${fromX + 40} ${y}, ${fromX + 40} ${y + 16}, ${fromX} ${y + 16}`}
                  fill="none"
                  stroke={toneStyle.line}
                  strokeWidth={1}
                  opacity={inferredOpacity}
                  markerEnd="url(#arrow-call)"
                />
                <text
                  x={fromX + 44}
                  y={y + 6}
                  fill={toneStyle.label}
                  fontSize={9.5}
                  opacity={inferredOpacity}
                  fontFamily="system-ui, -apple-system, sans-serif"
                >
                  {truncate(msg.label, 28)}
                </text>
              </g>
            );
          }

          const isReturn = msg.message_type === "return";
          const isAsync = msg.message_type === "async";
          const goingRight = toX > fromX;
          const lineColor = isReturn ? "#64748b" : isAsync ? "#facc15" : toneStyle.line;
          const dashArray = isReturn ? "5 3" : isAsync ? "3 3" : "none";
          const marker = isReturn ? "url(#arrow-return)" : isAsync ? "url(#arrow-async)" : "url(#arrow-call)";

          // Shorten line so arrow doesn't overlap lifeline
          const gap = 6;
          const x1 = goingRight ? fromX + gap : fromX - gap;
          const x2 = goingRight ? toX - gap : toX + gap;

          // Label position
          const labelX = (fromX + toX) / 2;
          const labelAnchor = "middle";

          return (
            <g key={msg.id}>
              <line
                x1={x1} y1={y}
                x2={x2} y2={y}
                stroke={lineColor}
                strokeWidth={1.2}
                opacity={inferredOpacity}
                strokeDasharray={dashArray}
                markerEnd={marker}
              />
              <text
                x={labelX}
                y={y - 6}
                textAnchor={labelAnchor}
                fill={isReturn ? "#64748b" : toneStyle.label}
                fontSize={9.5}
                fontStyle={isReturn ? "italic" : "normal"}
                opacity={inferredOpacity}
                fontFamily="system-ui, -apple-system, sans-serif"
              >
                {truncate(msg.label, 30)}
              </text>
            </g>
          );
        })}
        </svg>
      </div>

      <div className="sequence-step-list">
        <div className="sequence-step-list-header">
          <span>Resolved steps</span>
          <span>{visibleMsgs.length} shown</span>
        </div>
        {visibleMsgs.map((message, index) => {
          const fromLabel = participantById.get(message.from_participant)?.label ?? message.from_participant;
          const toLabel = participantById.get(message.to_participant)?.label ?? message.to_participant;
          const stageLabel = stageTypeLabel(message.source_stage_type, message.message_type);
          const tone = messageTone(message);
          const toneClass = MESSAGE_TONES[tone].badge;
          const anchorText = formatAnchorSummary(message.code_anchor ?? message.best_target ?? null);
          const compact = isLowSignalMessage(message);
          const actionable = Boolean(onMessageSelect && anchorText);
          const content = (
            <>
              <div className="sequence-step-main">
                <div className="sequence-step-order">{index + 1}</div>
                <div className="sequence-step-copy">
                  <div className="sequence-step-topline">
                    <span className="sequence-step-label">{message.label}</span>
                    <div className="sequence-step-badges">
                      <span className={`sequence-step-badge ${toneClass}`}>{stageLabel}</span>
                      <span className={`sequence-step-badge ${message.is_inferred ? "is-inferred" : "is-direct"}`}>
                        {message.is_inferred ? "Inferred" : "Direct"}
                      </span>
                      {typeof message.confidence === "number" && (
                        <span className="sequence-step-badge is-neutral">{formatConfidence(message.confidence)}</span>
                      )}
                      {anchorText && <span className="sequence-step-badge is-anchor">Code-ready</span>}
                    </div>
                  </div>
                  <div className="sequence-step-path">{fromLabel} → {toLabel}</div>
                  {anchorText && <div className="sequence-step-anchor">{anchorText}</div>}
                  <InlineCodePeek
                    projectId={data.project_id}
                    anchor={codePeekAnchorForMessage(message)}
                    isInferred={Boolean(message.is_inferred)}
                    confidence={message.confidence}
                    sourceLabel={stageLabel}
                    compact
                    unavailableReason={message.is_inferred
                      ? "This inferred sequence step does not have a grounded file anchor for Code Peek."
                      : "No grounded file anchor was detected for this sequence step."}
                  />
                </div>
              </div>
            </>
          );

          if (actionable) {
            return (
              <button
                key={message.id}
                type="button"
                className={`sequence-step-card ${compact ? "is-compact" : ""} is-actionable`}
                onClick={() => onMessageSelect?.(message)}
                data-anchor-path={message.code_anchor?.file_path ?? message.best_target?.file_path ?? undefined}
                data-anchor-symbol={message.code_anchor?.symbol_name ?? message.best_target?.symbol_name ?? undefined}
              >
                {content}
              </button>
            );
          }

          return (
            <div
              key={message.id}
              className={`sequence-step-card ${compact ? "is-compact" : ""}`}
              data-anchor-path={message.code_anchor?.file_path ?? message.best_target?.file_path ?? undefined}
              data-anchor-symbol={message.code_anchor?.symbol_name ?? message.best_target?.symbol_name ?? undefined}
            >
              {content}
            </div>
          );
        })}
      </div>

      {/* Additional flow examples */}
      {flows.length > 1 && (
        <div className="sequence-alt-flows">
          {flows.slice(1).map((f) => (
            <span key={f.flow_id} className="sequence-alt-flow-chip">
              {f.route_example || f.flow_name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Helpers ── */

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

function routeTitle(data: SequenceData): string {
  if (data.route_method && data.route_path) {
    return `${data.route_method} ${data.route_path}`;
  }
  return data.flows?.[0]?.route_example ?? data.flows?.[0]?.flow_name ?? "Route sequence";
}

function participantTypeLabel(type: Participant["type"]): string {
  if (type === "database") return "Data";
  if (type === "external") return "External";
  if (type === "queue") return "Queue";
  if (type === "client") return "Client";
  return "Component";
}

function sequenceSourceLabel(source?: string): string {
  switch (source) {
    case "request_flow":
      return "Request-flow grounded";
    case "analysis_request_flow":
      return "Request flow via analysis";
    case "route_analysis_fallback":
      return "Fallback analysis";
    case "minimal_fallback":
      return "Minimal fallback";
    default:
      return "Sequence";
  }
}

function formatConfidence(value: number): string {
  return value.toFixed(2);
}

function buildSequenceNarrative(
  data: SequenceData,
  visibleMsgs: Message[],
  source: string,
  degraded: boolean,
): string {
  const requestFlowStageCount = data.metadata.request_flow_stage_count;
  const external = visibleMsgs.some((message) => message.source_stage_type === "external");
  const dataTouch = visibleMsgs.some((message) => ["repository", "data_access"].includes(message.source_stage_type ?? ""));
  const guards = visibleMsgs.some((message) => ["auth", "validation", "middleware"].includes(message.source_stage_type ?? ""));
  const parts = [
    `${source} sequence for ${data.route_method ?? "this route"}`,
    requestFlowStageCount ? `${requestFlowStageCount} request-flow stages available` : null,
    guards ? "guards are marked separately" : null,
    external ? "external calls are highlighted" : null,
    dataTouch ? "data steps are distinguished from business logic" : null,
  ].filter(Boolean);
  const sentence = `${parts.join(". ")}.`;
  if (!degraded) {
    return sentence;
  }
  return `${sentence} Fallback-backed or inferred steps stay visible but are marked so the diagram does not overclaim precision.`;
}

function messageTone(message: Message): keyof typeof MESSAGE_TONES {
  const stageType = message.source_stage_type ?? "";
  if (stageType === "external") return "external";
  if (stageType === "data_access" || stageType === "repository") return "data";
  if (stageType === "auth" || stageType === "validation" || stageType === "middleware") return "guard";
  if (stageType === "response" || message.message_type === "return") return "response";
  if (stageType === "service" || stageType === "handler" || stageType === "dispatch") return "business";
  return "neutral";
}

function stageTypeLabel(stageType: string | null | undefined, messageType: Message["message_type"]): string {
  if (stageType) {
    return stageType.replace(/_/g, " ");
  }
  if (messageType === "return") {
    return "return";
  }
  return "step";
}

function formatAnchorSummary(anchor: SequenceCodeAnchor | Participant["metadata"] | null | undefined): string | null {
  if (!anchor?.file_path) {
    return null;
  }
  const lineLabel = anchor.line_start ? `:${anchor.line_start}` : "";
  const owner = anchor.class_name && anchor.symbol_name
    ? `${anchor.class_name}.${anchor.symbol_name}`
    : anchor.class_name || anchor.symbol_name || null;
  return owner ? `${anchor.file_path}${lineLabel} • ${owner}` : `${anchor.file_path}${lineLabel}`;
}

function isLowSignalMessage(message: Message): boolean {
  const lowSignalLabels = new Set([
    "result",
    "service result",
    "repository result",
    "query result",
    "provider response",
    "cache result",
    "write complete",
  ]);
  return message.message_type === "return" || lowSignalLabels.has(message.label.toLowerCase());
}

function codePeekAnchorForMessage(message: Message): InlineCodePeekAnchor | null {
  const anchor = message.code_anchor ?? message.best_target ?? null;
  return {
    file_path: message.file_path ?? anchor?.file_path ?? null,
    symbol_name: message.symbol_name ?? anchor?.symbol_name ?? null,
    class_name: message.class_name ?? anchor?.class_name ?? null,
    line_start: message.line_start ?? anchor?.line_start ?? null,
    line_end: message.line_end ?? anchor?.line_end ?? null,
    selection_reason: anchor?.selection_reason ?? null,
  };
}
