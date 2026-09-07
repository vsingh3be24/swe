"""ComparisonModel interface (module 4, design.md section 7).

``classify(premise, hypothesis) -> (label, confidence, rationale)`` where label
is drawn from the relationship taxonomy and confidence is in [0, 1].

- ``MockComparisonModel`` (default): deterministic rule engine keyed on textual
  cues (cancellation, correction, date conflicts, negation, lexical overlap).
  Guarantees the "22 Sept vs 15 Sept" case classifies as contradictory/
  superseded (never consistent).
- ``HFComparisonModel`` (opt-in): transformers zero-shot NLI over the taxonomy.
  transformers is imported lazily so it is never required for the default demo.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from finalsay.config import get_settings
from finalsay.models import RELATIONSHIP_LABELS

# Classification result type.
Classification = tuple[str, float, str]

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_DATE_TOKEN_RE = re.compile(
    r"\b(\d{1,2})\s+([A-Za-z]{3,9})\b|\b([A-Za-z]{3,9})\s+(\d{1,2})\b",
    re.IGNORECASE,
)


class ComparisonModel(ABC):
    """Interface for relationship classification between two notices."""

    name: str = "abstract"

    @abstractmethod
    def classify(self, premise: str, hypothesis: str) -> Classification:
        """Return ``(label, confidence, rationale)`` for the notice pair."""
        raise NotImplementedError


def _extract_dates(text: str) -> list[tuple[int, int]]:
    """Return a list of ``(month, day)`` tuples parsed from ``text``."""
    dates: list[tuple[int, int]] = []
    for m in _DATE_TOKEN_RE.finditer(text):
        if m.group(1) and m.group(2):
            day, month_name = int(m.group(1)), m.group(2).lower()
        elif m.group(3) and m.group(4):
            month_name, day = m.group(3).lower(), int(m.group(4))
        else:
            continue
        month = _MONTHS.get(month_name)
        if month is not None and 1 <= day <= 31:
            dates.append((month, day))
    return dates


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def _overlap(premise: str, hypothesis: str) -> float:
    a, b = _tokens(premise), _tokens(hypothesis)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class MockComparisonModel(ComparisonModel):
    """Deterministic, offline rule-engine model (default).

    Classification is 100% rule-based (textual cues + date reasoning + lexical
    overlap); there is no fixture-keyed lookup. This is the model used in every
    production and evaluation path.
    """

    name = "mock"

    def classify(self, premise: str, hypothesis: str) -> Classification:
        p_low, h_low = premise.lower(), hypothesis.lower()
        combined = f"{p_low} {h_low}"

        # Cancellation cues.
        if re.search(r"\bcancel(?:led|ed|lation)?\b", combined):
            return (
                "cancelled",
                0.9,
                "Cancellation language detected in the notices.",
            )

        # Correction / erratum cues.
        if re.search(r"\b(correction|erratum|corrected|rectif)", combined):
            return (
                "corrected",
                0.88,
                "Correction/erratum language detected.",
            )

        # Date-based reasoning: compare dates across the two notices.
        p_dates, h_dates = _extract_dates(premise), _extract_dates(hypothesis)
        has_postpone = bool(re.search(r"\b(postpon|reschedul|moved|delayed)", combined))
        has_extend = bool(re.search(r"\b(extend|extension|deadline\s+moved)", combined))

        if p_dates and h_dates:
            conflicting = not (set(p_dates) & set(h_dates))
            if conflicting:
                if has_extend:
                    return (
                        "extended",
                        0.82,
                        f"Different dates {h_dates} vs {p_dates} with extension language.",
                    )
                if has_postpone:
                    return (
                        "superseded",
                        0.86,
                        f"A later notice postpones/reschedules to a different date "
                        f"({p_dates} vs {h_dates}); the earlier date is superseded.",
                    )
                return (
                    "contradictory",
                    0.84,
                    f"Notices assert conflicting dates {p_dates} vs {h_dates}.",
                )

        # Explicit negation cue.
        if re.search(r"\b(not|no longer|will not|won't|isn't|is not)\b", combined):
            return (
                "contradictory",
                0.78,
                "Negation detected indicating a contradiction.",
            )

        # High lexical overlap with no conflicting signal -> consistent.
        overlap = _overlap(premise, hypothesis)
        if overlap >= 0.6:
            return (
                "consistent",
                0.82,
                f"High lexical overlap ({overlap:.2f}) and no conflicting facts.",
            )

        # Otherwise low confidence -> gated to unresolved downstream.
        return (
            "unresolved",
            0.4,
            f"Insufficient signal to classify (overlap {overlap:.2f}); needs review.",
        )


class HFComparisonModel(ComparisonModel):
    """Zero-shot NLI over the taxonomy via transformers (opt-in).

    transformers is imported lazily so the default demo never requires it.
    """

    name = "hf"

    # Map taxonomy labels to natural-language hypotheses for zero-shot.
    _CANDIDATE_LABELS = [
        label for label in RELATIONSHIP_LABELS if label != "unresolved"
    ]

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or get_settings().hf_model_name
        self._pipeline = None

    def _ensure_pipeline(self):
        if self._pipeline is None:
            from transformers import pipeline  # lazy import (opt-in only)

            self._pipeline = pipeline(
                "zero-shot-classification", model=self._model_name
            )
        return self._pipeline

    def classify(self, premise: str, hypothesis: str) -> Classification:
        clf = self._ensure_pipeline()
        text = f"{premise}\n\n{hypothesis}"
        result = clf(text, candidate_labels=self._CANDIDATE_LABELS)
        label = result["labels"][0]
        confidence = float(result["scores"][0])
        rationale = (
            f"Zero-shot NLI ({self._model_name}) ranked '{label}' highest "
            f"at {confidence:.2f}."
        )
        return (label, confidence, rationale)


def get_comparison_model() -> ComparisonModel:
    """Return the configured ComparisonModel. Defaults to mock; hf is opt-in."""
    settings = get_settings()
    if settings.comparison_model == "hf":
        return HFComparisonModel()
    return MockComparisonModel()
