import { useEffect, useMemo, useState } from "react";
import { fetchProjectDashboard, fetchProjectIndexingStatus, fetchProjectUnderstanding } from "../api/client";
import type { IndexingStatusResponse, ProjectDashboardResponse } from "../types";
import type { NavItem } from "../app/navigation";
import { Loader2, Code, Search, Link, Zap, LogIn, Plug, Shield, BookOpen, ArrowRight } from "lucide-react";
import AIChatBubble from "../components/AIChatBubble";
import "./ProjectDashboard.css";

interface ProjectDashboardProps {
  projectId: string;
  onNavigate: (view: NavItem) => void;
}

function getLanguageColorClass(lang: string) {
  const lower = lang.toLowerCase();
  if (lower.includes('ts') || lower.includes('typescript')) return 'terra-badge-ts';
  if (lower.includes('js') || lower.includes('javascript')) return 'terra-badge-js';
  if (lower.includes('py') || lower.includes('python')) return 'terra-badge-py';
  if (lower.includes('sql')) return 'terra-badge-sql';
  return 'terra-badge-default';
}

function getMethodClass(method: string) {
  return `terra-method-${method.toUpperCase()}`;
}

export default function ProjectDashboard({ projectId, onNavigate }: ProjectDashboardProps) {
  const [data, setData] = useState<ProjectDashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [indexingStatus, setIndexingStatus] = useState<IndexingStatusResponse | null>(null);
  const [understandingStatus, setUnderstandingStatus] = useState<string>("pending");

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    
    const checkStatus = async () => {
      try {
        const uRes = await fetchProjectUnderstanding(projectId);
        setUnderstandingStatus(uRes.status);
        if (uRes.status === "complete" || uRes.status === "failed") {
          clearInterval(interval);
        }
      } catch (err) {
        // May 404 while generating, keep checking
      }
    };

    checkStatus();
    interval = setInterval(checkStatus, 3000);

    return () => clearInterval(interval);
  }, [projectId]);

  const dashboardSuggestedQuestions = useMemo(
    () => [
      "Where should I start reading this codebase?",
      "What is the riskiest part of this project?",
      "What external services does this project depend on?",
      "What are the main entry points?",
    ],
    [],
  );

  const dashboardPageContext = useMemo(() => {
    if (!data) {
      return { page: "dashboard" };
    }

    return {
      page: "dashboard",
      project_name: data.project_name,
      tech_stack: (data.languages || []).map((language) => language.name),
      entry_points: (data.routes_preview || []).slice(0, 8).map((route) => `${route.method} ${route.path}`),
    };
  }, [data]);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    let cancelled = false;

    const checkIndexingStatus = async () => {
      try {
        const status = await fetchProjectIndexingStatus(projectId);
        if (!cancelled) {
          setIndexingStatus(status);
          if (status.status === "complete" || status.status === "failed") {
            clearInterval(interval);
          }
        }
      } catch {
        if (!cancelled) {
          setIndexingStatus(null);
        }
      }
    };

    void checkIndexingStatus();
    interval = setInterval(checkIndexingStatus, 3000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [projectId]);

  useEffect(() => {
    setData(null);
    setError(null);
    setIndexingStatus(null);
    fetchProjectDashboard(projectId)
      .then(res => {
        setData(res);
      })
      .catch(err => setError(err.message));
  }, [projectId]);

  if (error) {
    return <div className="terra-dashboard"><div style={{color: '#d94141'}}>Failed to load dashboard: {error}</div></div>;
  }

  if (!data) {
    return (
      <div className="terra-dashboard" style={{display:'flex', justifyContent:'center', marginTop:'100px'}}>
        <style dangerouslySetInnerHTML={{__html: `\n          @keyframes terra-spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }\n          .terra-spinner { animation: terra-spin 1s linear infinite; }\n        `}} />
        <Loader2 size={32} className="terra-spinner" style={{ color: '#4a7c59' }} />
      </div>
    );
  }

  const indexingFailed = indexingStatus?.status === "failed";
  const indexingInProgress = indexingStatus?.status === "indexing";
  const indexingErrorMessage = indexingStatus?.error_message?.trim() || "Indexing failed.";

  return (
    <div className="terra-dashboard">
      <h1 className="terra-dashboard-header">Welcome to {data.project_name}</h1>

      <section className="terra-card-section">
        <h2 className="terra-card-title"><Search color="#4a7c59" /> What is this project?</h2>
        <div className="terra-card-body">{data.executive_summary}</div>
        <div style={{ height: "1px", background: "rgba(46,50,48,0.1)", margin: "20px 0" }}></div>
        {indexingFailed ? (
          <div
            className="terra-docs-status"
            style={{
              color: "#d94141",
              display: "grid",
              gap: "8px",
              alignItems: "start",
            }}
          >
            <div style={{ fontWeight: 700 }}>File indexing could not start.</div>
            <div>{indexingErrorMessage}</div>
          </div>
        ) : indexingInProgress ? (
          <div className="terra-docs-status pulse" style={{ display: "grid", gap: "6px" }}>
            <div><BookOpen size={16} /> Indexing source files for search and documentation...</div>
            <div style={{ fontSize: "0.92rem", color: "#545e57" }}>
              {indexingStatus?.indexed_files ?? 0} of {indexingStatus?.total_files ?? 0} files processed
              {typeof indexingStatus?.percentage === "number" ? ` (${indexingStatus.percentage}%)` : ""}
            </div>
          </div>
        ) : understandingStatus === "complete" ? (
          <button 
            className="terra-docs-btn"
            onClick={() => onNavigate("understanding")}
          >
            <BookOpen size={18} /> Explore Full Documentation <ArrowRight size={18} />
          </button>
        ) : understandingStatus === "failed" ? (
          <div className="terra-docs-status" style={{color: '#d94141'}}>Documentation generation failed</div>
        ) : (
          <div className="terra-docs-status pulse">
            <BookOpen size={16} /> Preparing full documentation...
          </div>
        )}
      </section>

      <section className="terra-card-section">
        <h2 className="terra-card-title"><Code color="#4a7c59" /> Tech Stack & Languages</h2>
        <div className="terra-pill-container">
          {data.languages.map(l => (
            <div key={l.name} className="terra-pill">
              <span className={getLanguageColorClass(l.name)}>
                {l.name.substring(0,2).toUpperCase()}
              </span>
              {l.name}
              <div className="terra-pill-tooltip">Don't know what this is? Ask the AI Architect</div>
            </div>
          ))}
          {data.dependencies.map(d => (
            <div key={d} className="terra-pill">
              <span className="terra-badge-default">📦</span>
              {d}
              <div className="terra-pill-tooltip">Don't know what this is? Ask the AI Architect</div>
            </div>
          ))}
        </div>
      </section>

      {data.insights && (
        <section className="terra-insights-grid">
          {/* Complexity */}
          <div className="terra-insight-card" title="More detail coming soon">
            <div className="terra-insight-header">
              <Zap size={18} color="#4a7c59" /> 
              <span className="terra-insight-title">Complexity</span>
            </div>
            <div className={`terra-insight-value complexity-${data.insights.complexity.toLowerCase()}`}>
              {data.insights.complexity}
            </div>
            <div className="terra-insight-sub">{data.insights.complexity_reason}</div>
          </div>

          {/* Entry Points */}
          <div className="terra-insight-card" title="More detail coming soon">
            <div className="terra-insight-header">
              <LogIn size={18} color="#4a7c59" /> 
              <span className="terra-insight-title">Entry Points</span>
            </div>
            <div className="terra-insight-value">{data.insights.entry_points}</div>
            <div className="terra-insight-sub">{data.insights.entry_points_detail}</div>
          </div>

          {/* Connects To */}
          <div className="terra-insight-card" title="More detail coming soon">
            <div className="terra-insight-header">
              <Plug size={18} color="#4a7c59" /> 
              <span className="terra-insight-title">Connects To</span>
            </div>
            <div className="terra-insight-services">
              {data.insights.external_services.length > 0 ? (
                data.insights.external_services.map((svc: string) => (
                  <span key={svc} className="terra-svc-pill">{svc}</span>
                ))
              ) : (
                <span className="terra-svc-pill">None detected</span>
              )}
            </div>
            <div className="terra-insight-sub">{data.insights.external_services_detail}</div>
          </div>

          {/* Authentication */}
          <div className="terra-insight-card" title="More detail coming soon">
            <div className="terra-insight-header">
              <Shield size={18} color="#4a7c59" /> 
              <span className="terra-insight-title">Auth</span>
            </div>
            <div className={`terra-insight-value auth-${data.insights.auth_summary.toLowerCase().includes('no') ? 'none' : 'protected'}`}>
              {data.insights.auth_summary.toLowerCase().includes('no') ? 'No Auth' : 'Protected'}
            </div>
            <div className="terra-insight-sub">{data.insights.auth_summary}</div>
          </div>
        </section>
      )}

      <section className="terra-card-section">
        <h2 className="terra-card-title"><Link color="#4a7c59" /> API Inventory</h2>
        <div className="terra-api-grid">
          {data.routes_preview.map((r, i) => (
            <div key={i} className="terra-api-card">
              <div>
                <span className={`terra-method-badge ${getMethodClass(r.method)}`}>{r.method}</span>
                <span className="terra-api-path">{r.path}</span>
              </div>
              <div className="terra-api-summary">{r.summary}</div>
              
              <div className="terra-api-overlay">
                <div style={{fontSize: '0.85rem', fontWeight: 600, color: '#2c332e', marginBottom: '8px'}}>{r.summary}</div>
              </div>
            </div>
          ))}
        </div>
        {data.total_routes > 0 && (
          <div style={{textAlign: 'center', marginTop: '16px'}}>
            <button className="terra-btn" style={{background: 'transparent', color: '#4a7c59', fontWeight: 700, border: 'none', cursor: 'pointer', fontSize: '1rem'}} onClick={() => onNavigate("api-explorer")}>
              View all routes &rarr;
            </button>
          </div>
        )}
      </section>

      <AIChatBubble
        projectId={projectId}
        context={{
          page: "dashboard",
          data,
          projectName: data.project_name,
          pageContext: dashboardPageContext,
          resetKey: data.project_name,
        }}
        suggestedQuestions={dashboardSuggestedQuestions}
      />

    </div>
  );
}
