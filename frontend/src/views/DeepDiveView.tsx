import {
  Background,
  ReactFlow,
  ReactFlowProvider,
  type Edge as ReactFlowEdge,
  type Node as ReactFlowNode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { ScanResult, DeepDiveResult } from "../types";
import { shortenLabel } from "../types";

const roleColor = (role: string): string => {
  switch (role) {
    case "entry":
      return "#22c55e";
    case "routing":
      return "#3b82f6";
    case "service":
      return "#a855f7";
    case "data":
      return "#f59e0b";
    case "configuration":
      return "#64748b";
    case "controller":
      return "#06b6d4";
    case "middleware":
      return "#ec4899";
    case "utility":
      return "#94a3b8";
    case "core / mixed":
      return "#818cf8";
    case "test":
      return "#ef4444";
    default:
      return "#475569";
  }
};

interface DeepDiveViewProps {
  scan: ScanResult | null;
  ddSelectedRoot: string | null;
  ddResult: DeepDiveResult | null;
  ddLoading: boolean;
  ddError: string | null;
  ddExpandEdges: boolean;
  onDeepDive: (componentRoot: string) => void;
  onToggleExpandEdges: () => void;
  projectName: string;
}

export default function DeepDiveView({
  scan,
  ddSelectedRoot,
  ddResult,
  ddLoading,
  ddError,
  ddExpandEdges,
  onDeepDive,
  onToggleExpandEdges,
  projectName,
}: DeepDiveViewProps) {
  const components = scan?.components || [];
  const deepDiveComponents = components.filter(
    (c) =>
      c.type === "frontend" || c.type === "backend" || c.type === "service",
  );

  if (!scan || deepDiveComponents.length === 0) {
    return (
      <div>
        <h1 className="view-title">Deep Dive</h1>
        <div className="view-empty">
          <p className="view-empty-title">No components available</p>
          <p className="view-empty-sub">
            Run a scan first to discover components.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="view-title">Deep Dive</h1>

      {/* Component selector */}
      <div style={{ marginBottom: 16 }}>
        <div className="card-label">Select a component</div>
        <div className="chip-list" style={{ marginTop: 6 }}>
          {deepDiveComponents.map((comp) => (
            <button
              key={comp.root_path}
              className={`dd-chip${ddSelectedRoot === comp.root_path ? " dd-chip-active" : ""}`}
              onClick={() => onDeepDive(comp.root_path)}
            >
              {comp.name === "root" ? projectName : comp.name}
              <span className="tag-dim"> &middot; {comp.type}</span>
            </button>
          ))}
        </div>
      </div>

      {ddLoading && <p className="msg-info">Analyzing component…</p>}
      {ddError && <p className="msg-error">{ddError}</p>}

      {!ddSelectedRoot && !ddLoading && (
        <p className="text-muted" style={{ fontSize: 14 }}>
          Select a component above to see its internal structure.
        </p>
      )}

      {ddResult && (() => {
        const dd = ddResult;
        const showFileEdges = ddExpandEdges;

        const miniNodes: ReactFlowNode[] = dd.internal_modules.map((m, i) => ({
          id: m.name,
          position: {
            x: (i % 3) * 220 + 40,
            y: Math.floor(i / 3) * 100 + 30,
          },
          data: { label: m.name },
          style: {
            background:
              m.dominant_role === "core / mixed" ? "#1e1b4b" : "#111111",
            color: "#e2e8f0",
            border: `1px solid ${roleColor(m.dominant_role)}44`,
            borderRadius: 8,
            fontSize: 11,
            fontWeight: 600,
            padding: "6px 14px",
            minWidth: 80,
            textAlign: "center" as const,
          },
        }));
        const miniEdges: ReactFlowEdge[] = dd.module_edges.map((me, i) => ({
          id: `me-${i}`,
          source: me.source_module,
          target: me.target_module,
          label: String(me.edge_count),
          style: {
            stroke: "#6366f1",
            strokeWidth: me.edge_count > 3 ? 2 : 1,
          },
          labelStyle: { fill: "#94a3b8", fontSize: 10 },
          animated: me.edge_count > 5,
        }));

        return (
          <div className="dd-panel">
            <div className="dd-summary">{dd.component_summary}</div>

            {dd.probable_start_file && (
              <div className="dd-block">
                <div className="dd-block-title">Entry Point</div>
                <code className="dd-start-file">
                  {dd.probable_start_file}
                </code>
              </div>
            )}

            {miniNodes.length > 1 && miniEdges.length > 0 && (
              <div className="dd-block">
                <div className="dd-block-title">Module Dependencies</div>
                <div className="dd-mini-graph">
                  <ReactFlowProvider>
                    <ReactFlow
                      nodes={miniNodes}
                      edges={miniEdges}
                      fitView
                      fitViewOptions={{
                        padding: 0.3,
                        minZoom: 0.5,
                        maxZoom: 1.5,
                      }}
                      proOptions={{ hideAttribution: true }}
                      nodesDraggable
                      nodesConnectable={false}
                      elementsSelectable={false}
                      panOnDrag
                      zoomOnScroll={false}
                      zoomOnPinch
                    >
                      <Background gap={18} color="#1a1a1a" />
                    </ReactFlow>
                  </ReactFlowProvider>
                </div>
              </div>
            )}

            {dd.internal_modules.length > 0 && (
              <div className="dd-block">
                <div className="dd-block-title">
                  Modules
                  <span className="dd-block-count">
                    {dd.internal_modules.length}
                  </span>
                </div>
                <div className="dd-module-grid">
                  {dd.internal_modules.map((m) => (
                    <div key={m.name} className="dd-module-card">
                      <div className="dd-module-name">{m.name}</div>
                      <div className="dd-module-meta">
                        {m.file_count} {m.file_count === 1 ? "file" : "files"}
                      </div>
                      <div className="dd-role-tags">
                        <span
                          className="dd-role-tag dd-role-primary"
                          style={{
                            borderColor: roleColor(m.dominant_role) + "66",
                            color: roleColor(m.dominant_role),
                          }}
                        >
                          {m.dominant_role}
                        </span>
                        {m.roles
                          .filter(
                            (r) => r !== m.dominant_role && r !== "other",
                          )
                          .slice(0, 3)
                          .map((r) => (
                            <span
                              key={r}
                              className="dd-role-tag"
                              style={{ color: roleColor(r) + "cc" }}
                            >
                              {r}
                            </span>
                          ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {dd.important_files.length > 0 && (
              <div className="dd-block">
                <div className="dd-block-title">Key Files</div>
                <div className="dd-file-list">
                  {dd.important_files.slice(0, 10).map((f) => (
                    <div key={f.path} className="dd-file-row">
                      <code className="dd-file-path">{f.path}</code>
                      <span
                        className="dd-file-role"
                        style={{ color: roleColor(f.role) }}
                      >
                        {f.role}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {dd.module_edges.length > 0 && (
              <div className="dd-block">
                <div className="dd-block-title">
                  Internal Relationships
                  <span className="dd-block-count">
                    {dd.module_edges.length} module{" "}
                    {dd.module_edges.length === 1 ? "link" : "links"}
                  </span>
                </div>
                <div className="dd-edge-list">
                  {dd.module_edges.map((me, i) => (
                    <div key={i} className="dd-edge-row dd-edge-module">
                      <span className="dd-edge-src">
                        {me.source_module}
                      </span>
                      <span className="dd-edge-arrow">→</span>
                      <span className="dd-edge-tgt">
                        {me.target_module}
                      </span>
                      <span className="dd-edge-count">
                        {me.edge_count}{" "}
                        {me.edge_count === 1 ? "import" : "imports"}
                      </span>
                    </div>
                  ))}
                </div>

                {dd.internal_edges.length > 0 && (
                  <button
                    className="dd-expand-btn"
                    onClick={onToggleExpandEdges}
                  >
                    {showFileEdges ? "Hide" : "Show"} file-level imports (
                    {dd.internal_edges.length})
                  </button>
                )}
                {showFileEdges && (
                  <div className="dd-edge-list dd-edge-file-list">
                    {dd.internal_edges.slice(0, 30).map((e, i) => (
                      <div key={i} className="dd-edge-row dd-edge-file">
                        <code className="dd-edge-src">
                          {shortenLabel(e.source)}
                        </code>
                        <span className="dd-edge-arrow">→</span>
                        <code className="dd-edge-tgt">
                          {shortenLabel(e.target)}
                        </code>
                      </div>
                    ))}
                    {dd.internal_edges.length > 30 && (
                      <div className="msg-info">
                        +{dd.internal_edges.length - 30} more
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {dd.probable_flow_steps.length > 0 && (
              <div className="dd-block">
                <div className="dd-block-title">Execution Flow</div>
                <div className="dd-flow-list">
                  {dd.probable_flow_steps.map((s, i) => (
                    <div key={i} className="dd-flow-step">
                      <span className="dd-flow-num">{i + 1}</span>
                      <div className="dd-flow-body">
                        <div className="dd-flow-name">{s.step}</div>
                        <div className="dd-flow-files">
                          {s.example_files.slice(0, 3).map((f) => (
                            <code key={f}>{shortenLabel(f)}</code>
                          ))}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {dd.notes.length > 0 && (
              <div className="dd-block">
                <div className="dd-block-title">Notes</div>
                <ul className="dd-notes">
                  {dd.notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        );
      })()}
    </div>
  );
}
