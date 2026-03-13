from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.models.project import Project
from app.models.route_analysis import RouteAnalysis
from app.models.scan import Scan
from app.models.sequence_diagram import SequenceDiagram
from app.services.code_peek import _detect_language, _extract_snippet, _load_retrieval_context, _resolve_file_reference
from app.services.identity import make_route_id
from app.services.route_analysis_utils import build_route_analysis_from_route, ensure_route_analysis_signature

logger = logging.getLogger(__name__)

_MAX_ROUTE_STAGES = 8
_MAX_EVIDENCE_ITEMS = 4
_MAX_SNIPPET_CHARS = 4000
_MAX_SNIPPET_LINES = 40

_DIRECT_PROVENANCE = {
    "route_detection",
    "route_metadata",
    "direct_handler",
    "direct_code_signal",
    "route_completion",
}

SYSTEM_PROMPT = """You explain deterministic backend route and sequence artifacts for engineers.

STRICT RULES
1. Use only the JSON context provided.
2. Never invent hidden steps, files, components, failure modes, or user intent.
3. Preserve uncertainty exactly as given. If a step is inferred, degraded, fallback-derived, or low-confidence, say so.
4. If the grounding is partial, explain only what is grounded and make the limit explicit.
5. Keep each field concise and specific.
6. Respond with JSON only in this exact schema:
{
  "summary": "<2-4 sentences>",
  "why_it_matters": "<1-3 sentences>",
  "what_could_fail": "<1-3 sentences>",
  "confidence_note": "<1-2 sentences>",
  "evidence_used": ["<short evidence item>"]
}
7. evidence_used must contain 1-4 short strings copied or derived directly from the context.
8. Do not mention being an AI model, the prompt, or unavailable source code outside the provided context.
"""


class ExplanationNotFoundError(LookupError):
    pass


class ExplanationUnavailableError(RuntimeError):
    pass


