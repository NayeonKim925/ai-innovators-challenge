import pytest

from evals.metrics import score_ranking


def test_metrics_keep_duplicate_predictions_from_inflating_average_precision() -> None:
    score = score_ranking(["A", "B"], ["A", "A", "A"])

    assert score == {"hit@1": 1.0, "hit@3": 1.0, "mrr": 1.0, "ap@3": 0.5}


def test_metrics_require_truth() -> None:
    with pytest.raises(ValueError, match="nonempty"):
        score_ranking([], ["A"])
