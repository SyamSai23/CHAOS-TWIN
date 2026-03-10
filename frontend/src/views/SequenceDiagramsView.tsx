import { useState, useEffect, useCallback } from "react";
import { GitCommitHorizontal } from "lucide-react";
import SequenceDiagram, { type SequenceData } from "../SequenceDiagram";

const API = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

const METHOD_COLORS: Record<string, string> = {
  GET: "#22c55e",
  POST: "#3b82f6",
  PUT: "#eab308",
  DELETE: "#ef4444",
  PATCH: "#a855f7",
};

type RouteSeqRecord = {
  route_id: string;
  diagram_data: SequenceData;
  created_at: string | null;
};

type Props = {
  projectId: string;
};

export default function SequenceDiagramsView({ projectId }: Props) {
  const [records, setRecords] = useState<RouteSeqRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [genAllState, setGenAllState] = useState<{ running: boolean; progress: string | null }>({
    running: false,
    progress: null,
  });

  const fetchRecords = useCallback(() => {
    setLoading(true);
    setError(null);
    fetch(`${API}/projects/${encodeURIComponent(projectId)}/sequence/routes`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load route diagrams");
        return res.json();
      })
      .then((data: RouteSeqRecord[]) => setRecords(data))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => {
    setRecords([]);
    setExpandedId(null);
    fetchRecords();
  }, [projectId, fetchRecords]);

  const handleGenerateAll = () => {
    setGenAllState({ running: true, progress: "Starting batch generation…" });

    fetch(`${API}/projects/${encodeURIComponent(projectId)}/sequence/all`, {
      method: "POST",
    })
      .then((res) => {
        if (!res.ok) throw new Error("Batch generation failed");
        return res.json();
      })
      .then((result: { generated: number; failed: number; route_ids: string[] }) => {
        setGenAllState({
          running: false,
          progress: `Generated ${result.generated} diagrams${result.failed ? `, ${result.failed} failed` : ""}`,
        });
        fetchRecords();
      })
      .catch((e) => {
        setGenAllState({ running: false, progress: e.message });
      });
  };

  if (loading) {
    return (
      <div className="placeholder-view">
        <p className="text-muted">Loading sequence diagrams…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="placeholder-view">
        <GitCommitHorizontal size={48} color="#6b6b6b" strokeWidth={1.5} />
        <h2 className="placeholder-title">Could not load diagrams</h2>
        <p className="placeholder-sub">{error}</p>
      </div>
    );
  }

  if (records.length === 0) {
    return (
      <div className="placeholder-view">
        <GitCommitHorizontal size={48} color="#6b6b6b" strokeWidth={1.5} />
        <h2 className="placeholder-title">No Route Sequence Diagrams</h2>
        <p className="placeholder-sub">
          Generate diagrams from the API Explorer, or use Generate All below.
        </p>
        <button
          className="btn btn-primary"
          style={{ marginTop: 16 }}
          disabled={genAllState.running}
          onClick={handleGenerateAll}
        >
          {genAllState.running ? "Generating…" : "Generate All"}
        </button>
        {genAllState.progress && (
          <p className="text-muted" style={{ marginTop: 8, fontSize: 12 }}>
            {genAllState.progress}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="seq-diagrams-view">
      <div className="seq-diagrams-header">
        <h1 className="view-title">Sequence Diagrams</h1>
        <button
          className="btn btn-secondary btn-sm"
          disabled={genAllState.running}
          onClick={handleGenerateAll}
        >
          {genAllState.running ? "Generating…" : "Generate All"}
        </button>
      </div>
      {genAllState.progress && (
        <p className="text-muted" style={{ fontSize: 12, marginBottom: 12 }}>
          {genAllState.progress}
        </p>
      )}
      <div className="seq-route-grid">
        {records.map((rec) => {
          const d = rec.diagram_data;
          const method = d.route_method ?? d.flows?.[0]?.route_example?.split(" ")[0] ?? "GET";
          const path = d.route_path ?? d.flows?.[0]?.route_example?.split(" ").slice(1).join(" ") ?? "/";
          const mColor = METHOD_COLORS[method] || "#6b6b6b";
          const isExpanded = expandedId === rec.route_id;

          return (
            <div key={rec.route_id} className="seq-route-card">
              <div className="seq-route-card-header">
                <div className="seq-route-card-info">
                  <span className="seq-route-method" style={{ background: mColor }}>
                    {method}
                  </span>
                  <span className="seq-route-path">{path}</span>
                </div>
                <div className="seq-route-card-meta">
                  <span className="chip chip-muted">
                    {d.participants?.length ?? 0} participants
                  </span>
                  <span className="chip chip-muted">
                    {d.messages?.length ?? 0} messages
                  </span>
                </div>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => setExpandedId(isExpanded ? null : rec.route_id)}
                >
                  {isExpanded ? "Collapse" : "View"}
                </button>
              </div>
              {isExpanded && (
                <div className="seq-route-card-diagram">
                  <SequenceDiagram data={d} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