class ExplanationBuilder:
    def __init__(self) -> None:
        self._enabled = bool(OPENAI_API_KEY)
        self._model = OPENAI_MODEL
        self._client = OpenAI(api_key=OPENAI_API_KEY) if self._enabled else None

    def explain(
        self,
        *,
        project_id: str,
        route_id: str,
        target_type: str,
        db: Session,
        stage_step: Optional[int] = None,
        message_id: Optional[str] = None,
    ) -> dict[str, Any]:
        latest_scan = self._get_latest_scan(project_id=project_id, db=db)
        if latest_scan is None:
            raise ExplanationNotFoundError("No scan found")

        raw_route = self._find_route_by_id(list(latest_scan.routes or []), route_id)
        if raw_route is None:
            raise ExplanationNotFoundError("Route not found")

        analysis, analysis_source = self._load_route_analysis(project_id=project_id, route_id=route_id, route=raw_route, db=db)
        request_flow = self._preferred_request_flow(raw_route, analysis)
        sequence = self._load_route_sequence(project_id=project_id, route_id=route_id, db=db)

        prompt_context, metadata = self._build_target_context(
            target_type=target_type,
            route_id=route_id,
            route=raw_route,
            request_flow=request_flow,
            analysis=analysis,
            analysis_source=analysis_source,
            sequence=sequence,
            stage_step=stage_step,
            message_id=message_id,
            project_id=project_id,
            db=db,
        )
        prompt_char_count = len(json.dumps(prompt_context, separators=(",", ":"), ensure_ascii=True))

        fallback = self._build_fallback_explanation(target_type=target_type, prompt_context=prompt_context)
        generated_status = "fallback"
        fallback_reason = "OPENAI_API_KEY is not configured"
        explanation = fallback

        if self._enabled and self._client is not None:
            try:
                explanation = self._generate_llm_explanation(prompt_context=prompt_context, fallback=fallback)
                generated_status = "ai_generated"
                fallback_reason = None
            except Exception as exc:
                logger.warning(
                    "Explanation generation fell back for project %s route %s target %s: %s",
                    project_id,
                    route_id,
                    target_type,
                    exc,
                )
                fallback_reason = str(exc)

        logger.info(
            "Explanation built for project %s route %s target %s status=%s prompt_chars=%s snippet=%s",
            project_id,
            route_id,
            target_type,
            generated_status,
            prompt_char_count,
            metadata["snippet_included"],
        )

        return {
            "target_type": target_type,
            "target_id": metadata["target_id"],
            "title": metadata["title"],
            "explanation": explanation,
            "grounding": metadata["grounding"],
            "generated_from": {
                "status": generated_status,
                "model": self._model,
                "llm_enabled": self._enabled,
                "prompt_char_count": prompt_char_count,
                "snippet_included": metadata["snippet_included"],
                "fallback_reason": fallback_reason,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    def _generate_llm_explanation(self, *, prompt_context: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        assert self._client is not None
        user_prompt = (
            "Explain this grounded route artifact using only the provided JSON context.\n\n"
            f"{json.dumps(prompt_context, indent=2)}"
        )
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=350,
            temperature=0.2,
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = self._parse_json_object(raw)
        return self._validate_explanation(parsed=parsed, fallback=fallback)

    @staticmethod
    def _parse_json_object(raw: str) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("Model did not return a JSON object")
        return parsed

    def _validate_explanation(self, *, parsed: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        return {
            "summary": self._clean_text(parsed.get("summary")) or fallback["summary"],
            "why_it_matters": self._clean_text(parsed.get("why_it_matters")) or fallback["why_it_matters"],
            "what_could_fail": self._clean_text(parsed.get("what_could_fail")) or fallback["what_could_fail"],
            "confidence_note": self._clean_text(parsed.get("confidence_note")) or fallback["confidence_note"],
            "evidence_used": self._clean_evidence_list(parsed.get("evidence_used")) or fallback["evidence_used"],
        }

    @staticmethod
    def _clean_text(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        text = re.sub(r"\s+", " ", value).strip()
        return text[:500]

    def _clean_evidence_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            text = self._clean_text(item)
            if text and text not in cleaned:
                cleaned.append(text)
            if len(cleaned) >= _MAX_EVIDENCE_ITEMS:
                break
        return cleaned

    def _build_target_context(
        self,
        *,
        target_type: str,
        route_id: str,
        route: dict[str, Any],
        request_flow: Optional[dict[str, Any]],
        analysis: Optional[dict[str, Any]],
        analysis_source: str,
        sequence: Optional[dict[str, Any]],
        stage_step: Optional[int],
        message_id: Optional[str],
        project_id: str,
        db: Session,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        route_meta = {
            "route_id": route_id,
            "method": str(route.get("method") or "GET").upper(),
            "path": str(route.get("path") or "/"),
            "file": route.get("file"),
            "component": route.get("component"),
            "handler_function": route.get("handler_function") or ((analysis or {}).get("handler_function")),
        }

        if target_type == "route":
            if not request_flow and not analysis:
                raise ExplanationUnavailableError("Deterministic route flow is unavailable for this route")
            warnings = self._route_warnings(request_flow=request_flow, analysis_source=analysis_source)
            prompt_context = {
                "target_type": target_type,
                "route": route_meta,
                "analysis_source": analysis_source,
                "analysis": self._analysis_summary(analysis),
                "request_flow": self._request_flow_summary(request_flow),
                "warnings": warnings,
            }
            return prompt_context, {
                "target_id": route_id,
                "title": f"Journey explanation for {route_meta['method']} {route_meta['path']}",
                "snippet_included": False,
                "grounding": {
                    **route_meta,
                    "target_type": target_type,
                    "analysis_source": analysis_source,
                    "confidence": request_flow.get("confidence") if request_flow else None,
                    "warnings": warnings,
                },
            }

        if target_type == "request_flow_step":
            if not request_flow:
                raise ExplanationUnavailableError("Deterministic request flow is unavailable for this route")
            if stage_step is None:
                raise ExplanationUnavailableError("stage_step is required for request_flow_step explanations")
            stage, stage_index = self._find_request_flow_stage(request_flow, stage_step)
            snippet = self._snippet_for_anchor(project_id=project_id, anchor=self._stage_anchor(stage), db=db)
            warnings = self._route_warnings(request_flow=request_flow, analysis_source=analysis_source)
            prompt_context = {
                "target_type": target_type,
                "route": route_meta,
                "request_flow": self._request_flow_summary(request_flow),
                "analysis": self._analysis_summary(analysis),
                "selected_stage": self._stage_summary(stage),
                "previous_stage": self._neighbor_stage_summary(request_flow, stage_index - 1),
                "next_stage": self._neighbor_stage_summary(request_flow, stage_index + 1),
                "warnings": warnings,
                "code_snippet": snippet,
            }
            target_id = f"{route_id}:stage:{stage.get('step', stage_index)}"
            return prompt_context, {
                "target_id": target_id,
                "title": f"Step explanation: {stage.get('label') or stage.get('stage_type')}",
                "snippet_included": bool(snippet),
                "grounding": {
                    **route_meta,
                    "target_type": target_type,
                    "step": stage.get("step", stage_index),
                    "stage_type": stage.get("stage_type"),
                    "label": stage.get("label"),
                    "file_path": stage.get("file_path"),
                    "symbol_name": stage.get("symbol_name"),
                    "class_name": stage.get("class_name"),
                    "line_start": stage.get("line_start"),
                    "line_end": stage.get("line_end"),
                    "confidence": stage.get("confidence"),
                    "is_inferred": self._stage_is_inferred(stage),
                    "provenance": stage.get("provenance"),
                    "warnings": warnings,
                },
            }

        if target_type == "sequence_step":
            if not sequence:
                raise ExplanationUnavailableError("Stored route sequence is unavailable for this route")
            if not message_id:
                raise ExplanationUnavailableError("message_id is required for sequence_step explanations")
            message, message_index = self._find_sequence_message(sequence=sequence, message_id=message_id)
            related_stage = self._resolve_related_stage(request_flow=request_flow, message=message)
            snippet = self._snippet_for_anchor(project_id=project_id, anchor=self._message_anchor(message), db=db)
            warnings = list((sequence.get("metadata") or {}).get("warnings") or [])
            prompt_context = {
                "target_type": target_type,
                "route": route_meta,
                "sequence": self._sequence_summary(sequence),
                "selected_message": self._message_summary(sequence, message),
                "previous_message": self._neighbor_message_summary(sequence, message_index - 1),
                "next_message": self._neighbor_message_summary(sequence, message_index + 1),
                "related_request_flow_stage": self._stage_summary(related_stage) if related_stage else None,
                "warnings": warnings,
                "code_snippet": snippet,
            }
            return prompt_context, {
                "target_id": str(message.get("id")),
                "title": f"Sequence step explanation: {message.get('label') or 'step'}",
                "snippet_included": bool(snippet),
                "grounding": {
                    **route_meta,
                    "target_type": target_type,
                    "message_id": message.get("id"),
                    "step": message.get("step"),
                    "message_type": message.get("message_type"),
                    "label": message.get("label"),
                    "file_path": message.get("file_path"),
                    "symbol_name": message.get("symbol_name"),
                    "class_name": message.get("class_name"),
                    "line_start": message.get("line_start"),
                    "line_end": message.get("line_end"),
                    "confidence": message.get("confidence"),
                    "is_inferred": bool(message.get("is_inferred")),
                    "provenance": message.get("provenance"),
                    "sequence_source": (sequence.get("metadata") or {}).get("sequence_source"),
                    "warnings": warnings,
                },
            }

        raise ExplanationUnavailableError(f"Unsupported explanation target: {target_type}")

    def _build_fallback_explanation(self, *, target_type: str, prompt_context: dict[str, Any]) -> dict[str, Any]:
        evidence_used = self._fallback_evidence(prompt_context)
        if target_type == "route":
            request_flow = prompt_context.get("request_flow") or {}
            analysis = prompt_context.get("analysis") or {}
            stage_count = request_flow.get("stage_count") or 0
            route = prompt_context.get("route") or {}
            warnings = prompt_context.get("warnings") or []
            summary = (
                f"{route.get('method', 'GET')} {route.get('path', '/')} is grounded to {stage_count} request-flow step"
                f"{'s' if stage_count != 1 else ''}. The flow centers on {self._route_focus_phrase(request_flow=request_flow, analysis=analysis)}."
            )
            return {
                "summary": summary,
                "why_it_matters": "This explains where the route hands work off, which is usually the fastest way to trace ownership, dependencies, and side effects.",
                "what_could_fail": self._route_failure_note(request_flow=request_flow, analysis=analysis, warnings=warnings),
                "confidence_note": self._route_confidence_note(prompt_context),
                "evidence_used": evidence_used,
            }

        if target_type == "request_flow_step":
            stage = prompt_context.get("selected_stage") or {}
            return {
                "summary": self._stage_summary_text(stage),
                "why_it_matters": self._stage_importance_text(stage),
                "what_could_fail": self._stage_failure_text(stage, prompt_context.get("warnings") or []),
                "confidence_note": self._stage_confidence_note(stage),
                "evidence_used": evidence_used,
            }

        message = prompt_context.get("selected_message") or {}
        sequence = prompt_context.get("sequence") or {}
        return {
            "summary": self._message_summary_text(message),
            "why_it_matters": self._message_importance_text(message),
            "what_could_fail": self._message_failure_text(message, prompt_context.get("warnings") or []),
            "confidence_note": self._message_confidence_note(message, sequence),
            "evidence_used": evidence_used,
        }

    @staticmethod
    def _route_focus_phrase(*, request_flow: dict[str, Any], analysis: dict[str, Any]) -> str:
        summary = request_flow.get("summary") or {}
        if summary.get("has_external"):
            return "internal service work plus an external dependency"
        if summary.get("has_repository") or summary.get("has_data_access") or analysis.get("has_database"):
            return "handler logic with a data-access hop"
        if summary.get("has_service"):
            return "handler logic that hands off into a service layer"
        return "the grounded handler path that is currently visible"

    @staticmethod
    def _route_failure_note(*, request_flow: dict[str, Any], analysis: dict[str, Any], warnings: list[str]) -> str:
        summary = request_flow.get("summary") or {}
        if summary.get("has_external"):
            return "External calls can fail independently of the handler, so upstream timeouts or API errors may break the route even when local code is healthy."
        if summary.get("has_repository") or summary.get("has_data_access") or analysis.get("has_database"):
            return "The route depends on a persistence step, so query errors, missing records, or write failures can break the request path."
        if warnings:
            return f"The flow already carries a degraded warning: {warnings[0]}"
        return "If a hidden intermediate step exists, this explanation intentionally stops at the grounded boundary instead of guessing past it."

    def _route_confidence_note(self, prompt_context: dict[str, Any]) -> str:
        request_flow = prompt_context.get("request_flow") or {}
        warnings = prompt_context.get("warnings") or []
        confidence = request_flow.get("confidence")
        inferred_steps = request_flow.get("inferred_steps") or 0
        if warnings:
            return f"This explanation is bounded by the recorded warning: {warnings[0]}"
        if inferred_steps:
            return f"{inferred_steps} step{'s are' if inferred_steps != 1 else ' is'} inferred, so the explanation stays cautious about exact control flow."
        if isinstance(confidence, (int, float)):
            return f"The route-level request flow confidence is {confidence:.2f}."
        return "Confidence is limited to the deterministic artifacts attached to this route."

    @staticmethod
    def _stage_summary_text(stage: dict[str, Any]) -> str:
        label = stage.get("label") or stage.get("stage_type") or "step"
        stage_type = str(stage.get("stage_type") or "step").replace("_", " ")
        return f"This {stage_type} step centers on {label} and marks one grounded transition in the route flow."

    @staticmethod
    def _stage_importance_text(stage: dict[str, Any]) -> str:
        stage_type = stage.get("stage_type")
        if stage_type in {"auth", "validation", "middleware"}:
            return "It matters because it can stop invalid or unauthorized requests before deeper application work starts."
        if stage_type in {"repository", "data_access"}:
            return "It matters because this is where the route touches persisted state, which usually drives downstream correctness and user-visible results."
        if stage_type == "external":
            return "It matters because the route is leaving the local code path and depending on another system."
        if stage_type == "response":
            return "It matters because it shapes what the client finally receives."
        return "It matters because this is one of the grounded control-flow handoffs that explains where the request actually goes next."

    def _stage_failure_text(self, stage: dict[str, Any], warnings: list[str]) -> str:
        stage_type = stage.get("stage_type")
        if stage_type in {"auth", "validation", "middleware"}:
            return "Bad inputs, missing credentials, or failing guard logic can stop the request at this point."
        if stage_type in {"repository", "data_access"}:
            return "Query failures, missing data, or write conflicts can cause the request path to fail here."
        if stage_type == "external":
            return "Network issues, upstream errors, or schema mismatches from the remote system can break this step."
        if warnings:
            return f"This step sits inside a degraded flow: {warnings[0]}"
        return "If this step is only partially grounded, missing intermediate work is intentionally left unspecified."

    @staticmethod
    def _stage_confidence_note(stage: dict[str, Any]) -> str:
        if stage.get("is_inferred"):
            return "This step is inferred from deterministic evidence, so the explanation preserves uncertainty about the exact implementation boundary."
        confidence = stage.get("confidence")
        if isinstance(confidence, (int, float)):
            return f"This step carries confidence {confidence:.2f} and is explained only from its recorded anchor and neighboring stages."
        return "This step is explained only from its recorded deterministic anchor."

    @staticmethod
    def _message_summary_text(message: dict[str, Any]) -> str:
        return (
            f"This sequence step shows {message.get('from_label', 'one participant')} calling "
            f"{message.get('to_label', 'another participant')} for {message.get('label') or 'the recorded action'}."
        )

    @staticmethod
    def _message_importance_text(message: dict[str, Any]) -> str:
        if message.get("source_stage_type") in {"repository", "data_access"}:
            return "It matters because it captures the persistence boundary in the sequence, which is often the highest-risk side effect in the route."
        if message.get("source_stage_type") == "external":
            return "It matters because it makes the external dependency explicit in the sequence instead of hiding it inside the handler."
        return "It matters because it records an actual handoff between participants, which is the point of the sequence view."

    def _message_failure_text(self, message: dict[str, Any], warnings: list[str]) -> str:
        if message.get("source_stage_type") == "external":
            return "This handoff can fail if the remote dependency is unavailable, slow, or returns an unexpected response."
        if message.get("source_stage_type") in {"repository", "data_access"}:
            return "This handoff can fail if the underlying data operation errors or returns an unexpected shape."
        if warnings:
            return f"The sequence metadata already flags a degraded condition: {warnings[0]}"
        return "If earlier or later steps are not grounded, this explanation deliberately avoids filling those gaps with guesses."

    @staticmethod
    def _message_confidence_note(message: dict[str, Any], sequence: dict[str, Any]) -> str:
        if message.get("is_inferred"):
            return "This sequence step is inferred, so the explanation is limited to the recorded participants and stage metadata."
        confidence = message.get("confidence")
        if isinstance(confidence, (int, float)):
            return f"This sequence step carries confidence {confidence:.2f} and inherits sequence source {sequence.get('sequence_source') or 'unknown'}."
        return "This sequence step is explained from the stored sequence metadata only."

    def _fallback_evidence(self, prompt_context: dict[str, Any]) -> list[str]:
        evidence: list[str] = []
        route = prompt_context.get("route") or {}
        if route.get("method") and route.get("path"):
            evidence.append(f"{route['method']} {route['path']}")
        for key in ("selected_stage", "selected_message"):
            item = prompt_context.get(key) or {}
            label = item.get("label")
            if label:
                evidence.append(str(label))
            file_path = item.get("file_path")
            if file_path:
                evidence.append(str(file_path))
        request_flow = prompt_context.get("request_flow") or {}
        for stage in request_flow.get("stages") or []:
            label = stage.get("label")
            if label:
                evidence.append(str(label))
            if len(evidence) >= _MAX_EVIDENCE_ITEMS:
                break
        warnings = prompt_context.get("warnings") or []
        if warnings:
            evidence.append(str(warnings[0]))
        deduped: list[str] = []
        for item in evidence:
            if item and item not in deduped:
                deduped.append(item)
            if len(deduped) >= _MAX_EVIDENCE_ITEMS:
                break
        return deduped or ["deterministic route artifact"]

    @staticmethod
    def _get_latest_scan(project_id: str, db: Session) -> Optional[Scan]:
        project = db.query(Project).filter(Project.id == project_id).first()
        if project is None:
            raise ExplanationNotFoundError("Project not found")
        return (
            db.query(Scan)
            .filter(Scan.project_id == project_id)
            .order_by(Scan.created_at.desc())
            .first()
        )

    @staticmethod
    def _find_route_by_id(raw_routes: list[dict[str, Any]], route_id: str) -> Optional[dict[str, Any]]:
        for route in raw_routes:
            if not isinstance(route, dict):
                continue
            method = str(route.get("method") or "ANY").upper()
            path = str(route.get("path") or "")
            file_path = str(route.get("file") or "")
            if make_route_id(method, path, file_path) == route_id:
                return dict(route)
        return None

    def _load_route_analysis(self, *, project_id: str, route_id: str, route: dict[str, Any], db: Session) -> tuple[Optional[dict[str, Any]], str]:
        record = (
            db.query(RouteAnalysis)
            .filter(
                RouteAnalysis.project_id == project_id,
                RouteAnalysis.route_id == route_id,
            )
            .first()
        )
        if record and isinstance(record.analysis_data, dict):
            analysis = ensure_route_analysis_signature(dict(record.analysis_data))
            if not analysis.get("request_flow") and route.get("request_flow"):
                analysis["request_flow"] = dict(route.get("request_flow") or {})
            return analysis, "stored_route_analysis"
        if route.get("request_flow"):
            return build_route_analysis_from_route(route), "derived_from_request_flow"
        return None, "none"

    @staticmethod
    def _preferred_request_flow(route: dict[str, Any], analysis: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        candidates = [route.get("request_flow"), (analysis or {}).get("request_flow")]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("stages"):
                return dict(candidate)
        return None

    @staticmethod
    def _load_route_sequence(project_id: str, route_id: str, db: Session) -> Optional[dict[str, Any]]:
        record = (
            db.query(SequenceDiagram)
            .filter(
                SequenceDiagram.project_id == project_id,
                SequenceDiagram.route_id == route_id,
            )
            .order_by(SequenceDiagram.created_at.desc())
            .first()
        )
        if record and isinstance(record.diagram_data, dict):
            return dict(record.diagram_data)
        return None

    def _find_request_flow_stage(self, request_flow: dict[str, Any], stage_step: int) -> tuple[dict[str, Any], int]:
        stages = [stage for stage in request_flow.get("stages") or [] if isinstance(stage, dict)]
        for index, stage in enumerate(stages):
            if stage.get("step") == stage_step:
                return stage, index
        if 0 <= stage_step < len(stages):
            return stages[stage_step], stage_step
        if 1 <= stage_step <= len(stages):
            return stages[stage_step - 1], stage_step - 1
        raise ExplanationNotFoundError("Request-flow step not found")

    def _find_sequence_message(self, *, sequence: dict[str, Any], message_id: str) -> tuple[dict[str, Any], int]:
        messages = [message for message in sequence.get("messages") or [] if isinstance(message, dict)]
        for index, message in enumerate(messages):
            if message.get("id") == message_id:
                return message, index
        raise ExplanationNotFoundError("Sequence step not found")

    def _resolve_related_stage(self, *, request_flow: Optional[dict[str, Any]], message: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not request_flow:
            return None
        source_stage_step = message.get("source_stage_step")
        if source_stage_step is None:
            return None
        try:
            stage, _stage_index = self._find_request_flow_stage(request_flow, int(source_stage_step))
        except (ExplanationNotFoundError, TypeError, ValueError):
            return None
        return stage

    def _request_flow_summary(self, request_flow: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not request_flow:
            return None
        stages = [self._stage_summary(stage) for stage in (request_flow.get("stages") or [])[:_MAX_ROUTE_STAGES] if isinstance(stage, dict)]
        inferred_steps = sum(1 for stage in request_flow.get("stages") or [] if isinstance(stage, dict) and self._stage_is_inferred(stage))
        return {
            "stage_count": int(request_flow.get("stage_count") or len(request_flow.get("stages") or [])),
            "confidence": request_flow.get("confidence"),
            "summary": dict(request_flow.get("summary") or {}),
            "inferred_steps": inferred_steps,
            "stages": stages,
        }

    @staticmethod
    def _analysis_summary(analysis: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not analysis:
            return None
        participants = [
            {
                "label": participant.get("label"),
                "type": participant.get("type"),
            }
            for participant in (analysis.get("participants") or [])[:6]
            if isinstance(participant, dict)
        ]
        return {
            "complexity": analysis.get("complexity"),
            "has_database": bool(analysis.get("has_database")),
            "has_external": bool(analysis.get("has_external")),
            "has_filesystem": bool(analysis.get("has_filesystem")),
            "participants": participants,
        }

    def _sequence_summary(self, sequence: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(sequence.get("metadata") or {})
        return {
            "route_id": sequence.get("route_id"),
            "sequence_source": metadata.get("sequence_source"),
            "warnings": list(metadata.get("warnings") or []),
            "degraded": bool(metadata.get("degraded")),
            "step_count": metadata.get("step_count"),
            "request_flow_stage_count": metadata.get("request_flow_stage_count"),
            "request_flow_confidence": metadata.get("request_flow_confidence"),
        }

    def _stage_summary(self, stage: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not stage:
            return None
        return {
            "step": stage.get("step"),
            "stage_type": stage.get("stage_type"),
            "label": stage.get("label"),
            "file_path": stage.get("file_path"),
            "symbol_name": stage.get("symbol_name"),
            "class_name": stage.get("class_name"),
            "line_start": stage.get("line_start"),
            "line_end": stage.get("line_end"),
            "confidence": stage.get("confidence"),
            "is_inferred": self._stage_is_inferred(stage),
            "provenance": stage.get("provenance"),
            "anchor_kind": stage.get("anchor_kind"),
            "selection_reason": stage.get("selection_reason"),
        }

    def _neighbor_stage_summary(self, request_flow: dict[str, Any], index: int) -> Optional[dict[str, Any]]:
        stages = [stage for stage in request_flow.get("stages") or [] if isinstance(stage, dict)]
        if index < 0 or index >= len(stages):
            return None
        return self._stage_summary(stages[index])

    @staticmethod
    def _participant_labels(sequence: dict[str, Any]) -> dict[str, str]:
        labels: dict[str, str] = {}
        for participant in sequence.get("participants") or []:
            if not isinstance(participant, dict):
                continue
            participant_id = participant.get("id")
            label = participant.get("label")
            if participant_id and label:
                labels[str(participant_id)] = str(label)
        return labels

    def _message_summary(self, sequence: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
        labels = self._participant_labels(sequence)
        return {
            "id": message.get("id"),
            "step": message.get("step"),
            "label": message.get("label"),
            "message_type": message.get("message_type"),
            "from_label": labels.get(str(message.get("from_participant")), str(message.get("from_participant") or "unknown")),
            "to_label": labels.get(str(message.get("to_participant")), str(message.get("to_participant") or "unknown")),
            "source_stage_step": message.get("source_stage_step"),
            "source_stage_type": message.get("source_stage_type"),
            "file_path": message.get("file_path"),
            "symbol_name": message.get("symbol_name"),
            "class_name": message.get("class_name"),
            "line_start": message.get("line_start"),
            "line_end": message.get("line_end"),
            "confidence": message.get("confidence"),
            "is_inferred": bool(message.get("is_inferred")),
            "provenance": message.get("provenance"),
        }

    def _neighbor_message_summary(self, sequence: dict[str, Any], index: int) -> Optional[dict[str, Any]]:
        messages = [message for message in sequence.get("messages") or [] if isinstance(message, dict)]
        if index < 0 or index >= len(messages):
            return None
        return self._message_summary(sequence, messages[index])

    def _route_warnings(self, *, request_flow: Optional[dict[str, Any]], analysis_source: str) -> list[str]:
        warnings: list[str] = []
        if not request_flow:
            warnings.append("No deterministic request_flow is attached to this route.")
        elif any(self._stage_is_inferred(stage) for stage in request_flow.get("stages") or [] if isinstance(stage, dict)):
            warnings.append("At least one request-flow step is inferred from deterministic evidence instead of a direct handler anchor.")
        if analysis_source == "stored_route_analysis":
            warnings.append("The explanation uses stored route analysis plus deterministic route metadata.")
        return warnings

    @staticmethod
    def _stage_is_inferred(stage: dict[str, Any]) -> bool:
        provenance = str(stage.get("provenance") or "")
        if stage.get("is_inferred") is not None:
            return bool(stage.get("is_inferred"))
        return provenance not in _DIRECT_PROVENANCE

    @staticmethod
    def _stage_anchor(stage: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not stage:
            return None
        code_anchor = dict(stage.get("code_anchor") or stage.get("evidence") or {})
        return {
            "file_path": stage.get("file_path") or code_anchor.get("file_path"),
            "symbol_name": stage.get("symbol_name") or code_anchor.get("symbol_name"),
            "class_name": stage.get("class_name") or code_anchor.get("class_name"),
            "line_start": stage.get("line_start") or code_anchor.get("line_start"),
            "line_end": stage.get("line_end") or code_anchor.get("line_end"),
        }

    @staticmethod
    def _message_anchor(message: dict[str, Any]) -> Optional[dict[str, Any]]:
        code_anchor = dict(message.get("code_anchor") or message.get("best_target") or {})
        return {
            "file_path": message.get("file_path") or code_anchor.get("file_path"),
            "symbol_name": message.get("symbol_name") or code_anchor.get("symbol_name"),
            "class_name": message.get("class_name") or code_anchor.get("class_name"),
            "line_start": message.get("line_start") or code_anchor.get("line_start"),
            "line_end": message.get("line_end") or code_anchor.get("line_end"),
        }

    def _snippet_for_anchor(self, *, project_id: str, anchor: Optional[dict[str, Any]], db: Session) -> Optional[dict[str, Any]]:
        if not anchor or not anchor.get("file_path"):
            return None
        try:
            retrieval_context = _load_retrieval_context(project_id=project_id, db=db)
            resolved_path = _resolve_file_reference(
                workspace_root=retrieval_context.workspace.workspace_root,
                raw_path=str(anchor.get("file_path")),
                source_root_kind="source_relative",
            )
            if resolved_path is None or not resolved_path.is_file():
                return None
            snippet = _extract_snippet(
                resolved_path,
                line_start=anchor.get("line_start"),
                line_end=anchor.get("line_end"),
                symbol_name=anchor.get("symbol_name"),
            )
            if snippet is None:
                return None
            text = snippet.get("text") or ""
            line_count = len(text.splitlines())
            truncated = bool(snippet.get("truncated"))
            if line_count > _MAX_SNIPPET_LINES:
                text = "\n".join(text.splitlines()[:_MAX_SNIPPET_LINES])
                truncated = True
            if len(text) > _MAX_SNIPPET_CHARS:
                text = text[:_MAX_SNIPPET_CHARS]
                truncated = True
            return {
                "file_path": anchor.get("file_path"),
                "symbol_name": anchor.get("symbol_name"),
                "line_start": snippet.get("requested_line_start"),
                "line_end": snippet.get("requested_line_end"),
                "language": _detect_language(resolved_path),
                "snippet_text": text,
                "truncated": truncated,
            }
        except Exception as exc:
            logger.warning("Failed to resolve explanation snippet for project %s: %s", project_id, exc)
            return None


explanation_builder = ExplanationBuilder()