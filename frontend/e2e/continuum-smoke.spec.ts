import { expect, test } from "@playwright/test";

const incident = {
  id: "case_1",
  source_dataset: "causrca",
  title: "Continuum demo incident",
  time_range_s: { start: 0, end: 10 },
  capabilities: ["time_series", "root_cause_ranking"],
  observations: [
    { time_s: 2, signal: "P101", value: true, kind: "Alarm" },
  ],
};

const investigation = {
  investigation_id: "inv_1",
  incident_id: "case_1",
  dataset: "causrca",
  diagnosis_time: 3,
  question: "",
  mode: "deterministic",
  candidates: [
    {
      rank: 1,
      signal: "P101",
      reason: "Active alarm before the cutoff.",
      evidence_ids: ["E1"],
      status: "candidate",
    },
  ],
  evidence: [
    {
      id: "E1",
      title: "Active alarm: P101",
      detail: "P101 reported true before the diagnosis cutoff.",
      source: "Prepared runtime observation",
    },
  ],
  trace: [],
  warnings: [],
  next_action: "Verify the evidence-linked candidate.",
  llm_narrative: null,
  llm_status: "not_requested",
};

function makeCase(status: string, version: number, taskStatus: string) {
  return {
    id: "case_1",
    incident_id: "case_1",
    dataset: "causrca",
    investigation_id: "inv_1",
    status,
    version,
    schema_version: 2,
    current_run_id: "run_1",
    analysis_runs: [
      {
        id: "run_1",
        investigation_id: "inv_1",
        incident_id: "case_1",
        dataset: "causrca",
        diagnosis_time: 3,
        algorithm_version: "test",
        idempotency_key: null,
        created_by: "case_orchestrator",
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    observations: [],
    open_items: [
      {
        id: "item_1",
        title: "Verify P101 evidence",
        status: taskStatus === "completed" ? "resolved" : "not_started",
        assignee: null,
        requested_role: "process_expert",
        due_at: null,
        hold_reason: "",
        evidence_ids: ["E1"],
        observation_ids: [],
        completion_note: taskStatus === "completed" ? "Checked" : "",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ],
    hypotheses: [
      {
        id: "hyp_1",
        run_id: "run_1",
        candidate_signal: "P101",
        evidence_ids: ["E1"],
        supporting_observation_ids: [],
        opposing_evidence_ids: [],
        judgment: "unreviewed",
        change_reason: "",
        updated_by: null,
        updated_at: "2026-01-01T00:00:00Z",
      },
    ],
    handover_snapshots: [],
    handovers: [],
    current_handover_id: null,
    next_action: "Verify the evidence-linked candidate.",
    tasks: [
      {
        id: "task_1",
        kind: "verify_candidate",
        status: taskStatus,
        requested_role: "process_expert",
        title: "P101 근거를 확인해 주세요",
        instructions: "근거가 관측 가능한지 확인하세요.",
        candidate_signal: "P101",
        evidence_ids: ["E1"],
        trace_steps: [2, 3],
        open_item_id: "item_1",
        response: taskStatus === "completed"
          ? { outcome: "confirmed", comment: "확인했습니다.", responder: "Shift A" }
          : null,
        created_at: "2026-01-01T00:00:00Z",
        completed_at: taskStatus === "completed" ? "2026-01-01T01:00:00Z" : null,
      },
    ],
    events: [],
    reviews: status === "closed"
      ? [{ decision: "approve", comment: "검토 완료", reviewer: "Shift B", reviewed_at: "2026-01-01T02:00:00Z" }]
      : [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

test("Continuum keeps the handover investigation flow usable without runtime fixtures", async ({ page }) => {
  let currentCase = makeCase("awaiting_evidence", 0, "pending");
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { status: "ok", llm_provider: "not_configured" } }),
  );
  await page.route("**/api/datasets", (route) =>
    route.fulfill({ json: { datasets: [{ dataset: "causrca", status: "ready", incident_count: 1 }] } }),
  );
  await page.route("**/api/incidents?*", (route) =>
    route.fulfill({ json: { incidents: [incident] } }),
  );
  await page.route("**/api/incidents/case_1", (route) =>
    route.fulfill({ json: incident }),
  );
  await page.route("**/api/cases", (route) =>
    route.fulfill({ json: { cases: currentCase.status === "closed" ? [currentCase] : [] } }),
  );
  await page.route("**/api/incidents/case_1/investigations", (route) =>
    route.fulfill({ json: investigation }),
  );
  await page.route("**/api/incidents/case_1/cases", (route) => {
    currentCase = makeCase("awaiting_evidence", 0, "pending");
    return route.fulfill({ json: currentCase });
  });
  await page.route("**/api/investigations/inv_1", (route) =>
    route.fulfill({ json: investigation }),
  );
  await page.route("**/api/cases/case_1/tasks/task_1/responses", (route) => {
    currentCase = makeCase("ready_for_review", 1, "completed");
    return route.fulfill({ json: currentCase });
  });
  await page.route("**/api/cases/case_1/reviews", (route) => {
    currentCase = makeCase("closed", 2, "completed");
    return route.fulfill({ json: currentCase });
  });

  await page.goto("/");
  await expect(page).toHaveTitle("Continuum 컨티뉴엄 · 제조 이상 조사·교대 연속성 워크스페이스");
  await page.getByRole("button", { name: /최근 알람 발생 시점으로 이동/ }).click();
  await page.getByRole("button", { name: "조사 실행", exact: true }).click();
  await expect(page.locator(".candidate").first()).toBeVisible();
  await page.getByRole("button", { name: "확인 업무로 전환" }).click();
  await expect(page.getByText("Continuum RESUME")).toBeVisible();
  await page.locator(".task-form input").fill("Shift A");
  await page.locator(".task-form textarea").fill("교대 전 근거 확인 기록");
  await page.getByRole("button", { name: "응답 기록" }).click();
  await expect(page.getByText("최종 검토가 남아 있습니다")).toBeVisible();
  await page.getByPlaceholder("최종 검토자").fill("Shift B");
  await page.getByRole("button", { name: "검토 승인 후 종료" }).click();
  await expect(page.getByText("종료됨", { exact: true })).toBeVisible();
});
