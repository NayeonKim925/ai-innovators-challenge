"""Deterministic fault-onset estimation from observable alarm activity only.

This closes the gap documented in `docs/AGENT_FAULT_DETECTION_PLAN.md` Phase 1:
today a human must move a cutoff slider to decide "when did this look wrong."
This tool answers that question the same way causRCA's own Baro baseline does
(see the causRCA repository's `_split_by_oldest_active_alarm`) -- by reading
the earliest currently-active Alarm-kind observation -- but it never subtracts
an arbitrary buffer, because this estimate is shown to a human as an
investigation cue, not asserted as the true physical fault start. The
evaluation-only ground truth (`data/evaluation/causrca/cases.json`'s
`cause_start_at`) is not read here; `evals/run_fault_onset_benchmark.py` is
the only place that compares this estimate against it.
"""

from __future__ import annotations

from ..domain import Evidence, Incident


def estimate_fault_onset(
    incident: Incident, up_to_time_s: float
) -> tuple[float | None, Evidence | None]:
    """Return the earliest active-alarm time observed up to a cutoff.

    :param incident: Runtime incident containing only pre-cutoff-safe observations.
    :param up_to_time_s: How far into the recording has been observed so far
        (the stream simulator's current playback position, not a cause-finding
        cutoff a human picked with foreknowledge of the answer).
    :return: ``(onset_time_s, evidence)`` if an active alarm was observed, or
        ``(None, None)`` if no alarm has activated yet.
    """
    # causRCA logs a row only when a value CHANGES (OPC UA change-driven capture,
    # per data/README_DATASET.md's "Known limitations"), so a naive scan for any
    # historical value=="True" row picks up short-lived, unrelated transients --
    # e.g. a routine machine-cycle alarm that flips True then False again within
    # a second -- which almost always predate the actual fault alarm and make the
    # estimate wildly early. What matters is each alarm's CURRENT (last-known)
    # state as of the cutoff, exactly like `analytics.recency_baseline.rank_active_alarms`.
    latest_by_signal: dict[str, object] = {}
    for item in incident.observations:
        if item.time_s > up_to_time_s or item.kind != "Alarm":
            continue
        current = latest_by_signal.get(item.signal)
        if current is None or item.time_s >= current.time_s:
            latest_by_signal[item.signal] = item

    active_alarms = [
        item for item in latest_by_signal.values() if str(item.value).lower() == "true"
    ]
    if not active_alarms:
        return None, None

    earliest = min(active_alarms, key=lambda item: item.time_s)
    evidence = Evidence(
        id="E_fault_onset",
        title=f"Earliest active alarm: {earliest.signal}",
        detail=(
            f"At t={earliest.time_s:g}s, {earliest.signal} became active. This is the "
            "earliest observable signal of a problem, not a confirmed fault start -- the "
            "underlying cause may have begun earlier than any alarm fired."
        ),
        source="Alarm-activation fault-onset estimator (observed data only)",
    )
    return earliest.time_s, evidence
