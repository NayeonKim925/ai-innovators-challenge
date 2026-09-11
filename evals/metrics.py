"""Ranking metrics. This module is evaluation-only and must not be imported by runtime code."""

from __future__ import annotations


def score_ranking(truth: list[str], ranking: list[str], limit: int = 3) -> dict[str, float]:
    """Return Hit@1, Hit@k, reciprocal rank, and AP@k for one incident."""
    relevant = set(truth)
    if not relevant:
        raise ValueError("ground truth must be nonempty")
    top = ranking[:limit]
    first_rank = next((index for index, item in enumerate(top, start=1) if item in relevant), None)
    seen: set[str] = set()
    hits = 0
    precision_sum = 0.0
    for rank, item in enumerate(top, start=1):
        if item in relevant and item not in seen:
            hits += 1
            precision_sum += hits / rank
        seen.add(item)
    return {
        "hit@1": float(bool(relevant.intersection(top[:1]))),
        f"hit@{limit}": float(bool(relevant.intersection(top))),
        "mrr": 1 / first_rank if first_rank else 0.0,
        f"ap@{limit}": precision_sum / min(len(relevant), limit),
    }
