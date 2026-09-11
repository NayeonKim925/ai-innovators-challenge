#!/usr/bin/env python3
"""Validate prepared causRCA data independently of the service runtime.

This script is deliberately standard-library only. It checks that runtime data has
no benchmark labels, that the 100 HIL cases match the evaluation manifest, and that
each diagnosis cutoff is valid for its own observable time range.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_RUNTIME_KEYS = frozenset(
    {
        "label",
        "label_value",
        "root_cause",
        "ground_truth",
        "ground_truth_nodes",
        "manipulated_variable",
        "manipulated_nodes",
        "diagnosis_time",
        "fault_name",
        "split",
        "scenario",
        "source_file",
    }
)
CASE_ID = re.compile(r"^case_[a-f0-9]{24}$")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def reject_forbidden_keys(value: Any) -> None:
    if isinstance(value, dict):
        found = FORBIDDEN_RUNTIME_KEYS.intersection(value)
        if found:
            raise ValueError(f"Runtime data contains evaluation-only keys: {sorted(found)}")
        for child in value.values():
            reject_forbidden_keys(child)
    elif isinstance(value, list):
        for child in value:
            reject_forbidden_keys(child)


def validate(
    runtime_root: Path, evaluation_root: Path, expected_count: int = 100
) -> dict[str, int]:
    incidents_path = runtime_root / "causrca" / "incidents.json"
    graph_path = runtime_root / "causrca" / "expert_graph.gml"
    evaluation_path = evaluation_root / "causrca" / "cases.json"
    incidents = read_json(incidents_path)
    cases = read_json(evaluation_path)
    if not isinstance(incidents, list) or len(incidents) != expected_count:
        raise ValueError(f"Expected {expected_count} runtime incidents")
    if not isinstance(cases, list) or len(cases) != expected_count:
        raise ValueError(f"Expected {expected_count} evaluation cases")
    if not graph_path.is_file() or not graph_path.read_bytes():
        raise ValueError("Missing runtime expert graph")
    reject_forbidden_keys(incidents)

    ranges: dict[str, tuple[float, float]] = {}
    for incident in incidents:
        if not isinstance(incident, dict) or not CASE_ID.fullmatch(str(incident.get("id", ""))):
            raise ValueError("Invalid runtime case identifier")
        time_range = incident.get("time_range_s")
        observations = incident.get("observations")
        if (
            not isinstance(time_range, dict)
            or not isinstance(observations, list)
            or not observations
        ):
            raise ValueError(f"Invalid runtime incident: {incident.get('id')}")
        start, end = float(time_range["start"]), float(time_range["end"])
        if not math.isfinite(start) or not math.isfinite(end) or start > end:
            raise ValueError(f"Invalid range for {incident['id']}")
        previous = -math.inf
        for observation in observations:
            time_s = float(observation["time_s"])
            if not math.isfinite(time_s) or not start <= time_s <= end or time_s < previous:
                raise ValueError(f"Invalid observation order for {incident['id']}")
            previous = time_s
        ranges[incident["id"]] = (start, end)

    seen_evaluation_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Invalid evaluation case")
        case_id = case.get("case_id")
        truth = case.get("ground_truth_nodes")
        cutoff = case.get("diagnosis_time")
        if not isinstance(case_id, str) or case_id in seen_evaluation_ids or case_id not in ranges:
            raise ValueError("Evaluation case does not match a unique runtime case")
        if (
            not isinstance(truth, list)
            or not truth
            or not all(isinstance(node, str) and node for node in truth)
        ):
            raise ValueError(f"Invalid ground truth for {case_id}")
        if (
            isinstance(cutoff, bool)
            or not isinstance(cutoff, (float, int))
            or not math.isfinite(float(cutoff))
        ):
            raise ValueError(f"Invalid diagnosis cutoff for {case_id}")
        start, end = ranges[case_id]
        if not start <= float(cutoff) <= end:
            raise ValueError(f"Diagnosis cutoff outside runtime range for {case_id}")
        seen_evaluation_ids.add(case_id)
    if len(seen_evaluation_ids) != len(ranges):
        raise ValueError("Runtime and evaluation case sets differ")
    return {"runtime_incidents": len(incidents), "evaluation_cases": len(cases)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=ROOT / "data" / "runtime")
    parser.add_argument("--evaluation-root", type=Path, default=ROOT / "data" / "evaluation")
    parser.add_argument("--expected-count", type=int, default=100)
    args = parser.parse_args()
    result = validate(args.runtime_root, args.evaluation_root, args.expected_count)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
