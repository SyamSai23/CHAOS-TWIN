import type { GraphResponse, SimulationResult } from "../types";
import { shortenLabel } from "../types";

interface SimulationViewProps {
  graph: GraphResponse | null;
  simSelectedNode: string;
  simulating: boolean;
  simResult: SimulationResult | null;
  simError: string | null;
  onSelectNode: (nodeId: string) => void;
  onSimulate: () => void;
  onClear: () => void;
}

export default function SimulationView({
  graph,
  simSelectedNode,
  simulating,
  simResult,
  simError,
  onSelectNode,
  onSimulate,
  onClear,
}: SimulationViewProps) {
  if (!graph) {
    return (
      <div>
        <h1 className="view-title">Chaos Simulation</h1>
        <div className="view-empty">
          <p className="view-empty-title">No graph available</p>
          <p className="view-empty-sub">
            Build the architecture graph first, then run a simulation.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="view-title">Chaos Simulation</h1>

      <div className="sim-controls">
        <select
          className="sim-select"
          value={simSelectedNode}
          onChange={(e) => onSelectNode(e.target.value)}
        >
          <option value="">Choose a component…</option>
          {graph.nodes.map((node) => (
            <option key={node.id} value={node.id}>
              {shortenLabel(node.label)} ({node.node_type})
            </option>
          ))}
        </select>
        <button
          className="btn btn-primary btn-sm"
          disabled={!simSelectedNode || simulating}
          onClick={onSimulate}
        >
          {simulating ? "Running…" : "Run Simulation"}
        </button>
        {simResult && (
          <button className="btn btn-secondary btn-sm" onClick={onClear}>
            Clear
          </button>
        )}
      </div>

      {!simResult && !simError && (
        <p className="text-muted" style={{ marginTop: 12, fontSize: 14 }}>
          Pick a component and run a simulation to see what breaks.
        </p>
      )}

      {simError && <p className="msg-error">{simError}</p>}

      {simResult && (
        <div className="sim-result">
          <div className="sim-summary-row">
            <span className={`sim-severity sim-severity-${simResult.severity}`}>
              {simResult.severity === "high"
                ? "High Risk"
                : simResult.severity === "medium"
                  ? "Med Risk"
                  : "Low Risk"}
            </span>
            <span className="sim-summary-text">{simResult.summary}</span>
          </div>

          <div className="sim-stats">
            <div className="sim-stat">
              <span className="sim-stat-label">Failed Component</span>
              <span className="sim-stat-value">
                {shortenLabel(simResult.result.failed_node_label)}{" "}
                <span className="tag-dim">
                  &middot; {simResult.result.failed_node_type}
                </span>
              </span>
            </div>
            <div className="sim-stat">
              <span className="sim-stat-label">Components Affected</span>
              <span className="sim-stat-value">
                {simResult.result.impacted_count}
              </span>
            </div>
          </div>

          {simResult.impacted_nodes.length > 0 && (
            <div className="sim-impacted">
              <div className="card-label">Blast Radius</div>
              <div className="sim-impacted-list">
                {simResult.impacted_nodes.map((node) => (
                  <div key={node.id} className="sim-impacted-item">
                    <span className="sim-impacted-label">
                      {shortenLabel(node.label)}
                    </span>
                    <span className="chip chip-muted">{node.node_type}</span>
                    <span className="sim-distance">
                      {node.distance === 1
                        ? "1 hop away"
                        : `${node.distance} hops away`}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
