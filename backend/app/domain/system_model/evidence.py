"""Evidence and confidence structures for the canonical system model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ConfidenceLabel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SourcePathKind(str, Enum):
    SOURCE_RELATIVE = "source_relative"
    ABSOLUTE = "absolute"
    LOGICAL_ROOT = "logical_root"


def confidence_label_for_score(score: float) -> ConfidenceLabel:
    if score >= 0.85:
        return ConfidenceLabel.HIGH
    if score >= 0.6:
        return ConfidenceLabel.MEDIUM
    return ConfidenceLabel.LOW


@dataclass
class Confidence:
    """Reusable confidence envelope for entities and relations."""

    score: float
    label: ConfidenceLabel
    rationale: Optional[str] = None
    evidence_count: int = 0
    signal_count: int = 0
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    producer: Optional[str] = None


@dataclass
class Evidence:
    """First-class source evidence for inferred or extracted facts.

    Purpose:
    - Points a claim back to a concrete source location or detector output.
    - Supports future Code Peek, auditability, and chatbot grounding.

    Stable ID:
    - Deterministic from source_id + file path + symbol/range + detector metadata.

    Layer:
    - Internal.
    """

    id: str
    source_id: str
    file_path: str
    path_kind: SourcePathKind = SourcePathKind.SOURCE_RELATIVE
    symbol: Optional[str] = None
    symbol_kind: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    column_start: Optional[int] = None
    column_end: Optional[int] = None
    snippet_summary: Optional[str] = None
    snippet_excerpt: Optional[str] = None
    detector_type: Optional[str] = None
    parser_type: Optional[str] = None
    rule_name: Optional[str] = None
    extraction_source: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


def make_confidence(
    score: float,
    rationale: Optional[str] = None,
    evidence_count: int = 0,
    signal_count: int = 0,
    reasons: Optional[list[str]] = None,
    signals: Optional[dict[str, Any]] = None,
    producer: Optional[str] = None,
) -> Confidence:
    safe_score = max(0.0, min(score, 1.0))
    return Confidence(
        score=safe_score,
        label=confidence_label_for_score(safe_score),
        rationale=rationale,
        evidence_count=evidence_count,
        signal_count=signal_count,
        reasons=list(reasons or ([] if rationale is None else [rationale])),
        signals=signals or {},
        producer=producer,
    )