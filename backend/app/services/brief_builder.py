"""Build an AI repo brief grounded in structured scan / graph / simulation data.

The prompt sent to the LLM contains *only* pre-ranked, trimmed, and
path-sanitized facts extracted from the project's own scan results, graph
topology, and (optionally) the latest simulation run.  Internal workspace
paths, UUID folders, and cross-project leakage are stripped before the prompt
is assembled.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Trimming limits — keep these small to stay token-efficient
# --------------------------------------------------------------------------- #
_MAX_COMPONENTS = 5
_MAX_LANGUAGES = 5
_MAX_FRAMEWORKS = 6
_MAX_FOLDERS = 5
_MAX_ENTRY_POINTS = 5
_MAX_KEY_FILES = 6
_MAX_GRAPH_EDGES = 10
_MAX_SIM_IMPACTED = 5

# --------------------------------------------------------------------------- #
#  Path sanitization
# --------------------------------------------------------------------------- #

# Matches internal workspace/upload prefixes:
#   backend/workspaces/<uuid>/<uuid>/<WrapperDir>/rest/of/path
#   backend/uploads/<uuid>/file
#   workspaces/<uuid>/...   uploads/<uuid>/...
# The regex eats everything up to and including the first "real" repo segment
# after the UUID + optional wrapper-dir layer.
_UUID_RE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_INTERNAL_PATH_RE = re.compile(
    r"^(?:backend/)?"               # optional leading "backend/"
    r"(?:workspaces|uploads)/"      # internal storage dir
    r"(?:" + _UUID_RE + r"/)+"      # one or more UUID folders
    r"(?:[^/]+-(?:main|master)/)?"  # optional GitHub-style wrapper (e.g. Repo-main/)
)


def _sanitize_path(path: str) -> Optional[str]:
    """Strip internal workspace/upload prefixes and return a clean repo-relative path.

    Returns ``None`` if the path is entirely internal noise or empty after
    sanitization.
    """
    # Check if the original path is an upload/workspace path before stripping
    is_internal = bool(_INTERNAL_PATH_RE.search(path))
    cleaned = _INTERNAL_PATH_RE.sub("", path)
    # Drop any path that is now empty or still contains a UUID folder segment
    if not cleaned or re.search(_UUID_RE, cleaned):
        return None
    # If the path was internal and what remains has no directory depth,
    # it's likely just a bare filename from uploads — drop it.
    if is_internal and "/" not in cleaned:
        return None
    # Normalise slashes
    cleaned = cleaned.replace("\\", "/").strip("/")
    return cleaned or None


def _sanitize_paths(paths: list[str]) -> list[str]:
    """Sanitize a list of paths, dropping any that resolve to noise."""
    out: list[str] = []
    seen: set[str] = set()
    for p in paths:
        clean = _sanitize_path(p)
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


# --------------------------------------------------------------------------- #
#  Ranking helpers
# --------------------------------------------------------------------------- #

# Edge types ordered by architectural significance (most → least).
_EDGE_TYPE_RANK = {
    "connects_to": 0,
    "runs_on": 1,
    "contains": 2,
    "uses": 3,
}


def _rank_edge(edge: dict) -> int:
    return _EDGE_TYPE_RANK.get(edge.get("edge_type", ""), 99)


# Folders that are almost always low-signal boilerplate.
_LOW_SIGNAL_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv",
                    "dist", "build", ".idea", ".vscode", "public"}


def _is_high_signal_dir(name: str) -> bool:
    return name.lower() not in _LOW_SIGNAL_DIRS


# --------------------------------------------------------------------------- #
#  Public: build_brief_context()
# --------------------------------------------------------------------------- #


def build_brief_context(
    *,
    scan: dict,
    nodes: list[dict],
    edges: list[dict],
    simulation: Optional[dict] = None,
) -> dict[str, Any]:
    """Distil scan / graph / simulation into a compact, ranked context dict.

    All file paths are sanitized to strip internal workspace/upload prefixes.
    Every list is trimmed to a fixed maximum so downstream token usage stays
    predictable regardless of repo size.
    """

    # --- Languages: top N by implied file count (extension_counts proxy) ---
    languages = scan.get("languages", [])[:_MAX_LANGUAGES]

    # --- Frameworks / tools: deduplicate and cap ---
    frameworks = scan.get("frameworks", [])[:_MAX_FRAMEWORKS]

    # --- Folders: filter noise, keep top N ---
    all_dirs = scan.get("top_level_dirs", [])
    folders = [d for d in all_dirs if _is_high_signal_dir(d)][:_MAX_FOLDERS]

    # --- Components: keep top N, emit only name + type ---
    raw_components = scan.get("components", [])
    components = [
        {"name": c.get("name", "?"), "type": c.get("type", "?")}
        for c in raw_components[:_MAX_COMPONENTS]
    ]

    # --- Entry points: sanitize paths, keep top N ---
    entry_points = _sanitize_paths(
        scan.get("entry_points", [])
    )[:_MAX_ENTRY_POINTS]

    # --- Key files: sanitize paths, keep top N ---
    key_files = _sanitize_paths(
        scan.get("key_files", [])
    )[:_MAX_KEY_FILES]

    # --- Graph summary: compact node list + ranked/trimmed edges ---
    label_map = {n["id"]: n["label"] for n in nodes}
    graph_nodes_compact = []
    for n in nodes:
        item: dict[str, Any] = {"label": n["label"], "type": n["node_type"]}
        data = n.get("data", {})
        if data.get("tools"):
            item["tools"] = data["tools"]
        graph_nodes_compact.append(item)

    ranked_edges = sorted(edges, key=_rank_edge)[:_MAX_GRAPH_EDGES]
    graph_edges_compact = [
        {
            "from": label_map.get(e["source_node_id"], "?"),
            "to": label_map.get(e["target_node_id"], "?"),
            "rel": e["edge_type"],
        }
        for e in ranked_edges
    ]

    graph_summary = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "nodes": graph_nodes_compact,
        "edges": graph_edges_compact,
    }

    # --- Simulation summary (one run, trimmed impacted list) ---
    sim_summary: Optional[dict[str, Any]] = None
    if simulation:
        impacted = simulation.get("impacted_nodes", [])[:_MAX_SIM_IMPACTED]
        sim_summary = {
            "failed_node": simulation.get("failed_node_label", "?"),
            "failed_type": simulation.get("failed_node_type", "?"),
            "severity": simulation.get("severity", "?"),
            "summary": simulation.get("summary", ""),
            "impacted": [
                {"label": i.get("label", "?"), "distance": i.get("distance", "?")}
                for i in impacted
            ],
        }

    return {
        "project_type": scan.get("project_type", "unknown"),
        "file_count": scan.get("file_count", 0),
        "top_languages": languages,
        "top_frameworks_tools": frameworks,
        "main_components": components,
        "key_entry_points": entry_points,
        "top_folders": folders,
        "top_key_files": key_files,
        "graph_summary": graph_summary,
        "latest_simulation": sim_summary,
    }


# --------------------------------------------------------------------------- #
#  Prompt template
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """\
You are a software-architecture analyst.  You will receive a compact JSON
context about ONE codebase.  Write a concise, grounded repo brief.

