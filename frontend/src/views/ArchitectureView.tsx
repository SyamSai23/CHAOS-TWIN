import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Edge as ReactFlowEdge,
  type Node as ReactFlowNode,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type {
  GraphResponse,
  ScanResult,
  SimulationResult,
} from "../types";
import { shortenLabel } from "../types";

/* ── Node color palette ── */

const NODE_COLORS: Record<string, { bg: string; border: string }> = {
  frontend: { bg: "#1e3a5f", border: "#60a5fa" },
  backend: { bg: "#1a3329", border: "#4ade80" },
  database: { bg: "#3b1f4a", border: "#c084fc" },
  runtime: { bg: "#2d2305", border: "#facc15" },
  tool: { bg: "#1e293b", border: "#94a3b8" },
  entry_point: { bg: "#3b1520", border: "#fb7185" },
  component: { bg: "#1e3a5f", border: "#60a5fa" },
  external: { bg: "#2d1b4e", border: "#a78bfa" },
};

/* ── Graph layout ── */

function toReactFlowGraph(
  graph: GraphResponse,
  simulationResult?: SimulationResult | null,
  selectedComponentNodeId?: string | null,
): { nodes: ReactFlowNode[]; edges: ReactFlowEdge[] } {
  const failedNodeId = simulationResult?.failed_node_id ?? null;
  const impactedNodeIds = new Set(
    simulationResult?.impacted_nodes.map((n) => n.id) ?? [],
  );
  const hasSimulation = failedNodeId !== null;

  function shortLabel(node: { label: string }): string {
    return shortenLabel(node.label);
  }

  const entryParentMap = new Map<string, string>();
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  for (const edge of graph.edges) {
    const src = nodeById.get(edge.source_node_id);
    const tgt = nodeById.get(edge.target_node_id);
    if (edge.edge_type === "contains" && tgt?.node_type === "entry_point") {
      entryParentMap.set(edge.target_node_id, edge.source_node_id);
    }
    if (edge.edge_type === "contains" && src?.node_type === "entry_point") {
      entryParentMap.set(edge.source_node_id, edge.target_node_id);
    }
  }

  const mainTypes = new Set(["frontend", "backend", "database", "component"]);
  const auxTypes = new Set(["runtime", "tool", "external"]);

  const mainNodes = graph.nodes.filter((n) => mainTypes.has(n.node_type));
  const auxNodes = graph.nodes.filter((n) => auxTypes.has(n.node_type));
  const entryNodes = graph.nodes.filter((n) => n.node_type === "entry_point");
  const otherNodes = graph.nodes.filter(
    (n) =>
      !mainTypes.has(n.node_type) &&
      !auxTypes.has(n.node_type) &&
      n.node_type !== "entry_point",
  );

  const COL_W = 200;
  const ROW_H = 90;
  const NODE_W = 170;

  const rfNodes: ReactFlowNode[] = [];
  const componentColIndex = new Map<string, number>();

  function simStyle(
    nodeId: string,
    baseStyle: Record<string, unknown>,
  ): Record<string, unknown> {
    if (!hasSimulation && selectedComponentNodeId) {
      if (nodeId === selectedComponentNodeId) {
        return {
          ...baseStyle,
          border: "2.5px solid #818cf8",
          boxShadow: "0 0 14px 4px rgba(129,140,248,0.35)",
          cursor: "pointer",
        };
      }
      return { ...baseStyle, opacity: 0.35, cursor: "pointer" };
    }
    if (!hasSimulation) return { ...baseStyle, cursor: "pointer" };
    if (nodeId === failedNodeId) {
      return {
        ...baseStyle,
        border: "2.5px solid #ef4444",
        boxShadow: "0 0 14px 4px rgba(239,68,68,0.45)",
        background: "#2a0a0a",
        opacity: 1,
      };
    }
    if (impactedNodeIds.has(nodeId)) {
      return {
        ...baseStyle,
        border: "2px solid #f59e0b",
        boxShadow: "0 0 10px 2px rgba(245,158,11,0.35)",
        background: "#2a1a00",
        opacity: 1,
      };
    }
    return { ...baseStyle, opacity: 0.25 };
  }

  mainNodes.forEach((node, i) => {
    componentColIndex.set(node.id, i);
    const colors = NODE_COLORS[node.node_type] || NODE_COLORS.tool;
    rfNodes.push({
      id: node.id,
      position: { x: i * COL_W, y: 0 },
      data: { label: shortLabel(node) },
      style: simStyle(node.id, {
        border: `2px solid ${colors.border}`,
        borderRadius: "10px",
        padding: "8px 10px",
        background: colors.bg,
        color: "#e5e7eb",
        width: NODE_W,
        fontSize: "13px",
        fontWeight: 700,
        textAlign: "center",
      }),
    });
  });

  const entryCountPerParent = new Map<string, number>();
  entryNodes.forEach((node) => {
    const parentId = entryParentMap.get(node.id);
    const parentCol =
      parentId != null ? componentColIndex.get(parentId) : undefined;
    const col =
      parentCol ?? componentColIndex.size + (entryCountPerParent.size || 0);
    const subIdx = entryCountPerParent.get(String(col)) ?? 0;
    entryCountPerParent.set(String(col), subIdx + 1);

    const colors = NODE_COLORS.entry_point;
    rfNodes.push({
      id: node.id,
      position: { x: col * COL_W + 10, y: ROW_H + subIdx * (ROW_H - 10) },
      data: { label: shortLabel(node) },
      style: simStyle(node.id, {
        border: `1.5px dashed ${colors.border}`,
        borderRadius: "6px",
        padding: "5px 8px",
        background: colors.bg,
        color: "#e5e7eb",
        width: NODE_W - 20,
        fontSize: "11px",
        fontWeight: 500,
        textAlign: "center",
      }),
    });
  });

  const maxEntries = Math.max(
    1,
    ...Array.from(entryCountPerParent.values()),
  );
  const auxY = ROW_H + maxEntries * (ROW_H - 10) + 30;

  auxNodes.forEach((node, i) => {
    const colors = NODE_COLORS[node.node_type] || NODE_COLORS.tool;
    rfNodes.push({
      id: node.id,
      position: { x: i * COL_W, y: auxY },
      data: { label: shortLabel(node) },
      style: simStyle(node.id, {
        border: `1.5px solid ${colors.border}`,
        borderRadius: "8px",
        padding: "6px 8px",
        background: colors.bg,
        color: "#e5e7eb",
        width: NODE_W - 10,
        fontSize: "11px",
        fontWeight: 600,
        textAlign: "center",
      }),
    });
  });

  otherNodes.forEach((node, i) => {
    const colors = NODE_COLORS.tool;
    rfNodes.push({
      id: node.id,
      position: { x: (auxNodes.length + i) * COL_W, y: auxY },
      data: { label: shortLabel(node) },
      style: simStyle(node.id, {
        border: `1px solid ${colors.border}`,
        borderRadius: "8px",
        padding: "6px 8px",
        background: colors.bg,
        color: "#e5e7eb",
        width: NODE_W - 10,
        fontSize: "11px",
        fontWeight: 600,
        textAlign: "center",
      }),
    });
  });

  const simNodeIds = new Set<string>();
  if (hasSimulation) {
    simNodeIds.add(failedNodeId!);
    for (const n of simulationResult!.impacted_nodes) simNodeIds.add(n.id);
  }

  const rfEdges: ReactFlowEdge[] = graph.edges.map((edge) => {
    const srcInSim = simNodeIds.has(edge.source_node_id);
    const tgtInSim = simNodeIds.has(edge.target_node_id);
    const bothInSim = srcInSim && tgtInSim;

    return {
      id: edge.id,
      source: edge.source_node_id,
      target: edge.target_node_id,
      animated: bothInSim,
      style: hasSimulation
        ? bothInSim
          ? { stroke: "#f59e0b", strokeWidth: 2 }
          : { stroke: "#475569", strokeWidth: 1.2, opacity: 0.2 }
        : { stroke: "#475569", strokeWidth: 1.2 },
    };
  });

  return { nodes: rfNodes, edges: rfEdges };
}

