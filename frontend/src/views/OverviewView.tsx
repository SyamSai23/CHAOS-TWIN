import type { Project, ScanResult } from "../types";
import { shortenLabel } from "../types";

interface OverviewViewProps {
  project: Project;
  scan: ScanResult | null;
}

const LANG_EXT_MAP: Record<string, string[]> = {
  Python: [".py"],
  TypeScript: [".ts", ".tsx"],
  JavaScript: [".js", ".jsx"],
  Java: [".java"],
  "C#": [".cs"],
  Go: [".go"],
  Rust: [".rs"],
  Ruby: [".rb"],
  PHP: [".php"],
  HTML: [".html", ".htm"],
  CSS: [".css", ".scss", ".sass"],
};

export default function OverviewView({ project, scan }: OverviewViewProps) {
  if (!scan) {
    return (
      <div className="view-empty">
        <p className="view-empty-title">No scan data yet</p>
        <p className="view-empty-sub">
          Upload a ZIP and run a scan from the sidebar to see the overview.
        </p>
      </div>
    );
  }

  const langCounts = scan.languages.map((lang) => {
    const exts = LANG_EXT_MAP[lang] || [];
    const count = exts.reduce(
      (sum, ext) => sum + (scan.extension_counts[ext] || 0),
      0,
    );
    return { lang, count: count || 1 };
  });
  const maxLangCount = Math.max(...langCounts.map((l) => l.count), 1);

  return (
    <div>
      <h1 className="view-title">{project.name}</h1>

      <div className="overview-grid">
        {/* Scan Status */}
        <div className="card">
          <div className="card-label">Scan Status</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
            <span
              className={`badge ${scan.status === "completed" ? "badge-success" : "badge-pending"}`}
            >
              {scan.status}
            </span>
          </div>
          <div className="card-meta-text">
            {new Date(scan.created_at).toLocaleString()}
          </div>
          <div className="card-meta-text">
            {scan.file_count} files &middot; {scan.project_type}
          </div>
        </div>

        {/* Languages */}
        <div className="card">
          <div className="card-label">Languages</div>
          <div style={{ marginTop: 8 }}>
            {langCounts.length > 0 ? (
              langCounts.map(({ lang, count }) => (
                <div key={lang} className="lang-bar-row">
                  <span className="lang-bar-label">{lang}</span>
                  <div className="lang-bar-track">
                    <div
                      className="lang-bar-fill"
                      style={{
                        width: `${Math.max((count / maxLangCount) * 100, 8)}%`,
                      }}
                    />
                  </div>
                  <span className="lang-bar-count">{count}</span>
                </div>
              ))
            ) : (
              <span className="text-muted">None detected</span>
            )}
          </div>
        </div>

        {/* Components */}
        <div className="card">
          <div className="card-label">Components</div>
          <div className="card-big-number">{scan.components.length}</div>
          <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
            {scan.components.map((c) => (
              <div key={c.root_path} className="mini-row">
                <span className="text-primary">{c.name}</span>
                <span className="text-muted" style={{ fontSize: 12 }}>
                  {c.type}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Tech Stack */}
        <div className="card">
          <div className="card-label">Tech Stack</div>
          <div className="chip-list" style={{ marginTop: 8 }}>
            {scan.frameworks.length > 0 ? (
              scan.frameworks.map((f) => (
                <span key={f} className="chip">
                  {f}
                </span>
              ))
            ) : (
              <span className="text-muted">None detected</span>
            )}
          </div>
        </div>
      </div>

      {/* Key Files + Entry Points */}
      <div className="overview-two-col">
        <div className="card">
          <div className="card-label">Key Files</div>
          <div className="mono-list">
            {scan.key_files.length > 0 ? (
              scan.key_files.slice(0, 8).map((f) => (
                <div key={f} className="mono-list-item">
                  <code>{shortenLabel(f)}</code>
                </div>
              ))
            ) : (
              <span className="text-muted">None found</span>
            )}
            {scan.key_files.length > 8 && (
              <span className="text-muted">
                +{scan.key_files.length - 8} more
              </span>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-label">Entry Points</div>
          <div className="mono-list">
            {scan.entry_points.length > 0 ? (
              scan.entry_points.slice(0, 8).map((e) => (
                <div key={e} className="mono-list-item">
                  <code>{shortenLabel(e)}</code>
                </div>
              ))
            ) : (
              <span className="text-muted">None found</span>
            )}
            {scan.entry_points.length > 8 && (
              <span className="text-muted">
                +{scan.entry_points.length - 8} more
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
