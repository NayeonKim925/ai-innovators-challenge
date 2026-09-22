import test from "node:test";
import assert from "node:assert/strict";
import { assignedToActor, shiftTotals, summarizeShiftCase, visibleShiftCases } from "./src/shiftSummary.ts";

const at = "2026-09-21T00:00:00Z";
const now = Date.parse("2026-09-21T06:00:00Z");
const run = (id, cutoff) => ({ id, investigation_id: `inv_${id}`, incident_id: "incident_1", dataset: "causrca", diagnosis_time: cutoff, algorithm_version: "test", idempotency_key: null, created_by: "Shift B", created_at: at });
const openItem = (id, runId, assignee, status = "not_started") => ({ id, title: id, status, assignee, requested_role: "operator", due_at: null, hold_reason: "", run_id: runId, evidence_ids: ["E1"], observation_ids: [], completion_note: "", created_at: at, updated_at: at });
const hypothesis = (id, runId, signal, judgment) => ({ id, run_id: runId, candidate_signal: signal, judgment, evidence_ids: ["E1"], supporting_observation_ids: [], opposing_evidence_ids: [], change_reason: "", updated_by: null, updated_at: at });

function caseRecord(id, overrides = {}) {
  return {
    id, incident_id: `incident_${id}`, dataset: "causrca", investigation_id: "inv_run_1",
    status: "awaiting_evidence", version: 4, next_action: "Continue investigation",
    analysis_runs: [run("run_1", 140)], current_run_id: "run_1",
    open_items: [], hypotheses: [], observations: [], handovers: [], handover_snapshots: [], current_handover_id: null,
    tasks: [], events: [], reviews: [], schema_version: 3, created_at: at, updated_at: at,
    ...overrides,
  };
}
const handover = (status = "accepted") => ({ id: "handover_1", sender: "Shift A", receiver: "Shift B", source_case_version: 2, snapshot_id: "snapshot_1", status, exception_reason: "", change_request: "", created_at: at, published_at: at, accepted_at: status === "accepted" ? at : null, accepted_by: status === "accepted" ? "Shift B" : null, change_requested_at: null });

test("multiple Cases preserve current R2 and run-scoped candidates while counting unresolved work", () => {
  const first = caseRecord("case_1", {
    analysis_runs: [run("run_1", 140), run("run_2", 170)], current_run_id: "run_2",
    open_items: [openItem("item_r1", "run_1", "Shift A"), openItem("item_r2", "run_2", "Shift B"), openItem("done", "run_1", "Shift B", "resolved")],
    hypotheses: [hypothesis("h1", "run_1", "F_Filter_Ok", "supported"), hypothesis("h2", "run_2", "Human_Only_Track", "unreviewed")],
  });
  const second = caseRecord("case_2", { status: "ready_for_review", open_items: [openItem("item_2", "run_1", null)] });
  const r2Result = { investigation_id: "inv_run_2", candidates: [{ rank: 2, signal: "CLF_Filter_Ok" }, { rank: 1, signal: "LP_Pump_Ok" }] };
  const items = [summarizeShiftCase(first, null, r2Result), summarizeShiftCase(second)];
  assert.equal(items.length, 2);
  assert.equal(items[0].current_run.id, "run_2");
  assert.equal(items[0].run_number, 2);
  assert.equal(items[0].run_count, 2);
  assert.deepEqual(items[0].current_candidate_signals, ["LP_Pump_Ok", "CLF_Filter_Ok"]);
  assert.equal(summarizeShiftCase(first).current_candidate_signals, null);
  assert.equal(summarizeShiftCase(first, null, { investigation_id: "inv_run_1", candidates: [{ rank: 1, signal: "F_Filter_Ok" }] }).current_candidate_signals, null);
  assert.equal(items[0].unresolved_open_items.length, 2);
  assert.equal(items[0].hypothesis_summary.supported, 1);
  assert.equal(items[0].hypothesis_summary.unreviewed, 1);
  assert.deepEqual(shiftTotals(items, now), { active_cases: 2, needs_attention_cases: 2, unresolved_open_items: 3, awaiting_handover: 0, recently_updated_cases: 2 });
});

