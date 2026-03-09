"""Build an AI repo brief grounded in structured scan / graph / simulation data.

The prompt sent to the LLM contains *only* pre-ranked, trimmed facts extracted
from the project's own scan results, graph topology, and (optionally) the
latest simulation run.  Raw file lists, full extension maps, and low-signal
metadata are stripped before the prompt is assembled so the context stays
compact and high-signal.
"""

from __future__ import annotations

import json
import logging
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

    # --- Entry points: keep top N ---
    entry_points = scan.get("entry_points", [])[:_MAX_ENTRY_POINTS]

    # --- Key files: keep top N ---
    key_files = scan.get("key_files", [])[:_MAX_KEY_FILES]

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
context about a codebase.  Write a concise, grounded repo brief.

RULES
1. Base EVERY claim on the context provided — do not invent files, components,
   frameworks, or risks that are absent from the data.
2. Keep each field to 2-4 sentences.
3. For reading_order, list 3-6 concrete file paths drawn from key_entry_points
   and top_key_files in the context.
4. For risk_notes, cite only risks visible in the graph edges or simulation
   (e.g. single points of failure, missing redundancy, tight coupling).
5. If latest_simulation is null, set simulation_insight to null.
6. Do NOT pad the response with generic advice.

Respond with ONLY a JSON object in this exact schema:
{
  "repo_summary": "<one-paragraph overview of the project>",
  "main_components": [
    {"name": "<name>", "type": "<type>", "description": "<1-2 sentences>"}
  ],
  "architecture_explanation": "<how components connect — reference graph edges>",
  "reading_order": ["<path1>", "<path2>"],
  "risk_notes": ["<concrete risk 1>", "<concrete risk 2>"],
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
