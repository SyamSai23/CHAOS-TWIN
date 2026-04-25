import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import { Zap, BookOpen, Map as MapIcon, ArrowRight, Lightbulb, AlertTriangle, List, ArrowUp } from "lucide-react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { API_BASE, fetchProjectUnderstanding } from "../api/client";
import type { ProjectUnderstandingResponse } from "../types";
import AIChatBubble, { AskCopilotButton, requestAIChatPrompt, type AIContextSection } from "../components/AIChatBubble";
import "./UnderstandingPage.css";

interface UnderstandingPageProps {
  projectId: string;
}

type FeatureFile = {
  path: string;
  file_type: string;
  summary: string;
  importance_score: number;
};

type Feature = {
  name: string;
  description: string;
  entry_point: string;
  files?: string[];
  importance: number;
  file_details?: FeatureFile[];
  files_detail?: FeatureFile[];
};

type FeatureNodeData = {
  name: string;
  description: string;
  importance: number;
  entry_point: string;
  file_count: number;
  files: FeatureFile[];
  dominant_type: string;
};

type TooltipState = {
  feature: FeatureNodeData;
  x: number;
  y: number;
} | null;

type GlossaryLookupItem = {
  term: string;
  definition: string;
  usedIn: string[];
};

type GlossaryTooltipState = (GlossaryLookupItem & {
  x: number;
  y: number;
}) | null;

type UnderstandingDepthRecord = {
  title?: string;
  beginner?: string;
  intermediate?: string;
  advanced?: string;
};

type UnderstandingWithDepth = ProjectUnderstandingResponse & {
  project_story_beginner?: string | null;
  project_story_intermediate?: string | null;
  project_story_advanced?: string | null;
  key_decisions_beginner?: UnderstandingDepthRecord[] | null;
  key_decisions_intermediate?: UnderstandingDepthRecord[] | null;
  key_decisions_advanced?: UnderstandingDepthRecord[] | null;
  gotchas_beginner?: UnderstandingDepthRecord[] | null;
  gotchas_intermediate?: UnderstandingDepthRecord[] | null;
  gotchas_advanced?: UnderstandingDepthRecord[] | null;
};

const FILE_TYPE_COLORS: Record<string, string> = {
  controller: "#4a7c59",
  model: "#705c30",
  service: "#2980b9",
  page: "#8e44ad",
  component: "#e67e22",
  route: "#c0392b",
  entry_point: "#c0392b",
  config: "#6c5ce7",
  other: "#74796e",
};

function typeColor(type: string | null | undefined) {
  const colors: Record<string, string> = {
    request: "#2980b9",
    processing: "#4a7c59",
    database: "#705c30",
    response: "#8e44ad",
    external: "#e67e22",
  };
  return colors[type || ""] || "#74796e";
}

function typeIcon(type: string | null | undefined) {
  const icons: Record<string, string> = {
    request: "→",
    processing: "⚙",
    database: "🗄",
    response: "←",
    external: "🌐",
  };
  return icons[type || ""] || "•";
}

function getDominantFileType(files?: FeatureFile[]) {
  if (!files || files.length === 0) return "other";
  const counts: Record<string, number> = {};
  files.forEach((file) => {
    counts[file.file_type] = (counts[file.file_type] || 0) + 1;
  });
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || "other";
}

function getFeatureFiles(feature: Feature) {
  return feature.files_detail
    ?? feature.file_details
    ?? (feature.files || []).map((path) => ({
      path,
      file_type: "other",
      summary: "",
      importance_score: 0,
    }));
}

function circularLayout(nodes: Node<FeatureNodeData>[], radius = 250) {
  const cx = 400;
  const cy = 250;
  if (nodes.length === 1) {
    return [
      {
        ...nodes[0],
        position: { x: cx - 75, y: cy - 40 },
      },
    ];
  }
  return nodes.map((node, index) => ({
    ...node,
    position: {
      x: cx + radius * Math.cos((2 * Math.PI * index) / nodes.length) - 75,
      y: cy + radius * Math.sin((2 * Math.PI * index) / nodes.length) - 40,
    },
  }));
}

