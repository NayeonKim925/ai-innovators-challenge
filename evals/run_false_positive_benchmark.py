#!/usr/bin/env python3
"""Score the fault-detection agent's false-positive rate on normal operation.

AGENT_FAULT_DETECTION_PLAN.md Phase 2 promised this: `run_fault_onset_benchmark.py`
only ever sees the 100 labeled fault recordings, so it cannot show whether the
detector would wrongly fire on ordinary production. This script runs the same
`workflows/detection.py` agent used by the live API against causRCA's 170
`real_op` recordings (which carry no fault label at all -- see
`analytics/causrca_anomaly.py`'s module docstring) and reports how often it
would have decided `trigger_rca` or `elevated_watch` on a perfectly normal run.

Both this script and `analytics/causrca_anomaly.py`'s own PCA baseline are fit
on the SAME 170 real_op recordings, so a "0% false positive rate" here would
mean nothing (the model perfectly reconstructs its own training data by
definition). This script exists to make that leave-in bias visible, not to
hide it: `p95_spe` is calibrated as the baseline's own 95th percentile, so a
false-positive rate near 5% on this same data is the EXPECTED, honest result,
not evidence of a well-tuned detector on unseen data.

This module must never be imported by `backend/app`, same constraint as
`run_causrca_benchmark.py`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain import Capability, DatasetName, Incident, TimeRange  # noqa: E402
from app.workflows.detection import detect_fault_onset  # noqa: E402


def _incident_from_normal_recording(record: dict[str, Any]) -> Incident:
    observations = record["observations"]
    return Incident(
        id=record["recording_id"],
        source_dataset=DatasetName.CAUSRCA,
        title="Normal-operation recording (real_op)",
        time_range_s=TimeRange(start=observations[0]["time_s"], end=observations[-1]["time_s"]),
        capabilities={Capability.TIME_SERIES},
        observations=observations,
    )


def run(normal_recordings: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for record in normal_recordings:
        incident = _incident_from_normal_recording(record)
        result = detect_fault_onset(incident, observed_up_to_s=incident.time_range_s.end)
        rows.append(
            {
                "recording_id": record["recording_id"],
                "decision": result.decision,
                "onset_time_s": result.onset_time_s,
                "anomaly_score": result.anomaly_score,
                "anomaly_threshold": result.anomaly_threshold,
            }
        )
    # Two severities: an unattended auto-trigger on normal operation would be
    # the actual failure this agent design must avoid, while "elevated_watch"
    # is a soft signal that never opens a Case on its own (services/detection.py
    # only auto-runs RCA on "trigger_rca") -- reporting them separately shows
    # whether the two-signal AND-style corroboration in decide_next_action is
    # actually doing its job of not letting one signal alone auto-trigger.
    full_trigger_false_positives = [row for row in rows if row["decision"] == "trigger_rca"]
    any_false_positive_decisions = {"trigger_rca", "elevated_watch"}
    any_false_positives = [row for row in rows if row["decision"] in any_false_positive_decisions]
    return {
        "summary": {
            "recording_count": len(rows),
            "full_trigger_false_positive_count": len(full_trigger_false_positives),
            "full_trigger_false_positive_rate": (
                len(full_trigger_false_positives) / len(rows) if rows else 0.0
            ),
            "any_false_positive_count": len(any_false_positives),
            "any_false_positive_rate": len(any_false_positives) / len(rows) if rows else 0.0,
            "by_decision": {
                decision: sum(1 for row in rows if row["decision"] == decision)
                for decision in {row["decision"] for row in rows}
            },
        },
        "recordings": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=ROOT / "data" / "runtime")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    baseline_path = args.runtime_root / "causrca" / "normal_baseline.json"
    normal_recordings = json.loads(baseline_path.read_text(encoding="utf-8"))
    if len(normal_recordings) != 170:
        raise ValueError(
            f"Expected all 170 official real_op recordings; got {len(normal_recordings)}"
        )

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "causRCA real_op (normal operation, no fault label)",
        "method": "workflows.detection.detect_fault_onset (alarm + PCA anomaly agent)",
        "limitations": [
            "The PCA baseline is fit on these same 170 recordings, so this measures "
            "leave-in false positives against the baseline's own calibration set, not "
            "true held-out generalization. A ~5% rate is the expected result of using "
            "the baseline's own 95th percentile as the elevated-anomaly threshold, not "
            "evidence of tuning quality.",
            "'full_trigger_false_positive_rate' (decision=='trigger_rca') is the metric that "
            "matters for autonomy safety: services/detection.py only opens an unattended "
            "investigation on that decision. 'any_false_positive_rate' additionally counts "
            "'elevated_watch', a softer signal that surfaces to a human but never opens a "
            "Case on its own.",
        ],
        "result": run(normal_recordings),
    }
    default_output = ROOT / "data" / "evaluation" / "causrca" / "reports" / "false_positive.json"
    output = args.output or default_output
    output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output.write_text(content, encoding="utf-8")
    summary = {"report": str(output), **report["result"]["summary"]}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
