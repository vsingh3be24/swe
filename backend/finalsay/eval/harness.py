"""Evaluation harness CLI (module 6, design.md section 10).

Runnable as::

    python -m finalsay.eval.harness [--split temporal|institution] [--model mock|hf]

It loads the gold-labeled fixtures (writing/seeding them if needed), builds a
holdout split, and reports for the FinalSay model and each of the four
baselines:

- per-field extraction F1 (token-set F1 per field, macro-averaged),
- relationship precision / recall / F1 (sklearn, macro),
- false-confirmation rate (predicted ``consistent`` but gold is not),
- unresolved-case rate,
- Cohen's kappa (from the seeded two-annotator benchmark).

Splits: ``temporal`` holds out the latest submissions; ``institution`` holds out
one full institution (Summit). Exits 0 on success regardless of metric values.

Honesty note: the held-out (temporal_bucket==1) submissions use *naturalistic*
phrasings that are NOT engineered around the mock model's rule cues (see
``seed/dataset.py``). Relationship metrics on the held-out splits therefore
reflect real generalisation and need not be perfect. The early/training rounds
still use cue phrasings so the seeded demo shows every taxonomy label.
"""

from __future__ import annotations

import argparse
import sys

from finalsay.config import get_settings
from finalsay.eval import baselines
from finalsay.models_iface.comparison_model import (
    MockComparisonModel,
    get_comparison_model,
)
from finalsay.seed import dataset
from finalsay.seed.seed import load_gold_submissions


# --- Metric helpers -----------------------------------------------------------

def _token_set(value) -> set[str]:
    import re

    if not value:
        return set()
    return {t for t in re.findall(r"[a-z0-9]+", str(value).lower()) if t}


def token_set_f1(gold, pred) -> float:
    """Token-set F1 between a gold and predicted field value."""
    g, p = _token_set(gold), _token_set(pred)
    if not g and not p:
        return 1.0
    if not g or not p:
        return 0.0
    tp = len(g & p)
    if tp == 0:
        return 0.0
    precision = tp / len(p)
    recall = tp / len(g)
    return 2 * precision * recall / (precision + recall)


def field_extraction_f1(gold_records: list[dict], officials_by_ext: dict) -> dict:
    """Macro token-set F1 per official-notice field over the officials.

    Compares the extraction pipeline's stored fields against the gold field
    values embedded in the official fixtures.
    """
    from finalsay.services import extraction

    fields = ["issuer", "date", "deadline", "audience", "action"]
    sums = {f: 0.0 for f in fields}
    count = 0
    for record in officials_by_ext.values():
        result = extraction.extract(text=record["text"])
        gold_map = {
            "issuer": record.get("gold_issuer"),
            "date": record.get("gold_date"),
            "deadline": record.get("gold_deadline"),
            "audience": record.get("gold_audience"),
            "action": record.get("gold_action"),
        }
        for f in fields:
            sums[f] += token_set_f1(gold_map[f], result.field_value(f))
        count += 1
    per_field = {f: (sums[f] / count if count else 0.0) for f in fields}
    per_field["macro"] = sum(per_field.values()) / len(fields) if count else 0.0
    return per_field


def relationship_metrics(gold_labels: list[str], pred_labels: list[str]) -> dict:
    """Macro precision/recall/F1 via sklearn (offline, deterministic)."""
    from sklearn.metrics import precision_recall_fscore_support

    if not gold_labels:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    precision, recall, f1, _ = precision_recall_fscore_support(
        gold_labels, pred_labels, average="macro", zero_division=0
    )
    return {"precision": float(precision), "recall": float(recall), "f1": float(f1)}


def false_confirmation_rate(gold_labels: list[str], pred_labels: list[str]) -> float:
    """Fraction predicted ``consistent`` while gold was not ``consistent``."""
    if not gold_labels:
        return 0.0
    bad = sum(
        1
        for g, p in zip(gold_labels, pred_labels)
        if p == "consistent" and g != "consistent"
    )
    return bad / len(gold_labels)


def unresolved_rate(pred_labels: list[str]) -> float:
    if not pred_labels:
        return 0.0
    return sum(1 for p in pred_labels if p == "unresolved") / len(pred_labels)


def benchmark_kappa() -> float:
    """Cohen's kappa from the seeded two-annotator benchmark triples."""
    from finalsay.services.kappa import cohen_kappa

    labels_a = [t[1] for t in dataset.BENCHMARK_TRIPLES]
    labels_b = [t[2] for t in dataset.BENCHMARK_TRIPLES]
    return cohen_kappa(labels_a, labels_b)


# --- Split construction -------------------------------------------------------

def build_split(gold: list[dict], split: str) -> list[dict]:
    """Return the held-out evaluation subset for the given split."""
    if split == "institution":
        return [g for g in gold if g["institution_slug"] == dataset.HELD_OUT_SLUG]
    # temporal: hold out the latest submissions (temporal_bucket == 1).
    holdout = [g for g in gold if g.get("temporal_bucket") == 1]
    return holdout or gold


