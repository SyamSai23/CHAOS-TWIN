import { useState } from "react";
import {
  Database,
  CheckCircle,
  FolderOpen,
  Globe,
  Cpu,
  ArrowRight,
  GitBranch,
  RefreshCw,
  Send,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import type { AnalysisPhase } from "../types";

const PHASE_COLORS: Record<string, string> = {
  Validation: "#f97316",
  Processing: "#3b82f6",
  Database: "#a855f7",
  Response: "#22c55e",
};

const STEP_ICONS: Record<string, React.ComponentType<{ size?: number }>> = {
  db_read: Database,
  db_write: Database,
  db_commit: CheckCircle,
  filesystem: FolderOpen,
  external: Globe,
  service: Cpu,
  internal: ArrowRight,
  conditional: GitBranch,
  loop: RefreshCw,
  response: Send,
};

type Props = {
  phase: AnalysisPhase;
  index: number;
  mode: "story" | "technical";
};

export default function PhaseCard({ phase, index, mode }: Props) {
  const [showDetails, setShowDetails] = useState(mode === "technical");
  const pillColor = PHASE_COLORS[phase.name] || "#6b7280";
  const hasSteps = phase.steps.length > 0 && !phase.steps.every((s) => !s.label && !s.technical);

  /* ── Story Mode ── */
  if (mode === "story") {
    const orphan = !phase.description || phase.description.trim() === "";
    return (
      <div className={`phase-card phase-card-story${orphan ? " phase-orphan" : ""}`}>
        <div className="phase-card-row">
          <span className="phase-number">{index + 1}</span>
          <span className="phase-pill" style={{ background: pillColor }}>
            {phase.name}
          </span>
          <span className="phase-description">{phase.description}</span>
        </div>
        {hasSteps && !showDetails && (
          <button
            className="phase-details-link"
            onClick={() => setShowDetails(true)}
          >
            Show details &rarr;
          </button>
        )}
        {hasSteps && showDetails && (
          <>
            <button
              className="phase-details-link"
              onClick={() => setShowDetails(false)}
            >
              Hide details
            </button>
            <div className="phase-card-body phase-card-body-story">
              {phase.steps.map((step, i) => {
                const Icon = STEP_ICONS[step.type] || ArrowRight;
                const label = step.label || step.type.charAt(0).toUpperCase() + step.type.slice(1).replace(/_/g, " ");
                const hasRaw = (t: string) =>
                  t.includes("{") || t.includes("'") || t.includes('"') ||
                  t.includes(":") || t.startsWith("return ") || t.startsWith("Return {");
                if (hasRaw(label)) return null;
                const showTech = step.technical && !hasRaw(step.technical);
                return (
                  <div key={i} className="phase-step phase-step-story">
                    <Icon size={14} />
                    <div className="phase-step-story-text">
                      <span className="phase-step-label">{label}</span>
                      {showTech && (
                        <span className="phase-step-technical">{step.technical}</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    );
  }

  /* ── Technical Mode ── */
  return (
    <div className="phase-card">
      <button className="phase-card-header" onClick={() => setShowDetails(!showDetails)}>
        <span className="phase-pill" style={{ background: pillColor }}>
          {phase.name}
        </span>
        <span className="phase-description">{phase.description}</span>
        <span className="phase-chevron">
          {showDetails ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
      </button>

      {showDetails && (
        <div className="phase-card-body">
          {phase.steps.map((step, i) => {
            const Icon = STEP_ICONS[step.type] || ArrowRight;
            const label = step.label || step.type.charAt(0).toUpperCase() + step.type.slice(1).replace(/_/g, " ");
            return (
              <div key={i} className="phase-step">
                <Icon size={14} />
                <div className="phase-step-text">
                  <span className="phase-step-label">{label}</span>
                  {step.technical && (
                    <span className="phase-step-technical">{step.technical}</span>
                  )}
                </div>
                {step.line_number && (
                  <span className="phase-step-line">L{step.line_number}</span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
