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
- Cohen's kappa (from the seeded two-annotator benchmark),
- time-to-identify-applicable-notice (scope note section 5, see below).

Time-to-identify proxy (HONEST caveat - this is a PROXY, not a live-user timing):
    There is no live user in this offline deterministic harness, so
    "time-to-identify" is modelled as a *scan cost*: the number of notices a
    student would have to read before reaching the applicable official notice
    (the one referenced by each held-out pair's ``official_external_id``).

    - A CHRONOLOGICAL feed lists an institution's official notices newest-first.
      A student scanning that feed reads notices until reaching the applicable
      one, so the scan cost is that notice's 1-based rank in the institution's
      reverse-chronological official feed (derived deterministically from the
      officials' dates via ``models_iface.comparison_model._extract_dates`` on
      the ``gold_date`` field). This is the ``chronological`` baseline's cost.
    - The ``page_change``, ``nli`` and ``prompted_llm`` baselines also present a
      chronological-style feed (they classify a notice against whatever the
      student is already looking at; they do not retrieve the applicable
      official), so they INHERIT the same chronological scan cost. This choice
      is documented rather than hand-waved: none of them ranks the applicable
      official higher than recency does.
    - FinalSay is assigned a scan cost of 1 under an explicit IDEALIZATION:
      that its candidate retrieval surfaces the applicable official at rank 1.
      This is an assumption of PERFECT retrieval, NOT a measured value. This
      offline harness does not measure retrieval recall or rank -- it never
      calls ``services.comparison.retrieve_candidates`` for this metric and
      takes the applicable official directly from each pair's gold pairing. Real
      retrieval can rank the applicable official below 1 or miss it, so the
      reported FinalSay cost (and the saving ratio) are best-case figures under
      the perfect-retrieval assumption, not an empirical retrieval result.

    We aggregate as the MEAN scan cost over the held-out pairs (lower is better)
    and also report ``saving_ratio_vs_chronological`` = chronological_mean /
    system_mean, quantifying the "saves the student time" claim under the same
    idealization. No wall-clock timing is claimed; it is a rank-position proxy
    only, and FinalSay's value assumes ideal retrieval (recall/rank unmeasured).

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


def _chronological_rank(official_ext_id: str, officials: dict) -> int:
    """1-based rank of the applicable official in its institution's newest-first feed.

    The institution is derived from the official's ``external_id`` prefix (e.g.
    ``northgate-exam-00`` -> ``northgate``). The feed is the institution's
    officials sorted by parsed date descending (newest first); ties broken by
    external_id descending for determinism. Returns the number of notices a
    student would scan before reaching the applicable one. Falls back to 1 when
    the official is unknown (no feed to scan).
    """
    from finalsay.models_iface.comparison_model import _extract_dates

    target = officials.get(official_ext_id)
    if target is None:
        return 1
    slug = official_ext_id.split("-", 1)[0]

    def _sort_key(rec: dict) -> tuple[tuple[int, int], str]:
        dates = _extract_dates(rec.get("gold_date") or rec.get("text") or "")
        latest = max(dates) if dates else (0, 0)
        return (latest, rec["external_id"])

    feed = [
        rec
        for ext, rec in officials.items()
        if ext.split("-", 1)[0] == slug
    ]
    feed.sort(key=_sort_key, reverse=True)
    for position, rec in enumerate(feed, start=1):
        if rec["external_id"] == official_ext_id:
            return position
    return 1


def time_to_identify(held_out: list[dict], officials: dict, system_name: str) -> dict:
    """Proxy 'time-to-identify-applicable-notice' scan cost for one system.

    Returns ``{"mean_scan_cost": float, "saving_ratio_vs_chronological": float}``.

    - ``finalsay`` is assigned a scan cost of 1.0 per pair as an IDEALIZATION
      assuming perfect retrieval (the applicable official surfaced at rank 1).
      Retrieval recall/rank is NOT measured in this offline harness, so this is
      a best-case assumption, not an empirical value.
    - ``chronological`` and the other chronological-style baselines
      (``page_change``, ``nli``, ``prompted_llm``) scan the reverse-chronological
      feed, so the scan cost is the applicable official's 1-based rank in it.

    ``saving_ratio_vs_chronological`` is chronological_mean / this_mean (>= 1.0
    means this system reaches the applicable notice at least as fast as scanning
    the chronological feed). It is a proxy only — no live-user timing (see the
    module docstring).
    """
    if not held_out:
        return {"mean_scan_cost": 0.0, "saving_ratio_vs_chronological": 1.0}

    if system_name == "finalsay":
        # IDEALIZATION: assumes perfect retrieval (applicable official at rank
        # 1). Retrieval recall/rank is not measured in this offline harness, so
        # 1.0 is a best-case assumption, not a measured value.
        costs = [1.0 for _ in held_out]
    else:
        costs = [
            float(_chronological_rank(g["official_external_id"], officials))
            for g in held_out
        ]
    mean_cost = sum(costs) / len(costs)

    chrono_costs = [
        float(_chronological_rank(g["official_external_id"], officials))
        for g in held_out
    ]
    chrono_mean = sum(chrono_costs) / len(chrono_costs)
    if mean_cost <= 0.0:
        saving = 1.0
    else:
        saving = chrono_mean / mean_cost
    return {
        "mean_scan_cost": mean_cost,
        "saving_ratio_vs_chronological": saving,
    }


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
    systems["finalsay"]["time_to_identify"] = time_to_identify(
        holdout, officials, "finalsay"
    )

    for name, fn in baselines.BASELINES.items():
        g, p = _predict_baseline(holdout, officials, fn)
        systems[name] = _score(g, p)
        systems[name]["time_to_identify"] = time_to_identify(holdout, officials, name)

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

    print(
        "\nTime-to-identify-applicable-notice (PROXY - no live-user timing):\n"
        "  Mean scan cost = number of notices a student reads before reaching\n"
        "  the applicable official. Chronological-style feeds pay the official's\n"
        "  reverse-chronological rank. FinalSay's cost of 1 is an IDEALIZATION\n"
        "  assuming perfect retrieval (applicable official at rank 1); retrieval\n"
        "  recall/rank is NOT measured here, so FinalSay's figure and the saving\n"
        "  ratio are best-case under that assumption, not an empirical result.\n"
        "  saving_ratio = chronological_mean / system_mean (higher is better)."
    )
    t_header = f"  {'system':<14}{'mean_scan_cost':>16}{'saving_vs_chrono':>18}"
    print(t_header)
    print("  " + "-" * (len(t_header) - 2))
    chrono_mean = results["systems"]["chronological"]["time_to_identify"][
        "mean_scan_cost"
    ]
    for name, scores in results["systems"].items():
        tti = scores["time_to_identify"]
        print(
            f"  {name:<14}{tti['mean_scan_cost']:>16.3f}"
            f"{tti['saving_ratio_vs_chronological']:>18.3f}"
        )
    finalsay_mean = results["systems"]["finalsay"]["time_to_identify"][
        "mean_scan_cost"
    ]
    if finalsay_mean > 0:
        saved = chrono_mean - finalsay_mean
        print(
            f"\n  => FinalSay reaches the applicable notice in a mean of "
            f"{finalsay_mean:.3f} scans vs {chrono_mean:.3f} for a chronological\n"
            f"     feed: {saved:.3f} fewer notices scanned per case "
            f"({chrono_mean / finalsay_mean:.2f}x faster)."
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
