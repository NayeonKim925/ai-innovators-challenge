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

test("localizes Monitor's fault-detection agent evidence text (AGENT_FAULT_DETECTION_PLAN.md)", () => {
  // Regression test: an earlier fix used a manually-counted .slice() offset that
  // clipped the first character of the signal name ("Hyd_A_700203" -> "yd_A_700203").
  assert.equal(
    displayText("Earliest active alarm: Hyd_A_700203"),
    "최초 활성 알람: Hyd_A_700203",
  );
  assert.equal(
    displayText("CausTR candidate signal: HP_Pump_Ok"),
    "CausTR 후보 신호: HP_Pump_Ok",
  );
  assert.equal(
    displayText(
      "At t=129.853s, Hyd_A_700203 became active. This is the earliest observable signal of a problem, not a confirmed fault start -- the underlying cause may have begun earlier than any alarm fired.",
    ),
    "t=129.853초에 Hyd_A_700203이(가) 활성화됐습니다. 이는 관측 가능한 최초 이상 징후일 뿐, 확정된 fault 시작 시점은 아닙니다 — 실제 원인은 이보다 먼저 시작됐을 수 있습니다.",
  );
  assert.equal(
    displayText(
      "Deviation from normal-operation baseline (largest contributor: TL_lock)",
    ),
    "정상 운전 기준선 대비 이상 (최대 기여 신호: TL_lock)",
  );
  assert.equal(
    displayText(
      "Reconstruction error (SPE)=172 vs. normal-operation baseline (typical=2.01, elevated threshold=16.5). TL_lock contributed the most to this deviation.",
    ),
    "재구성 오차(SPE)=172 (정상 운전 기준선 평균=2.01, 이상 판단 임계값=16.5). TL_lock 신호가 이 편차에 가장 크게 기여했습니다.",
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
