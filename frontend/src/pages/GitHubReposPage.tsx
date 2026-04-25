import { useEffect, useMemo, useState } from "react";
import { Github, Loader2, RefreshCw, Star } from "lucide-react";

import { API_BASE } from "../api/client";

type GitHubRepo = {
  id: number;
  name: string;
  full_name: string;
  description: string | null;
  language: string | null;
  updated_at: string;
  default_branch: string;
  private: boolean;
  stargazers_count: number;
};

type GitHubBranch = {
  name: string;
};

type ImportedProject = {
  id: string;
  name: string;
  path: string;
  created_at: string;
};

function navigateTo(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function formatUpdatedAt(value: string) {
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

export default function GitHubReposPage() {
  const [githubToken, setGithubToken] = useState<string | null>(null);
  const [repos, setRepos] = useState<GitHubRepo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [languageFilter, setLanguageFilter] = useState<string>("All");
  const [openRepoId, setOpenRepoId] = useState<number | null>(null);
  const [branchesByRepo, setBranchesByRepo] = useState<Record<number, GitHubBranch[]>>({});
  const [branchLoadingByRepo, setBranchLoadingByRepo] = useState<Record<number, boolean>>({});
  const [selectedBranchByRepo, setSelectedBranchByRepo] = useState<Record<number, string>>({});
  const [importingRepoId, setImportingRepoId] = useState<number | null>(null);
  const [importErrors, setImportErrors] = useState<Record<number, string>>({});

  const pageShellStyle = {
    height: "100vh",
    overflowY: "auto" as const,
    overflowX: "hidden" as const,
    background: "#faf6f0",
    color: "#2e3230",
    fontFamily: "'Nunito Sans', sans-serif",
  };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (token) {
      setGithubToken(token);
      window.history.replaceState({}, "", "/github/repos");
      return;
    }
    setLoading(false);
    setError("GitHub session expired — reconnect");
  }, []);

  useEffect(() => {
    if (!githubToken) {
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    fetch(`${API_BASE}/github/repos`, {
      headers: {
        Authorization: `Bearer ${githubToken}`,
      },
    })
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok) {
          throw new Error(body?.detail || "Failed to load repositories");
        }
        return Array.isArray(body) ? body as GitHubRepo[] : [];
      })
      .then((body) => {
        if (cancelled) {
          return;
        }
        setRepos(body);
      })
      .catch((fetchError) => {
        if (cancelled) {
          return;
        }
        const message = fetchError instanceof Error ? fetchError.message : "Failed to load repositories";
        setError(message);
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [githubToken]);

  const languages = useMemo(() => {
    const values = new Set<string>();
    repos.forEach((repo) => {
      if (repo.language) {
        values.add(repo.language);
      }
    });
    return ["All", ...Array.from(values).sort((a, b) => a.localeCompare(b))];
  }, [repos]);

  const filteredRepos = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return repos.filter((repo) => {
      const haystack = `${repo.full_name} ${repo.name} ${repo.description || ""}`.toLowerCase();
      const matchesQuery = !normalizedQuery || haystack.includes(normalizedQuery);
      const matchesLanguage = languageFilter === "All" || repo.language === languageFilter;
      return matchesQuery && matchesLanguage;
    });
  }, [languageFilter, query, repos]);

  function reconnectGitHub() {
    window.location.href = `${API_BASE}/auth/github`;
  }

  async function openImportPanel(repo: GitHubRepo) {
    setOpenRepoId((current) => (current === repo.id ? null : repo.id));
    setImportErrors((current) => {
      const next = { ...current };
      delete next[repo.id];
      return next;
    });

    if (!githubToken || branchesByRepo[repo.id] || branchLoadingByRepo[repo.id]) {
      return;
    }

    setBranchLoadingByRepo((current) => ({ ...current, [repo.id]: true }));
    try {
      const [owner, repoName] = repo.full_name.split("/");
      const response = await fetch(`${API_BASE}/github/repos/${owner}/${repoName}/branches`, {
        headers: {
          Authorization: `Bearer ${githubToken}`,
        },
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.detail || "Failed to load branches");
      }
      const branches = Array.isArray(body) ? body as GitHubBranch[] : [];
      setBranchesByRepo((current) => ({ ...current, [repo.id]: branches }));
      setSelectedBranchByRepo((current) => ({
        ...current,
        [repo.id]: current[repo.id] || repo.default_branch || branches[0]?.name || "",
      }));
    } catch (branchError) {
      setImportErrors((current) => ({
        ...current,
        [repo.id]: branchError instanceof Error ? branchError.message : "Failed to load branches",
      }));
    } finally {
      setBranchLoadingByRepo((current) => ({ ...current, [repo.id]: false }));
    }
  }

  async function importRepo(repo: GitHubRepo) {
    if (!githubToken) {
      setError("GitHub session expired — reconnect");
      return;
    }

    const [owner, repoName] = repo.full_name.split("/");
    const branch = selectedBranchByRepo[repo.id] || repo.default_branch;
    setImportErrors((current) => {
      const next = { ...current };
      delete next[repo.id];
      return next;
    });
    setImportingRepoId(repo.id);

    try {
      const response = await fetch(`${API_BASE}/github/import`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          owner,
          repo: repoName,
          branch,
          github_token: githubToken,
          project_name: repo.name,
        }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.detail || "Repository import failed");
      }
      if (body?.project?.id) {
        window.dispatchEvent(new CustomEvent<ImportedProject>("chaos-twin:project-created", {
          detail: body.project as ImportedProject,
        }));
      }
      navigateTo(`/projects/${body.project_id}/dashboard`);
    } catch (importError) {
      setImportErrors((current) => ({
        ...current,
        [repo.id]: importError instanceof Error ? importError.message : "Repository import failed",
      }));
    } finally {
      setImportingRepoId(null);
    }
  }

  if (loading) {
    return (
      <div style={{ ...pageShellStyle, display: "grid", placeItems: "center" }}>
        <div style={{ display: "grid", placeItems: "center", gap: 12 }}>
          <Loader2 size={30} style={{ color: "#4a7c59", animation: "terra-spin 1s linear infinite" }} />
          <div style={{ color: "#74796e", fontSize: 15 }}>Loading your GitHub repositories...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ ...pageShellStyle, padding: 32 }}>
        <div style={{ maxWidth: 640, margin: "80px auto 0", background: "#fffdf9", border: "1px solid #ddd8ce", borderRadius: 18, padding: 28 }}>
          <div style={{ fontFamily: "'Literata', serif", fontSize: 28, color: "#2e3230", marginBottom: 12 }}>
            GitHub Repositories
          </div>
          <div style={{ color: "#c0392b", fontSize: 15, marginBottom: 18 }}>{error}</div>
          <button
            type="button"
            onClick={reconnectGitHub}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
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
            <RefreshCw size={16} />
            Reconnect GitHub
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={pageShellStyle}>
      <div style={{ maxWidth: 1120, margin: "0 auto", padding: "40px 24px 56px" }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap", marginBottom: 28 }}>
          <div>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "#4a7c59", fontSize: 12, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10 }}>
              <Github size={16} />
              GitHub Import
            </div>
            <h1 style={{ margin: 0, fontFamily: "'Literata', serif", fontSize: 34, color: "#2e3230" }}>Choose a repository</h1>
            <p style={{ margin: "10px 0 0", color: "#74796e", fontSize: 15, lineHeight: 1.6, maxWidth: 720 }}>
              Import a GitHub repository directly into Chaos Twin. We will download the ZIP, run the normal scan pipeline, and send you straight to the project dashboard.
            </p>
          </div>
          <button
            type="button"
            onClick={() => navigateTo("/")}
            style={{
              background: "transparent",
              color: "#4a7c59",
              border: "1px solid #4a7c59",
              borderRadius: 10,
              padding: "10px 16px",
              fontSize: 14,
              fontWeight: 700,
              cursor: "pointer",
              fontFamily: "'Nunito Sans', sans-serif",
            }}
          >
            Back to home
          </button>
        </div>

        <div style={{ display: "grid", gap: 14, marginBottom: 22 }}>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search repositories..."
            style={{
              width: "100%",
              maxWidth: 460,
              border: "1px solid #c4c8bc",
              borderRadius: 10,
              padding: "10px 14px",
              background: "#fffdf9",
              color: "#2e3230",
              fontSize: 14,
              fontFamily: "'Nunito Sans', sans-serif",
            }}
          />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {languages.map((language) => {
              const active = languageFilter === language;
              return (
                <button
                  key={language}
                  type="button"
                  onClick={() => setLanguageFilter(language)}
                  style={{
                    borderRadius: 999,
                    border: active ? "1px solid #4a7c59" : "1px solid #c4c8bc",
                    background: active ? "#eef4f1" : "#f5f1ea",
                    color: active ? "#4a7c59" : "#74796e",
                    padding: "6px 12px",
                    fontSize: 12,
                    fontWeight: 700,
                    cursor: "pointer",
                  }}
                >
                  {language}
                </button>
              );
            })}
          </div>
        </div>

        <div style={{ display: "grid", gap: 14 }}>
          {filteredRepos.length === 0 && (
            <div style={{ background: "#fffdf9", border: "1px solid #ddd8ce", borderRadius: 16, padding: 24, color: "#74796e", fontSize: 14 }}>
              No repositories match your current search and language filters.
            </div>
          )}
          {filteredRepos.map((repo) => {
            const isOpen = openRepoId === repo.id;
            const branches = branchesByRepo[repo.id] || [];
            const branchLoading = branchLoadingByRepo[repo.id] === true;
            const importError = importErrors[repo.id];
            const selectedBranch = selectedBranchByRepo[repo.id] || repo.default_branch;

            return (
              <div
                key={repo.id}
                style={{
                  background: "#f5f1ea",
                  border: "1px solid #c4c8bc",
                  borderRadius: 14,
                  padding: 20,
                  display: "grid",
                  gap: 14,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: 19, fontWeight: 700, color: "#2e3230", marginBottom: 6 }}>
                      {repo.full_name}
                    </div>
                    <div style={{ color: "#74796e", fontSize: 14, lineHeight: 1.6 }}>
                      {repo.description || "No description provided."}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      void openImportPanel(repo);
                    }}
                    style={{
                      background: "#4a7c59",
                      color: "#fff",
                      border: "none",
                      borderRadius: 10,
                      padding: "10px 16px",
                      fontSize: 13,
                      fontWeight: 700,
                      cursor: "pointer",
                    }}
                  >
                    Import
                  </button>
                </div>

                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {repo.language && (
                    <span style={{ background: "#eef4f1", color: "#4a7c59", borderRadius: 999, padding: "4px 9px", fontSize: 11, fontWeight: 700 }}>
                      {repo.language}
                    </span>
                  )}
                  <span style={{ background: repo.private ? "#fef3c7" : "#e0f2fe", color: repo.private ? "#92400e" : "#0369a1", borderRadius: 999, padding: "4px 9px", fontSize: 11, fontWeight: 700 }}>
                    {repo.private ? "Private" : "Public"}
                  </span>
                  <span style={{ background: "#f5f1ea", color: "#74796e", borderRadius: 999, padding: "4px 9px", fontSize: 11, border: "1px solid #d8d4cc" }}>
                    Updated {formatUpdatedAt(repo.updated_at)}
                  </span>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 4, background: "#f5f1ea", color: "#74796e", borderRadius: 999, padding: "4px 9px", fontSize: 11, border: "1px solid #d8d4cc" }}>
                    <Star size={12} />
                    {repo.stargazers_count}
                  </span>
                </div>

                {isOpen && (
                  <div style={{ background: "#fffdf9", border: "1px solid #ddd8ce", borderRadius: 12, padding: 16, display: "grid", gap: 12 }}>
                    <div style={{ fontSize: 11, color: "#74796e", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                      Select branch
                    </div>
                    {branchLoading ? (
                      <div style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "#74796e", fontSize: 13 }}>
                        <Loader2 size={14} style={{ animation: "terra-spin 1s linear infinite" }} />
                        Loading branches...
                      </div>
                    ) : (
                      <select
                        value={selectedBranch}
                        onChange={(event) => {
                          setSelectedBranchByRepo((current) => ({ ...current, [repo.id]: event.target.value }));
                        }}
                        style={{
                          maxWidth: 280,
                          border: "1px solid #c4c8bc",
                          borderRadius: 8,
                          padding: "9px 12px",
                          background: "#fff",
                          color: "#2e3230",
                          fontSize: 14,
                        }}
                      >
                        {(branches.length > 0 ? branches : [{ name: repo.default_branch }]).map((branch) => (
                          <option key={branch.name} value={branch.name}>
                            {branch.name}
                          </option>
                        ))}
                      </select>
                    )}

                    {importError && (
                      <div style={{ color: "#c0392b", fontSize: 13 }}>{importError}</div>
                    )}

                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                      <button
                        type="button"
                        onClick={() => {
                          void importRepo(repo);
                        }}
                        disabled={importingRepoId === repo.id || branchLoading}
                        style={{
                          background: "#4a7c59",
                          color: "#fff",
                          border: "none",
                          borderRadius: 10,
                          padding: "10px 16px",
                          fontSize: 13,
                          fontWeight: 700,
                          cursor: importingRepoId === repo.id || branchLoading ? "wait" : "pointer",
                          opacity: importingRepoId === repo.id || branchLoading ? 0.8 : 1,
                        }}
                      >
                        {importingRepoId === repo.id ? "Importing..." : "Import this repo →"}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          void openImportPanel(repo);
                        }}
                        style={{
                          background: "transparent",
                          color: "#74796e",
                          border: "none",
                          padding: "10px 4px",
                          fontSize: 13,
                          cursor: "pointer",
                        }}
                      >
                        {isOpen ? "Close" : "Choose branch"}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
