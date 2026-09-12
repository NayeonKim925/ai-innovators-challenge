#!/usr/bin/env python3
"""Run an offline causRCA root-cause ranking benchmark.

Runtime observations and evaluation truth are intentionally opened in separate
functions. This module must never be imported by `backend/app`: its output contains
ground truth and is an offline evaluation artifact only.

The default ``time_recency`` method is a dependency-free, transparent baseline.
``caus_tr`` uses the pinned causRCA upstream implementation when its optional
dependencies have been installed. Failed runs remain in the denominator.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from evals.metrics import score_ranking

ROOT = Path(__file__).resolve().parents[1]


class Ranker(Protocol):
    name: str

    def rank(self, incident: dict[str, Any], diagnosis_time: float) -> list[str]: ...


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_runtime(path: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    if not isinstance(payload, list):
        raise ValueError("Runtime incident index must be a list")
    records: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Invalid runtime incident")
        if item["id"] in records:
            raise ValueError(f"Duplicate runtime incident: {item['id']}")
        records[item["id"]] = item
    return records


def load_evaluation(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    if not isinstance(payload, list) or not payload:
        raise ValueError("Evaluation manifest must be a nonempty list")
    cases: list[dict[str, Any]] = []
    for item in payload:
        truth = item.get("ground_truth_nodes") if isinstance(item, dict) else None
        if not isinstance(item.get("case_id"), str) or not isinstance(truth, list) or not truth:
            raise ValueError("Invalid evaluation case")
        cases.append(item)
    return cases


def _last_values(incident: dict[str, Any], diagnosis_time: float) -> list[dict[str, Any]]:
    latest: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, observation in enumerate(incident.get("observations", [])):
        time_s = float(observation["time_s"])
        if time_s <= diagnosis_time:
            latest[str(observation["signal"])] = (index, observation)
    return [entry[1] for entry in latest.values()]


class TimeRecencyRanker:
    """Readable baseline equivalent in intent to upstream time-recency ranking."""

    name = "time_recency"

    def rank(self, incident: dict[str, Any], diagnosis_time: float) -> list[str]:
        latest = _last_values(incident, diagnosis_time)
        active_alarms = (
            item
            for item in latest
            if item.get("kind") == "Alarm" and str(item.get("value")) == "True"
        )
        alarms = sorted(
            active_alarms,
            key=lambda item: float(item["time_s"]),
            reverse=True,
        )
        changes = sorted(
            (item for item in latest if item.get("kind") != "Alarm"),
            key=lambda item: float(item["time_s"]),
            reverse=True,
        )
        if not alarms:
            return _unique(item["signal"] for item in changes)
        ranking: list[str] = []
        for alarm in alarms:
            ranking.extend(
                item["signal"] for item in changes if float(item["time_s"]) < float(alarm["time_s"])
            )
        return _unique(ranking)


def _unique(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


class CausTRRanker:
    name = "caus_tr"

    def __init__(self, graph_path: Path, upstream_root: Path) -> None:
        source = (upstream_root / "src").resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"Pinned causRCA source not found: {source}")
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        try:
            import networkx as nx
            from causrca.rca_models.unsupervised_rca_models import CausalPrioTimeRecencyRCA
        except ImportError as exc:
            raise RuntimeError(
                "CausTR optional dependencies are missing. "
                "Install with `pip install -e '.[causrca]'`."
            ) from exc
        self._graph = nx.read_gml(graph_path)
        self._model = CausalPrioTimeRecencyRCA(causal_graph=self._graph)

    def rank(self, incident: dict[str, Any], diagnosis_time: float) -> list[str]:
        import csv
        import tempfile

        observations = [
            item for item in incident["observations"] if float(item["time_s"]) <= diagnosis_time
        ]
        with tempfile.TemporaryDirectory(prefix="causrca-eval-") as directory:
            path = Path(directory) / "observations.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["time_s", "node", "value", "type"])
                writer.writeheader()
                writer.writerows(
                    {
                        "time_s": item["time_s"],
                        "node": item["signal"],
                        "value": item["value"],
                        "type": item["kind"],
                    }
                    for item in observations
                )
            output = self._model.predict(str(path), diagnosis_time=diagnosis_time)
        if not isinstance(output, list):
            raise TypeError("CausTR returned a non-list ranking")
        return _unique(output)


def aggregate(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    if not rows:
        raise ValueError("Cannot aggregate zero benchmark cases")
    return {
        "case_count": len(rows),
        "failed_count": sum(row["error"] is not None for row in rows),
        "hit@1": sum(row["hit@1"] for row in rows) / len(rows),
        "hit@3": sum(row["hit@3"] for row in rows) / len(rows),
        "mrr": sum(row["mrr"] for row in rows) / len(rows),
        "map@3": sum(row["ap@3"] for row in rows) / len(rows),
    }


def run(
    ranker: Ranker, runtime: dict[str, dict[str, Any]], cases: list[dict[str, Any]]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        case_id = case["case_id"]
        ranking: list[str] = []
        error: str | None = None
        try:
            incident = runtime[case_id]
            ranking = ranker.rank(incident, float(case["diagnosis_time"]))
        except Exception as exc:  # Failures must score zero and remain reported.
            error = f"{type(exc).__name__}: {exc}"
        scores = score_ranking(case["ground_truth_nodes"], ranking)
        rows.append(
            {
                "case_id": case_id,
                "subsystem": case.get("subsystem", "unknown"),
                "ground_truth_nodes": case["ground_truth_nodes"],
                "ranking": ranking,
                "error": error,
                **scores,
            }
        )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["subsystem"]].append(row)
    return {
        "summary": aggregate(rows),
        "by_subsystem": {name: aggregate(group) for name, group in sorted(grouped.items())},
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=("time_recency", "caus_tr"), default="time_recency")
    parser.add_argument("--runtime-root", type=Path, default=ROOT / "data" / "runtime")
    parser.add_argument("--evaluation-root", type=Path, default=ROOT / "data" / "evaluation")
    parser.add_argument("--upstream-root", type=Path, default=ROOT / "third_party" / "causRCA")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    runtime = load_runtime(args.runtime_root / "causrca" / "incidents.json")
    cases = load_evaluation(args.evaluation_root / "causrca" / "cases.json")
    if len(runtime) != 100 or len(cases) != 100:
        raise ValueError("The causRCA benchmark requires all 100 prepared HIL cases")
    ranker: Ranker = (
        TimeRecencyRanker()
        if args.method == "time_recency"
        else CausTRRanker(args.runtime_root / "causrca" / "expert_graph.gml", args.upstream_root)
    )
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "causRCA",
        "source_kind": "hil_simulation",
        "method": ranker.name,
        "llm_used": False,
        "definitions": {
            "hit@k": "1 when any ground-truth node appears in the first k ranking positions; "
            "average over all 100 cases.",
            "mrr": "Reciprocal of the first relevant rank, or zero for an empty/missing ranking.",
            "map@3": "Mean AP@3 across all cases; duplicate predicted nodes cannot "
            "increase a score.",
        },
        "limitations": [
            "Diagnosis cutoffs are official evaluation inputs, not a learned alert-time detector.",
            "Results measure ranking against HIL simulation ground truth only, not repair success "
            "or operational downtime reduction.",
            "LLM output is not included in this metric.",
        ],
        "result": run(ranker, runtime, cases),
    }
    output = args.output or args.evaluation_root / "causrca" / "reports" / f"{args.method}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output.write_text(content, encoding="utf-8")
    summary = {"report": str(output), **report["result"]["summary"]}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
