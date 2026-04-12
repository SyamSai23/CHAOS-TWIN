import { useEffect, useState } from "react";
import { FolderUp, GitBranch, Share2, Sparkles, Wand2, Box, PenTool, Loader2 } from "lucide-react";
import type { Project } from "../types";
import "./TerraLandingView.css";

interface TerraLandingViewProps {
  showCreateForm: boolean;
  name: string;
  setName: (v: string) => void;
  path: string;
  setPath: (v: string) => void;
  handleSubmit: (e: React.FormEvent) => void;
  handleCancelCreate: () => void;
  createError: string | null;
  isUploading: boolean;
  projects: Project[];
  uploadError: string | null;
  entryIntent: "zip" | "github" | null;
  onSelectProject: (projectId: string) => void;
  onUploadZip: () => void;
}

export default function TerraLandingView({
  showCreateForm,
  name,
  setName,
  path,
  setPath,
  handleSubmit,
  handleCancelCreate,
  createError,
  isUploading,
  projects,
  uploadError,
  entryIntent,
  onSelectProject,
  onUploadZip,
}: TerraLandingViewProps) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 20);
    };
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <div className="terra-theme">
      <nav className={`terra-nav ${scrolled ? "scrolled" : ""}`}>
        <div className="terra-container" style={{ display: 'flex', width: '100%', justifyContent: 'space-between', alignItems: 'center' }}>
          <a href="/" className="terra-logo">
            <span className="terra-logo-text">Chaos Twin</span>
          </a>
          <div className="terra-nav-links">
            <a href="#" className="terra-nav-link">Features</a>
            <a href="#" className="terra-nav-link">Documentation</a>
            <a href="#" className="terra-nav-link">Pricing</a>
          </div>
          <div>
            <button className="terra-btn terra-btn-primary">
              Connect with GitHub
            </button>
          </div>
        </div>
      </nav>

      <main className="terra-container">
        <section className="terra-hero">
          <div className="terra-badge">
            <Sparkles size={14} /> AI-POWERED HIGH FIDELITY
          </div>
          <h1>
            Understand your system in <br /><span className="highlight">high fidelity.</span>
          </h1>
          <p className="terra-hero-subtitle">
            Chaos Twin maps complex codebases into living architecture graphs. Trace data flow, identify bottlenecks, and generate deep insights without leaving your environment.
          </p>
          <div className="terra-hero-actions">
            <button className="terra-btn terra-btn-primary">
              <GitBranch size={18} /> Connect with GitHub
            </button>
            <div style={{ position: 'relative' }}>
              <style dangerouslySetInnerHTML={{__html: `\n                @keyframes terra-spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }\n                .terra-spinner { animation: terra-spin 1s linear infinite; }\n              `}} />
              <button 
                className="terra-btn terra-btn-secondary" 
                onClick={onUploadZip}
                disabled={isUploading}
              >
                {isUploading ? (
                  <><Loader2 size={18} className="terra-spinner" /> Analyzing...</>
                ) : (
                  <><FolderUp size={18} /> Upload Codebase</>
                )}
              </button>
              {uploadError && (
                <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, marginTop: '8px', color: '#d94141', fontSize: '0.85rem', fontWeight: 600, textAlign: 'center' }}>
                  {uploadError}
                </div>
              )}
            </div>
          </div>
        </section>

        <section id="features" className="terra-sandbox-section">
          <div className="terra-sandbox-content">
            <h2>The Bridge from Syntax to Structure</h2>
            <p>
              Raw source code is a labyrinth. Chaos Twin acts as your semantic layer, ingesting complex repositories and distilling them into a navigable, visual reality.
            </p>
            <div className="terra-feature-item">
              <div className="terra-feature-icon">
                <Box size={20} />
              </div>
              <div>
                <h3>Semantic Ingestion</h3>
                <p>Deep parsing of relationships, dependencies, and implicit patterns across multiple repositories.</p>
              </div>
            </div>
            <div className="terra-feature-item">
              <div className="terra-feature-icon">
                <Share2 size={20} />
              </div>
              <div>
                <h3>High Fidelity Graphing</h3>
                <p>Real-time generation of interactive architecture diagrams that evolve as your code does.</p>
              </div>
            </div>
          </div>
          <div className="terra-visual-card">
            <div style={{ padding: '24px', background: '#ffffff', borderRadius: '12px', border: '1px solid rgba(46,50,48,0.1)' }}>
              <pre style={{ margin: 0, fontSize: '0.85rem', color: '#545e57', fontFamily: 'monospace' }}>
{`export function 
processUser(data) {
  return pipeline.execute(data);
}`}
              </pre>
            </div>
            <div style={{ position: 'absolute', top: '50px', right: '40px' }}>
              <div style={{ width: '48px', height: '48px', borderRadius: '50%', background: '#4a7c59', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', boxShadow: '0 4px 12px rgba(74, 124, 89, 0.3)' }}>
                <Share2 size={20} />
              </div>
            </div>
            <div style={{ height: '120px', marginTop: '24px', borderRadius: '12px', background: '#dce5df', display: 'flex', alignItems: 'flex-end', padding: '16px', gap: '8px' }}>
              <div style={{ width: '20%', height: '40%', background: 'rgba(74, 124, 89, 0.6)', borderRadius: '4px' }}></div>
              <div style={{ width: '20%', height: '70%', background: 'rgba(74, 124, 89, 0.8)', borderRadius: '4px' }}></div>
              <div style={{ width: '20%', height: '90%', background: '#4a7c59', borderRadius: '4px' }}></div>
              <div style={{ width: '20%', height: '60%', background: 'rgba(74, 124, 89, 0.5)', borderRadius: '4px' }}></div>
            </div>
          </div>
        </section>

        {projects.length > 0 && (
          <section style={{ marginTop: "10px", marginBottom: "56px" }}>
            <div style={{ marginBottom: "18px" }}>
              <div className="terra-badge" style={{ marginBottom: "10px" }}>
                <Sparkles size={14} /> RECENT PROJECTS
              </div>
              <h2 style={{ margin: 0, fontFamily: "'Literata', serif", color: "#2e3230" }}>Switch back anytime</h2>
            </div>
            <div style={{ display: "grid", gap: "12px" }}>
              {projects.slice(0, 6).map((project) => (
                <button
                  key={project.id}
                  onClick={() => onSelectProject(project.id)}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    width: "100%",
                    padding: "16px 18px",
                    borderRadius: "18px",
                    border: "1px solid rgba(46,50,48,0.08)",
                    background: "#fff",
                    color: "#2e3230",
                    fontFamily: "inherit",
                    cursor: "pointer",
                    boxShadow: "0 6px 18px rgba(46,50,48,0.06)",
                  }}
                >
                  <span style={{ fontWeight: 700 }}>{project.name}</span>
                  <span style={{ fontSize: "0.85rem", color: "#6b736c" }}>
                    Open
                  </span>
                </button>
              ))}
            </div>
          </section>
        )}
      </main>

      <section className="terra-brain-section">
        <div className="terra-container">
          <div className="terra-section-header">
            <h2>The Developer's Second Brain</h2>
            <p>Chaos Twin automates the cognitive overhead of understanding complex systems.</p>
          </div>
          <div className="terra-grid">
            
            <div className="terra-card">
              <div className="terra-card-header">
                <div className="terra-card-badge"><Share2 size={14} /></div>
                <h3>Visual Sequence Mapping</h3>
              </div>
              <p>See exactly how requests flow through your stack. Trace an API call from the entry point down to the database query and back.</p>
              <div className="terra-card-visual" style={{ background: '#1c2220' }}>
                <div style={{ width: '80%', height: '40px', background: 'rgba(255,255,255,0.1)', borderRadius: '6px', margin: 'auto' }}></div>
              </div>
            </div>

            <div className="terra-card highlight">
              <div className="terra-card-header">
                <div className="terra-card-badge" style={{ background: 'rgba(112, 92, 48, 0.1)', color: '#705c30' }}><Wand2 size={14} /></div>
                <h3>AI Code Insights</h3>
              </div>
              <p>Automatic documentation that stays in sync. Detect technical debt and architectural drift as they happen.</p>
              <div className="terra-card-visual" style={{ background: 'rgba(255,255,255,0.5)', border: 'none' }}>
                <pre style={{ fontSize: '0.75rem', color: '#705c30' }}>
{`// AI: Circular Dependency
detected in UserAuth.ts and
RoleMiddleware.ts`}
                </pre>
              </div>
            </div>

            <div className="terra-card">
              <div className="terra-card-header">
                <div className="terra-card-badge"><PenTool size={14} /></div>
                <h3>Instant Architecture Diagrams</h3>
              </div>
              <p>No more outdated Miro diagrams. Generate Mermaid or SVG exports of your system architecture on every pull request.</p>
              <div className="terra-card-visual">
                <div style={{ padding: '8px 24px', background: '#dce5df', borderRadius: '16px', color: '#4a7c59' }}>
                   <PenTool size={24} />
                </div>
              </div>
            </div>

            <div className="terra-card">
              <div className="terra-card-header">
                <h3>High-Fidelity Dependency Analysis</h3>
              </div>
              <p>Identify the "Blast Radius" of potential changes. Know exactly what will break before you merge, not after the deployment.</p>
              <ul className="terra-check-list">
                <li><Sparkles size={16}/> Impact Prediction</li>
                <li><Sparkles size={16}/> Side-effect Isolation</li>
                <li><Sparkles size={16}/> Legacy Code Refactor Path</li>
              </ul>
            </div>

          </div>
        </div>
      </section>

      <section className="terra-container">
        <div className="terra-cta-section">
          <h2>Ready to see the forest, not just the trees?</h2>
          <p>Connect your repository today and experience the clarity of a high-fidelity codebase analysis.</p>
          
          <button className="terra-btn terra-cta-btn">
            <GitBranch size={18} /> Connect with GitHub
          </button>

          <div className="terra-trust">
            Trusted by engineering teams at scale. Free to start.
          </div>
          
          {/* Subtle tree decoration in background */}
          <svg style={{ position: 'absolute', right: '-5%', bottom: '-10%', opacity: 0.1, pointerEvents: 'none' }} width="400" height="400" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
            <path d="M12 2L1 21H10V24H14V21H23L12 2Z"/>
          </svg>
        </div>
        
        <footer className="terra-footer">
          <div>
            <span style={{ fontWeight: 700, color: '#2c332e' }}>Chaos Twin</span> <br/>
            &copy; {new Date().getFullYear()} Chaos Twin. Rooted in stability.
          </div>
          <div className="terra-footer-links">
            <a href="#">Privacy Policy</a>
            <a href="#">Terms of Service</a>
            <a href="#">Security</a>
            <a href="#">Changelog</a>
          </div>
        </footer>
      </section>

      {showCreateForm && (
        <div style={{ position: 'fixed', top: 0, left: 0, width: '100%', height: '100%', background: 'rgba(250, 246, 240, 0.9)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#ffffff', padding: '40px', borderRadius: '24px', boxShadow: '0 8px 30px rgba(46,50,48,0.1)', width: '100%', maxWidth: '420px', border: '1px solid rgba(46,50,48,0.08)' }}>
            <h3 style={{ margin: '0 0 16px', fontSize: '1.4rem' }}>
              {entryIntent === 'github' ? 'Prepare GitHub Shell' : 'Create Project Area'}
            </h3>
            <p style={{ margin: '0 0 24px', fontSize: '0.9rem', color: '#545e57' }}>
              {entryIntent === 'github' ? 'Create a project name to receive the staged GitHub sync.' : 'First, create a shell. Then you will upload the ZIP archive from the workspace.'}
            </p>
            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '6px' }}>Project Name</label>
                <input required type="text" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Acme API" autoFocus
                  style={{ width: '100%', padding: '12px 14px', borderRadius: '12px', border: '1px solid rgba(46,50,48,0.15)', background: '#f5f1e8', fontFamily: 'inherit', fontSize: '1rem', outline: 'none' }} />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '6px' }}>Workspace Path</label>
                <input required type="text" value={path} onChange={e => setPath(e.target.value)} placeholder="e.g. /projects/acme-api"
                  style={{ width: '100%', padding: '12px 14px', borderRadius: '12px', border: '1px solid rgba(46,50,48,0.15)', background: '#f5f1e8', fontFamily: 'inherit', fontSize: '1rem', outline: 'none' }} />
              </div>
              {createError && <p style={{ margin: 0, color: '#d94141', fontSize: '0.85rem', fontWeight: 600 }}>{createError}</p>}
              <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
                <button type="submit" className="terra-btn terra-btn-primary" style={{ flex: 1 }}>Create Project</button>
                <button type="button" onClick={handleCancelCreate} className="terra-btn terra-btn-secondary" style={{ padding: '12px' }}>Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
