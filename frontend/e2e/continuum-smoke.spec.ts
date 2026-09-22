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
    schema_version: 3,
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
        run_id: "run_1",
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
        run_id: "run_1",
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
  let resumeRequests = 0;
  let currentRunRequests = 0;
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
  await page.route("**/api/investigations/inv_2", (route) => {
    currentRunRequests += 1;
    return route.fulfill({
      json: {
        ...investigation,
        investigation_id: "inv_2",
        diagnosis_time: 7,
      },
    });
  });
  await page.route("**/api/cases/case_1/resume", (route) => {
    resumeRequests += 1;
    return route.fulfill({
      json: {
        case_id: "case_1",
        case_version: currentCase.version + 3,
        status: currentCase.status,
        next_action: currentCase.next_action,
        current_run: {
          ...currentCase.analysis_runs[0],
          id: "run_2",
          investigation_id: "inv_2",
          diagnosis_time: 7,
        },
        observations: [
          { id: "obs_1", text: "인계 당시 관찰", author: "Shift A", recorded_at: "2026-01-01T00:00:00Z", provenance: "synthetic_demo" },
          { id: "obs_2", text: "인계 이후 관찰", author: "Shift B", recorded_at: "2026-01-01T01:00:00Z", provenance: "synthetic_demo" },
        ],
        open_items: [{ ...currentCase.open_items[0], status: "resolved" }],
        hypotheses: [{ ...currentCase.hypotheses[0], judgment: "not_supported" }],
        current_handover: {
          id: "handover_1", sender: "Shift A", receiver: "Shift B", source_case_version: 0,
          snapshot_id: "snapshot_1", status: "accepted", exception_reason: "", change_request: "",
          created_at: "2026-01-01T00:00:00Z", published_at: "2026-01-01T00:00:00Z",
          accepted_at: "2026-01-01T00:30:00Z", accepted_by: "Shift B", change_requested_at: null,
        },
        current_snapshot: {
          id: "snapshot_1", case_id: "case_1", source_case_version: 0, snapshot_hash: "hash",
          current_run_id: "run_1", hypothesis_ids: ["hyp_1"], evidence_ids: ["E1"],
          open_item_ids: ["item_1"], observation_ids: ["obs_1"], constraints: [], findings: [],
          created_at: "2026-01-01T00:00:00Z",
          payload: {
            observations: [{ id: "obs_1", original_text: "인계 당시 관찰" }],
            open_items: [currentCase.open_items[0]],
            hypotheses: [currentCase.hypotheses[0]],
          },
        },
        handover_delta: [
          { kind: "case-version-changed", from_version: 0, to_version: currentCase.version + 3 },
          { kind: "added", entity: "observations", id: "obs_2" },
          { kind: "updated", entity: "open_items", id: "item_1" },
          { kind: "updated", entity: "hypotheses", id: "hyp_1" },
        ],
        constraints: [currentCase.next_action],
      },
    });
  });
  await page.route("**/api/cases/case_1/tasks/task_1/responses", (route) => {
    currentCase = makeCase("ready_for_review", 1, "completed");
    return route.fulfill({ json: currentCase });
  });
  await page.route("**/api/cases/case_1/reviews", (route) => {
    currentCase = makeCase("closed", 2, "completed");
    return route.fulfill({ json: currentCase });
  });
  await page.route("**/api/cases/case_1/handover-checks", (route) => {
    currentCase = { ...currentCase, version: currentCase.version + 1 };
    return route.fulfill({ json: { case: currentCase, findings: [], blocking: false } });
  });
  await page.route("**/api/cases/case_1/handovers", (route) => {
    currentCase = {
      ...currentCase,
      version: currentCase.version + 1,
      current_handover_id: "handover_1",
      handover_snapshots: [{ id: "snapshot_1", case_id: "case_1", source_case_version: currentCase.version, snapshot_hash: "hash", current_run_id: "run_1", hypothesis_ids: [], evidence_ids: ["E1"], open_item_ids: ["item_1"], observation_ids: [], constraints: [], payload: { observations: [], open_items: currentCase.open_items, hypotheses: currentCase.hypotheses }, findings: [], created_at: "2026-01-01T00:00:00Z" }],
      handovers: [{ id: "handover_1", sender: "Shift A", receiver: "Shift B", source_case_version: currentCase.version, snapshot_id: "snapshot_1", status: "published", exception_reason: "", change_request: "", created_at: "2026-01-01T00:00:00Z", published_at: "2026-01-01T00:00:00Z", accepted_at: null, accepted_by: null, change_requested_at: null }],
    } as typeof currentCase;
    return route.fulfill({ json: currentCase });
  });
  await page.route("**/api/cases/case_1/handovers/handover_1/acceptance", (route) => {
    currentCase = { ...currentCase, version: currentCase.version + 1, handovers: currentCase.handovers.map((item) => ({ ...item, status: "accepted", accepted_at: "2026-01-01T01:00:00Z", accepted_by: "Shift B" })) } as typeof currentCase;
    return route.fulfill({ json: currentCase });
  });

  await page.goto("/");
  await expect(page).toHaveTitle("Continuum 컨티뉴엄 · 제조 이상 조사·교대 연속성 워크스페이스");
  await page.getByRole("button", { name: "새 사건 분석" }).click();
  await page.getByRole("button", { name: /최근 알람 발생 시점으로 이동/ }).click();
  await page.getByRole("button", { name: "조사 실행", exact: true }).click();
  await expect(page.locator(".candidate").first()).toBeVisible();
  await page.getByRole("button", { name: "확인 업무로 전환" }).click();
  await expect(page.getByRole("region", { name: "조사 연속성" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "인계 당시", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "현재 상태" })).toBeVisible();
  await expect(page.getByText("기록 버전 0 → 3")).toBeVisible();
  await expect(page.getByText("미해결 업무 item_1: 시작 전 → 완료")).toBeVisible();
  await expect(page.getByText("원인 가설 hyp_1: 미평가 → 지지되지 않음")).toBeVisible();
  await expect(page.getByRole("region", { name: "Case 개요" })).toContainText("cutoff 7s");
  const handoverPanel = page.getByRole("region", { name: "인계" });
  await handoverPanel.getByLabel("인계자").fill("Shift A");
  await handoverPanel.getByLabel("인수자").fill("Shift B");
  await handoverPanel.getByRole("button", { name: "사전 점검" }).click();
  await expect(page.getByText("인계 점검을 완료했습니다.")).toBeVisible();
  await handoverPanel.getByRole("button", { name: "Packet 발행" }).click();
  await expect(handoverPanel).toContainText("수락 대기");
  await handoverPanel.getByRole("button", { name: "인수 확인" }).click();
  await expect(handoverPanel).toContainText("수락됨");
  expect(resumeRequests).toBeGreaterThan(0);
  expect(currentRunRequests).toBeGreaterThan(0);
  await page.locator(".task-form input").fill("Shift A");
  await page.locator(".task-form textarea").fill("교대 전 근거 확인 기록");
  await page.getByRole("button", { name: "응답 기록" }).click();
  await expect(page.getByText("최종 검토가 남아 있습니다")).toBeVisible();
  await page.getByPlaceholder("최종 검토자").fill("Shift B");
  await page.getByRole("button", { name: "검토 승인 후 종료" }).click();
  await expect(
    page.getByRole("region", { name: "사건 상세" }).locator(".case-detail-heading .case-status"),
  ).toBeVisible();
});

