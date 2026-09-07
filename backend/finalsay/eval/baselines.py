"""Baselines for the evaluation harness (design.md section 10).

Each baseline is a callable ``predict(sample) -> label`` over the taxonomy, so
they can be scored on the same split as the FinalSay model for comparison:

- ``chronological``: predicts by recency — if the submission looks newer than
  the official (later date / reschedule language), call it ``superseded``, else
  ``consistent``.
- ``page_change``: predicts ``superseded`` whenever the submission text differs
  from the official text, else ``consistent`` (a naive "did the page change?").
- ``nli``: an off-the-shelf-style mapping from surface cues to taxonomy labels
  (a stand-in for a generic NLI model's entail/contradict/neutral output).
- ``prompted_llm``: a prompt-style mock that recognises a slightly richer cue
  set (closest to the real MockComparisonModel but without confidence gating).

A ``sample`` is a dict with at least ``sub_text``, ``off_text`` and
``sub_dates``/``off_dates`` (lists of ``(month, day)`` tuples).
"""

from __future__ import annotations

import re

from finalsay.models_iface.comparison_model import _extract_dates

Baseline = str


def _conflicting_dates(sample: dict) -> bool:
    s, o = sample.get("sub_dates") or [], sample.get("off_dates") or []
    if not s or not o:
        return False
    return not (set(s) & set(o))


def _max_day(dates) -> tuple[int, int]:
    return max(dates) if dates else (0, 0)


def chronological(sample: dict) -> Baseline:
    """Predict by recency: a later/rescheduled submission supersedes."""
    text = f"{sample['sub_text']} {sample['off_text']}".lower()
    if _conflicting_dates(sample):
        if _max_day(sample.get("sub_dates")) > _max_day(sample.get("off_dates")):
            return "superseded"
        return "contradictory"
    if re.search(r"\b(postpon|reschedul|moved|delayed)", text):
        return "superseded"
    return "consistent"


def page_change(sample: dict) -> Baseline:
    """Predict superseded whenever the submission text changed the official."""
    sub = sample["sub_text"].strip()
    off = sample["off_text"].strip()
    return "superseded" if sub != off else "consistent"


def nli(sample: dict) -> Baseline:
    """Off-the-shelf NLI-style mapping: entail/contradict/neutral -> taxonomy."""
    text = f"{sample['sub_text']} {sample['off_text']}".lower()
    if re.search(r"\bcancel", text):
        return "cancelled"
    if re.search(r"\b(not|no longer|whereas|instead)\b", text) or _conflicting_dates(sample):
        return "contradictory"
    if re.search(r"\b(correct|erratum)", text):
        return "corrected"
    return "consistent"


def prompted_llm(sample: dict) -> Baseline:
    """Prompt-style mock recognising a richer cue set (no confidence gating)."""
    text = f"{sample['sub_text']} {sample['off_text']}".lower()
    if re.search(r"\bcancel", text):
        return "cancelled"
    if re.search(r"\b(correct|erratum|rectif)", text):
        return "corrected"
    if re.search(r"\b(extend|extension)", text):
        return "extended"
    if _conflicting_dates(sample) or re.search(r"\b(postpon|reschedul|moved)", text):
        return "superseded"
    if re.search(r"\b(not|no longer|whereas|instead)\b", text):
        return "contradictory"
    return "consistent"


BASELINES = {
    "chronological": chronological,
    "page_change": page_change,
    "nli": nli,
    "prompted_llm": prompted_llm,
}


def build_sample(sub_text: str, off_text: str) -> dict:
    """Build the feature dict a baseline consumes from two notice texts."""
    return {
        "sub_text": sub_text,
        "off_text": off_text,
        "sub_dates": _extract_dates(sub_text),
        "off_dates": _extract_dates(off_text),
    }
