import {
  useEffect,
  useState,
  type ChangeEvent,
  type Dispatch,
  type FormEvent,
  type SetStateAction,
} from "react";

import type {
  DeepDiveResult,
  GraphResponse,
  Project,
  ScanResult,
  SimulationResult,
} from "../types";
import {
  createProject,
  deleteProject,
  fetchComponentDeepDive,
  fetchDbHealth,
  fetchHealth,
  fetchLatestProjectScan,
  generateProjectGraph,
  listProjects,
  runProjectScan,
  runProjectSimulation,
  uploadProjectZip,
} from "../api/client";
import type { NavItem } from "./navigation";

export function useChaosTwinApp() {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<NavItem>("workspace");
  const [showCreateForm, setShowCreateForm] = useState(false);

  const [apiStatus, setApiStatus] = useState<string>("loading...");
  const [dbStatus, setDbStatus] = useState<string>("loading...");

  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);

  const [scans, setScans] = useState<Record<string, ScanResult | null>>({});
  const [scanning, setScanning] = useState<Record<string, boolean>>({});
  const [scanErrors, setScanErrors] = useState<Record<string, string | null>>({});

  const [uploading, setUploading] = useState<Record<string, boolean>>({});
  const [uploadMessages, setUploadMessages] = useState<Record<string, string | null>>({});
  const [uploadedFilenames, setUploadedFilenames] = useState<Record<string, string | null>>({});

  const [graphs, setGraphs] = useState<Record<string, GraphResponse | null>>({});
  const [generatingGraph, setGeneratingGraph] = useState<Record<string, boolean>>({});
  const [graphMessages, setGraphMessages] = useState<Record<string, string | null>>({});

  const [simSelectedNode, setSimSelectedNode] = useState<Record<string, string>>({});
  const [simulating, setSimulating] = useState<Record<string, boolean>>({});
  const [simResults, setSimResults] = useState<Record<string, SimulationResult | null>>({});
  const [simErrors, setSimErrors] = useState<Record<string, string | null>>({});

  const [ddSelectedRoot, setDdSelectedRoot] = useState<Record<string, string | null>>({});
  const [ddLoading, setDdLoading] = useState<Record<string, boolean>>({});
  const [ddResults, setDdResults] = useState<Record<string, DeepDiveResult | null>>({});
  const [ddErrors, setDdErrors] = useState<Record<string, string | null>>({});
  const [ddExpandEdges, setDdExpandEdges] = useState<Record<string, boolean>>({});
  const [projectRefreshKeys, setProjectRefreshKeys] = useState<Record<string, number>>({});

  useEffect(() => {
    fetchHealth()
      .then((data) => setApiStatus(data.status))
      .catch(() => setApiStatus("error"));

    fetchDbHealth()
      .then((data) => setDbStatus(data.database))
      .catch(() => setDbStatus("error"));

    void fetchProjects();
  }, []);

  useEffect(() => {
    if (projects.length > 0 && !selectedProjectId) {
      setSelectedProjectId(projects[0].id);
    }

    if (selectedProjectId && !projects.find((project) => project.id === selectedProjectId)) {
      setSelectedProjectId(projects.length > 0 ? projects[0].id : null);
    }
  }, [projects, selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId || selectedProjectId in scans) {
      return;
    }

    let cancelled = false;

    void fetchLatestProjectScan(selectedProjectId)
      .then((data) => {
        if (!cancelled) {
          setScans((prev) => ({ ...prev, [selectedProjectId]: data }));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setScans((prev) => ({ ...prev, [selectedProjectId]: null }));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [scans, selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId) {
      return;
    }
    if (!(scans[selectedProjectId] ?? null) && activeView !== "workspace") {
      setActiveView("workspace");
    }
  }, [activeView, scans, selectedProjectId]);

  const selectedProject = projects.find((project) => project.id === selectedProjectId) || null;

  async function fetchProjects() {
    try {
      const data = await listProjects();
      setProjects(data);
    } catch {
      console.error("Failed to fetch projects");
    }
  }

  function bumpProjectRefreshKey(projectId: string) {
    setProjectRefreshKeys((prev) => ({
      ...prev,
      [projectId]: (prev[projectId] ?? 0) + 1,
    }));
  }

  function resetProjectDerivedState(projectId: string) {
    setScans((prev) => ({ ...prev, [projectId]: null }));
    setGraphs((prev) => ({ ...prev, [projectId]: null }));
    setGraphMessages((prev) => ({ ...prev, [projectId]: null }));
    setSimSelectedNode((prev) => ({ ...prev, [projectId]: "" }));
    setSimResults((prev) => ({ ...prev, [projectId]: null }));
    setSimErrors((prev) => ({ ...prev, [projectId]: null }));
    setDdSelectedRoot((prev) => ({ ...prev, [projectId]: null }));
    setDdResults((prev) => ({ ...prev, [projectId]: null }));
    setDdErrors((prev) => ({ ...prev, [projectId]: null }));
    setDdExpandEdges((prev) => ({ ...prev, [projectId]: false }));
    bumpProjectRefreshKey(projectId);
  }

  function clearProjectKey<T>(
    setter: Dispatch<SetStateAction<Record<string, T>>>,
    projectId: string,
  ) {
    setter((prev) => {
      const next = { ...prev };
      delete next[projectId];
      return next;
    });
  }

  function removeProjectState(projectId: string) {
    clearProjectKey(setScans, projectId);
    clearProjectKey(setScanning, projectId);
    clearProjectKey(setScanErrors, projectId);
    clearProjectKey(setUploading, projectId);
    clearProjectKey(setUploadMessages, projectId);
    clearProjectKey(setUploadedFilenames, projectId);
    clearProjectKey(setGraphs, projectId);
    clearProjectKey(setGeneratingGraph, projectId);
    clearProjectKey(setGraphMessages, projectId);
    clearProjectKey(setSimSelectedNode, projectId);
    clearProjectKey(setSimulating, projectId);
    clearProjectKey(setSimResults, projectId);
    clearProjectKey(setSimErrors, projectId);
    clearProjectKey(setDdSelectedRoot, projectId);
    clearProjectKey(setDdLoading, projectId);
    clearProjectKey(setDdResults, projectId);
    clearProjectKey(setDdErrors, projectId);
    clearProjectKey(setDdExpandEdges, projectId);
    clearProjectKey(setProjectRefreshKeys, projectId);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setCreateError(null);

    try {
      const newProject = await createProject({ name, path });
      setName("");
      setPath("");
      setShowCreateForm(false);
      setProjects((prev) => [...prev, newProject]);
      setSelectedProjectId(newProject.id);
      setActiveView("workspace");
    } catch {
      setCreateError("Failed to create project");
    }
  }

  function cancelCreateForm() {
    setShowCreateForm(false);
    setCreateError(null);
  }

  async function handleDeleteProject(projectId: string) {
    if (!window.confirm("Delete this project and all its data? This cannot be undone.")) {
      return;
    }

    try {
      await deleteProject(projectId);
      removeProjectState(projectId);
      setProjects((prev) => prev.filter((project) => project.id !== projectId));
    } catch (error) {
      alert(error instanceof Error ? error.message : "Failed to delete project");
    }
  }

  async function handleFileSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    const projectId = selectedProjectId;
    if (!file || !projectId) {
      return;
    }

    event.target.value = "";
    setUploading((prev) => ({ ...prev, [projectId]: true }));
    setUploadMessages((prev) => ({ ...prev, [projectId]: null }));

    try {
      const data = await uploadProjectZip(projectId, file);
      resetProjectDerivedState(projectId);
      setUploadMessages((prev) => ({ ...prev, [projectId]: "Uploaded successfully" }));
      setUploadedFilenames((prev) => ({ ...prev, [projectId]: data.filename }));
    } catch (error) {
      setUploadMessages((prev) => ({
        ...prev,
        [projectId]: error instanceof Error ? error.message : "Upload failed",
      }));
    } finally {
      setUploading((prev) => ({ ...prev, [projectId]: false }));
    }
  }

  async function handleScan(projectId: string) {
    setScanning((prev) => ({ ...prev, [projectId]: true }));
    setScanErrors((prev) => ({ ...prev, [projectId]: null }));

    try {
      const data = await runProjectScan(projectId);
      resetProjectDerivedState(projectId);
      setScans((prev) => ({ ...prev, [projectId]: data }));
      if (projectId === selectedProjectId) {
        setActiveView("workspace");
      }
    } catch (error) {
      setScanErrors((prev) => ({
        ...prev,
        [projectId]: error instanceof Error ? error.message : "Scan failed",
      }));
    } finally {
      setScanning((prev) => ({ ...prev, [projectId]: false }));
    }
  }

  async function handleGenerateGraph(projectId: string) {
    setGeneratingGraph((prev) => ({ ...prev, [projectId]: true }));
    setGraphMessages((prev) => ({ ...prev, [projectId]: null }));

    try {
      const data = await generateProjectGraph(projectId);
      setGraphs((prev) => ({ ...prev, [projectId]: data }));
      setGraphMessages((prev) => ({ ...prev, [projectId]: "Graph ready" }));
      setSimSelectedNode((prev) => ({ ...prev, [projectId]: "" }));
      setSimResults((prev) => ({ ...prev, [projectId]: null }));
      setSimErrors((prev) => ({ ...prev, [projectId]: null }));
      bumpProjectRefreshKey(projectId);
    } catch (error) {
      setGraphMessages((prev) => ({
        ...prev,
        [projectId]: error instanceof Error ? error.message : "Failed to build graph",
      }));
    } finally {
      setGeneratingGraph((prev) => ({ ...prev, [projectId]: false }));
    }
  }

  async function handleSimulate(projectId: string) {
    const nodeId = simSelectedNode[projectId];
    if (!nodeId) {
      return;
    }

    setSimulating((prev) => ({ ...prev, [projectId]: true }));
    setSimErrors((prev) => ({ ...prev, [projectId]: null }));
    setSimResults((prev) => ({ ...prev, [projectId]: null }));

    try {
      const data = await runProjectSimulation(projectId, nodeId);
      setSimResults((prev) => ({ ...prev, [projectId]: data }));
    } catch (error) {
      setSimErrors((prev) => ({
        ...prev,
        [projectId]: error instanceof Error ? error.message : "Simulation failed",
      }));
    } finally {
      setSimulating((prev) => ({ ...prev, [projectId]: false }));
    }
  }

  async function handleDeepDive(projectId: string, componentRoot: string) {
    if (ddSelectedRoot[projectId] === componentRoot) {
      setDdSelectedRoot((prev) => ({ ...prev, [projectId]: null }));
      setDdResults((prev) => ({ ...prev, [projectId]: null }));
      setDdErrors((prev) => ({ ...prev, [projectId]: null }));
      return;
    }

    setDdSelectedRoot((prev) => ({ ...prev, [projectId]: componentRoot }));
    setDdLoading((prev) => ({ ...prev, [projectId]: true }));
    setDdErrors((prev) => ({ ...prev, [projectId]: null }));
    setDdResults((prev) => ({ ...prev, [projectId]: null }));

    try {
      const data = await fetchComponentDeepDive(projectId, componentRoot);
      setDdResults((prev) => ({ ...prev, [projectId]: data }));
    } catch (error) {
      setDdErrors((prev) => ({
        ...prev,
        [projectId]: error instanceof Error ? error.message : "Deep dive failed",
      }));
    } finally {
      setDdLoading((prev) => ({ ...prev, [projectId]: false }));
    }
  }

  async function openDeepDive(projectId: string, componentRoot: string) {
    if (ddSelectedRoot[projectId] !== componentRoot) {
      await handleDeepDive(projectId, componentRoot);
    }
    setActiveView("deep-dive");
  }

  function handleGraphNodeClick(projectId: string, nodeId: string) {
    const graph = graphs[projectId];
    const scan = scans[projectId];
    if (!graph || !scan) {
      return;
    }

    const node = graph.nodes.find((item) => item.id === nodeId);
    if (!node || !["frontend", "backend", "component"].includes(node.node_type)) {
      return;
    }

    const nodeComponentKey = typeof node.data.component_key === "string" ? node.data.component_key : null;
    const component = (scan.components || []).find((item) => item.component_key === nodeComponentKey)
      || (scan.components || []).find((item) => item.root_path === node.data.root_path);

    if (component) {
      void openDeepDive(projectId, component.root_path);
    }
  }

  function setSimulationNode(projectId: string, nodeId: string) {
    setSimSelectedNode((prev) => ({ ...prev, [projectId]: nodeId }));
  }

  function clearSimulationResult(projectId: string) {
    setSimResults((prev) => ({ ...prev, [projectId]: null }));
  }

  function toggleDeepDiveEdges(projectId: string) {
    setDdExpandEdges((prev) => ({
      ...prev,
      [projectId]: !(prev[projectId] ?? false),
    }));
  }

  function selectProject(projectId: string) {
    setSelectedProjectId(projectId);
    setActiveView("workspace");
  }

  function statusDotClass(value: string) {
    if (value === "loading...") return "loading";
    if (value === "ok" || value === "connected" || value === "running") return "ok";
    return "err";
  }

  return {
    activeView,
    apiStatus,
    createError,
    dbStatus,
    ddErrors,
    ddExpandEdges,
    ddLoading,
    ddResults,
    ddSelectedRoot,
    generatingGraph,
    graphMessages,
    graphs,
    name,
    path,
    projectRefreshKeys,
    projects,
    scanErrors,
    scanning,
    scans,
    selectedProject,
    selectedProjectId,
    showCreateForm,
    simErrors,
    simResults,
    simSelectedNode,
    simulating,
    uploadedFilenames,
    uploading,
    uploadMessages,
    clearSimulationResult,
    cancelCreateForm,
    handleDeepDive,
    handleDeleteProject,
    handleFileSelected,
    handleGenerateGraph,
    handleGraphNodeClick,
    handleScan,
    handleSimulate,
    handleSubmit,
    openDeepDive,
    selectProject,
    setActiveView,
    setName,
    setPath,
    setSelectedProjectId,
    setShowCreateForm,
    setSimulationNode,
    statusDotClass,
    toggleDeepDiveEdges,
  };
}