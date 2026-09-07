"""Eval tests: the harness runs both splits and returns all metric keys, and
the CLI entrypoint exits 0 for both splits."""

from __future__ import annotations

from finalsay.eval import baselines
from finalsay.eval.harness import evaluate, main


def _assert_metric_shape(results: dict):
    assert "field_f1" in results
    for field in ("issuer", "date", "deadline", "audience", "action", "macro"):
        assert field in results["field_f1"]
    assert "kappa" in results

    systems = results["systems"]
    # FinalSay + all four baselines are scored on the same split.
    assert "finalsay" in systems
    for name in baselines.BASELINES:
        assert name in systems

    for scores in systems.values():
        rel = scores["relationship"]
        assert {"precision", "recall", "f1"} <= set(rel)
        assert "false_confirmation_rate" in scores
        assert "unresolved_rate" in scores
        # Sixth scope-note metric: time-to-identify-applicable-notice (proxy).
        assert "time_to_identify" in scores
        tti = scores["time_to_identify"]
        assert {"mean_scan_cost", "saving_ratio_vs_chronological"} <= set(tti)
        assert tti["mean_scan_cost"] >= 0.0


def test_evaluate_temporal_returns_all_metrics():
    results = evaluate("temporal", "mock")
    assert results["split"] == "temporal"
    assert results["held_out_count"] > 0
    _assert_metric_shape(results)


def test_evaluate_institution_returns_all_metrics():
    results = evaluate("institution", "mock")
    assert results["split"] == "institution"
    assert results["held_out_count"] > 0
    _assert_metric_shape(results)


def test_all_four_baselines_scored():
    results = evaluate("temporal", "mock")
    assert set(results["systems"]) == {"finalsay", *baselines.BASELINES.keys()}


def test_cli_main_exits_zero_both_splits():
    assert main(["--split", "temporal"]) == 0
    assert main(["--split", "institution"]) == 0


def test_finalsay_has_lowest_false_confirmation_rate():
    """The value of FinalSay's confidence gating is safety, not raw F1: on the
    held-out naturalistic split it should never falsely confirm a notice as
    ``consistent`` when it is not, and should do at least as well as the naive
    baselines on that metric. (Metrics are honest on held-out data and need not
    be perfect; see dataset.py — the held-out phrasings are not engineered
    around the model's cues.)"""
    results = evaluate("temporal", "mock")
    fcr = {
        name: scores["false_confirmation_rate"]
        for name, scores in results["systems"].items()
    }
    assert fcr["finalsay"] == 0.0
    assert fcr["finalsay"] <= min(fcr.values())


def test_time_to_identify_finalsay_at_most_chronological_both_splits():
    """The whole point of the sixth metric: FinalSay's mean scan cost to reach
    the applicable official notice must be <= the chronological baseline's on
    BOTH held-out splits (it does not do worse than scrolling a feed, and in
    practice saves the student time)."""
    for split in ("temporal", "institution"):
        results = evaluate(split, "mock")
        systems = results["systems"]
        finalsay_cost = systems["finalsay"]["time_to_identify"]["mean_scan_cost"]
        chrono_cost = systems["chronological"]["time_to_identify"]["mean_scan_cost"]
        assert finalsay_cost <= chrono_cost, (
            f"{split}: finalsay {finalsay_cost} > chronological {chrono_cost}"
        )
        # The other chronological-style baselines inherit the chronological cost.
        for name in ("page_change", "nli", "prompted_llm"):
            assert (
                systems[name]["time_to_identify"]["mean_scan_cost"] == chrono_cost
            )
        # Saving ratio is reported and >= 1.0 for finalsay (at least as fast).
        assert (
            systems["finalsay"]["time_to_identify"]["saving_ratio_vs_chronological"]
            >= 1.0
        )


def test_institution_split_finalsay_beats_naive_page_change():
    """On the institution split (which includes cue and naturalistic phrasings)
    FinalSay should clearly out-perform the naive page_change baseline on F1,
    guarding against a broken pipeline."""
    results = evaluate("institution", "mock")
    finalsay_f1 = results["systems"]["finalsay"]["relationship"]["f1"]
    page_change_f1 = results["systems"]["page_change"]["relationship"]["f1"]
    assert finalsay_f1 > page_change_f1
