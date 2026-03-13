import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Layers3,
  Network,
  RefreshCw,
  Search,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Edge as ReactFlowEdge,
  type Node as ReactFlowNode,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type {
  GraphNode,
  GraphResponse,
  ScanResult,
  SimulationResult,
} from "../types";
import PageHeader from "../components/PageHeader";
import { shortenLabel } from "../types";

type GraphScope = "all" | "core" | "entry" | "integrations";

type ArchitectureNodeData = {
  label: string;
  nodeTypeLabel: string;
  nodeTypeKey: string;
  subtitle: string;
  meta: string | null;
  tone: string;
  isSelected: boolean;
  isDimmed: boolean;
  isFailed: boolean;
  isImpacted: boolean;
};

type GraphTone = "canonical" | "fallback" | "sparse";

type NodeTypeMeta = {
  label: string;
  description: string;
  tone: string;
};

const NODE_TYPE_META: Record<string, NodeTypeMeta> = {
  frontend: {
    label: "Frontend",
    description: "User-facing application surfaces and UI composition.",
    tone: "frontend",
  },
  backend: {
    label: "Backend",
    description: "Primary server-side application surfaces and APIs.",
    tone: "backend",
  },
  component: {
    label: "Component",
    description: "Detected bounded subsystem or service-level block.",
    tone: "component",
  },
  entry_point: {
    label: "Entry point",
    description: "Ingress into a component such as route or startup boundary.",
    tone: "entry",
  },
  database: {
    label: "Database",
    description: "Persisted storage or query boundary.",
    tone: "database",
  },
  external: {
    label: "External",
    description: "Third-party system or external dependency edge.",
    tone: "external",
  },
  runtime: {
    label: "Runtime",
    description: "Execution environment, platform, or infrastructure runtime.",
    tone: "runtime",
  },
  tool: {
    label: "Tooling",
    description: "Build, orchestration, or supporting platform surface.",
    tone: "tool",
  },
};

const NODE_TYPE_ORDER = [
  "frontend",
  "backend",
  "component",
  "entry_point",
  "database",
  "external",
  "runtime",
  "tool",
];

const EDGE_LABELS: Record<string, string> = {
  contains: "contains",
  calls: "calls",
  connects_to: "connects to",
  uses: "uses",
  depends_on: "depends on",
  serves: "serves",
};

const ARCHITECTURE_NODE_TYPES = {
  architectureNode: ArchitectureGraphNode,
};

function ArchitectureGraphNode({ data }: NodeProps<ReactFlowNode<ArchitectureNodeData>>) {
  const nodeData = data as ArchitectureNodeData;

  return (
    <div
      className={[
        "arch-node",
        `tone-${nodeData.tone}`,
        nodeData.isSelected ? "is-selected" : "",
        nodeData.isDimmed ? "is-dimmed" : "",
        nodeData.isFailed ? "is-failed" : "",
        nodeData.isImpacted ? "is-impacted" : "",
      ].filter(Boolean).join(" ")}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0, pointerEvents: "none" }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0, pointerEvents: "none" }} />
      <div className="arch-node-topline">
        <span className="arch-node-type">{nodeData.nodeTypeLabel}</span>
        {nodeData.isFailed ? <span className="arch-node-flag is-failed">Failed</span> : null}
        {!nodeData.isFailed && nodeData.isImpacted ? <span className="arch-node-flag is-impacted">Impacted</span> : null}
      </div>
      <div className="arch-node-title">{nodeData.label}</div>
      <div className="arch-node-subtitle">{nodeData.subtitle}</div>
      {nodeData.meta ? <div className="arch-node-meta">{nodeData.meta}</div> : null}
    </div>
  );
}

function readableNodeType(nodeType: string): string {
  return NODE_TYPE_META[nodeType]?.label ?? nodeType.replace(/_/g, " ");
}

function readableEdgeType(edgeType: string): string {
  return EDGE_LABELS[edgeType] ?? edgeType.replace(/_/g, " ");
}

function graphSource(graph: GraphResponse): string {
  const sources = new Set(
    graph.nodes
      .map((node) => typeof node.data.graph_source === "string" ? node.data.graph_source : null)
      .filter((value): value is string => Boolean(value)),
  );

  if (sources.has("canonical_snapshot")) {
    return "canonical_snapshot";
  }
  if (sources.has("raw_scan_fallback")) {
    return "raw_scan_fallback";
  }
  return "unknown";
}

