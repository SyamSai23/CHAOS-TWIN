"""AI-powered phrase generator for human-readable route descriptions."""

from __future__ import annotations

import json
import logging
import os
import re

from openai import OpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a technical writer who explains \
API routes to non-technical users such as product managers, \
designers, and business stakeholders. \
You write clear, friendly, one-sentence descriptions of what \
each phase of an API route does. \
Rules you must follow:
- Never use jargon like: iterates, commits transaction, \
  instantiates, traverses, db_, query(), .filter(), \
  HTTPException, ORM, session
- Always focus on WHAT it does for the user, not HOW \
  the code works
- Be specific — use the actual operation described
- Each description must be ONE sentence only
- Write in present tense: "Checks...", "Saves...", \
  "Returns...", "Generates..."
"""

_JARGON = [
    "iterates", "commits", "instantiate", "traverse",
    "db_", "query(", ".filter(", "HTTPException",
    "transaction", "ORM", "session", "rollback",
]

_FALLBACKS: dict[str, str] = {
    "validation": "Verifies that everything is in order before processing your request.",
    "processing": "Handles the main work of your request.",
    "database": "Saves or retrieves your data.",
    "response": "Returns the result to you.",
}


class PhraseGenerator:
    """Generates human-readable phase descriptions via OpenAI."""

    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        self._enabled = bool(api_key)
        if self._enabled:
            self._client = OpenAI(api_key=api_key)

    # ── public ──────────────────────────────────────────────────────

    def generate_phrases(self, route_analysis: dict) -> dict[str, str]:
        """Return {phase_id: description} for every phase in the analysis."""
        phases = route_analysis.get("phases", [])
        if not phases:
            return {}

        if not self._enabled:
            logger.warning("OPENAI_API_KEY not set — returning fallback phrases")
            return {p["phase_id"]: _FALLBACKS.get(p["phase_id"], "") for p in phases}

        method = route_analysis.get("method", "GET")
        path = route_analysis.get("path", "/")
        noun = self._extract_noun(path)
        compact = self._build_compact_context(method, path, noun, phases)
        phase_summaries = self._build_phase_summaries(compact["phases"])

        user_prompt = (
            f"Explain each phase of this API route in plain English "
            f"for a non-technical user.\n\n"
            f"Route: {method} {path}\n"
            f"This route handles: {noun} operations\n\n"
            f"For each phase below, write ONE clear sentence explaining "
            f"what it does for the user. Be specific — use the actual "
            f"operation names provided. Focus on the user benefit, "
            f"not the technical implementation.\n\n"
            f"Phases:\n{phase_summaries}\n\n"
            f"Respond in JSON only — no preamble, no explanation, "
            f"no markdown fences:\n"
            "{\n"
            + ",\n".join(
                f'  "{p["phase_id"]}": "one sentence here"'
                for p in compact["phases"]
            )
            + "\n}\n"
            f"Only include phase_ids that exist in the input above."
        )

        try:
            response = self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=200,
                temperature=0.3,
            )
            raw = response.choices[0].message.content.strip()
            parsed = self._parse_response(raw)
            return self._validate(parsed, phases)
        except Exception as e:
            logger.warning("Phrase generation failed for %s: %s", path, str(e))
            return {p["phase_id"]: _FALLBACKS.get(p["phase_id"], "") for p in phases}

    # ── private helpers ─────────────────────────────────────────────

    @staticmethod
    def _extract_noun(path: str) -> str:
        """Pull the primary resource noun from a route path."""
        segments = [s for s in path.split("/") if s and not s.startswith("{")]
        return segments[-1] if segments else "resource"

    @staticmethod
    def _build_compact_context(
        method: str, path: str, noun: str, phases: list[dict]
    ) -> dict:
        compact_phases = []
        for p in phases:
            steps = p.get("steps", [])
            step_types = list({s.get("type", "") for s in steps})
            step_labels = [s.get("label", "") for s in steps[:3]]
            error_codes = [
                s.get("line_number")  # not real codes; check error_paths instead
                for s in steps
                if s.get("is_error_path")
            ]
            compact_phases.append({
                "phase_id": p["phase_id"],
                "step_types": step_types,
                "step_labels": step_labels,
                "has_error": any(s.get("is_error_path") for s in steps),
                "error_codes": error_codes[:3],
                "has_loop": any(s.get("type") == "loop" for s in steps),
                "has_external": any(s.get("type") == "external" for s in steps),
                "step_count": len(steps),
            })
        return {
            "route_method": method,
            "route_path": path,
            "route_noun": noun,
            "phases": compact_phases,
        }

    @staticmethod
    def _build_phase_summaries(compact_phases: list[dict]) -> str:
        lines = []
        for cp in compact_phases:
            parts = [cp["phase_id"] + ":"]
            labels = [l for l in cp["step_labels"] if l]
            if labels:
                parts.append(", ".join(labels))
            parts.append(f"({cp['step_count']} steps")
            extras = []
            if cp["has_error"]:
                extras.append("raises errors if invalid")
            if cp["has_loop"]:
                extras.append("loops over items")
            if cp["has_external"]:
                extras.append("calls external service")
            if extras:
                parts[-1] += ", " + ", ".join(extras)
            parts[-1] += ")"
            lines.append(" ".join(parts))
        return "\n".join(lines)

    @staticmethod
    def _parse_response(raw: str) -> dict:
        """Strip markdown fences and parse JSON."""
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        return json.loads(cleaned)

    @staticmethod
    def _validate(parsed: dict, phases: list[dict]) -> dict[str, str]:
        """Replace any description containing jargon with a fallback."""
        result: dict[str, str] = {}
        for p in phases:
            pid = p["phase_id"]
            desc = parsed.get(pid, "")
            if not desc or any(j in desc for j in _JARGON):
                result[pid] = _FALLBACKS.get(pid, "")
            else:
                result[pid] = desc
        return result