test("Same Case adds R2 while R1 evidence links remain run scoped", async ({ page }) => {
  const r1 = {
    ...investigation,
    candidates: [{ ...investigation.candidates[0], signal: "F_Filter_Ok" }],
    evidence: [{ ...investigation.evidence[0], title: "Active alarm: F_Filter_Ok" }],
  };
  const r2 = {
    ...investigation,
    investigation_id: "inv_2",
    diagnosis_time: 170,
    candidates: [
      { ...investigation.candidates[0], signal: "LP_Pump_Ok" },
      { ...investigation.candidates[0], rank: 2, signal: "F_Filter_Ok", evidence_ids: ["E2"] },
    ],
    evidence: [
      { ...investigation.evidence[0], title: "Active alarm: LP_Pump_Ok" },
      { ...investigation.evidence[0], id: "E2", title: "Active alarm: F_Filter_Ok" },
    ],
  };
  let currentCase = makeCase("awaiting_evidence", 0, "pending");
  currentCase.analysis_runs[0].diagnosis_time = 140;
  currentCase.hypotheses[0].candidate_signal = "F_Filter_Ok";
  let postedCutoff: number | null = null;
  let postedOpenItem: Record<string, unknown> | null = null;
  let postedHypothesis: Record<string, unknown> | null = null;

  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { status: "ok", llm_provider: "not_configured" } }),
  );
  await page.route("**/api/datasets", (route) =>
    route.fulfill({ json: { datasets: [{ dataset: "causrca", status: "ready", incident_count: 1 }] } }),
  );
  await page.route("**/api/incidents?*", (route) =>
    route.fulfill({ json: { incidents: [incident] } }),
  );
  await page.route("**/api/incidents/case_1", (route) => route.fulfill({ json: incident }));
  await page.route("**/api/cases", (route) =>
    route.fulfill({ json: { cases: [currentCase] } }),
  );
  await page.route("**/api/investigations/inv_1", (route) => route.fulfill({ json: r1 }));
  await page.route("**/api/investigations/inv_2", (route) => route.fulfill({ json: r2 }));
  await page.route("**/api/cases/case_1/resume", (route) => {
    const currentRun = currentCase.analysis_runs.find(
      (item) => item.id === currentCase.current_run_id,
    );
    return route.fulfill({
      json: {
        case_id: currentCase.id,
        case_version: currentCase.version,
        status: currentCase.status,
        next_action: currentCase.next_action,
        current_run: currentRun,
        observations: [],
        open_items: currentCase.open_items,
        hypotheses: currentCase.hypotheses,
        current_handover: { id: "handover_1", status: "accepted", sender: "Shift A", receiver: "Shift B" },
        current_snapshot: {
          id: "snapshot_1", source_case_version: 0, current_run_id: "run_1",
          payload: { observations: [], open_items: [makeCase("awaiting_evidence", 0, "pending").open_items[0]], hypotheses: [makeCase("awaiting_evidence", 0, "pending").hypotheses[0]] },
        },
        handover_delta: [
          { kind: "case-version-changed", from_version: 0, to_version: currentCase.version },
          ...(currentCase.hypotheses[0].judgment !== "unreviewed"
            ? [{ kind: "updated", entity: "hypotheses", id: "hyp_1" }] : []),
          ...(currentCase.open_items.length > 1
            ? [{ kind: "added", entity: "open_items", id: "item_2" }] : []),
        ],
        constraints: [],
      },
    });
  });
  await page.route("**/api/cases/case_1/analysis-runs", async (route) => {
    const body = route.request().postDataJSON();
    postedCutoff = body.diagnosis_time;
    const run2 = {
      ...currentCase.analysis_runs[0],
      id: "run_2",
      investigation_id: "inv_2",
      diagnosis_time: 170,
      created_by: body.created_by,
      created_at: "2026-01-01T01:00:00Z",
    };
    currentCase = {
      ...currentCase,
      version: 1,
      current_run_id: "run_2",
      analysis_runs: [...currentCase.analysis_runs, run2],
      open_items: [
        ...currentCase.open_items,
        { ...currentCase.open_items[0], id: "item_2", title: "Verify LP_Pump_Ok evidence", run_id: "run_2" },
      ],
      hypotheses: [
        ...currentCase.hypotheses,
        { ...currentCase.hypotheses[0], id: "hyp_2", run_id: "run_2", candidate_signal: "LP_Pump_Ok" },
      ],
      tasks: [
        ...currentCase.tasks,
        { ...currentCase.tasks[0], id: "task_2", run_id: "run_2", open_item_id: "item_2", candidate_signal: "LP_Pump_Ok" },
      ],
    };
    return route.fulfill({ json: currentCase });
  });
  await page.route("**/api/cases/case_1/hypotheses/hyp_1/assessments", (route) => {
    postedHypothesis = route.request().postDataJSON();
    currentCase = {
      ...currentCase,
      version: currentCase.version + 1,
      hypotheses: currentCase.hypotheses.map((item) => item.id === "hyp_1"
        ? { ...item, judgment: String(postedHypothesis!.judgment), updated_by: String(postedHypothesis!.updated_by), change_reason: String(postedHypothesis!.change_reason) }
        : item),
    };
    return route.fulfill({ json: currentCase });
  });
  await page.route("**/api/cases/case_1/open-items/item_2/updates", (route) => {
    postedOpenItem = route.request().postDataJSON();
    currentCase = {
      ...currentCase,
      version: currentCase.version + 1,
      open_items: currentCase.open_items.map((item) => item.id === "item_2"
        ? { ...item, status: String(postedOpenItem!.status), assignee: String(postedOpenItem!.assignee), completion_note: String(postedOpenItem!.completion_note) }
        : item),
    };
    return route.fulfill({ json: currentCase });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Case 상세" }).click();
  await page.locator(".case-list-item").click();
  await expect(page.getByRole("region", { name: "분석 이력" })).toBeVisible();
  await page.getByLabel("새 cutoff (초)").fill("170");
  await page.getByLabel("실행자").fill("Shift B");
  await page.getByRole("button", { name: "재분석 실행" }).click();

  await expect(page.getByText("LP_Pump_Ok", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/현재 Run/)).toBeVisible();
  expect(postedCutoff).toBe(170);

  await page.getByRole("button", { name: "Case 상세" }).click();
  await expect(page.getByText("R1", { exact: true })).toBeVisible();
  await expect(page.getByText("R2", { exact: true })).toBeVisible();
  const openItemPanel = page.getByRole("region", { name: "미해결 업무 관리" });
  await expect(openItemPanel.getByText(/분석 R1 · run_1/)).toBeVisible();
  await expect(openItemPanel.getByText(/분석 R2 · run_2/)).toBeVisible();
  const hypothesisPanel = page.getByRole("region", { name: "원인 가설 평가" });
  await hypothesisPanel.locator(".case-management-entry > button").first().click();
  await hypothesisPanel.getByLabel("판단자").fill("Shift B");
  await hypothesisPanel.getByRole("combobox", { name: "판단" }).selectOption("not_supported");
  await hypothesisPanel.getByLabel("판단 이유").fill("추가 관측과 일치하지 않음");
  await hypothesisPanel.getByRole("button", { name: "가설 판단 기록" }).click();
  await expect(page.getByText("원인 가설 hyp_1: 미평가 → 지지되지 않음")).toBeVisible();
  await expect(page.locator(".continuity-state.current").getByText("지지되지 않음")).toBeVisible();
  expect(postedHypothesis).toMatchObject({ expected_version: 1, judgment: "not_supported", updated_by: "Shift B", supporting_observation_ids: [], opposing_evidence_ids: [] });

  await openItemPanel.getByRole("button", { name: /Verify LP_Pump_Ok evidence/ }).click();
  await openItemPanel.getByLabel("담당자").fill("Shift B");
  await openItemPanel.getByRole("combobox", { name: "상태" }).selectOption("resolved");
  await openItemPanel.getByLabel("완료 기록").fill("R2 근거 확인 기록");
  await openItemPanel.getByRole("button", { name: "업무 변경 저장" }).click();
  await expect(openItemPanel.getByText("완료 · 담당 Shift B")).toBeVisible();
  expect(postedOpenItem).toMatchObject({ expected_version: 2, status: "resolved", assignee: "Shift B", completion_note: "R2 근거 확인 기록" });

  await openItemPanel.locator(".case-management-entry").nth(1).getByRole("button", { name: "근거 E1" }).click();
  await expect(page.getByRole("heading", { name: "활성 알람: LP_Pump_Ok" })).toBeVisible();
  await page.getByRole("button", { name: "Case 상세" }).click();
  await page.locator(".evidence-task").first().getByRole("button", { name: /근거 E1/ }).click();
  await expect(page.getByRole("heading", { name: "활성 알람: F_Filter_Ok" })).toBeVisible();
  await expect(page.getByText(/과거 Run/)).toBeVisible();
});
