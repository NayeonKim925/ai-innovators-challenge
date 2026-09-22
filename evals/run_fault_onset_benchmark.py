#!/usr/bin/env python3
"""Score the alarm-activation fault-onset detector against causRCA's `cause_start_at`.

This is the evaluation-only counterpart to `backend/app/analytics/fault_onset.py`
(AGENT_FAULT_DETECTION_PLAN.md Phase 1). The detector itself never reads
`cause_start_at` -- it estimates onset purely from observable alarm activity.
This script is the *only* place that compares that estimate against the
evaluation-only ground truth, to measure how well "earliest active alarm"
approximates "the labeled fault start."

Expected result, and why: the causal chain is cause -> ... -> alarm, so the
alarm always lags the true cause by some lead time. This script reports that
lag honestly rather than treating a positive error as a bug.

This module must never be imported by `backend/app`, same constraint as
`run_causrca_benchmark.py`.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.analytics.fault_onset import estimate_fault_onset  # noqa: E402
from app.domain import Incident  # noqa: E402

from evals.run_causrca_benchmark import load_runtime  # noqa: E402


def score_case(
    incident_payload: dict[str, Any], diagnosis_time: float, cause_start_at: float
) -> dict[str, Any]:
    incident = Incident.model_validate(incident_payload)
    onset_time_s, _evidence = estimate_fault_onset(incident, up_to_time_s=diagnosis_time)
    if onset_time_s is None:
        return {"detected": False, "onset_time_s": None, "error_s": None}
    error_s = onset_time_s - cause_start_at
    return {"detected": True, "onset_time_s": onset_time_s, "error_s": error_s}


def aggregate(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    if not rows:
        raise ValueError("Cannot aggregate zero benchmark cases")
    detected = [row for row in rows if row["detected"]]
    errors = [row["error_s"] for row in detected]
    return {
        "case_count": len(rows),
        "detected_count": len(detected),
        "detection_rate": len(detected) / len(rows),
        "mean_lag_s": statistics.fmean(errors) if errors else None,
        "median_lag_s": statistics.median(errors) if errors else None,
        "hit_within_5s": sum(0 <= error <= 5 for error in errors) / len(rows),
        "hit_within_10s": sum(0 <= error <= 10 for error in errors) / len(rows),
    }


def run(runtime: dict[str, dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        case_id = case["case_id"]
        error: str | None = None
        try:
            incident = runtime[case_id]
            diagnosis_time = float(case["diagnosis_time"])
            cause_start_at = float(case["cause_start_at"])
            result = score_case(incident, diagnosis_time, cause_start_at)
        except Exception as exc:  # Failures must score zero and remain reported.
            result = {"detected": False, "onset_time_s": None, "error_s": None}
            error = f"{type(exc).__name__}: {exc}"
        rows.append(
            {"case_id": case_id, "cause_start_at": case["cause_start_at"], "error": error, **result}
        )
    return {"summary": aggregate(rows), "cases": rows}


def load_evaluation_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    missing = [case["case_id"] for case in cases if "cause_start_at" not in case]
    if missing:
        raise ValueError(
            f"{len(missing)} evaluation case(s) are missing cause_start_at; "
            "re-run scripts/prepare_causrca.py"
        )
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=ROOT / "data" / "runtime")
    parser.add_argument("--evaluation-root", type=Path, default=ROOT / "data" / "evaluation")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    runtime = load_runtime(args.runtime_root / "causrca" / "incidents.json")
    cases = load_evaluation_cases(args.evaluation_root / "causrca" / "cases.json")
    if len(runtime) != 100 or len(cases) != 100:
        raise ValueError("The causRCA benchmark requires all 100 prepared HIL cases")

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "causRCA",
        "method": "alarm_activation_onset_estimator",
        "definitions": {
            "detection_rate": "Share of cases with an active alarm observed by diagnosis_time.",
            "mean_lag_s / median_lag_s": (
                "onset_time_s - cause_start_at over detected cases; expected to be "
                "positive because alarms causally lag the true fault start."
            ),
            "hit_within_5s / hit_within_10s": (
                "Share of ALL cases where the alarm fired within [0, N] seconds "
                "after cause_start_at."
            ),
        },
        "limitations": [
            "This measures how closely 'earliest active alarm' tracks the labeled cause "
            "start, not whether the detector caught every real anomaly -- there is no "
            "negative-control (normal-operation) false-positive rate here yet "
            "(AGENT_FAULT_DETECTION_PLAN.md Phase 2).",
            "A negative lag would mean the alarm fired before the labeled cause, which "
            "should not happen with this dataset's causal ordering; such a case would "
            "indicate a bug.",
        ],
        "result": run(runtime, cases),
    }
    output = args.output or args.evaluation_root / "causrca" / "reports" / "fault_onset.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output.write_text(content, encoding="utf-8")
    summary = {"report": str(output), **report["result"]["summary"]}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
