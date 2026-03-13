from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.explanation_builder import ExplanationNotFoundError, ExplanationUnavailableError, explanation_builder

router = APIRouter(prefix="/projects/{project_id}/explanations", tags=["explanations"])


class ExplanationRequest(BaseModel):
    target_type: Literal["route", "request_flow_step", "sequence_step"]
    route_id: str = Field(min_length=1)
    stage_step: Optional[int] = None
    message_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_target(self) -> "ExplanationRequest":
        if self.target_type == "request_flow_step" and self.stage_step is None:
            raise ValueError("stage_step is required for request_flow_step explanations")
        if self.target_type == "sequence_step" and not self.message_id:
            raise ValueError("message_id is required for sequence_step explanations")
        return self


class ExplanationContent(BaseModel):
    summary: str
    why_it_matters: str
    what_could_fail: str
    confidence_note: str
    evidence_used: list[str]


class ExplanationGeneratedFrom(BaseModel):
    status: str
    model: str
    llm_enabled: bool
    prompt_char_count: int
    snippet_included: bool
    fallback_reason: Optional[str] = None
    generated_at: str


class ExplanationResponse(BaseModel):
    target_type: str
    target_id: str
    title: str
    explanation: ExplanationContent
    grounding: dict[str, Any]
    generated_from: ExplanationGeneratedFrom


@router.post("", response_model=ExplanationResponse)
def generate_explanation(project_id: str, body: ExplanationRequest, db: Session = Depends(get_db)):
    try:
        return explanation_builder.explain(
            project_id=project_id,
            route_id=body.route_id,
            target_type=body.target_type,
            stage_step=body.stage_step,
            message_id=body.message_id,
            db=db,
        )
    except ExplanationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExplanationUnavailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc