import { useState } from "react";
import { FileCode2, LoaderCircle } from "lucide-react";

import { getCodePeek } from "../api/client";
import type { CodePeekResponse } from "../types";

export type InlineCodePeekAnchor = {
  file_path?: string | null;
  symbol_name?: string | null;
  class_name?: string | null;
  line_start?: number | null;
  line_end?: number | null;
  selection_reason?: string | null;
};

type Props = {
  projectId: string;
  anchor?: InlineCodePeekAnchor | null;
  isInferred?: boolean;
  confidence?: number | null;
  sourceLabel?: string | null;
  compact?: boolean;
  unavailableReason?: string | null;
};

export default function InlineCodePeek({
  projectId,
  anchor,
  isInferred = false,
  confidence,
  sourceLabel,
  compact = false,
  unavailableReason,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [payload, setPayload] = useState<CodePeekResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const filePath = anchor?.file_path?.trim() || null;
  const hasAnchor = Boolean(filePath);

  async function handleToggle() {
    if (!hasAnchor) {
      return;
    }
    if (expanded) {
      setExpanded(false);
      return;
    }

    setExpanded(true);
    if (payload || loading) {
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await getCodePeek(projectId, { file_path: filePath ?? undefined });
      setPayload(response);
    } catch (peekError) {
      setError(peekError instanceof Error ? peekError.message : "Code peek unavailable");
    } finally {
      setLoading(false);
    }
  }

  const owner = formatOwner(anchor);
  const requestedRange = formatRequestedRange(anchor);
  const snippetRange = payload
    ? formatSnippetRange(payload.generated_from.snippet_line_start, payload.generated_from.snippet_line_end)
    : requestedRange;

  return (
    <div className={`inline-codepeek ${compact ? "is-compact" : ""}`}>
      <div className="inline-codepeek-trigger-row">
        {hasAnchor ? (
          <button
            type="button"
            className="inline-codepeek-trigger"
            onClick={() => void handleToggle()}
          >
            <FileCode2 size={12} />
            {expanded ? "Hide code" : "View code"}
          </button>
        ) : (
          <span className="inline-codepeek-unavailable" title={unavailableReason ?? undefined}>
            Code unavailable
          </span>
        )}

        <div className="inline-codepeek-trigger-meta">
          {sourceLabel ? <span className="inline-codepeek-meta-chip">{sourceLabel}</span> : null}
          {typeof confidence === "number" ? (
            <span className="inline-codepeek-meta-chip">{confidence.toFixed(2)}</span>
          ) : null}
          {isInferred ? <span className="inline-codepeek-meta-chip is-inferred">Inferred step</span> : null}
        </div>
      </div>

      {expanded && (
        <div className="intel-codepeek-panel inline-codepeek-panel">
          <div className="intel-codepeek-header">
            <div>
              <div className="card-label">Code Peek</div>
              <div className="card-meta-text">
                {payload
                  ? `${payload.file_path}${payload.language ? ` · ${payload.language}` : ""}`
                  : owner
                    ? `${filePath} · ${owner}`
                    : filePath}
              </div>
            </div>
          </div>

          {loading && (
            <div className="intel-loading-row">
              <LoaderCircle size={14} className="intel-spinner" />
              <span className="text-muted">Resolving grounded snippet…</span>
            </div>
          )}

          {!loading && error && (
            <div className="intel-empty-state intel-codepeek-empty">
              <p className="view-empty-title">Code peek unavailable</p>
              <p className="view-empty-sub">{error}</p>
            </div>
          )}

          {!loading && payload && (
            <>
              <div className="intel-codepeek-meta">
                <span className="chip chip-muted">{prettifyLabel(payload.source_type)}</span>
                {payload.confidence?.label && (
                  <span className="chip chip-muted">{payload.confidence.label}</span>
                )}
                {snippetRange && <span className="text-muted">{snippetRange}</span>}
                {owner && <span className="text-muted">{owner}</span>}
              </div>
              <pre className="intel-codepeek-snippet"><code>{payload.snippet_text}</code></pre>
              <div className="inline-codepeek-reasons">
                {isInferred && (
                  <p className="intel-codepeek-reason">
                    This step is inferred. The snippet shows the strongest grounded file anchor behind it.
                  </p>
                )}
                <p className="intel-codepeek-reason">{payload.generated_from.selection_reason}</p>
                {anchor?.selection_reason && anchor.selection_reason !== payload.generated_from.selection_reason && (
                  <p className="intel-codepeek-reason">{anchor.selection_reason}</p>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function formatOwner(anchor?: InlineCodePeekAnchor | null): string | null {
  if (!anchor) {
    return null;
  }
  if (anchor.class_name && anchor.symbol_name) {
    return `${anchor.class_name}.${anchor.symbol_name}`;
  }
  return anchor.class_name || anchor.symbol_name || null;
}

function formatRequestedRange(anchor?: InlineCodePeekAnchor | null): string | null {
  if (!anchor?.line_start) {
    return null;
  }
  if (anchor.line_end && anchor.line_end !== anchor.line_start) {
    return `requested lines ${anchor.line_start}-${anchor.line_end}`;
  }
  return `requested line ${anchor.line_start}`;
}

function formatSnippetRange(start?: number | null, end?: number | null): string | null {
  if (!start) {
    return null;
  }
  if (end && end !== start) {
    return `lines ${start}-${end}`;
  }
  return `line ${start}`;
}

function prettifyLabel(value: string): string {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}