/* ── Component ── */

interface ArchitectureViewProps {
  graph: GraphResponse | null;
  scan: ScanResult | null;
  simResult: SimulationResult | null;
  ddSelectedRoot: string | null;
  onNodeClick: (nodeId: string) => void;
  onDeepDive: (componentRoot: string) => void;
  generatingGraph: boolean;
  graphMessage: string | null;
  onGenerateGraph: () => void;
}

export default function ArchitectureView({
  graph,
  scan,
  simResult,
  ddSelectedRoot,
  onNodeClick,
  onDeepDive,
  generatingGraph,
  graphMessage,
  onGenerateGraph,
}: ArchitectureViewProps) {
  if (!graph) {
    return (
      <div>
        <h1 className="view-title">Architecture</h1>
        <div className="view-empty">
          <p className="view-empty-title">No graph built yet</p>
          <p className="view-empty-sub">
            Run a scan first, then build the architecture graph.
          </p>
          <button
            className="btn btn-primary"
            style={{ marginTop: 16 }}
            onClick={onGenerateGraph}
            disabled={generatingGraph}
          >
            {generatingGraph ? "Building…" : "Build Graph"}
          </button>
          {graphMessage && graphMessage !== "Graph ready" && (
            <p className="text-error" style={{ marginTop: 8 }}>
              {graphMessage}
            </p>
          )}
        </div>
      </div>
    );
  }

  // Resolve selected component → graph node ID for highlight
  let selectedGraphNodeId: string | null = null;
  if (ddSelectedRoot && scan) {
    const selComp = (scan.components || []).find(
      (c) => c.root_path === ddSelectedRoot,
    );
    if (selComp) {
      selectedGraphNodeId =
        graph.nodes.find(
          (n) =>
            ["frontend", "backend", "component"].includes(n.node_type) &&
            n.data.component_key === selComp.component_key,
        )?.id ?? null;
    }
  }

  const flowGraph = toReactFlowGraph(graph, simResult, selectedGraphNodeId);
  const nodeLabelById = Object.fromEntries(
    graph.nodes.map((n) => [n.id, n.label]),
  );

  return (
    <div>
      <h1 className="view-title">Architecture</h1>

      {/* Stats badges */}
      <div className="graph-stats">
        <span className="chip">
          {graph.node_count} {graph.node_count === 1 ? "node" : "nodes"}
        </span>
        <span className="chip">
          {graph.edge_count}{" "}
          {graph.edge_count === 1 ? "connection" : "connections"}
        </span>
        <button
          className="btn btn-secondary btn-sm"
          style={{ marginLeft: "auto" }}
          onClick={onGenerateGraph}
          disabled={generatingGraph}
        >
          {generatingGraph ? "Rebuilding…" : "Rebuild"}
        </button>
      </div>

      {/* Graph canvas */}
      <div className="graph-full">
        <ReactFlow
          nodes={flowGraph.nodes}
          edges={flowGraph.edges}
          fitView
          fitViewOptions={{ padding: 0.18, minZoom: 0.3, maxZoom: 1.4 }}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          onNodeClick={(_event, node) => onNodeClick(node.id)}
          panOnDrag
          zoomOnScroll={false}
          zoomOnPinch
          onInit={(instance: ReactFlowInstance) => {
            setTimeout(() => {
              instance.fitView({
                padding: 0.18,
                minZoom: 0.3,
                maxZoom: 1.4,
              });
            }, 50);
          }}
        >
          <MiniMap pannable zoomable position="bottom-left" style={{ background: "#080808" }} />
          <Controls style={{ background: "#111111", border: "1px solid #1f1f1f", borderRadius: 6 }} />
          <Background gap={20} color="#1a1a1a" />
        </ReactFlow>
      </div>

      {/* Component chips — click to deep-dive */}
      {scan?.components && scan.components.length > 0 && (
        <div className="arch-section">
          <div className="card-label">Components — click to deep-dive</div>
          <div className="chip-list" style={{ marginTop: 6 }}>
            {scan.components
              .filter(
                (c) =>
                  c.type === "frontend" ||
                  c.type === "backend" ||
                  c.type === "service",
              )
              .map((comp) => (
                <button
                  key={comp.root_path}
                  className="chip chip-interactive"
                  onClick={() => onDeepDive(comp.root_path)}
                >
                  {comp.name === "root" ? "Project Root" : comp.name}
                  <span className="text-muted" style={{ marginLeft: 4 }}>
                    &middot; {comp.type}
                  </span>
                </button>
              ))}
          </div>
        </div>
      )}

      {/* All nodes */}
      {graph.nodes.length > 0 && (
        <div className="arch-section">
          <div className="card-label">All Nodes</div>
          <div className="chip-list" style={{ marginTop: 6 }}>
            {graph.nodes.map((node) => (
              <span key={node.id} className="chip chip-muted">
                {shortenLabel(node.label)}{" "}
                <span className="text-muted">&middot; {node.node_type}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Connections */}
      {graph.edges.length > 0 && (
        <div className="arch-section">
          <div className="card-label">Connections</div>
          <div className="chip-list" style={{ marginTop: 6 }}>
            {graph.edges.map((edge) => (
              <span key={edge.id} className="chip chip-muted">
                {shortenLabel(nodeLabelById[edge.source_node_id] || "?")}{" "}
                &rarr;{" "}
                {shortenLabel(nodeLabelById[edge.target_node_id] || "?")}
                <span className="text-muted"> &middot; {edge.edge_type}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
