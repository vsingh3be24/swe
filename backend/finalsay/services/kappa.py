"""Cohen's kappa (module 5, design.md section 8).

Cohen's kappa measures inter-annotator agreement corrected for chance:

    kappa = (p_o - p_e) / (1 - p_e)

where ``p_o`` is the observed agreement and ``p_e`` is the agreement expected
by chance from each annotator's marginal label distribution.

We prefer sklearn's implementation when a matching set of paired labels is
available (design.md section 10 asks for sklearn-based metrics) and fall back
to a dependency-free implementation otherwise.
"""

from __future__ import annotations

from collections import Counter


def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    """Return Cohen's kappa for two equal-length lists of categorical labels.

    Returns ``0.0`` when there is nothing to compare (fewer than one paired
    item). When observed and expected agreement are both perfect (e.g. a single
    constant label), returns ``1.0``.
    """
    if len(labels_a) != len(labels_b):
        raise ValueError("annotator label lists must be the same length")
    n = len(labels_a)
    if n == 0:
        return 0.0

    try:
        from sklearn.metrics import cohen_kappa_score

        categories = sorted(set(labels_a) | set(labels_b))
        if len(categories) < 2:
            # sklearn returns NaN for a single class; agreement is perfect here.
            return 1.0 if labels_a == labels_b else 0.0
        return float(cohen_kappa_score(labels_a, labels_b))
    except Exception:  # noqa: BLE001 - fall back to the manual computation
        return _manual_cohen_kappa(labels_a, labels_b)


def _manual_cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    n = len(labels_a)
    observed = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / n

    count_a = Counter(labels_a)
    count_b = Counter(labels_b)
    categories = set(count_a) | set(count_b)
    expected = sum(
        (count_a.get(c, 0) / n) * (count_b.get(c, 0) / n) for c in categories
    )

    if expected >= 1.0:
        return 1.0 if observed >= 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def per_label_counts(labels_a: list[str], labels_b: list[str]) -> dict[str, dict]:
    """Return, per label, how often each annotator used it and their agreement."""
    count_a = Counter(labels_a)
    count_b = Counter(labels_b)
    agree = Counter(a for a, b in zip(labels_a, labels_b) if a == b)
    labels = sorted(set(count_a) | set(count_b))
    return {
        label: {
            "annotator_a": count_a.get(label, 0),
            "annotator_b": count_b.get(label, 0),
            "agreed": agree.get(label, 0),
        }
        for label in labels
    }