STRICT RULES
1. Base EVERY claim on the context JSON provided.
2. Do NOT invent files, components, frameworks, tools, risks, or relationships
   that are absent from the context.  If a technology appears only under
   "top_frameworks_tools" it is a detected dependency — describe it as such,
   not as the primary application stack unless the component types confirm it.
3. Keep each text field to 2-4 sentences.
4. For reading_order, list 3-6 file paths taken ONLY from key_entry_points
   and top_key_files.  Do not fabricate paths.
5. For risk_notes, cite ONLY risks directly evidenced by graph_summary edges
   or latest_simulation (e.g. single points of failure, tight coupling).
   Do not add generic security or operational advice.
6. If latest_simulation is null, set simulation_insight to null.
7. Do NOT reference internal paths, UUIDs, workspace directories, or upload
   storage paths — use only clean repo-relative paths.
8. Do NOT pad the response with filler, disclaimers, or generic advice.

Respond with ONLY a JSON object in this exact schema:
{
  "repo_summary": "<one-paragraph overview>",
  "main_components": [
    {"name": "<name>", "type": "<type>", "description": "<1-2 sentences>"}
  ],
  "architecture_explanation": "<how components connect — cite graph edges>",
  "reading_order": ["<path1>", "<path2>"],
  "risk_notes": ["<evidence-based risk>"],
  "simulation_insight": "<what the simulation revealed, or null>"
}
"""


def _build_user_message(context: dict, project_name: str) -> str:
    """Serialise the compact context dict into the user message."""
    return (
        f"# Repo Brief — {project_name}\n\n"
        f"```json\n{json.dumps(context, indent=2)}\n```"
    )


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #


def generate_brief(
    *,
    project_name: str,
    project_id: str,
    scan: dict,
    nodes: list[dict],
    edges: list[dict],
    simulation: Optional[dict] = None,
) -> dict[str, Any]:
    """Build a compact context, call the LLM, and return the parsed brief.

    Raises ``RuntimeError`` when the API key is missing or the LLM response
    cannot be parsed.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to your .env file or environment."
        )

    context = build_brief_context(
        scan=scan, nodes=nodes, edges=edges, simulation=simulation,
    )
    user_msg = _build_user_message(context, project_name)

    logger.debug(
        "Brief prompt size: ~%d chars system, ~%d chars user",
        len(SYSTEM_PROMPT),
        len(user_msg),
    )

    client = OpenAI(api_key=OPENAI_API_KEY)

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0.15,
    )

    raw = response.choices[0].message.content
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error("LLM returned invalid JSON: %s", raw)
        raise RuntimeError("Failed to parse LLM response as JSON") from exc

    return {
        "project_id": project_id,
        "repo_summary": parsed.get("repo_summary", ""),
        "main_components": parsed.get("main_components", []),
        "architecture_explanation": parsed.get("architecture_explanation", ""),
        "reading_order": parsed.get("reading_order", []),
        "risk_notes": parsed.get("risk_notes", []),
        "simulation_insight": parsed.get("simulation_insight"),
    }