function navigateToPath(pathname: string) {
  window.history.pushState({}, "", pathname);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function escapeRegex(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlightGlossaryTerms(
  text: string | null | undefined,
  glossaryMap: Map<string, GlossaryLookupItem>,
  onTermHover: (termData: GlossaryLookupItem, event: ReactMouseEvent<HTMLSpanElement>) => void,
  onTermLeave: () => void,
): ReactNode {
  if (!text || glossaryMap.size === 0) {
    return text ?? "";
  }

  const terms = Array.from(glossaryMap.keys()).sort((a, b) => b.length - a.length);
  if (terms.length === 0) {
    return text;
  }

  const pattern = new RegExp(`\\b(${terms.map((term) => escapeRegex(term)).join("|")})\\b`, "gi");
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    const term = match[0];
    const termData = glossaryMap.get(term.toLowerCase());

    if (!termData) {
      parts.push(term);
    } else {
      parts.push(
        <span
          key={`${match.index}-${term.toLowerCase()}`}
          style={{
            borderBottom: "1px dashed #4a7c59",
            color: "#4a7c59",
            cursor: "help",
            fontWeight: 500,
          }}
          onMouseEnter={(event) => onTermHover(termData, event)}
          onMouseLeave={onTermLeave}
        >
          {term}
        </span>,
      );
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? parts : text;
}

function FeatureNode({ data }: NodeProps<Node<FeatureNodeData>>) {
  const color = FILE_TYPE_COLORS[data.dominant_type] || FILE_TYPE_COLORS.other;
  const importancePercent = Math.max(8, Math.min(100, (data.importance || 0) * 100));

  return (
    <div
      style={{
        background: "#f5f1ea",
        border: `2px solid ${color}`,
        borderRadius: "12px",
        padding: "12px 16px",
        minWidth: "150px",
        maxWidth: "180px",
        cursor: "pointer",
        boxShadow: "0 4px 12px rgba(46,50,48,0.08)",
        fontFamily: "'Nunito Sans', sans-serif",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0, pointerEvents: "none" }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0, pointerEvents: "none" }} />
      <div
        style={{
          width: "8px",
          height: "8px",
          borderRadius: "50%",
          background: color,
          marginBottom: "6px",
        }}
      />
      <div
        style={{
          fontWeight: 700,
          fontSize: "13px",
          color: "#2e3230",
          marginBottom: "4px",
          lineHeight: 1.3,
        }}
      >
        {data.name}
      </div>
      <div
        style={{
          fontSize: "11px",
          color: "#74796e",
        }}
      >
        {data.file_count} files
      </div>
      <div
        style={{
          marginTop: "6px",
          height: "3px",
          borderRadius: "2px",
          background: color,
          width: `${importancePercent}%`,
          opacity: 0.6,
        }}
      />
    </div>
  );
}

const nodeTypes = { featureNode: FeatureNode };

const SECTIONS = [
  { id: "story", label: "Project Story", icon: BookOpen },
  { id: "map", label: "System Map", icon: MapIcon },
  { id: "journey", label: "Data Journey", icon: ArrowRight },
  { id: "decisions", label: "Key Decisions", icon: Lightbulb },
  { id: "gotchas", label: "Gotchas", icon: AlertTriangle },
  { id: "glossary", label: "Glossary", icon: List },
];

export default function UnderstandingPage({ projectId }: UnderstandingPageProps) {
  const [data, setData] = useState<UnderstandingWithDepth | null>(null);
  const [features, setFeatures] = useState<Feature[]>([]);
  const [featureMapLoading, setFeatureMapLoading] = useState(true);
  const [featureMapError, setFeatureMapError] = useState<string | null>(null);
  const [selectedFeatureName, setSelectedFeatureName] = useState<string | null>(null);
  const [featureTooltip, setFeatureTooltip] = useState<TooltipState>(null);
  const [glossaryTooltip, setGlossaryTooltip] = useState<GlossaryTooltipState>(null);
  const [depth, setDepth] = useState<"beginner" | "intermediate" | "advanced">("intermediate");
  const [depthLoading, setDepthLoading] = useState(false);
  const [depthAvailable, setDepthAvailable] = useState(false);
  const [depthTransition, setDepthTransition] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<string>("story");
  const [visibleSections, setVisibleSections] = useState<Set<string>>(new Set(["story"]));
  const [showBackToTop, setShowBackToTop] = useState(false);

  // Intersection observer refs
  const sectionRefs = useRef<Record<string, HTMLElement | null>>({});
  const canvasRef = useRef<HTMLDivElement | null>(null);

  async function loadUnderstandingData(targetProjectId: string) {
    const res = await fetchProjectUnderstanding(targetProjectId);
    return res as UnderstandingWithDepth;
  }

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    let cancelled = false;
    
    const load = async () => {
      try {
        const res = await loadUnderstandingData(projectId);
        if (cancelled) {
          return;
        }
        setData(res);
        setError(null);
        if (res.status === "complete" || res.status === "failed") {
          clearInterval(interval);
        }
      } catch (err: any) {
        if (cancelled) {
          return;
        }
        if (err?.message?.includes("404")) {
          return;
        }
        setError(err?.message || "Failed to load understanding");
      }
    };

    load();
    interval = setInterval(load, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;

    async function loadFeatureMap() {
      setFeatureMapLoading(true);
      setFeatureMapError(null);
      setSelectedFeatureName(null);

      try {
        const response = await fetch(`${API_BASE}/projects/${projectId}/feature-map`);
        const body = await response.json().catch(() => null);
        if (!response.ok) {
          throw new Error(body?.detail || "Failed to load feature map");
        }
        if (!cancelled) {
          setFeatures(Array.isArray(body?.features) ? body.features : []);
        }
      } catch (fetchError) {
        if (!cancelled) {
          setFeatures([]);
          setFeatureMapError(fetchError instanceof Error ? fetchError.message : "Failed to load feature map");
        }
      } finally {
        if (!cancelled) {
          setFeatureMapLoading(false);
        }
      }
    }

    void loadFeatureMap();

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (!data || data.status !== "complete") return;

    const navObserver = new IntersectionObserver((entries) => {
      const intersecting = entries.find(e => e.isIntersecting);
      if (intersecting) {
        setActiveSection(intersecting.target.id);
      }
    }, {
      root: canvasRef.current,
      rootMargin: "-20% 0px -60% 0px"
    });

    const fadeObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          setVisibleSections(prev => new Set([...prev, entry.target.id]));
        }
      });
    }, {
      root: canvasRef.current,
      threshold: 0.1
    });

    Object.values(sectionRefs.current).forEach(ref => {
      if (ref) {
        navObserver.observe(ref);
        fadeObserver.observe(ref);
      }
    });

    return () => {
      navObserver.disconnect();
      fadeObserver.disconnect();
    };
  }, [data]);

  useEffect(() => {
    const style = document.createElement("style");
    style.textContent = `
      @keyframes flowPulse {
        0%, 100% { opacity: 0.4; }
        50% { opacity: 1; }
      }
    `;
    document.head.appendChild(style);
    return () => {
      document.head.removeChild(style);
    };
  }, []);

  useEffect(() => {
    setDepthAvailable(Boolean(data?.project_story_beginner));
  }, [data]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    if (e.currentTarget.scrollTop > 500) {
      setShowBackToTop(true);
    } else {
      setShowBackToTop(false);
    }
  };

  const scrollTo = (id: string | "top") => {
    if (id === "top") {
      canvasRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    } else {
      sectionRefs.current[id]?.scrollIntoView({ behavior: "smooth" });
    }
  };

  // Normalize payload defensively so stale/partial shapes do not crash rendering.
  const systemMap = Array.isArray(data?.system_map) ? data.system_map : [];
  const dataJourney = Array.isArray(data?.data_journey) ? data.data_journey : [];
  const keyDecisions = Array.isArray(data?.key_decisions) ? data.key_decisions : [];
  const gotchas = Array.isArray(data?.gotchas) ? data.gotchas : [];
  const glossary = Array.isArray(data?.glossary) ? data.glossary : [];
  const sortedGlossary = [...glossary].sort((a, b) => a.term.localeCompare(b.term));
  const glossaryMap = useMemo(() => {
    const map = new Map<string, GlossaryLookupItem>();
    glossary.forEach((item) => {
      map.set(item.term.toLowerCase(), {
        term: item.term,
        definition: item.plain_english,
        usedIn: Array.isArray(item.used_in) ? item.used_in : [],
      });
    });
    return map;
  }, [glossary]);
  const featureGraphNodes = useMemo<Node<FeatureNodeData>[]>(() => {
    if (!features || features.length === 0) {
      return [];
    }

    return features.map((feature) => {
      const files = getFeatureFiles(feature);
      return {
        id: feature.name,
        type: "featureNode",
        position: { x: 0, y: 0 },
        data: {
          name: feature.name,
          description: feature.description,
          importance: feature.importance,
          entry_point: feature.entry_point,
          file_count: files.length,
          files,
          dominant_type: getDominantFileType(files),
        },
      };
    });
  }, [features]);
  const layoutedFeatureNodes = useMemo(() => {
    if (featureGraphNodes.length === 0) {
      return [];
    }

    return circularLayout(featureGraphNodes);
  }, [featureGraphNodes]);
  const featureGraphEdges = useMemo<Edge[]>(() => {
    if (!features || features.length === 0) {
      return [];
    }

    const edges: Edge[] = [];

    for (let i = 0; i < features.length; i += 1) {
      for (let j = i + 1; j < features.length; j += 1) {
        const featureA = features[i];
        const featureB = features[j];
        const filesA = getFeatureFiles(featureA);
        const filesB = getFeatureFiles(featureB);
        const filesASet = new Set(filesA.map((file) => file.path));
        const filesBSet = new Set(filesB.map((file) => file.path));
        const sharedFiles = filesB.filter((file) => filesASet.has(file.path));
        const entryPointLinked =
          filesASet.has(featureB.entry_point)
          || filesBSet.has(featureA.entry_point);

        if (sharedFiles.length > 0 || entryPointLinked) {
          const label =
            sharedFiles.length > 1
              ? `${sharedFiles.length} shared`
              : sharedFiles.length === 1
                ? ""
                : "entry point";

          edges.push({
            id: `${featureA.name}-${featureB.name}`,
            source: featureA.name,
            target: featureB.name,
            type: "smoothstep",
            animated: false,
            style: { stroke: "#c4c8bc", strokeWidth: 2 },
            label,
            labelStyle: { fontSize: 10, fill: "#74796e" },
          });
        }
      }
    }

    return edges;
  }, [features]);
  const selectedFeature =
    layoutedFeatureNodes.find((node) => node.id === selectedFeatureName)?.data ?? null;
  const chatSection: AIContextSection =
    activeSection === "map" ? "system_map"
    : activeSection === "journey" ? "data_journey"
    : activeSection === "decisions" ? "key_decisions"
    : activeSection === "gotchas" ? "gotchas"
    : activeSection === "glossary" ? "glossary"
    : "project_story";
  const chatSectionData =
    chatSection === "system_map" ? systemMap
    : chatSection === "data_journey" ? dataJourney
    : chatSection === "key_decisions" ? keyDecisions
    : chatSection === "gotchas" ? gotchas
    : chatSection === "glossary" ? sortedGlossary
    : data?.project_story ?? "";
  const understandingSuggestedQuestions = useMemo(() => {
    switch (chatSection) {
      case "project_story":
        return [
          "What problem does this project solve?",
          "Who would use this?",
        ];
      case "system_map":
        return [
          "How do these components communicate?",
          "What is the most critical component?",
        ];
      case "data_journey":
        return [
          "What could go wrong in this flow?",
          "How is authentication handled?",
        ];
      case "key_decisions":
        return [
          "Were there better alternatives to these decisions?",
          "What would you change?",
        ];
      case "gotchas":
        return [
          "How serious are these issues?",
          "Which gotcha is most likely to affect me?",
        ];
      case "glossary":
        return [
          "How are these terms related?",
          "Which concept should I understand first?",
        ];
      default:
        return [
          "What problem does this project solve?",
          "Who would use this?",
        ];
    }
  }, [chatSection]);

  function askAboutUnderstandingFile(filePath: string, activeSectionOverride: AIContextSection = chatSection) {
    const fileName = filePath.split("/").pop() || filePath;
    requestAIChatPrompt({
      question: `Tell me about ${fileName}`,
      pageContext: {
        page: "understanding",
        active_section: activeSectionOverride,
        entity_type: "file",
        entity_name: fileName,
        entity_path: filePath,
      },
    });
  }
  const projectStoryDepthContent =
    depth === "beginner"
      ? data?.project_story_beginner
      : depth === "advanced"
        ? data?.project_story_advanced
        : data?.project_story_intermediate;
  const projectStoryContent =
    depthAvailable && depth !== "intermediate"
      ? projectStoryDepthContent ?? data?.project_story ?? ""
      : data?.project_story ?? "";
  const depthKeyDecisionItems =
    depth === "beginner"
      ? data?.key_decisions_beginner
      : depth === "advanced"
        ? data?.key_decisions_advanced
        : data?.key_decisions_intermediate;
  const depthGotchaItems =
    depth === "beginner"
      ? data?.gotchas_beginner
      : depth === "advanced"
        ? data?.gotchas_advanced
        : data?.gotchas_intermediate;

  function handleTermHover(termData: GlossaryLookupItem, event: ReactMouseEvent<HTMLSpanElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    setGlossaryTooltip({
      ...termData,
      x: rect.left + window.scrollX,
      y: rect.bottom + window.scrollY + 8,
    });
  }

  function handleTermLeave() {
    setGlossaryTooltip(null);
  }

  async function generateDepthTiers() {
    setDepthLoading(true);
    try {
      const response = await fetch(`${API_BASE}/projects/${projectId}/understanding/depth-tiers`, {
        method: "POST",
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || "Failed to generate depth tiers");
      }
      const updated = await loadUnderstandingData(projectId);
      setData(updated);
      setDepthAvailable(Boolean(updated?.project_story_beginner));
    } catch (generationError) {
      console.error("Failed to generate depth tiers", generationError);
    } finally {
      setDepthLoading(false);
    }
  }

  function handleDepthChange(newDepth: "beginner" | "intermediate" | "advanced") {
    if (newDepth === depth) {
      return;
    }
    setDepthTransition(true);
    window.setTimeout(() => {
      setDepth(newDepth);
      setDepthTransition(false);
    }, 150);
  }

  if (error) {
    return <div className="terra-docs-layout"><div style={{color: '#d94141', padding: 40}}>Failed to load understanding: {error}</div></div>;
  }

  if (!data || data.status === "pending" || data.status === "generating" || data.status === "partial") {
    const stageCopy =
      data?.status === "partial"
        ? ["Project summary ready", "System map ready", "Finishing remaining sections", "Refreshing the full page..."]
        : data?.status === "generating"
          ? ["Reading project structure...", "Analyzing key files...", "Mapping relationships...", "Generating documentation..."]
          : ["Queueing documentation job...", "Preparing source context...", "Analyzing key files...", "Generating documentation..."];

    return (
      <div className="terra-docs-loader">
        <div className="terra-docs-loader-content">
          <div className="terra-docs-loader-logo pulse">
            <Zap size={32} color="#fff" />
          </div>
          <h2 className="terra-docs-loader-title">Chaos Twin</h2>
          <p className="terra-docs-subtitle" style={{ marginBottom: 24 }}>
            Building understanding for this project. This page updates automatically when generation finishes.
          </p>
          <div className="terra-docs-stages">
            <div className="loader-stage active">{stageCopy[0]}</div>
            <div className="loader-stage active">{stageCopy[1]}</div>
            <div className="loader-stage active">{stageCopy[2]}</div>
            <div className="loader-stage pulse">{stageCopy[3]}</div>
          </div>
        </div>
      </div>
    );
  }

  if (data.status === "failed") {
    return (
      <div className="terra-docs-layout">
        <div style={{ color: "#d94141", padding: 40 }}>
          Understanding generation failed. Please retry from the dashboard.
        </div>
      </div>
    );
  }

  return (
    <div className="terra-docs-layout">
      {/* Left Nav */}
      <nav className="terra-docs-nav">
        <div className="terra-docs-nav-title">DOCUMENTATION</div>
        {SECTIONS.map(sec => {
          const Icon = sec.icon;
          return (
            <button 
              key={sec.id}
              className={`terra-docs-nav-item ${activeSection === sec.id ? 'active' : ''}`}
              onClick={() => scrollTo(sec.id)}
            >
              <Icon size={16} /> {sec.label}
            </button>
          );
        })}
      </nav>

      {/* Content Canvas */}
      <main className="terra-docs-canvas" ref={canvasRef} onScroll={handleScroll} style={{ paddingBottom: 100 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            padding: "12px 0",
            borderBottom: "1px solid #c4c8bc",
            marginBottom: "32px",
            position: "sticky",
            top: 0,
            zIndex: 5,
            background: "#faf6f0",
          }}
        >
          <span style={{ fontSize: "13px", color: "#74796e", fontFamily: "'Nunito Sans', sans-serif" }}>
            Depth:
          </span>
          {(["beginner", "intermediate", "advanced"] as const).map((level) => (
            <button
              key={level}
              onClick={() => handleDepthChange(level)}
              style={{
                padding: "6px 16px",
                borderRadius: "20px",
                border: depth === level ? "none" : "1px solid #c4c8bc",
                background: depth === level
                  ? level === "beginner" ? "#4a7c59"
                  : level === "intermediate" ? "#2980b9"
                  : "#705c30"
                  : "transparent",
                color: depth === level ? "white" : "#74796e",
                fontSize: "13px",
                cursor: "pointer",
                fontFamily: "'Nunito Sans', sans-serif",
                fontWeight: depth === level ? 600 : 400,
                transition: "all 0.2s ease",
              }}
            >
              {level === "beginner" ? "🟢 Beginner" : level === "intermediate" ? "🟡 Intermediate" : "🔴 Advanced"}
            </button>
          ))}
          {!depthAvailable && (
            <button
              onClick={() => {
                void generateDepthTiers();
              }}
              disabled={depthLoading}
              style={{
                marginLeft: "auto",
                padding: "6px 16px",
                borderRadius: "20px",
                border: "1px solid #4a7c59",
                background: "transparent",
                color: "#4a7c59",
                fontSize: "13px",
                cursor: depthLoading ? "not-allowed" : "pointer",
                fontFamily: "'Nunito Sans', sans-serif",
              }}
            >
              {depthLoading ? "Generating..." : "✨ Generate depth tiers"}
            </button>
          )}
        </div>
        {/* Story */}
        <section 
          id="story" 
          className={`terra-docs-section ${visibleSections.has("story") ? "fade-in" : ""}`} 
          ref={(el) => {
            sectionRefs.current.story = el;
          }}
        >
          <h1 className="terra-docs-h1">Project Story</h1>
          <div className="terra-docs-story-content" style={{ opacity: depthTransition ? 0 : 1, transition: "opacity 0.15s ease" }}>
            {projectStoryContent.split("\n\n").map((para, i) => (
              <p key={i}>{highlightGlossaryTerms(para, glossaryMap, handleTermHover, handleTermLeave)}</p>
            ))}
          </div>
        </section>

        {/* System Map */}
        <section 
          id="map" 
          className={`terra-docs-section ${visibleSections.has("map") ? "fade-in" : ""}`} 
          ref={(el) => {
            sectionRefs.current.map = el;
          }}
        >
          <h2 className="terra-docs-h2">System Map</h2>
          {featureMapLoading ? (
            <div
              style={{
                width: "100%",
                height: "500px",
                border: "1px solid #c4c8bc",
                borderRadius: "12px",
                background: "#f5f1ea",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#74796e",
                fontFamily: "'Nunito Sans', sans-serif",
                animation: "pulse 1.8s ease-in-out infinite",
              }}
            >
              Building system map...
            </div>
          ) : featureMapError ? (
            <div
              style={{
                width: "100%",
                minHeight: "180px",
                border: "1px solid #c4c8bc",
                borderRadius: "12px",
                background: "#faf6f0",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                textAlign: "center",
                padding: "32px",
                color: "#b44b3a",
                fontFamily: "'Nunito Sans', sans-serif",
              }}
            >
              Failed to build system map: {featureMapError}
            </div>
          ) : features.length === 0 ? (
            <div
              style={{
                width: "100%",
                minHeight: "180px",
                border: "1px solid #c4c8bc",
                borderRadius: "12px",
                background: "#faf6f0",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                textAlign: "center",
                padding: "32px",
                color: "#74796e",
                fontFamily: "'Nunito Sans', sans-serif",
              }}
            >
              📊 System map unavailable — rescan the project to generate the feature map first.
            </div>
          ) : (
            <div
              style={{
                width: "100%",
                height: "500px",
                border: "1px solid #c4c8bc",
                borderRadius: "12px",
                background: "#faf6f0",
                position: "relative",
                overflow: "hidden",
              }}
            >
              <ReactFlow
                nodes={layoutedFeatureNodes}
                edges={featureGraphEdges}
                nodeTypes={nodeTypes}
                fitView
                fitViewOptions={{ padding: 0.3 }}
                minZoom={0.5}
                maxZoom={2}
                panOnScroll
                zoomOnScroll
                nodesDraggable
                nodesConnectable={false}
                elementsSelectable
                onNodeClick={(_, node) => setSelectedFeatureName(node.id)}
                onNodeMouseEnter={(event, node) => {
                  setFeatureTooltip({
                    feature: node.data,
                    x: event.clientX,
                    y: event.clientY,
                  });
                }}
                onNodeMouseMove={(event, node) => {
                  setFeatureTooltip({
                    feature: node.data,
                    x: event.clientX,
                    y: event.clientY,
                  });
                }}
                onNodeMouseLeave={() => setFeatureTooltip(null)}
              >
                <Background color="#c4c8bc" gap={20} size={1} variant={BackgroundVariant.Dots} />
                <Controls style={{ background: "#f5f1ea", border: "1px solid #c4c8bc" }} />
                <MiniMap
                  nodeColor={(node) => FILE_TYPE_COLORS[String(node.data?.dominant_type || "other")] || "#74796e"}
                  style={{ background: "#f5f1ea", border: "1px solid #c4c8bc" }}
                />
              </ReactFlow>

              {featureTooltip && (
                <div
                  style={{
                    position: "fixed",
                    top: featureTooltip.y + 14,
                    left: featureTooltip.x + 14,
                    zIndex: 20,
                    width: 260,
                    background: "rgba(245, 241, 234, 0.98)",
                    border: "1px solid rgba(196,200,188,0.9)",
                    borderRadius: 12,
                    boxShadow: "0 18px 40px rgba(46,50,48,0.16)",
                    padding: "12px 14px",
                    pointerEvents: "none",
                    fontFamily: "'Nunito Sans', sans-serif",
                  }}
                >
                  <div style={{ fontWeight: 800, color: "#2e3230", marginBottom: 6 }}>
                    {featureTooltip.feature.name}
                  </div>
                  <div style={{ fontSize: 12, color: "#545e57", lineHeight: 1.5, marginBottom: 8 }}>
                    {featureTooltip.feature.description}
                  </div>
                  <div style={{ fontSize: 10, color: "#74796e", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
                    Entry point
                  </div>
                  <div
                    style={{
                      fontFamily: "monospace",
                      fontSize: 11,
                      color: "#2e3230",
                      marginBottom: 8,
                      wordBreak: "break-all",
                    }}
                  >
                    {featureTooltip.feature.entry_point || "Not available"}
                  </div>
                  <div style={{ fontSize: 11, color: "#74796e" }}>
                    Importance: {Math.round((featureTooltip.feature.importance || 0) * 100)}%
                  </div>
                </div>
              )}

              <div
                style={{
                  position: "absolute",
                  top: 0,
                  right: 0,
                  width: 300,
                  height: "100%",
                  background: "rgba(250, 246, 240, 0.98)",
                  borderLeft: "1px solid #c4c8bc",
                  boxShadow: "-14px 0 30px rgba(46,50,48,0.08)",
                  transform: selectedFeature ? "translateX(0)" : "translateX(100%)",
                  transition: "transform 260ms ease",
                  padding: "20px 18px",
                  zIndex: 15,
                  overflowY: "auto",
                }}
              >
                {selectedFeature && (
                  <>
                    <button
                      type="button"
                      onClick={() => setSelectedFeatureName(null)}
                      style={{
                        position: "absolute",
                        top: 14,
                        right: 14,
                        border: "none",
                        background: "transparent",
                        fontSize: 20,
                        lineHeight: 1,
                        cursor: "pointer",
                        color: "#74796e",
                      }}
                    >
                      ×
                    </button>
                    <div
                      style={{
                        fontFamily: "'Literata', serif",
                        fontSize: 18,
                        color: "#2e3230",
                        marginBottom: 10,
                        paddingRight: 24,
                      }}
                    >
                      {selectedFeature.name}
                    </div>
                    <p style={{ margin: "0 0 16px", color: "#545e57", fontSize: 13, lineHeight: 1.6 }}>
                      {highlightGlossaryTerms(selectedFeature.description, glossaryMap, handleTermHover, handleTermLeave)}
                    </p>
                    <div style={{ fontSize: 10, color: "#74796e", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
                      Entry Point
                    </div>
                    <div
                      style={{
                        padding: "10px 12px",
                        borderRadius: 10,
                        background: "#f5f1ea",
                        border: "1px solid rgba(196,200,188,0.65)",
                        fontFamily: "monospace",
                        fontSize: 11,
                        color: "#2e3230",
                        marginBottom: 18,
                        wordBreak: "break-all",
                      }}
                    >
                      {selectedFeature.entry_point || "Not available"}
                    </div>
                    <div style={{ fontSize: 10, color: "#74796e", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>
                      Files in this feature
                    </div>
                    <div style={{ display: "grid", gap: 10 }}>
                      {selectedFeature.files.map((file) => (
                        <div
                          key={file.path}
                          style={{
                            display: "grid",
                            gap: 4,
                            paddingBottom: 10,
                            borderBottom: "1px solid rgba(196,200,188,0.35)",
                          }}
                        >
                          <div className="ask-copilot-anchor" style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                            <span
                              style={{
                                width: 8,
                                height: 8,
                                borderRadius: "50%",
                                background: FILE_TYPE_COLORS[file.file_type] || FILE_TYPE_COLORS.other,
                                flexShrink: 0,
                              }}
                            />
                            <span
                              style={{
                                fontSize: 12,
                                color: "#2e3230",
                                fontFamily: "monospace",
                                whiteSpace: "nowrap",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                              }}
                              title={file.path}
                            >
                              {file.path}
                            </span>
                            <AskCopilotButton
                              inline
                              onAsk={() => askAboutUnderstandingFile(file.path, "system_map")}
                            />
                          </div>
                          <div
                            style={{
                              fontSize: 11,
                              color: "#74796e",
                              lineHeight: 1.45,
                              display: "-webkit-box",
                              WebkitLineClamp: 1,
                              WebkitBoxOrient: "vertical",
                              overflow: "hidden",
                            }}
                            title={file.summary}
                          >
                            {file.summary || "No summary available"}
                          </div>
                        </div>
                      ))}
                    </div>
                    <button
                      type="button"
                      onClick={() => navigateToPath(`/projects/${projectId}/feature-map`)}
                      style={{
                        marginTop: 18,
                        border: "none",
                        background: "transparent",
                        color: "#4a7c59",
                        fontSize: 13,
                        fontWeight: 700,
                        cursor: "pointer",
                        padding: 0,
                      }}
                    >
                      → Go to Feature Map
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
          <div
            style={{
              marginTop: 22,
              paddingTop: 18,
              borderTop: "1px solid rgba(196,200,188,0.5)",
            }}
          >
            <div
              style={{
                marginBottom: 14,
                fontSize: 11,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "#74796e",
                fontWeight: 700,
              }}
            >
              Component Details
            </div>
            <div className="terra-system-grid">
              {systemMap.map((comp) => {
                const connectsTo = Array.isArray(comp.connects_to) ? comp.connects_to : [];
                const keyFiles = Array.isArray(comp.key_files) ? comp.key_files : [];
                return (
                <div key={comp.id} className={`terra-map-card border-${comp.color || 'green'}`}>
                  <div className="terra-map-card-head">
                    <strong>{comp.name}</strong>
                    <span className="terra-map-card-type">{comp.type}</span>
                  </div>
                  <div className="terra-map-card-body">
                    {highlightGlossaryTerms(comp.description, glossaryMap, handleTermHover, handleTermLeave)}
                    <div className="terra-map-card-connects">
                      Connects to: {connectsTo.length ? connectsTo.join(", ") : "Nothing"}
                    </div>
                  </div>
                  <div className="terra-map-card-hover">
                    <div>Key Files: {keyFiles.length ? keyFiles.join(", ") : "None"}</div>
                  </div>
                </div>
                );
              })}
            </div>
          </div>
          <p className="terra-system-map-desc">How these pieces connect</p>
        </section>

        {/* Data Journey */}
        <section 
          id="journey" 
          className={`terra-docs-section ${visibleSections.has("journey") ? "fade-in" : ""}`}
          ref={(el) => {
            sectionRefs.current.journey = el;
          }}
        >
          <h2 className="terra-docs-h2">Data Journey</h2>
          <p className="terra-docs-subtitle">How a request flows through this system</p>
          {dataJourney.length === 0 ? (
            <div style={{ color: "#74796e", fontStyle: "italic", padding: "20px" }}>
              Data journey not available for this project.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column" }}>
              {dataJourney.map((step, index) => (
                <div key={step.step ?? index}>
                  <div style={{ display: "flex", gap: "16px", alignItems: "flex-start" }}>
                    <div
                      style={{
                        width: "32px",
                        height: "32px",
                        borderRadius: "50%",
                        background: typeColor(step.type),
                        color: "white",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 700,
                        fontSize: "13px",
                        flexShrink: 0,
                        marginTop: "4px",
                      }}
                    >
                      {step.step}
                    </div>

                    <div
                      style={{
                        flex: 1,
                        background: "#f5f1ea",
                        border: "1px solid #c4c8bc",
                        borderLeft: `4px solid ${typeColor(step.type)}`,
                        borderRadius: "10px",
                        padding: "14px 18px",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          gap: 12,
                          marginBottom: "6px",
                          flexWrap: "wrap",
                        }}
                      >
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 8,
                            fontWeight: 700,
                            fontSize: "14px",
                            color: "#2e3230",
                          }}
                        >
                          <span
                            style={{
                              color: typeColor(step.type),
                              fontSize: "15px",
                              lineHeight: 1,
                            }}
                          >
                            {typeIcon(step.type)}
                          </span>
                          {step.actor}
                        </span>
                        <span
                          style={{
                            fontSize: "10px",
                            fontWeight: 700,
                            color: typeColor(step.type),
                            background: `${typeColor(step.type)}18`,
                            border: `1px solid ${typeColor(step.type)}40`,
                            borderRadius: "20px",
                            padding: "2px 10px",
                            letterSpacing: "0.06em",
                          }}
                        >
                          {(step.type || "unknown").toUpperCase()}
                        </span>
                      </div>
                      <div
                        style={{
                          fontFamily: "monospace",
                          fontSize: "12px",
                          color: "#4a7c59",
                          marginBottom: "6px",
                          background: "#faf6f0",
                          padding: "4px 8px",
                          borderRadius: "4px",
                          display: "inline-block",
                        }}
                      >
                        {step.action}
                      </div>
                      <div style={{ fontSize: "13px", color: "#74796e", lineHeight: 1.5 }}>
                        {highlightGlossaryTerms(step.detail, glossaryMap, handleTermHover, handleTermLeave)}
                      </div>
                    </div>
                  </div>

                  {index < dataJourney.length - 1 && (
                    <div
                      style={{
                        width: "2px",
                        height: "28px",
                        background: `linear-gradient(to bottom, ${typeColor(step.type)}, ${typeColor(dataJourney[index + 1]?.type)})`,
                        marginLeft: "15px",
                        opacity: 0.6,
                        animation: "flowPulse 2s ease-in-out infinite",
                        animationDelay: `${index * 0.3}s`,
                      }}
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Key Decisions */}
        <section 
          id="decisions" 
          className={`terra-docs-section ${visibleSections.has("decisions") ? "fade-in" : ""}`}
          ref={(el) => {
            sectionRefs.current.decisions = el;
          }}
        >
          <h2 className="terra-docs-h2">Key Decisions</h2>
          <p className="terra-docs-subtitle">Why this codebase is built the way it is</p>
          <div className="terra-decisions-grid" style={{ opacity: depthTransition ? 0 : 1, transition: "opacity 0.15s ease" }}>
            {keyDecisions.map((dec, i) => (
              <div key={i} className="terra-decision-card">
                <div className="terra-decision-head">
                  <Lightbulb size={20} color="#4a7c59" />
                  <strong>{dec.title}</strong>
                </div>
                {depthAvailable && depth !== "intermediate" ? (
                  <div className="terra-decision-why">
                    {highlightGlossaryTerms(
                      depthKeyDecisionItems?.[i]?.[depth] || dec.why || dec.decision || "",
                      glossaryMap,
                      handleTermHover,
                      handleTermLeave,
                    )}
                  </div>
                ) : (
                  <>
                    <div className="terra-decision-chosen">
                      {highlightGlossaryTerms(dec.decision, glossaryMap, handleTermHover, handleTermLeave)}
                    </div>
                    <div className="terra-decision-why">
                      {highlightGlossaryTerms(dec.why, glossaryMap, handleTermHover, handleTermLeave)}
                    </div>
                  </>
                )}
                <div className="terra-decision-tradeoff">
                  Tradeoff: {highlightGlossaryTerms(dec.tradeoff, glossaryMap, handleTermHover, handleTermLeave)}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Gotchas */}
        <section 
          id="gotchas" 
          className={`terra-docs-section ${visibleSections.has("gotchas") ? "fade-in" : ""}`}
          ref={(el) => {
            sectionRefs.current.gotchas = el;
          }}
        >
          <h2 className="terra-docs-h2">Watch Out For</h2>
          <div className="terra-gotchas-stack" style={{ opacity: depthTransition ? 0 : 1, transition: "opacity 0.15s ease" }}>
            {gotchas.map((g, i) => {
              const affected = Array.isArray(g.affected) ? g.affected : [];
              return (
              <div key={i} className={`terra-gotcha-card severity-${g.severity || "low"}`}>
                <div className="terra-gotcha-head">
                  <AlertTriangle size={18} />
                  <strong>{g.title}</strong>
                </div>
                <div className="terra-gotcha-desc">
                  {highlightGlossaryTerms(
                    (depthAvailable && depth !== "intermediate"
                      ? depthGotchaItems?.[i]?.[depth]
                      : null) || g.description,
                    glossaryMap,
                    handleTermHover,
                    handleTermLeave,
                  )}
                </div>
                <div className="terra-gotcha-affected">
                  {affected.map((aff) => (
                    <span key={aff} className="terra-gotcha-pill">{aff}</span>
                  ))}
                </div>
              </div>
              );
            })}
          </div>
        </section>

        {/* Glossary */}
        <section 
          id="glossary" 
          className={`terra-docs-section ${visibleSections.has("glossary") ? "fade-in" : ""}`}
          ref={(el) => {
            sectionRefs.current.glossary = el;
          }}
        >
          <h2 className="terra-docs-h2">Glossary</h2>
          <p className="terra-docs-subtitle">Terms specific to this codebase</p>
          <div className="terra-glossary-list">
            {sortedGlossary.map((term, i) => (
              <div
                key={i}
                className="terra-glossary-item"
                style={{ borderLeft: "3px solid #4a7c59", paddingLeft: 14 }}
              >
                <div className="terra-glossary-term" style={{ color: "#4a7c59", fontWeight: 700 }}>
                  {term.term}
                </div>
                <div className="terra-glossary-detail">
                  <p className="terra-glossary-plain">
                    {highlightGlossaryTerms(term.plain_english, glossaryMap, handleTermHover, handleTermLeave)}
                  </p>
                  {(Array.isArray(term.used_in) ? term.used_in : []).length > 0 && (
                    <div className="terra-glossary-used" style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                      {(Array.isArray(term.used_in) ? term.used_in : []).map((u) => (
                        <span
                          key={u}
                          className="ask-copilot-anchor"
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                            background: "#f5f1ea",
                            border: "1px solid #c4c8bc",
                            borderRadius: 4,
                            padding: "2px 8px",
                            fontSize: 11,
                            fontFamily: "monospace",
                            color: "#5f655b",
                          }}
                        >
                          {u.split("/").pop()}
                          <AskCopilotButton
                            inline
                            onAsk={() => askAboutUnderstandingFile(u, "glossary")}
                          />
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
        
        {/* Bottom padding */}
        <div style={{height: 400}}></div>
      </main>

      {/* Back to Top */}
      {showBackToTop && (
        <button className="terra-back-to-top" onClick={() => scrollTo("top")}>
          <ArrowUp size={20} />
        </button>
      )}

      {glossaryTooltip && (
        <div
          style={{
            position: "fixed",
            left: Math.min(glossaryTooltip.x, window.innerWidth - 320),
            top: glossaryTooltip.y,
            zIndex: 9999,
            background: "#2e3230",
            color: "#faf6f0",
            borderRadius: "10px",
            padding: "12px 16px",
            maxWidth: "300px",
            boxShadow: "0 8px 24px rgba(46,50,48,0.3)",
            fontFamily: "'Nunito Sans', sans-serif",
            fontSize: "13px",
            pointerEvents: "none",
          }}
        >
          <div style={{ fontWeight: 700, fontSize: "14px", marginBottom: "6px", color: "#4a7c59" }}>
            {glossaryTooltip.term}
          </div>
          <div style={{ lineHeight: 1.5, color: "#e8e4dc" }}>
            {glossaryTooltip.definition}
          </div>
          {glossaryTooltip.usedIn?.length > 0 && (
            <div style={{ marginTop: "8px", borderTop: "1px solid rgba(255,255,255,0.1)", paddingTop: "8px" }}>
              <div style={{ fontSize: "10px", color: "#74796e", marginBottom: "4px", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Used in
              </div>
              {glossaryTooltip.usedIn.slice(0, 3).map((file, i) => (
                <div key={i} style={{ fontFamily: "monospace", fontSize: "11px", color: "#c4c8bc" }}>
                  {file.split("/").pop()}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <AIChatBubble
        projectId={projectId}
        context={{
          page: "understanding",
          section: chatSection,
          data: chatSectionData,
          pageContext: { page: "understanding", active_section: chatSection },
          resetKey: chatSection,
        }}
        suggestedQuestions={understandingSuggestedQuestions}
      />
    </div>
  );
}
