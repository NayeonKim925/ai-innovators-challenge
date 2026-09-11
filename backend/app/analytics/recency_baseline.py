"""Transparent baseline for a prepared incident.

This is intentionally not presented as causal discovery. It ranks active alarms by
their latest observable time and provides evidence for each ranking. The causRCA tool
adapter will replace this baseline for causRCA cases in the next milestone.
"""

from __future__ import annotations

from ..domain import Candidate, Evidence, Incident


def rank_active_alarms(incident: Incident, diagnosis_time: float, limit: int = 3) -> tuple[list[Candidate], list[Evidence]]:
    latest: dict[str, object] = {}
    for observation in incident.observations:
        if observation.time_s <= diagnosis_time and observation.kind == "Alarm":
            latest[observation.signal] = observation

    active = [item for item in latest.values() if str(item.value).lower() == "true"]
    active.sort(key=lambda item: item.time_s, reverse=True)

    evidence: list[Evidence] = []
    candidates: list[Candidate] = []
    for rank, item in enumerate(active[:limit], start=1):
        evidence_id = f"E{rank}"
        evidence.append(
            Evidence(
                id=evidence_id,
                title=f"Active alarm: {item.signal}",
                detail=f"At t={item.time_s:g}s, {item.signal} reported {item.value!r} before the diagnosis cutoff.",
                source="Prepared runtime observation",
            )
        )
        candidates.append(
            Candidate(
                rank=rank,
                signal=item.signal,
                reason="Transparent recency baseline: an active alarm is an investigation candidate, not a confirmed root cause.",
                evidence_ids=[evidence_id],
            )
        )
    return candidates, evidence