function graphTone(graph: GraphResponse): GraphTone {
  const source = graphSource(graph);
  if (source !== "canonical_snapshot") {
    return "fallback";
  }
  if (graph.node_count < 5 || graph.edge_count < 4) {
    return "sparse";
  }
  return "canonical";
}

function trustLabel(graph: GraphResponse): string {
  const source = graphSource(graph);
  if (source === "canonical_snapshot") {
    return "Canonical snapshot-backed";
  }
  if (source === "raw_scan_fallback") {
    return "Raw scan fallback";
  }
  return "Graph source unknown";
}

function trustCopy(graph: GraphResponse): string {
  const source = graphSource(graph);
  if (source === "canonical_snapshot") {
    if (graph.node_count < 5 || graph.edge_count < 4) {
      return "This graph is canonical-backed, but the visible topology is still sparse. Treat it as a partial architecture map rather than a full dependency picture.";
    }
    return "This graph is projected from the validated canonical snapshot. It should be treated as the strongest current architecture map for this project.";
  }
  if (source === "raw_scan_fallback") {
    return "This graph is built from raw scan signals because a canonical snapshot was not available. Use it for orientation and entry-point discovery, not exhaustive dependency truth.";
  }
  return "Graph provenance is not explicit in the current payload. Treat this surface as a structural map only.";
}

function architecturePurposeCopy(graph: GraphResponse): string {
  if (graphTone(graph) === "fallback") {
    return "Use this workspace to understand the current structural shape of the system, then move into Deep Dive or Simulation with appropriate caution.";
  }
  return "Use this workspace to read the system at a glance, understand the main blocks, and move into Deep Dive or Simulation from grounded graph structure.";
}

function nodeSubtitle(node: GraphNode): string {
  if (node.node_type === "entry_point") {
    return typeof node.data.entry_file === "string" && node.data.entry_file.length > 0
      ? shortenLabel(node.data.entry_file)
      : "Ingress boundary";
  }

  if (typeof node.data.component_type === "string" && node.data.component_type.length > 0) {
    return node.data.component_type;
  }

  if (typeof node.data.language === "string" && node.data.language.length > 0) {
    return node.data.language;
  }

  return readableNodeType(node.node_type);
}

function nodeMeta(node: GraphNode): string | null {
  if (typeof node.data.root_path === "string" && node.data.root_path.length > 0) {
    return shortenLabel(node.data.root_path);
  }

  if (typeof node.data.entry_file === "string" && node.data.entry_file.length > 0) {
    return shortenLabel(node.data.entry_file);
  }

  if (typeof node.data.file_count === "number") {
    return `${node.data.file_count} files`;
  }

  return null;
}

function scopeMatches(nodeType: string, scope: GraphScope): boolean {
  if (scope === "all") return true;
  if (scope === "core") return ["frontend", "backend", "component"].includes(nodeType);
  if (scope === "entry") return nodeType === "entry_point";
  return ["database", "external", "runtime", "tool"].includes(nodeType);
}

