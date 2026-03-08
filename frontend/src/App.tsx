import { useEffect, useState, type FormEvent } from "react";

const API = "http://127.0.0.1:8000";

type ApiStatus = {
  status: string;
};

type DbStatus = {
  status: string;
  database: string;
};

type Project = {
  id: string;
  name: string;
  path: string;
  created_at: string;
};

type ScanResult = {
  id: string;
  status: string;
  file_count: number;
  languages: string[];
  frameworks: string[];
  key_files: string[];
  top_level_dirs: string[];
  extension_counts: Record<string, number>;
  project_type: string;
  entry_points: string[];
  created_at: string;
};

type UploadResponse = {
  id: string;
  project_id: string;
  filename: string;
  storage_path: string;
  created_at: string;
};

function App() {
  const [apiStatus, setApiStatus] = useState<string>("loading...");
  const [dbStatus, setDbStatus] = useState<string>("loading...");

  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [scans, setScans] = useState<Record<string, ScanResult | null>>({});
  const [scanning, setScanning] = useState<Record<string, boolean>>({});
  const [scanErrors, setScanErrors] = useState<Record<string, string | null>>({});
  const [selectedFiles, setSelectedFiles] = useState<Record<string, File | null>>({});
  const [uploading, setUploading] = useState<Record<string, boolean>>({});
  const [uploadMessages, setUploadMessages] = useState<Record<string, string | null>>({});
  const [uploadedFilenames, setUploadedFilenames] = useState<Record<string, string | null>>({});

  useEffect(() => {
    const fetchStatuses = async () => {
      try {
        const apiResponse = await fetch(`${API}/health`);
        const apiData: ApiStatus = await apiResponse.json();
        setApiStatus(apiData.status);
      } catch {
        setApiStatus("error");
      }

      try {
        const dbResponse = await fetch(`${API}/health/db`);
        const dbData: DbStatus = await dbResponse.json();
        setDbStatus(dbData.database);
      } catch {
        setDbStatus("error");
      }
    };

    fetchStatuses();
    fetchProjects();
  }, []);

  async function fetchProjects() {
    try {
      const res = await fetch(`${API}/projects`);
      const data: Project[] = await res.json();
      setProjects(data);
    } catch {
      console.error("Failed to fetch projects");
    }
  }

  async function handleScan(projectId: string) {
    setScanning((prev) => ({ ...prev, [projectId]: true }));
    setScanErrors((prev) => ({ ...prev, [projectId]: null }));

    try {
      const res = await fetch(`${API}/projects/${projectId}/scan`, {
        method: "POST",
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setScanErrors((prev) => ({
          ...prev,
          [projectId]: body?.detail || "Scan failed",
        }));
        return;
      }

      const data: ScanResult = await res.json();
      setScans((prev) => ({ ...prev, [projectId]: data }));
    } catch {
      setScanErrors((prev) => ({ ...prev, [projectId]: "Scan failed" }));
    } finally {
      setScanning((prev) => ({ ...prev, [projectId]: false }));
    }
  }

  function handleFileChange(projectId: string, file: File | null) {
    setSelectedFiles((prev) => ({ ...prev, [projectId]: file }));
    setUploadMessages((prev) => ({ ...prev, [projectId]: null }));
  }

  async function handleUpload(projectId: string) {
    const file = selectedFiles[projectId];

    if (!file) {
      setUploadMessages((prev) => ({
        ...prev,
        [projectId]: "Please select a .zip file first",
      }));
      return;
    }

    setUploading((prev) => ({ ...prev, [projectId]: true }));
    setUploadMessages((prev) => ({ ...prev, [projectId]: null }));

    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`${API}/projects/${projectId}/upload`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setUploadMessages((prev) => ({
          ...prev,
          [projectId]: body?.detail || "Upload failed",
        }));
        return;
      }

      const data: UploadResponse = await res.json();
      setUploadMessages((prev) => ({ ...prev, [projectId]: "Upload successful" }));
      setUploadedFilenames((prev) => ({ ...prev, [projectId]: data.filename }));
      setSelectedFiles((prev) => ({ ...prev, [projectId]: null }));
    } catch {
      setUploadMessages((prev) => ({ ...prev, [projectId]: "Upload failed" }));
    } finally {
      setUploading((prev) => ({ ...prev, [projectId]: false }));
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    try {
      const res = await fetch(`${API}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, path }),
      });

      if (!res.ok) {
        setError("Failed to create project");
        return;
      }

      setName("");
      setPath("");
      fetchProjects();
    } catch {
      setError("Failed to create project");
    }
  }

  return (
    <div style={{ padding: "24px", fontFamily: "Arial, sans-serif" }}>
      <h1>Chaos Twin</h1>
      <p>Codebase intelligence and failure simulation platform.</p>

      <div style={{ marginTop: "24px" }}>
        <h2>System Status</h2>
        <ul>
          <li>Frontend: running</li>
          <li>Backend API: {apiStatus}</li>
          <li>Database: {dbStatus}</li>
        </ul>
      </div>

      <div style={{ marginTop: "32px" }}>
        <h2>Create Project</h2>
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "8px", maxWidth: "400px" }}>
          <input
            type="text"
            placeholder="Project name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            style={{ padding: "8px", fontSize: "14px" }}
          />
          <input
            type="text"
            placeholder="Project path (e.g. /home/user/my-app)"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            required
            style={{ padding: "8px", fontSize: "14px" }}
          />
          <button type="submit" style={{ padding: "8px 16px", fontSize: "14px", cursor: "pointer" }}>
            Add Project
          </button>
          {error && <p style={{ color: "red" }}>{error}</p>}
        </form>
      </div>

      <div style={{ marginTop: "32px" }}>
        <h2>Projects ({projects.length})</h2>
        {projects.length === 0 ? (
          <p>No projects yet. Create one above.</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {projects.map((p) => (
              <li
                key={p.id}
                style={{
                  marginBottom: "16px",
                  padding: "14px",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  background: "#0f172a",
                  color: "#e5e7eb",
                }}
              >
                <div style={{ marginBottom: "8px" }}>
                  <strong style={{ fontSize: "16px" }}>{p.name}</strong>
                </div>
                <div style={{ marginBottom: "4px" }}>
                  <span style={{ color: "#cbd5e1" }}>Path:</span> <code>{p.path}</code>
                </div>
                <small style={{ color: "#94a3b8" }}>
                  Created: {new Date(p.created_at).toLocaleString()}
                </small>

                <div
                  style={{
                    marginTop: "12px",
                    paddingTop: "10px",
                    borderTop: "1px solid #334155",
                  }}
                >
                  <div style={{ marginBottom: "8px" }}>
                    <input
                      type="file"
                      accept=".zip"
                      onChange={(e) => handleFileChange(p.id, e.target.files?.[0] || null)}
                      style={{ fontSize: "13px" }}
                    />
                    <button
                      onClick={() => handleUpload(p.id)}
                      disabled={uploading[p.id]}
                      style={{
                        marginLeft: "8px",
                        padding: "5px 12px",
                        fontSize: "13px",
                        cursor: "pointer",
                      }}
                    >
                      {uploading[p.id] ? "Uploading..." : "Upload ZIP"}
                    </button>
                  </div>

                  {uploadMessages[p.id] && (
                    <p
                      style={{
                        margin: "6px 0",
                        color: uploadMessages[p.id] === "Upload successful" ? "#86efac" : "#fca5a5",
                        fontWeight: 600,
                      }}
                    >
                      {uploadMessages[p.id]}
                    </p>
                  )}

                  {uploadedFilenames[p.id] && (
                    <p style={{ margin: "6px 0", fontSize: "13px", color: "#d1d5db" }}>
                      <strong>Latest upload:</strong> <code>{uploadedFilenames[p.id]}</code>
                    </p>
                  )}
                </div>

                <div
                  style={{
                    marginTop: "12px",
                    paddingTop: "10px",
                    borderTop: "1px solid #334155",
                  }}
                >
                  <button
                    onClick={() => handleScan(p.id)}
                    disabled={scanning[p.id]}
                    style={{ padding: "5px 12px", fontSize: "13px", cursor: "pointer" }}
                  >
                    {scanning[p.id] ? "Scanning..." : "Scan Latest Upload"}
                  </button>

                  {scanErrors[p.id] && (
                    <p style={{ color: "#fca5a5", margin: "8px 0 0" }}>{scanErrors[p.id]}</p>
                  )}

                  {scans[p.id] && (() => {
                    const scan = scans[p.id]!;
                    const extensionEntries = Object.entries(scan.extension_counts || {});
                    const visibleExtensions = extensionEntries.slice(0, 6);
                    const remainingExtensions = extensionEntries.length - visibleExtensions.length;
                    const visibleKeyFiles = scan.key_files.slice(0, 6);
                    const remainingKeyFiles = scan.key_files.length - visibleKeyFiles.length;
                    const visibleDirs = scan.top_level_dirs.slice(0, 8);
                    const remainingDirs = scan.top_level_dirs.length - visibleDirs.length;
                    const visibleEntryPoints = scan.entry_points.slice(0, 6);
                    const remainingEntryPoints = scan.entry_points.length - visibleEntryPoints.length;
                    return (
                      <div
                        style={{
                          marginTop: "10px",
                          padding: "10px",
                          background: "#111827",
                          border: "1px solid #374151",
                          borderRadius: "6px",
                          fontSize: "14px",
                          color: "#e5e7eb",
                          lineHeight: 1.6,
                        }}
                      >
                        <div style={{ marginBottom: "8px", fontWeight: 700, color: "#cbd5e1" }}>
                          Summary
                        </div>
                        <div><strong>Scan status:</strong> {scan.status}</div>
                        <div><strong>Project type:</strong> {scan.project_type}</div>
                        <div><strong>File count:</strong> {scan.file_count}</div>

                        <div style={{ marginTop: "10px", marginBottom: "4px", fontWeight: 700, color: "#cbd5e1" }}>
                          Languages / Extensions
                        </div>
                        <div>
                          <strong>Languages:</strong> {scan.languages.length > 0 ? scan.languages.join(", ") : "none detected"}
                        </div>
                        <div>
                          <strong>Extensions:</strong>{" "}
                          {visibleExtensions.length > 0
                            ? visibleExtensions.map(([ext, count]) => `${ext}: ${count}`).join(", ")
                            : "none detected"}
                          {remainingExtensions > 0 ? ` (+${remainingExtensions} more)` : ""}
                        </div>

                        <div style={{ marginTop: "10px", marginBottom: "4px", fontWeight: 700, color: "#cbd5e1" }}>
                          Frameworks & Tools
                        </div>
                        <div>
                          {scan.frameworks.length > 0 ? scan.frameworks.join(", ") : "none detected"}
                        </div>

                        <div style={{ marginTop: "10px", marginBottom: "4px", fontWeight: 700, color: "#cbd5e1" }}>
                          Key Files
                        </div>
                        {visibleKeyFiles.length > 0 ? (
                          <ul style={{ margin: "4px 0", paddingLeft: "18px" }}>
                            {visibleKeyFiles.map((file) => (
                              <li key={file}><code>{file}</code></li>
                            ))}
                          </ul>
                        ) : (
                          <div>none detected</div>
                        )}
                        {remainingKeyFiles > 0 && <div>+{remainingKeyFiles} more</div>}

                        <div style={{ marginTop: "10px", marginBottom: "4px", fontWeight: 700, color: "#cbd5e1" }}>
                          Top-Level Folders
                        </div>
                        <div>
                          {visibleDirs.length > 0 ? visibleDirs.join(", ") : "none detected"}
                          {remainingDirs > 0 ? ` (+${remainingDirs} more)` : ""}
                        </div>

                        <div style={{ marginTop: "10px", marginBottom: "4px", fontWeight: 700, color: "#cbd5e1" }}>
                          Entry Points
                        </div>
                        {visibleEntryPoints.length > 0 ? (
                          <ul style={{ margin: "4px 0", paddingLeft: "18px" }}>
                            {visibleEntryPoints.map((entry) => (
                              <li key={entry}><code>{entry}</code></li>
                            ))}
                          </ul>
                        ) : (
                          <div>none detected</div>
                        )}
                        {remainingEntryPoints > 0 && <div>+{remainingEntryPoints} more</div>}
                      </div>
                    );
                  })()}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default App;