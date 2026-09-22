#!/usr/bin/env python3
"""Prepare causRCA runtime incidents while isolating benchmark truth.

The source must be the official dataset's extracted directory containing `dig_twin/`,
`real_op/`, and `expert_graph/`. This script writes observable fault recordings only to
`data/runtime/causrca/incidents.json`; scenario labels and diagnosis cutoffs are written
only to `data/evaluation/causrca/cases.json`.

No generated file is intended for Git. Run `python scripts/prepare_causrca.py --help`.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OBSERVATION_FIELDS = ("time_s", "node", "value", "type")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def locate_dataset(source: Path) -> Path:
    source = source.resolve()
    if (source / "dig_twin").is_dir() and (source / "expert_graph").is_dir():
        return source
    matches = sorted(path.parent for path in source.glob("**/dig_twin") if path.is_dir())
    if len(matches) != 1:
        raise ValueError("Expected one extracted causRCA directory containing dig_twin/")
    return matches[0]


def read_observations(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != OBSERVATION_FIELDS:
            raise ValueError(f"Unexpected observation schema in {path}: {reader.fieldnames}")
        observations: list[dict[str, Any]] = []
        for line, row in enumerate(reader, start=2):
            if any(row.get(field) is None for field in OBSERVATION_FIELDS):
                raise ValueError(f"Malformed observation at {path}:{line}")
            time_s = float(row["time_s"])
            if not math.isfinite(time_s) or time_s < 0 or not row["node"]:
                raise ValueError(f"Invalid observation at {path}:{line}")
            observations.append(
                {
                    "time_s": time_s,
                    "signal": row["node"],
                    "value": row["value"],
                    "kind": row["type"] if row["type"] in {"Alarm", "Measurement", "Event"} else "Event",
                }
            )
    if not observations:
        raise ValueError(f"Empty recording: {path}")
    return sorted(observations, key=lambda item: item["time_s"])


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def opaque_case_id(relative_path: Path) -> str:
    digest = hashlib.sha256(f"causrca-v1:{relative_path.as_posix()}".encode()).hexdigest()
    return f"case_{digest[:24]}"


def prepare(source: Path, runtime_root: Path, evaluation_root: Path) -> dict[str, int]:
    dataset = locate_dataset(source)
    fault_paths = sorted((dataset / "dig_twin").glob("exp_*/exp_*/run_*/*.csv"))
    normal_paths = sorted((dataset / "real_op").glob("*.csv"))
    if len(fault_paths) != 100 or len(normal_paths) != 170:
        raise ValueError(f"Expected official 100 HIL fault and 170 normal recordings; got {len(fault_paths)} and {len(normal_paths)}")

    runtime_incidents: list[dict[str, Any]] = []
    evaluation_cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for recording in fault_paths:
        relative = recording.relative_to(dataset)
        case_id = opaque_case_id(relative)
        if case_id in seen_ids:
            raise ValueError("Duplicate opaque case ID")
        seen_ids.add(case_id)
        observations = read_observations(recording)

        # These source files include benchmark-only values. They are never copied into
        # runtime_incidents and are written solely to evaluation_root.
        timing = read_json(recording.parent / "causes.json")
        scenario_files = list(recording.parent.parent.glob("*_description.json"))
        if len(scenario_files) != 1:
            raise ValueError(f"Expected one scenario description for {recording}")
        scenario = read_json(scenario_files[0])
        diagnosis_time = float(timing["diagnosis_at"])
        cause_start_at = float(timing["cause_start_at"])
        truth = sorted(set(scenario["manipulatedVars"]))
        if not truth or not observations[0]["time_s"] <= diagnosis_time <= observations[-1]["time_s"]:
            raise ValueError(f"Invalid evaluation metadata for {recording}")
        if not observations[0]["time_s"] <= cause_start_at <= observations[-1]["time_s"]:
            raise ValueError(f"Invalid cause_start_at for {recording}")

        runtime_incidents.append(
            {
                "id": case_id,
                "source_dataset": "causrca",
                "title": "Prepared causRCA HIL incident",
                "time_range_s": {"start": observations[0]["time_s"], "end": observations[-1]["time_s"]},
                "capabilities": ["time_series", "root_cause_ranking", "causal_graph"],
                "observations": observations,
            }
        )
        evaluation_cases.append(
            {
                "case_id": case_id,
                "diagnosis_time": diagnosis_time,
                # AGENT_FAULT_DETECTION_PLAN.md Phase 1: evaluation-only ground truth
                # for scoring the fault-onset detector (evals/run_fault_onset_benchmark.py).
                # Never copied into runtime_incidents.
                "cause_start_at": cause_start_at,
                "ground_truth_nodes": truth,
                "subsystem": scenario.get("group", "unknown"),
                "source_file": relative.as_posix(),
            }
        )

    runtime_incidents.sort(key=lambda item: item["id"])
    evaluation_cases.sort(key=lambda item: item["case_id"])
    write_json(runtime_root / "causrca" / "incidents.json", runtime_incidents)
    graph_source = dataset / "expert_graph" / "expert_graph.gml"
    graph_target = runtime_root / "causrca" / "expert_graph.gml"
    graph_target.parent.mkdir(parents=True, exist_ok=True)
    graph_target.write_bytes(graph_source.read_bytes())
    write_json(evaluation_root / "causrca" / "cases.json", evaluation_cases)
    return {"runtime_incidents": len(runtime_incidents), "evaluation_cases": len(evaluation_cases), "normal_records_verified": len(normal_paths)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Official extracted causRCA dataset directory")
    parser.add_argument("--runtime-root", type=Path, default=ROOT / "data" / "runtime")
    parser.add_argument("--evaluation-root", type=Path, default=ROOT / "data" / "evaluation")
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.runtime_root, args.evaluation_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
