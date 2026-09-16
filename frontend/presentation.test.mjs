import test from "node:test";
import assert from "node:assert/strict";
import { displayText } from "./src/presentation.ts";
test("localizes known baseline text without inventing analysis", () => {
  assert.equal(displayText("deterministic"), "분석 도구 기반");
  assert.equal(
    displayText("Active alarm: SR_A_67040"),
    "활성 알람: SR_A_67040",
  );
  assert.equal(
    displayText(
      "At t=211.853s, SR_A_67040 reported 'True' before the diagnosis cutoff.",
    ),
    "진단 시점 이전 211.853초에 SR_A_67040 신호에서 'True' 값이 관측되었습니다.",
  );
  assert.equal(
    displayText("Unknown tool result with new evidence"),
    "Unknown tool result with new evidence",
  );
});
