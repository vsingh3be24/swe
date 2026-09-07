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


def test_institution_split_finalsay_beats_naive_page_change():
    """On the institution split (which includes cue and naturalistic phrasings)
    FinalSay should clearly out-perform the naive page_change baseline on F1,
    guarding against a broken pipeline."""
    results = evaluate("institution", "mock")
    finalsay_f1 = results["systems"]["finalsay"]["relationship"]["f1"]
    page_change_f1 = results["systems"]["page_change"]["relationship"]["f1"]
    assert finalsay_f1 > page_change_f1