function toReactFlowGraph(
  graph: GraphResponse,
  visibleNodeIds: Set<string>,
  simulationResult?: SimulationResult | null,
  selectedComponentNodeId?: string | null,
  focusedNodeId?: string | null,
): { nodes: ReactFlowNode<ArchitectureNodeData>[]; edges: ReactFlowEdge[] } {
  const failedNodeId = simulationResult?.failed_node_id ?? null;
  const impactedNodeIds = new Set(simulationResult?.impacted_nodes.map((node) => node.id) ?? []);
  const hasSimulation = failedNodeId !== null;
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const entryParentMap = new Map<string, string>();

  for (const edge of graph.edges) {
    const sourceNode = nodeById.get(edge.source_node_id);
    const targetNode = nodeById.get(edge.target_node_id);
    if (edge.edge_type === "contains" && targetNode?.node_type === "entry_point") {
      entryParentMap.set(edge.target_node_id, edge.source_node_id);
    }
    if (edge.edge_type === "contains" && sourceNode?.node_type === "entry_point") {
      entryParentMap.set(edge.source_node_id, edge.target_node_id);
    }
  }

  const focusRootId = focusedNodeId ?? selectedComponentNodeId ?? null;
  const focusNeighborhood = new Set<string>();
  if (focusRootId) {
    focusNeighborhood.add(focusRootId);
    for (const edge of graph.edges) {
      if (edge.source_node_id === focusRootId) {
        focusNeighborhood.add(edge.target_node_id);
      }
      if (edge.target_node_id === focusRootId) {
        focusNeighborhood.add(edge.source_node_id);
      }
    }
  }

  const mainNodes = graph.nodes.filter((node) => visibleNodeIds.has(node.id) && ["frontend", "backend", "component"].includes(node.node_type));
  const entryNodes = graph.nodes.filter((node) => visibleNodeIds.has(node.id) && node.node_type === "entry_point");
  const integrationNodes = graph.nodes.filter((node) => visibleNodeIds.has(node.id) && ["database", "external", "runtime", "tool"].includes(node.node_type));
  const otherNodes = graph.nodes.filter(
    (node) => visibleNodeIds.has(node.id)
      && !["frontend", "backend", "component", "entry_point", "database", "external", "runtime", "tool"].includes(node.node_type),
  );

  const columnIndexById = new Map<string, number>();
  const rfNodes: ReactFlowNode<ArchitectureNodeData>[] = [];
  const columnWidth = 260;
  const nodeWidth = 212;
  const mainRowY = 0;
  const entryRowBaseY = 176;

  function isSelected(nodeId: string): boolean {
    return Boolean(nodeId === focusRootId || nodeId === failedNodeId);
  }

  function isDimmed(nodeId: string): boolean {
    if (hasSimulation) {
      return nodeId !== failedNodeId && !impactedNodeIds.has(nodeId);
    }
    if (!focusRootId) {
      return false;
    }
    return !focusNeighborhood.has(nodeId);
  }

  mainNodes.forEach((node, index) => {
    columnIndexById.set(node.id, index);
    const typeMeta = NODE_TYPE_META[node.node_type] ?? NODE_TYPE_META.tool;
    rfNodes.push({
      id: node.id,
      type: "architectureNode",
      position: { x: index * columnWidth, y: mainRowY },
      data: {
        label: shortenLabel(node.label),
        nodeTypeLabel: typeMeta.label,
        nodeTypeKey: node.node_type,
        subtitle: nodeSubtitle(node),
        meta: nodeMeta(node),
        tone: typeMeta.tone,
        isSelected: isSelected(node.id),
        isDimmed: isDimmed(node.id),
        isFailed: node.id === failedNodeId,
        isImpacted: impactedNodeIds.has(node.id),
      },
      draggable: false,
      selectable: true,
      style: { width: nodeWidth },
    });
  });

  const entryCountPerColumn = new Map<number, number>();
  entryNodes.forEach((node, index) => {
    const parentId = entryParentMap.get(node.id);
    const columnIndex = parentId ? columnIndexById.get(parentId) ?? index : index;
    const offset = entryCountPerColumn.get(columnIndex) ?? 0;
    entryCountPerColumn.set(columnIndex, offset + 1);
    const typeMeta = NODE_TYPE_META.entry_point;

    rfNodes.push({
      id: node.id,
      type: "architectureNode",
      position: { x: columnIndex * columnWidth + 14, y: entryRowBaseY + offset * 114 },
      data: {
        label: shortenLabel(node.label),
        nodeTypeLabel: typeMeta.label,
        nodeTypeKey: node.node_type,
        subtitle: nodeSubtitle(node),
        meta: nodeMeta(node),
        tone: typeMeta.tone,
        isSelected: isSelected(node.id),
        isDimmed: isDimmed(node.id),
        isFailed: node.id === failedNodeId,
        isImpacted: impactedNodeIds.has(node.id),
      },
      draggable: false,
      selectable: true,
      style: { width: nodeWidth - 28 },
    });
  });

  const maxEntryStack = Math.max(1, ...Array.from(entryCountPerColumn.values(), (value) => value));
  const supportRowY = entryRowBaseY + maxEntryStack * 114 + 72;

  [...integrationNodes, ...otherNodes].forEach((node, index) => {
    const typeMeta = NODE_TYPE_META[node.node_type] ?? NODE_TYPE_META.tool;
    rfNodes.push({
      id: node.id,
      type: "architectureNode",
      position: { x: index * columnWidth, y: supportRowY },
      data: {
        label: shortenLabel(node.label),
        nodeTypeLabel: typeMeta.label,
        nodeTypeKey: node.node_type,
        subtitle: nodeSubtitle(node),
        meta: nodeMeta(node),
        tone: typeMeta.tone,
        isSelected: isSelected(node.id),
        isDimmed: isDimmed(node.id),
        isFailed: node.id === failedNodeId,
        isImpacted: impactedNodeIds.has(node.id),
      },
      draggable: false,
      selectable: true,
      style: { width: nodeWidth - 12 },
    });
  });

  const rfEdges: ReactFlowEdge[] = graph.edges
    .filter((edge) => visibleNodeIds.has(edge.source_node_id) && visibleNodeIds.has(edge.target_node_id))
    .map((edge) => {
      const touchesFocus = focusRootId && (edge.source_node_id === focusRootId || edge.target_node_id === focusRootId);
      const inSimulation = hasSimulation && (
        (edge.source_node_id === failedNodeId || impactedNodeIds.has(edge.source_node_id))
        && (edge.target_node_id === failedNodeId || impactedNodeIds.has(edge.target_node_id))
      );

      return {
        id: edge.id,
        source: edge.source_node_id,
        target: edge.target_node_id,
        animated: Boolean(inSimulation),
        style: hasSimulation
          ? inSimulation
            ? { stroke: "rgba(245, 158, 11, 0.78)", strokeWidth: 2 }
            : { stroke: "rgba(100, 116, 139, 0.18)", strokeWidth: 1.1 }
          : touchesFocus
            ? { stroke: "rgba(96, 165, 250, 0.58)", strokeWidth: 1.8 }
            : focusRootId
              ? { stroke: "rgba(100, 116, 139, 0.18)", strokeWidth: 1.1 }
              : { stroke: "rgba(148, 163, 184, 0.26)", strokeWidth: 1.2 },
      };
    });

  return { nodes: rfNodes, edges: rfEdges };
}

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
  const [scope, setScope] = useState<GraphScope>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [enabledTypes, setEnabledTypes] = useState<Set<string>>(new Set(NODE_TYPE_ORDER));
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance<ReactFlowNode<ArchitectureNodeData>, ReactFlowEdge> | null>(null);

  const filteredComponents = useMemo(
    () => (scan?.components ?? []).filter((component) => ["frontend", "backend", "service"].includes(component.type)),
    [scan],
  );

  let selectedGraphNodeId: string | null = null;
  if (graph && ddSelectedRoot && scan) {
    const selectedComponent = (scan.components || []).find((component) => component.root_path === ddSelectedRoot);
    if (selectedComponent) {
      selectedGraphNodeId = graph.nodes.find(
        (node) => ["frontend", "backend", "component"].includes(node.node_type)
          && node.data.component_key === selectedComponent.component_key,
      )?.id ?? null;
    }
  }

  const source = graph ? graphSource(graph) : "unknown";
  const tone = graph ? graphTone(graph) : "fallback";
  const nodeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of graph?.nodes ?? []) {
      counts.set(node.node_type, (counts.get(node.node_type) ?? 0) + 1);
    }
    return counts;
  }, [graph]);

  const edgeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const edge of graph?.edges ?? []) {
      counts.set(edge.edge_type, (counts.get(edge.edge_type) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .sort((left, right) => right[1] - left[1])
      .slice(0, 4);
  }, [graph]);

  const visibleNodeIds = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    return new Set(
      (graph?.nodes ?? [])
        .filter((node) => enabledTypes.has(node.node_type))
        .filter((node) => scopeMatches(node.node_type, scope))
        .filter((node) => {
          if (!normalizedQuery) {
            return true;
          }
          const haystack = [
            node.label,
            node.node_type,
            typeof node.data.root_path === "string" ? node.data.root_path : "",
            typeof node.data.entry_file === "string" ? node.data.entry_file : "",
            typeof node.data.component_type === "string" ? node.data.component_type : "",
          ].join(" ").toLowerCase();
          return haystack.includes(normalizedQuery);
        })
        .map((node) => node.id),
    );
  }, [enabledTypes, graph, scope, searchQuery]);

  const visibleNodes = useMemo(
    () => (graph?.nodes ?? []).filter((node) => visibleNodeIds.has(node.id)),
    [graph, visibleNodeIds],
  );
  const visibleEdges = useMemo(
    () => (graph?.edges ?? []).filter((edge) => visibleNodeIds.has(edge.source_node_id) && visibleNodeIds.has(edge.target_node_id)),
    [graph, visibleNodeIds],
  );

  const degreeByNodeId = useMemo(() => {
    const degreeMap = new Map<string, number>();
    for (const node of visibleNodes) {
      degreeMap.set(node.id, 0);
    }
    for (const edge of visibleEdges) {
      degreeMap.set(edge.source_node_id, (degreeMap.get(edge.source_node_id) ?? 0) + 1);
      degreeMap.set(edge.target_node_id, (degreeMap.get(edge.target_node_id) ?? 0) + 1);
    }
    return degreeMap;
  }, [visibleEdges, visibleNodes]);

  const topologyHotspots = useMemo(
    () => visibleNodes
      .map((node) => ({
        id: node.id,
        label: node.label,
        nodeType: node.node_type,
        degree: degreeByNodeId.get(node.id) ?? 0,
      }))
      .sort((left, right) => right.degree - left.degree)
      .slice(0, 4),
    [degreeByNodeId, visibleNodes],
  );

  const flowGraph = useMemo(
    () => graph
      ? toReactFlowGraph(graph, visibleNodeIds, simResult, selectedGraphNodeId, focusedNodeId)
      : { nodes: [], edges: [] },
    [focusedNodeId, graph, selectedGraphNodeId, simResult, visibleNodeIds],
  );

  const focusedNode = graph?.nodes.find(
    (node) => node.id === (focusedNodeId ?? selectedGraphNodeId ?? simResult?.failed_node_id ?? ""),
  ) ?? null;
  const visibleCountCopy = !graph || visibleNodeIds.size === graph.node_count
    ? `${graph?.node_count ?? 0} nodes in view`
    : `${visibleNodeIds.size} of ${graph.node_count} nodes visible`;
  const integrationCount = ["database", "external", "runtime", "tool"].reduce((sum, nodeType) => sum + (nodeCounts.get(nodeType) ?? 0), 0);
  const focusComponentRoot = typeof focusedNode?.data.root_path === "string" ? focusedNode.data.root_path : null;

  if (!graph) {
    return (
      <div className="page-shell architecture-page">
        <PageHeader
          eyebrow="System Graph"
          title="Architecture"
          description="Build the architecture workspace from the current scan to see the main system blocks, ingress points, and integration boundaries before deeper analysis."
        />
        <section className="arch-empty surface-panel">
          <div className="arch-empty-copy">
            <div className="intel-section-kicker">Architecture workspace</div>
            <h2 className="arch-empty-title">No architecture graph has been built for this project yet.</h2>
            <p className="arch-empty-sub">
              The graph is the structural map behind Deep Dive and Simulation. Build it after a scan so the page reflects the current backend truth instead of a placeholder abstraction.
            </p>
          </div>

          <div className="arch-empty-steps">
            <div className="arch-empty-step">
              <span className="arch-empty-step-number">1</span>
              <div>
                <p className="arch-empty-step-title">Run a scan first</p>
                <p className="arch-empty-step-copy">The graph only builds from current scan artifacts. No structure is invented client-side.</p>
              </div>
            </div>
            <div className="arch-empty-step">
              <span className="arch-empty-step-number">2</span>
              <div>
                <p className="arch-empty-step-title">Build the graph</p>
                <p className="arch-empty-step-copy">Canonical snapshot projection is used when available. Otherwise the page stays explicit about raw scan fallback.</p>
              </div>
            </div>
            <div className="arch-empty-step">
              <span className="arch-empty-step-number">3</span>
              <div>
                <p className="arch-empty-step-title">Use it as a workspace</p>
                <p className="arch-empty-step-copy">From here you can orient the system, focus a node, and move into Deep Dive or Simulation without leaving the truth boundary.</p>
              </div>
            </div>
          </div>

          <div className="arch-empty-actions">
            <button className="btn btn-primary" onClick={onGenerateGraph} disabled={generatingGraph}>
              {generatingGraph ? "Building…" : "Build Graph"}
            </button>
            {graphMessage && graphMessage !== "Graph ready" ? (
              <p className="text-error arch-empty-message">{graphMessage}</p>
            ) : null}
          </div>
        </section>
      </div>
    );
  }

  function handleNodeClick(nodeId: string) {
    setFocusedNodeId(nodeId);
    onNodeClick(nodeId);
  }

  function handleFitView() {
    flowInstance?.fitView({ padding: 0.18, minZoom: 0.3, maxZoom: 1.35 });
  }

  function clearFilters() {
    setScope("all");
    setSearchQuery("");
    setEnabledTypes(new Set(NODE_TYPE_ORDER));
  }

  function toggleType(nodeType: string) {
    setEnabledTypes((previous) => {
      const next = new Set(previous);
      if (next.has(nodeType)) {
        if (next.size === 1) {
          return previous;
        }
        next.delete(nodeType);
      } else {
        next.add(nodeType);
      }
      return next;
    });
  }

  return (
    <div className="page-shell architecture-page">
      <PageHeader
        eyebrow="System Graph"
        title="Architecture"
        description="A grounded architecture workspace for reading the current topology, understanding scope, and moving into deeper product surfaces without leaving backend truth."
        meta={(
          <>
            <span className={`badge ${tone === "canonical" ? "badge-success" : tone === "fallback" ? "badge-pending" : "badge-pending"}`}>
              {trustLabel(graph)}
            </span>
            <span className="chip chip-muted">{graph.node_count} nodes</span>
            <span className="chip chip-muted">{graph.edge_count} edges</span>
            {scan ? <span className="chip chip-muted">{scan.components.length} scanned components</span> : null}
          </>
        )}
      />

      <section className="arch-hero surface-panel">
        <div className="arch-hero-copy">
          <div className="intel-section-kicker">Architecture workspace</div>
          <h2 className="arch-hero-title">Read the system as topology, not just as a graph widget.</h2>
          <p className="arch-hero-subtitle">{architecturePurposeCopy(graph)}</p>
          <div className="arch-trust-banner-row">
            <div className={`arch-trust-banner tone-${tone}`}>
              {tone === "fallback" ? <AlertTriangle size={15} /> : <ShieldCheck size={15} />}
              <span>{trustCopy(graph)}</span>
            </div>
            {graphMessage ? <div className="arch-inline-message">{graphMessage}</div> : null}
          </div>
        </div>

        <div className="arch-hero-stats">
          <div className="arch-hero-stat">
            <span className="arch-hero-stat-label">Primary blocks</span>
            <span className="arch-hero-stat-value">{(nodeCounts.get("frontend") ?? 0) + (nodeCounts.get("backend") ?? 0) + (nodeCounts.get("component") ?? 0)}</span>
            <span className="arch-hero-stat-sub">Frontend, backend, and bounded components</span>
          </div>
          <div className="arch-hero-stat">
            <span className="arch-hero-stat-label">Entry points</span>
            <span className="arch-hero-stat-value">{nodeCounts.get("entry_point") ?? 0}</span>
            <span className="arch-hero-stat-sub">Visible ingress into the mapped system</span>
          </div>
          <div className="arch-hero-stat">
            <span className="arch-hero-stat-label">Integrations</span>
            <span className="arch-hero-stat-value">{integrationCount}</span>
            <span className="arch-hero-stat-sub">Data stores, runtime, external, and tools</span>
          </div>
          <div className="arch-hero-stat">
            <span className="arch-hero-stat-label">Visible scope</span>
            <span className="arch-hero-stat-value">{visibleNodes.length}</span>
            <span className="arch-hero-stat-sub">{visibleCountCopy}</span>
          </div>
        </div>
      </section>

      <div className="arch-workspace-layout">
        <section className="arch-main-column">
          <div className="arch-controls surface-panel">
            <div className="arch-controls-head">
              <div>
                <div className="intel-section-kicker">Graph controls</div>
                <h3 className="arch-controls-title">Scope the architecture map</h3>
              </div>
              <div className="arch-controls-actions">
                <button type="button" className="btn btn-secondary btn-sm" onClick={handleFitView}>
                  <Network size={14} />
                  Fit view
                </button>
                <button type="button" className="btn btn-secondary btn-sm" onClick={clearFilters}>
                  Reset filters
                </button>
                <button type="button" className="btn btn-primary btn-sm" onClick={onGenerateGraph} disabled={generatingGraph}>
                  <RefreshCw size={14} />
                  {generatingGraph ? "Rebuilding…" : "Rebuild graph"}
                </button>
              </div>
            </div>

            <div className="arch-search-shell">
              <Search size={15} />
              <input
                className="arch-search-input"
                type="text"
                placeholder="Search node label, type, file, or root path"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </div>

            <div className="arch-scope-row">
              {([
                ["all", "All graph"],
                ["core", "Core blocks"],
                ["entry", "Entry points"],
                ["integrations", "Integrations"],
              ] as Array<[GraphScope, string]>).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={`arch-scope-pill${scope === value ? " active" : ""}`}
                  onClick={() => setScope(value)}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="arch-filter-row">
              {NODE_TYPE_ORDER.filter((nodeType) => nodeCounts.get(nodeType)).map((nodeType) => (
                <button
                  key={nodeType}
                  type="button"
                  className={`arch-filter-chip tone-${NODE_TYPE_META[nodeType]?.tone ?? "tool"}${enabledTypes.has(nodeType) ? " active" : ""}`}
                  onClick={() => toggleType(nodeType)}
                >
                  <span>{NODE_TYPE_META[nodeType]?.label ?? readableNodeType(nodeType)}</span>
                  <span>{nodeCounts.get(nodeType)}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="arch-canvas-shell surface-panel">
            <div className="arch-canvas-head">
              <div>
                <div className="intel-section-kicker">Topology map</div>
                <h3 className="arch-canvas-title">Current architecture graph</h3>
                <p className="arch-canvas-subtitle">
                  Components sit on the primary rail, entry points sit beneath their owners, and supporting systems move to the lower support rail.
                </p>
              </div>
              <div className="arch-canvas-meta">
                <span className="chip chip-muted">{visibleCountCopy}</span>
                <span className="chip chip-muted">{visibleEdges.length} visible edges</span>
              </div>
            </div>

            <div className="graph-full arch-graph-frame">
              {visibleNodes.length === 0 ? (
                <div className="arch-graph-empty">
                  <Search size={20} />
                  <p className="arch-graph-empty-title">No graph elements match the current filters.</p>
                  <p className="arch-graph-empty-sub">Reset the scope or re-enable node categories to restore the current topology.</p>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={clearFilters}>
                    Reset filters
                  </button>
                </div>
              ) : (
                <ReactFlow
                  nodes={flowGraph.nodes}
                  edges={flowGraph.edges}
                  nodeTypes={ARCHITECTURE_NODE_TYPES}
                  fitView
                  fitViewOptions={{ padding: 0.18, minZoom: 0.3, maxZoom: 1.35 }}
                  proOptions={{ hideAttribution: true }}
                  nodesDraggable={false}
                  nodesConnectable={false}
                  elementsSelectable
                  panOnDrag
                  zoomOnScroll={false}
                  zoomOnPinch
                  onNodeClick={(_event, node) => handleNodeClick(node.id)}
                  onPaneClick={() => setFocusedNodeId(null)}
                  onInit={(instance) => {
                    setFlowInstance(instance);
                    setTimeout(() => {
                      instance.fitView({ padding: 0.18, minZoom: 0.3, maxZoom: 1.35 });
                    }, 50);
                  }}
                >
                  <MiniMap
                    pannable
                    zoomable
                    position="bottom-right"
                    className="arch-minimap"
                    maskColor="rgba(7, 12, 20, 0.74)"
                  />
                  <Controls position="top-right" className="arch-flow-controls" showInteractive={false} />
                  <Background gap={24} color="rgba(148, 163, 184, 0.08)" />
                </ReactFlow>
              )}
            </div>
          </div>
        </section>

        <aside className="arch-side-column">
          <div className="arch-side-panel surface-panel">
            <div className="arch-side-panel-head">
              <div>
                <div className="intel-section-kicker">Reading guide</div>
                <h3 className="arch-side-title">How to read this graph</h3>
              </div>
            </div>
            <div className="arch-guide-list">
              <div className="arch-guide-item">
                <Layers3 size={16} />
                <span>Start with the primary blocks. They describe the main application surface before you read support systems.</span>
              </div>
              <div className="arch-guide-item">
                <Workflow size={16} />
                <span>Entry points are attached below their owning block so ingress stays visually distinct from support dependencies.</span>
              </div>
              <div className="arch-guide-item">
                <ShieldCheck size={16} />
                <span>{source === "canonical_snapshot" ? "Canonical projection means the map is stronger and more authoritative." : "Fallback projection means this is still useful, but should be read as orientation rather than exhaustive truth."}</span>
              </div>
            </div>
          </div>

          <div className="arch-side-panel surface-panel">
            <div className="arch-side-panel-head">
              <div>
                <div className="intel-section-kicker">Node legend</div>
                <h3 className="arch-side-title">Visible categories</h3>
              </div>
            </div>
            <div className="arch-legend-list">
              {NODE_TYPE_ORDER.filter((nodeType) => nodeCounts.get(nodeType)).map((nodeType) => (
                <button
                  key={nodeType}
                  type="button"
                  className={`arch-legend-item tone-${NODE_TYPE_META[nodeType]?.tone ?? "tool"}${enabledTypes.has(nodeType) ? " active" : ""}`}
                  onClick={() => toggleType(nodeType)}
                >
                  <div>
                    <div className="arch-legend-title">{NODE_TYPE_META[nodeType]?.label ?? readableNodeType(nodeType)}</div>
                    <div className="arch-legend-copy">{NODE_TYPE_META[nodeType]?.description ?? "Visible graph category"}</div>
                  </div>
                  <span className="arch-legend-count">{nodeCounts.get(nodeType)}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="arch-side-panel surface-panel">
            <div className="arch-side-panel-head">
              <div>
                <div className="intel-section-kicker">Topology summary</div>
                <h3 className="arch-side-title">What stands out right now</h3>
              </div>
            </div>
            <div className="arch-summary-list">
              {topologyHotspots.length > 0 ? topologyHotspots.map((item) => (
                <div key={item.id} className="arch-summary-item">
                  <div>
                    <div className="arch-summary-title">{shortenLabel(item.label)}</div>
                    <div className="arch-summary-copy">{readableNodeType(item.nodeType)} · {item.degree} visible connections</div>
                  </div>
                  <button type="button" className="chip chip-interactive" onClick={() => handleNodeClick(item.id)}>
                    Focus
                  </button>
                </div>
              )) : (
                <div className="arch-summary-empty">No visible topology hotspots in the current filter scope.</div>
              )}
            </div>
            <div className="arch-edge-row">
              {edgeCounts.map(([edgeType, count]) => (
                <span key={edgeType} className="chip chip-muted">{readableEdgeType(edgeType)} {count}</span>
              ))}
            </div>
          </div>

          <div className="arch-side-panel surface-panel">
            <div className="arch-side-panel-head">
              <div>
                <div className="intel-section-kicker">Focus</div>
                <h3 className="arch-side-title">Selected architecture node</h3>
              </div>
            </div>
            {focusedNode ? (
              <div className="arch-focus-card">
                <div className="arch-focus-topline">
                  <span className={`arch-focus-badge tone-${NODE_TYPE_META[focusedNode.node_type]?.tone ?? "tool"}`}>
                    {readableNodeType(focusedNode.node_type)}
                  </span>
                  {focusedNode.data.graph_source === "raw_scan_fallback" ? <span className="arch-focus-note">Fallback-backed</span> : <span className="arch-focus-note">Canonical-backed</span>}
                </div>
                <div className="arch-focus-title">{focusedNode.label}</div>
                <div className="arch-focus-meta">
                  {focusedNode.data.root_path ? <span>{focusedNode.data.root_path}</span> : null}
                  {focusedNode.data.entry_file ? <span>{shortenLabel(String(focusedNode.data.entry_file))}</span> : null}
                  {focusedNode.data.component_type ? <span>{String(focusedNode.data.component_type)}</span> : null}
                </div>
                <p className="arch-focus-copy">
                  {NODE_TYPE_META[focusedNode.node_type]?.description ?? "This node is part of the current graph topology."}
                </p>
                {focusComponentRoot ? (
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => onDeepDive(focusComponentRoot)}>
                    Open in Deep Dive
                  </button>
                ) : null}
              </div>
            ) : (
              <div className="arch-summary-empty">Select a node to inspect its category, source backing, and direct handoff into deeper analysis.</div>
            )}
          </div>

          {filteredComponents.length > 0 && (
            <div className="arch-side-panel surface-panel">
              <div className="arch-side-panel-head">
                <div>
                  <div className="intel-section-kicker">Component handoff</div>
                  <h3 className="arch-side-title">Jump into component detail</h3>
                </div>
              </div>
              <div className="arch-component-list">
                {filteredComponents.map((component) => (
                  <button
                    key={component.root_path}
                    type="button"
                    className="arch-component-chip"
                    onClick={() => onDeepDive(component.root_path)}
                  >
                    <span>{component.name === "root" ? "Project Root" : component.name}</span>
                    <span>{component.type}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
