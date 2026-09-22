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
    "기록 버전 3 → 6",
  );
  assert.equal(
    describeHandoverDelta(
      { kind: "added", entity: "observations", id: "obs_2" },
      resume,
    ),
    "관찰 기록 obs_2 추가",
  );
  assert.equal(
    describeHandoverDelta(
      { kind: "updated", entity: "open_items", id: "item_1" },
      resume,
    ),
    "미해결 업무 item_1: 시작 전 → 완료",
  );
  assert.equal(
    describeHandoverDelta(
      { kind: "updated", entity: "hypotheses", id: "hyp_1" },
      resume,
    ),
    "원인 가설 hyp_1: 미평가 → 지지되지 않음",
  );
});
