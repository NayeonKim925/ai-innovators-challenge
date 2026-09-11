"""Optional adapter for the pinned upstream causRCA CausTR implementation.

The upstream project is not vendored here. Configure `CAUSRCA_UPSTREAM_DIR` after
obtaining the pinned, licensed source. If that dependency or its runtime graph is not
available, callers receive a transparent fallback warning rather than a fabricated
causal result.
"""

from __future__ import annotations

import csv
import os
import sys
import tempfile
from pathlib import Path

from ..data.runtime_repository import runtime_root
from ..domain import Candidate, Evidence, Incident

UPSTREAM_COMMIT = "d932ab7ad91abe889b67e4d87186d0fccec7fbc1"


def _upstream_source() -> Path | None:
    configured = os.getenv("CAUSRCA_UPSTREAM_DIR")
    if not configured:
        return None
    source = (Path(configured).resolve() / "src").resolve()
    return source if source.is_dir() else None


def _latest_observations(incident: Incident, diagnosis_time: float) -> dict[str, object]:
    latest: dict[str, object] = {}
    for item in incident.observations:
        if item.time_s <= diagnosis_time:
            latest[item.signal] = item
    return latest


def rank_with_caus_tr(incident: Incident, diagnosis_time: float, limit: int = 3) -> tuple[list[Candidate], list[Evidence], list[str]]:
    """Return CausTR candidates from runtime observations only.

    This adapter never reads `data/evaluation`. The chosen cutoff is supplied by the
    caller and must be validated by the workflow before this function is invoked.
    """
    source = _upstream_source()
    graph_path = runtime_root() / "causrca" / "expert_graph.gml"
    if source is None or not graph_path.is_file():
        return [], [], ["Official causRCA CausTR tool or runtime expert graph is unavailable; using the declared baseline instead."]

    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    try:
        import networkx as nx
        from causrca.rca_models.unsupervised_rca_models import CausalPrioTimeRecencyRCA
    except ImportError:
        return [], [], ["causRCA optional dependencies are unavailable; using the declared baseline instead."]

    observed = [item for item in incident.observations if item.time_s <= diagnosis_time]
    graph = nx.read_gml(graph_path)
    with tempfile.TemporaryDirectory(prefix="causrca-runtime-") as directory:
        path = Path(directory) / "observed.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["time_s", "node", "value", "type"])
            writer.writeheader()
            writer.writerows(
                {
                    "time_s": item.time_s,
                    "node": item.signal,
                    "value": item.value,
                    "type": item.kind,
                }
                for item in observed
            )
        ranking = CausalPrioTimeRecencyRCA(causal_graph=graph).predict(str(path), diagnosis_time)

    latest = _latest_observations(incident, diagnosis_time)
    candidates: list[Candidate] = []
    evidence: list[Evidence] = []
    for rank, node in enumerate(ranking[:limit], start=1):
        item = latest.get(node)
        if item is None:
            continue
        evidence_id = f"E{rank}"
        evidence.append(
            Evidence(
                id=evidence_id,
                title=f"CausTR candidate signal: {node}",
                detail=f"At t={item.time_s:g}s, {node} reported {item.value!r} before the diagnosis cutoff.",
                source=f"Pinned causRCA CausalPrioTimeRecencyRCA ({UPSTREAM_COMMIT[:12]}) with runtime expert graph",
            )
        )
        candidates.append(
            Candidate(
                rank=rank,
                signal=node,
                reason="CausTR ranked this observable signal using the runtime expert graph and pre-cutoff observations. It remains an investigation candidate, not a confirmed cause.",
                evidence_ids=[evidence_id],
            )
        )
    if not candidates:
        return [], [], ["CausTR produced no observable candidates at the selected cutoff; the workflow will abstain."]
    return candidates, evidence, []