test("Handover status, Snapshot run, and entity delta determine attention without treating acceptance alone as investigation change", () => {
  const base = caseRecord("case_1", {
    analysis_runs: [run("run_1", 140), run("run_2", 170)], current_run_id: "run_2",
    handovers: [handover()], current_handover_id: "handover_1",
    handover_snapshots: [{ id: "snapshot_1", current_run_id: "run_1" }],
  });
  const resume = { case_id: base.id, case_version: base.version, handover_delta: [
    { kind: "case-version-changed", from_version: 2, to_version: 4 },
    { kind: "added", entity: "observations", id: "obs_2" },
  ] };
  const summary = summarizeShiftCase(base, resume);
  assert.equal(summary.latest_handover.status, "accepted");
  assert.equal(summary.new_run_since_handover, true);
  assert.equal(summary.has_changes_since_handover, true);
  assert.equal(summary.recent_changes.length, 2);
  assert.deepEqual(summary.attention_reasons, ["new analysis run since handover", "case updated after handover"]);
  const acceptedOnly = summarizeShiftCase(caseRecord("case_2", {
    handovers: [handover()], current_handover_id: "handover_1",
    handover_snapshots: [{ id: "snapshot_1", current_run_id: "run_1" }],
  }), { case_id: "case_2", case_version: 4, handover_delta: [{ kind: "case-version-changed", from_version: 2, to_version: 4 }] });
  assert.equal(acceptedOnly.has_changes_since_handover, false);
  assert.deepEqual(acceptedOnly.attention_reasons, []);
  assert.equal(summarizeShiftCase(base).has_changes_since_handover, true); // Run comparison remains available if Resume fails.
  assert.equal(summarizeShiftCase(base, { ...resume, case_version: 3 }).recent_changes, null); // Stale Resume is not used.
  assert.deepEqual(visibleShiftCases([acceptedOnly, summary], "all", "attention", "Shift B", "all", now).map((item) => item.case_id), ["case_1", "case_2"]);
});

test("actor, attention, handover, recent, status, and sort filters work across Cases", () => {
  const recent = summarizeShiftCase(caseRecord("recent", { updated_at: "2026-09-21T05:00:00Z", open_items: [openItem("a", "run_1", "Shift B"), openItem("b", "run_1", "Shift B")] }));
  const waiting = summarizeShiftCase(caseRecord("waiting", { updated_at: "2026-09-20T00:00:00Z", handovers: [handover("published")], current_handover_id: "handover_1", handover_snapshots: [{ id: "snapshot_1", current_run_id: "run_1" }] }));
  const requested = summarizeShiftCase(caseRecord("requested", { updated_at: "2026-09-19T00:00:00Z", handovers: [handover("changes_requested")], current_handover_id: "handover_1" }));
  const closed = summarizeShiftCase(caseRecord("closed", { status: "closed" }));
  const items = [waiting, closed, requested, recent];
  assert.equal(assignedToActor(recent, " shift b "), true);
  assert.equal(assignedToActor(waiting, "Shift B"), true);
  assert.equal(assignedToActor(closed, ""), false);
  assert.deepEqual(visibleShiftCases(items, "active", "updated", "Shift B", "all", now).map((item) => item.case_id), ["recent", "waiting", "requested"]);
  assert.deepEqual(visibleShiftCases(items, "assigned", "updated", "Shift B", "all", now).map((item) => item.case_id), ["recent", "waiting", "requested"]);
  assert.equal(visibleShiftCases(items, "assigned", "updated", "Shift C", "all", now).length, 0);
  assert.deepEqual(visibleShiftCases(items, "handover", "updated", "Shift B", "all", now).map((item) => item.case_id), ["waiting", "requested"]);
  assert.deepEqual(visibleShiftCases(items, "attention", "updated", "Shift B", "all", now).map((item) => item.case_id), ["recent", "waiting", "requested"]);
  assert.deepEqual(visibleShiftCases(items, "recent", "updated", "Shift B", "all", now).map((item) => item.case_id), ["recent"]);
  assert.equal(visibleShiftCases(items, "all", "updated", "Shift B", "closed", now)[0].case_id, "closed");
  assert.equal(visibleShiftCases(items, "active", "unresolved", "Shift B", "all", now)[0].case_id, "recent");
  assert.equal(shiftTotals(items, now).awaiting_handover, 2);
});
