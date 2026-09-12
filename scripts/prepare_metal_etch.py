#!/usr/bin/env python3
"""Prepare Metal Etch runtime incidents while isolating benchmark truth.

The source must be `MACHINE_Data.mat` (the LAM 9600 engineering-variable file).
This script writes observable wafer recordings and the normal-wafer baseline only to
`data/runtime/metal_etch/`; fault labels and label-reliability flags are written only
to `data/evaluation/metal_etch/labels.json`. See ADR-0002 for why this adapter exists
and `backend/app/data/metal_etch_adapter.py` for the conversion logic this script calls.

No generated file is intended for Git. Run `python scripts/prepare_metal_etch.py --help`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.data.metal_etch_adapter import build_metal_etch_dataset  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def prepare(source: Path, runtime_root: Path, evaluation_root: Path) -> dict[str, int]:
    if not source.is_file():
        raise ValueError(f"MACHINE_Data.mat not found at {source}")

    dataset = build_metal_etch_dataset(source)
    if not dataset.incidents:
        raise ValueError("No faulty wafers were produced; check the source file")
    if not dataset.normal_baseline:
        raise ValueError("No normal wafers were produced; check the source file")

    write_json(
        runtime_root / "metal_etch" / "incidents.json",
        [incident.model_dump(mode="json") for incident in dataset.incidents],
    )
    write_json(
        runtime_root / "metal_etch" / "normal_baseline.json",
        [record.model_dump(mode="json") for record in dataset.normal_baseline],
    )
    write_json(
        evaluation_root / "metal_etch" / "labels.json",
        [label.model_dump(mode="json") for label in dataset.evaluation_labels],
    )
    return {
        "runtime_incidents": len(dataset.incidents),
        "normal_baseline_wafers": len(dataset.normal_baseline),
        "evaluation_labels": len(dataset.evaluation_labels),
        "unreliable_labels": sum(1 for item in dataset.evaluation_labels if not item.label_reliable),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "MACHINE_Data.mat", help="Path to MACHINE_Data.mat")
    parser.add_argument("--runtime-root", type=Path, default=ROOT / "data" / "runtime")
    parser.add_argument("--evaluation-root", type=Path, default=ROOT / "data" / "evaluation")
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.runtime_root, args.evaluation_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
