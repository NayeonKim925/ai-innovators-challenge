import test from "node:test";
import assert from "node:assert/strict";
import {
  displayCaseEventDetail,
  displayCaseEventType,
  displayText,
} from "./src/presentation.ts";
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

test("localizes known case orchestration records without changing identifiers", () => {
  assert.equal(displayCaseEventType("case_ready_for_review"), "최종 검토 대기");
  assert.equal(
    displayText(
      "An expert reviewer must explicitly approve or reject this evidence-linked candidate.",
    ),
    "담당 전문가가 근거와 연결된 후보를 명시적으로 승인 또는 거절해야 합니다.",
  );
  assert.equal(
    displayCaseEventDetail(
      "Recorded confirmed response from 공정 전문가 for verify_candidate.",
    ),
    "공정 전문가의 후보 근거 확인 응답을 기록했습니다: 확인 가능.",
  );
});