# --- Prediction ---------------------------------------------------------------

def _officials_by_ext() -> dict:
    import json
    import os

    fixtures_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "seed", "fixtures"
    )
    officials: dict[str, dict] = {}
    for inst in dataset.INSTITUTIONS:
        path = os.path.join(fixtures_dir, f"{inst['slug']}_official.json")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as handle:
            for record in json.load(handle):
                officials[record["external_id"]] = record
    return officials


def _predict_finalsay(gold: list[dict], officials: dict, model) -> tuple[list, list]:
    """Predict labels for the FinalSay ComparisonModel (with confidence gating)."""
    settings = get_settings()
    threshold = settings.confidence_threshold
    preds, golds = [], []
    for g in gold:
        official = officials.get(g["official_external_id"])
        off_text = official["text"] if official else ""
        label, confidence, _ = model.classify(off_text, g["text"])
        if confidence < threshold:
            label = "unresolved"
        preds.append(label)
        golds.append(g["gold_label"])
    return golds, preds


def _predict_baseline(gold: list[dict], officials: dict, fn) -> tuple[list, list]:
    preds, golds = [], []
    for g in gold:
        official = officials.get(g["official_external_id"])
        off_text = official["text"] if official else ""
        sample = baselines.build_sample(g["text"], off_text)
        preds.append(fn(sample))
        golds.append(g["gold_label"])
    return golds, preds


# --- Report -------------------------------------------------------------------

def evaluate(split: str, model_name: str) -> dict:
    """Run the full evaluation for one split and return a results dict."""
    gold_all = load_gold_submissions()
    officials = _officials_by_ext()
    holdout = build_split(gold_all, split)

    field_f1 = field_extraction_f1(gold_all, officials)
    kappa = benchmark_kappa()

    model = MockComparisonModel() if model_name == "mock" else get_comparison_model()

    systems: dict[str, dict] = {}

    golds, preds = _predict_finalsay(holdout, officials, model)
    systems["finalsay"] = _score(golds, preds)

    for name, fn in baselines.BASELINES.items():
        g, p = _predict_baseline(holdout, officials, fn)
        systems[name] = _score(g, p)

    return {
        "split": split,
        "model": model_name,
        "held_out_count": len(holdout),
        "field_f1": field_f1,
        "kappa": kappa,
        "systems": systems,
    }


def _score(golds: list[str], preds: list[str]) -> dict:
    rel = relationship_metrics(golds, preds)
    return {
        "relationship": rel,
        "false_confirmation_rate": false_confirmation_rate(golds, preds),
        "unresolved_rate": unresolved_rate(preds),
    }


def print_report(results: dict) -> None:
    print("=" * 72)
    print(
        f"FinalSay evaluation — split={results['split']} model={results['model']} "
        f"(held-out={results['held_out_count']})"
    )
    print("=" * 72)

    print(
        "\nNote: held-out submissions use naturalistic phrasing NOT engineered\n"
        "around the model's rule cues, so relationship metrics reflect real\n"
        "generalisation (they are not guaranteed to be perfect). For this\n"
        "safety-critical task the key metric is the false-confirmation rate:\n"
        "FinalSay's confidence gating routes ambiguous cases to a reviewer\n"
        "(higher unresolved rate) rather than wrongly confirming them."
    )

    print("\nPer-field extraction F1 (token-set, macro over officials):")
    for field, value in results["field_f1"].items():
        print(f"  {field:>10}: {value:.3f}")

    print(f"\nInter-annotator Cohen's kappa (benchmark): {results['kappa']:.3f}")

    print("\nRelationship metrics per system:")
    header = (
        f"  {'system':<14}{'precision':>10}{'recall':>9}{'f1':>8}"
        f"{'false_conf':>12}{'unresolved':>12}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, scores in results["systems"].items():
        rel = scores["relationship"]
        print(
            f"  {name:<14}{rel['precision']:>10.3f}{rel['recall']:>9.3f}"
            f"{rel['f1']:>8.3f}{scores['false_confirmation_rate']:>12.3f}"
            f"{scores['unresolved_rate']:>12.3f}"
        )
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="finalsay.eval.harness",
        description="FinalSay evaluation harness (metrics + baselines + splits).",
    )
    parser.add_argument(
        "--split",
        choices=["temporal", "institution"],
        default="temporal",
        help="Holdout split to evaluate (default: temporal).",
    )
    parser.add_argument(
        "--model",
        choices=["mock", "hf"],
        default="mock",
        help="ComparisonModel to evaluate (default: mock, offline).",
    )
    args = parser.parse_args(argv)

    results = evaluate(args.split, args.model)
    print_report(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
