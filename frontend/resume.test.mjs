import test from "node:test";
import assert from "node:assert/strict";
import { describeHandoverDelta, snapshotEntities } from "./src/resume.ts";

const snapshot = {
  id: "snapshot_1",
  payload: {
    observations: [{ id: "obs_1", original_text: "At handover" }],
    open_items: [{ id: "item_1", status: "not_started" }],
    hypotheses: [{ id: "hyp_1", judgment: "unreviewed" }],
  },
};

const resume = {
  current_snapshot: snapshot,
  observations: [
    { id: "obs_1", text: "At handover" },
    { id: "obs_2", text: "After handover" },
  ],
  open_items: [{ id: "item_1", status: "resolved" }],
  hypotheses: [{ id: "hyp_1", judgment: "not_supported" }],
};

test("reads entity collections from a handover snapshot safely", () => {
  assert.equal(snapshotEntities(snapshot, "observations").length, 1);
  assert.deepEqual(snapshotEntities(null, "open_items"), []);
});

test("describes handover changes with status transitions when available", () => {
  assert.equal(
    describeHandoverDelta(
      { kind: "case-version-changed", from_version: 3, to_version: 6 },
      resume,
    ),
    "Case version 3 → 6",
  );
  assert.equal(
    describeHandoverDelta(
      { kind: "added", entity: "observations", id: "obs_2" },
      resume,
    ),
    "Observation obs_2 added",
  );
  assert.equal(
    describeHandoverDelta(
      { kind: "updated", entity: "open_items", id: "item_1" },
      resume,
    ),
    "Open Item item_1: not_started → resolved",
  );
  assert.equal(
    describeHandoverDelta(
      { kind: "updated", entity: "hypotheses", id: "hyp_1" },
      resume,
    ),
    "Hypothesis hyp_1: unreviewed → not_supported",
  );
});
