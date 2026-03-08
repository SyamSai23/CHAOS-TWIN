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

function App() {
  const [apiStatus, setApiStatus] = useState<string>("loading...");
  const [dbStatus, setDbStatus] = useState<string>("loading...");

  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [error, setError] = useState<string | null>(null);

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
          <ul>
            {projects.map((p) => (
              <li key={p.id} style={{ marginBottom: "8px" }}>
                <strong>{p.name}</strong> — <code>{p.path}</code>
                <br />
                <small style={{ color: "#666" }}>
                  Created: {new Date(p.created_at).toLocaleString()}
                </small>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default App;