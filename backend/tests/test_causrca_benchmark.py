from evals.run_causrca_benchmark import TimeRecencyRanker, run


def test_time_recency_ranking_uses_only_pre_cutoff_active_alarm_history() -> None:
    incident = {
        "id": "case_a",
        "observations": [
            {"time_s": 1, "signal": "source", "value": "1", "kind": "Measurement"},
            {"time_s": 2, "signal": "alarm", "value": "True", "kind": "Alarm"},
            {"time_s": 3, "signal": "future", "value": "1", "kind": "Measurement"},
        ],
    }
    report = run(
        TimeRecencyRanker(),
        {"case_a": incident},
        [{"case_id": "case_a", "diagnosis_time": 2, "ground_truth_nodes": ["source"]}],
    )

    assert report["summary"]["hit@1"] == 1.0
    assert report["cases"][0]["ranking"] == ["source"]


def test_benchmark_retains_failed_cases_in_denominator() -> None:
    cases = [{"case_id": "missing", "diagnosis_time": 1, "ground_truth_nodes": ["x"]}]
    report = run(TimeRecencyRanker(), {}, cases)

    assert report["summary"]["case_count"] == 1
    assert report["summary"]["failed_count"] == 1
    assert report["summary"]["hit@3"] == 0.0
