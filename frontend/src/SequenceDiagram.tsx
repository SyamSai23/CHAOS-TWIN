import { type CSSProperties } from "react";

/* ── Types matching the API response ── */

export type Participant = {
  id: string;
  label: string;
  type: "client" | "component" | "database" | "external" | "queue";
  order: number;
};

export type Message = {
  id: string;
  from_participant: string;
  to_participant: string;
  label: string;
  message_type: "call" | "return" | "async";
  step: number;
  order: number;
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
    component_count: number;
    step_count: number;
    has_external_calls: boolean;
    has_database: boolean;
    is_multi_component: boolean;
  };
};

/* ── Color palette (matches existing dark theme) ── */

const PARTICIPANT_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  client:    { bg: "#1e293b", border: "#64748b", text: "#e2e8f0" },
  component: { bg: "#1e3a5f", border: "#60a5fa", text: "#e2e8f0" },
  database:  { bg: "#3b1f4a", border: "#c084fc", text: "#e2e8f0" },
  external:  { bg: "#2d1b4e", border: "#a78bfa", text: "#e2e8f0" },
  queue:     { bg: "#2d2305", border: "#facc15", text: "#e2e8f0" },
};

/* ── Layout constants ── */

const COL_W = 160;     // horizontal spacing between participants
const HEADER_H = 60;   // participant header height
const MSG_H = 38;      // vertical spacing per message
const TOP_PAD = 20;    // top padding
const BOT_PAD = 30;    // bottom padding
const HEAD_W = 120;    // participant box width
const HEAD_H = 36;     // participant box height

/* ── Component ── */

export default function SequenceDiagram({ data }: { data: SequenceData }) {
  const { participants, messages, flows } = data;

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
    <div style={{ overflowX: "auto" }}>
      {/* Flow name */}
      {primaryFlow && (
        <div style={flowHeaderStyle}>
          <span style={{ color: "#94a3b8", fontSize: "0.7rem", textTransform: "uppercase", fontWeight: 700, letterSpacing: "0.06em" }}>
            {primaryFlow.flow_name}
          </span>
          {primaryFlow.route_example && (
            <code style={{ color: "#a78bfa", fontSize: "0.75rem", marginLeft: 8 }}>
              {primaryFlow.route_example}
            </code>
          )}
        </div>
      )}

      <svg
        width={svgW}
        height={svgH}
        style={{ display: "block", minWidth: svgW }}
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
                y={TOP_PAD + HEAD_H / 2 + 1}
                textAnchor="middle"
                dominantBaseline="middle"
                fill={colors.text}
                fontSize={11}
                fontWeight={600}
                fontFamily="system-ui, -apple-system, sans-serif"
              >
                {truncate(p.label, 16)}
              </text>
            </g>
          );
        })}

        {/* Messages */}
        {visibleMsgs.map((msg, i) => {
          const y = msgAreaTop + i * MSG_H + MSG_H / 2;
          const fromX = px(msg.from_participant);
          const toX = px(msg.to_participant);

          if (fromX === toX) {
            // Self-call: draw a small loop
            return (
              <g key={msg.id}>
                <path
                  d={`M ${fromX} ${y} C ${fromX + 40} ${y}, ${fromX + 40} ${y + 16}, ${fromX} ${y + 16}`}
                  fill="none"
                  stroke="#94a3b8"
                  strokeWidth={1}
                  markerEnd="url(#arrow-call)"
                />
                <text
                  x={fromX + 44}
                  y={y + 6}
                  fill="#cbd5e1"
                  fontSize={9.5}
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
          const lineColor = isReturn ? "#64748b" : isAsync ? "#facc15" : "#94a3b8";
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
                strokeDasharray={dashArray}
                markerEnd={marker}
              />
              <text
                x={labelX}
                y={y - 6}
                textAnchor={labelAnchor}
                fill={isReturn ? "#64748b" : "#cbd5e1"}
                fontSize={9.5}
                fontStyle={isReturn ? "italic" : "normal"}
                fontFamily="system-ui, -apple-system, sans-serif"
              >
                {truncate(msg.label, 30)}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Additional flow examples */}
      {flows.length > 1 && (
        <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
          {flows.slice(1).map((f) => (
            <span key={f.flow_id} style={flowBadgeStyle}>
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

const flowHeaderStyle: CSSProperties = {
  marginBottom: 8,
  display: "flex",
  alignItems: "center",
};

const flowBadgeStyle: CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 4,
  background: "#1e293b",
  border: "1px solid #334155",
  color: "#94a3b8",
  fontSize: "0.7rem",
  fontFamily: "monospace",
};
