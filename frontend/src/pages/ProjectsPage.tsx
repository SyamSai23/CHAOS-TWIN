import { useEffect, useState } from "react";
import { FolderOpen, Loader2 } from "lucide-react";

import { API_BASE } from "../api/client";

type ProjectListItem = {
  id: string;
  name: string;
  path?: string;
  created_at: string;
  file_count: number | null;
  status: string | null;
};

type ProjectsPageProps = {};

function navigateTo(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function statusStyle(status: string | null | undefined) {
  switch (status) {
    case "completed":
      return { background: "#dcfce7", color: "#15803d" };
    case "running":
      return { background: "#fef9c3", color: "#854d0e" };
    case "failed":
      return { background: "#fee2e2", color: "#b91c1c" };
    default:
      return { background: "#eef1ec", color: "#6f766d" };
  }
}

export default function ProjectsPage(_props: ProjectsPageProps) {
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteErrors, setDeleteErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;

    async function loadProjects() {
      try {
        const response = await fetch(`${API_BASE}/projects`);
        const body = await response.json().catch(() => null);
        if (!response.ok) {
          throw new Error(body?.detail || "Failed to load projects");
        }
        if (!cancelled) {
          setProjects(Array.isArray(body) ? body : []);
        }
      } catch (fetchError) {
        if (!cancelled) {
          setError(fetchError instanceof Error ? fetchError.message : "Failed to load projects");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadProjects();

    return () => {
      cancelled = true;
    };
  }, []);

  async function confirmDelete(projectId: string) {
    const projectIndex = projects.findIndex((project) => project.id === projectId);
    const projectToDelete = projectIndex >= 0 ? projects[projectIndex] : null;
    if (!projectToDelete) {
      return;
    }

    setDeletingId(projectId);
    setDeleteErrors((current) => {
      const next = { ...current };
      delete next[projectId];
      return next;
    });
    setConfirmingId((current) => (current === projectId ? null : current));
    setProjects((current) => current.filter((project) => project.id !== projectId));

    try {
      const response = await fetch(`${API_BASE}/projects/${projectId}`, {
        method: "DELETE",
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.detail || "Failed to delete project");
      }
    } catch (deleteError) {
      setProjects((current) => {
        if (current.some((project) => project.id === projectId)) {
          return current;
        }
        const next = [...current];
        next.splice(Math.min(projectIndex, next.length), 0, projectToDelete);
        return next;
      });
      setDeleteErrors((current) => ({
        ...current,
        [projectId]: deleteError instanceof Error ? deleteError.message : "Failed to delete project",
      }));
    } finally {
      setDeletingId((current) => (current === projectId ? null : current));
    }
  }

  if (loading) {
    return (
      <div style={{ minHeight: "calc(100vh - 120px)", display: "grid", placeItems: "center", background: "#faf6f0", borderRadius: 18, color: "#2e3230", fontFamily: "'Nunito Sans', sans-serif" }}>
        <div style={{ display: "grid", placeItems: "center", gap: 12 }}>
          <Loader2 size={28} style={{ color: "#4a7c59", animation: "terra-spin 1s linear infinite" }} />
          <div style={{ fontSize: 15, color: "#74796e" }}>Loading projects...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ minHeight: "calc(100vh - 120px)", background: "#faf6f0", borderRadius: 18, padding: 24, color: "#c0392b", fontFamily: "'Nunito Sans', sans-serif" }}>
        {error}
      </div>
    );
  }

  return (
    <div style={{ minHeight: "calc(100vh - 120px)", background: "#faf6f0", borderRadius: 18, padding: 24, color: "#2e3230", fontFamily: "'Nunito Sans', sans-serif" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap", marginBottom: 28 }}>
        <div>
          <h1 style={{ margin: 0, fontFamily: "'Literata', serif", fontSize: 28, color: "#2e3230" }}>Your Projects</h1>
          <p style={{ margin: "8px 0 0", fontSize: 15, color: "#74796e" }}>
            Manage your uploaded codebases.
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigateTo("/")}
          style={{
            background: "#4a7c59",
            color: "#fff",
            border: "none",
            borderRadius: 10,
            padding: "10px 16px",
            fontSize: 14,
            fontWeight: 700,
            cursor: "pointer",
            fontFamily: "'Nunito Sans', sans-serif",
          }}
        >
          Upload New Project
        </button>
      </div>

      {projects.length === 0 ? (
        <div style={{ minHeight: 360, display: "grid", placeItems: "center", textAlign: "center", gap: 12 }}>
          <FolderOpen size={34} style={{ color: "#74796e" }} />
          <div style={{ fontFamily: "'Literata', serif", fontSize: 24, color: "#2e3230" }}>No projects yet</div>
          <div style={{ color: "#74796e", fontSize: 14 }}>Upload a codebase to get started.</div>
          <button
            type="button"
            onClick={() => navigateTo("/")}
            style={{
              marginTop: 6,
              background: "#4a7c59",
              color: "#fff",
              border: "none",
              borderRadius: 10,
              padding: "10px 16px",
              fontSize: 14,
              fontWeight: 700,
              cursor: "pointer",
              fontFamily: "'Nunito Sans', sans-serif",
            }}
          >
            Upload a project
          </button>
        </div>
      ) : (
        <div>
          {projects.map((project) => {
            const confirming = confirmingId === project.id;
            const deleting = deletingId === project.id;
            const errorMessage = deleteErrors[project.id];
            const fileCountLabel = project.file_count == null ? "—" : `${project.file_count} files`;
            const statusLabel = project.status ?? "unknown";
            return (
              <div
                key={project.id}
                style={{
                  background: "#f5f1ea",
                  border: "1px solid #c4c8bc",
                  borderRadius: 12,
                  padding: "20px 24px",
                  marginBottom: 12,
                  opacity: deleting ? 0.72 : 1,
                  transform: deleting ? "translateY(-2px)" : "translateY(0)",
                  transition: "opacity 0.22s ease, transform 0.22s ease",
                  gridTemplateColumns: "minmax(0, 1.8fr) auto auto",
                  gap: 16,
                  alignItems: "center",
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: 16, color: "#2e3230" }}>{project.name}</div>
                  <div style={{ marginTop: 6, color: "#74796e", fontSize: 12 }}>
                    {formatDate(project.created_at)}
                  </div>
                  {errorMessage && (
                    <div style={{ marginTop: 10, color: "#b91c1c", fontSize: 12 }}>
                      {errorMessage}
                    </div>
                  )}
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ background: "#fffdf9", border: "1px solid #c4c8bc", borderRadius: 999, padding: "4px 10px", fontSize: 12, color: "#5f655b" }}>
                    {fileCountLabel}
                  </span>
                  <span
                    style={{
                      borderRadius: 999,
                      padding: "4px 10px",
                      fontSize: 12,
                      textTransform: "capitalize",
                      ...statusStyle(project.status),
                    }}
                  >
                    {statusLabel}
                  </span>
                </div>

                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                  {confirming ? (
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
                      <span style={{ fontSize: 13, color: "#74796e" }}>Are you sure?</span>
                      <button
                        type="button"
                        onClick={() => {
                          void confirmDelete(project.id);
                        }}
                        disabled={deleting}
                        style={{
                          background: "#b91c1c",
                          color: "#fff",
                          border: "none",
                          borderRadius: 8,
                          padding: "6px 14px",
                          fontSize: 13,
                          fontWeight: 700,
                          cursor: deleting ? "wait" : "pointer",
                          fontFamily: "'Nunito Sans', sans-serif",
                        }}
                      >
                        {deleting ? "Deleting..." : "Yes, delete"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmingId(null)}
                        style={{
                          background: "transparent",
                          color: "#74796e",
                          border: "1px solid #c4c8bc",
                          borderRadius: 8,
                          padding: "6px 14px",
                          fontSize: 13,
                          cursor: "pointer",
                          fontFamily: "'Nunito Sans', sans-serif",
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <div style={{ display: "flex", gap: 10 }}>
                      <button
                        type="button"
                        onClick={() => navigateTo(`/projects/${project.id}/dashboard`)}
                        style={{
                          background: "#4a7c59",
                          color: "#fff",
                          border: "none",
                          borderRadius: 8,
                          padding: "6px 14px",
                          fontSize: 13,
                          fontWeight: 700,
                          cursor: "pointer",
                          fontFamily: "'Nunito Sans', sans-serif",
                        }}
                      >
                        Open →
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmingId(project.id)}
                        style={{
                          background: "transparent",
                          color: "#b91c1c",
                          border: "1px solid #b91c1c",
                          borderRadius: 8,
                          padding: "6px 14px",
                          fontSize: 13,
                          cursor: "pointer",
                          fontFamily: "'Nunito Sans', sans-serif",
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
