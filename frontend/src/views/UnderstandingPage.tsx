import { useEffect, useState, useRef } from "react";
import { Zap, BookOpen, Map as MapIcon, ArrowRight, Lightbulb, AlertTriangle, List, ArrowUp } from "lucide-react";
import { fetchProjectUnderstanding } from "../api/client";
import type { ProjectUnderstandingResponse } from "../types";
import AIChatBubble, { type AIContextSection } from "../components/AIChatBubble";
import "./UnderstandingPage.css";

interface UnderstandingPageProps {
  projectId: string;
}

const SECTIONS = [
  { id: "story", label: "Project Story", icon: BookOpen },
  { id: "map", label: "System Map", icon: MapIcon },
  { id: "journey", label: "Data Journey", icon: ArrowRight },
  { id: "decisions", label: "Key Decisions", icon: Lightbulb },
  { id: "gotchas", label: "Gotchas", icon: AlertTriangle },
  { id: "glossary", label: "Glossary", icon: List },
];

export default function UnderstandingPage({ projectId }: UnderstandingPageProps) {
  const [data, setData] = useState<ProjectUnderstandingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<string>("story");
  const [visibleSections, setVisibleSections] = useState<Set<string>>(new Set(["story"]));
  const [showBackToTop, setShowBackToTop] = useState(false);

  // Intersection observer refs
  const sectionRefs = useRef<Record<string, HTMLElement | null>>({});
  const canvasRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    let cancelled = false;
    
    const load = async () => {
      try {
        const res = await fetchProjectUnderstanding(projectId);
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

  // Normalize payload defensively so stale/partial shapes do not crash rendering.
  const systemMap = Array.isArray(data.system_map) ? data.system_map : [];
  const dataJourney = Array.isArray(data.data_journey) ? data.data_journey : [];
  const keyDecisions = Array.isArray(data.key_decisions) ? data.key_decisions : [];
  const gotchas = Array.isArray(data.gotchas) ? data.gotchas : [];
  const glossary = Array.isArray(data.glossary) ? data.glossary : [];
  const sortedGlossary = [...glossary].sort((a, b) => a.term.localeCompare(b.term));
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
    : data.project_story ?? "";

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
        {/* Story */}
        <section 
          id="story" 
          className={`terra-docs-section ${visibleSections.has("story") ? "fade-in" : ""}`} 
          ref={(el) => {
            sectionRefs.current.story = el;
          }}
        >
          <h1 className="terra-docs-h1">Project Story</h1>
          <div className="terra-docs-story-content">
            {data.project_story?.split('\n\n').map((para, i) => (
              <p key={i}>{para}</p>
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
                  {comp.description}
                  <div className="terra-map-card-connects">
                    Connects to: {connectsTo.length ? connectsTo.join(', ') : 'Nothing'}
                  </div>
                </div>
                <div className="terra-map-card-hover">
                  <div>Key Files: {keyFiles.length ? keyFiles.join(', ') : "None"}</div>
                </div>
              </div>
              );
            })}
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
          <div className="terra-journey-flow">
            {dataJourney.map((step, idx) => (
              <div key={idx} className="terra-journey-step-container">
                <div className={`terra-journey-card type-${step.type || 'processing'}`}>
                  <div className="terra-journey-step-num">{step.step}</div>
                  <div className="terra-journey-actor">{step.actor}</div>
                  <div className="terra-journey-action">{step.action}</div>
                  <div className="terra-journey-detail">{step.detail}</div>
                </div>
                {idx < dataJourney.length - 1 && (
                  <div className="terra-journey-arrow">
                    <ArrowRight size={24} color="#705c30" />
                  </div>
                )}
              </div>
            ))}
          </div>
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
          <div className="terra-decisions-grid">
            {keyDecisions.map((dec, i) => (
              <div key={i} className="terra-decision-card">
                <div className="terra-decision-head">
                  <Lightbulb size={20} color="#4a7c59" />
                  <strong>{dec.title}</strong>
                </div>
                <div className="terra-decision-chosen">{dec.decision}</div>
                <div className="terra-decision-why">{dec.why}</div>
                <div className="terra-decision-tradeoff">Tradeoff: {dec.tradeoff}</div>
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
          <div className="terra-gotchas-stack">
            {gotchas.map((g, i) => {
              const affected = Array.isArray(g.affected) ? g.affected : [];
              return (
              <div key={i} className={`terra-gotcha-card severity-${g.severity || "low"}`}>
                <div className="terra-gotcha-head">
                  <AlertTriangle size={18} />
                  <strong>{g.title}</strong>
                </div>
                <div className="terra-gotcha-desc">{g.description}</div>
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
              <div key={i} className="terra-glossary-item">
                <div className="terra-glossary-term">{term.term}</div>
                <div className="terra-glossary-detail">
                  <p className="terra-glossary-plain">{term.plain_english}</p>
                  <div className="terra-glossary-used">
                    {(Array.isArray(term.used_in) ? term.used_in : []).map((u) => (
                      <span key={u} className="terra-gotcha-pill">Used in: {u}</span>
                    ))}
                  </div>
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

      <AIChatBubble
        projectId={projectId}
        context={{
          page: "understanding",
          section: chatSection,
          data: chatSectionData,
        }}
      />
    </div>
  );
}
