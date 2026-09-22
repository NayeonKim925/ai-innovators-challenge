import { expect, test } from "@playwright/test";

const recent = new Date(Date.now() - 60 * 60 * 1000).toISOString();
const old = "2026-01-01T00:00:00Z";
const run = (id: string, cutoff: number, incidentId: string) => ({ id, investigation_id: `inv_${id}`, incident_id: incidentId, dataset: "causrca", diagnosis_time: cutoff, algorithm_version: "test", idempotency_key: null, created_by: "Shift A", created_at: old });
const item = (id: string, runId: string, assignee: string | null) => ({ id, title: `Inspect ${id}`, status: "not_started", assignee, requested_role: "operator", due_at: null, hold_reason: "", run_id: runId, evidence_ids: ["E1"], observation_ids: [], completion_note: "", created_at: old, updated_at: old });
const hypothesis = (id: string, runId: string, signal: string, judgment = "unreviewed") => ({ id, run_id: runId, candidate_signal: signal, evidence_ids: ["E1"], supporting_observation_ids: [], opposing_evidence_ids: [], judgment, change_reason: "", updated_by: null, updated_at: old });
const packet = (id: string, receiver: string, status: string) => ({ id, sender: "Shift A", receiver, source_case_version: 1, snapshot_id: `snapshot_${id}`, status, exception_reason: "", change_request: "", created_at: old, published_at: old, accepted_at: status === "accepted" ? old : null, accepted_by: status === "accepted" ? receiver : null, change_requested_at: null });
function caseRecord(id: string, status: string, updated: string) {
  return { id, incident_id: `incident_${id}`, dataset: "causrca", investigation_id: `inv_${id}1`, status, version: 3, schema_version: 3,
    current_run_id: `${id}1`, analysis_runs: [run(`${id}1`, 140, `incident_${id}`)],
    observations: [], open_items: [], hypotheses: [], handover_snapshots: [], handovers: [], current_handover_id: null,
    next_action: `Continue ${id}`, tasks: [], events: [], reviews: [], created_at: old, updated_at: updated };
}

test("Shift Workspace summarizes multiple Cases, filters work, and a Case opens the existing Resume", async ({ page }) => {
  const a = caseRecord("case_A", "awaiting_evidence", recent);
  a.analysis_runs = [run("case_A1", 140, a.incident_id), run("case_A2", 170, a.incident_id)];
  a.current_run_id = "case_A2";
  a.open_items = [item("item_A1", "case_A1", "Shift B"), item("item_A2", "case_A2", "Shift B")];
  a.hypotheses = [hypothesis("hyp_A1", "case_A1", "F_Filter_Ok", "supported"), hypothesis("hyp_A2", "case_A2", "Human_Only_Track")];
  a.handovers = [packet("packet_A", "Shift B", "accepted")];
  a.current_handover_id = "packet_A";
  a.handover_snapshots = [{ id: "snapshot_packet_A", current_run_id: "case_A1", source_case_version: 1, payload: { observations: [], open_items: [], hypotheses: [] } }];
  a.observations = [{ id: "obs_A", original_text: "Synthetic demo observation", author: "Shift A", recorded_at: recent, observed_at: null, scope: "", source_location: "", provenance: "synthetic_demo", approved: true }];
  const b = caseRecord("case_B", "ready_for_review", old);
  b.open_items = [item("item_B1", "case_B1", "Shift C")];
  b.hypotheses = [hypothesis("hyp_B1", "case_B1", "Sensor_B")];
  b.handovers = [packet("packet_B", "Shift C", "published")];
  b.current_handover_id = "packet_B";
  b.handover_snapshots = [{ id: "snapshot_packet_B", current_run_id: "case_B1", source_case_version: 1, payload: { observations: [], open_items: [], hypotheses: [] } }];
  const c = caseRecord("case_C", "closed", old);
  const allCases = [a, b, c];
  let resumeCalls = 0;
  let serverWorkspaceCalls = 0;
  const investigationRequests: string[] = [];

  await page.route("**/api/shift-workspace?*", (route) => {
    serverWorkspaceCalls++;
    return route.fulfill({ status: 404, json: { detail: "Not Found" } });
  });
  await page.route("**/api/health", (route) => route.fulfill({ json: { status: "ok", llm_provider: "not_configured" } }));
  await page.route("**/api/datasets", (route) => route.fulfill({ json: { datasets: [{ dataset: "causrca", status: "ready", incident_count: 3 }] } }));
  await page.route("**/api/incidents?*", (route) => route.fulfill({ json: { incidents: allCases.map((entry) => ({ id: entry.incident_id, source_dataset: "causrca", title: `Incident ${entry.id}`, time_range_s: { start: 0, end: 200 }, capabilities: [] })) } }));
  await page.route("**/api/incidents/incident_case_A", (route) => route.fulfill({ json: { id: a.incident_id, source_dataset: "causrca", title: "Incident case_A", time_range_s: { start: 0, end: 200 }, capabilities: [], observations: [] } }));
  await page.route("**/api/cases", (route) => route.fulfill({ json: { cases: allCases } }));
  await page.route(/\/api\/cases\/case_[ABC]\/resume$/, (route) => {
    resumeCalls++;
    const source = allCases.find((entry) => route.request().url().includes(`/${entry.id}/resume`))!;
    return route.fulfill({ json: {
      case_id: source.id, case_version: source.version, status: source.status, next_action: source.next_action,
      current_run: source.analysis_runs.find((entry) => entry.id === source.current_run_id),
      observations: source.observations.map((entry) => ({ id: entry.id, text: entry.original_text, author: entry.author, recorded_at: entry.recorded_at, provenance: entry.provenance })),
      open_items: source.open_items, hypotheses: source.hypotheses,
      current_handover: source.handovers[0] || null, current_snapshot: source.handover_snapshots[0] || null,
      handover_delta: source.id === "case_A" ? [{ kind: "case-version-changed", from_version: 1, to_version: 3 }, { kind: "added", entity: "observations", id: "obs_A" }] : [], constraints: [],
    } });
  });
  await page.route(/\/api\/investigations\/inv_case_[ABC]1$/, (route) => {
    const id = route.request().url().split("/").at(-1)!;
    investigationRequests.push(id);
    return route.fulfill({ json: { investigation_id: id, candidates: [{ rank: 1, signal: id === "inv_case_A1" ? "F_Filter_Ok" : "Other_RCA" }] } });
  });
  await page.route(/\/api\/investigations\/inv_case_A2$/, (route) => {
    investigationRequests.push("inv_case_A2");
    return route.fulfill({ json: {
    investigation_id: "inv_case_A2", incident_id: a.incident_id, dataset: "causrca", diagnosis_time: 170, question: "", mode: "deterministic",
    candidates: [{ rank: 1, signal: "LP_Pump_Ok", reason: "Runtime observation", evidence_ids: ["E1"], status: "candidate" }, { rank: 2, signal: "CLF_Filter_Ok", reason: "Runtime observation", evidence_ids: ["E1"], status: "candidate" }],
    evidence: [{ id: "E1", title: "Pump event", detail: "Runtime event", source: "runtime" }], trace: [], warnings: [], next_action: "Continue", llm_narrative: null, llm_status: "not_requested",
    } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "교대 워크스페이스" }).click();
  await expect(page.getByRole("region", { name: "교대 워크스페이스" })).toBeVisible();
  const summary = page.locator(".shift-totals > div").first();
  await expect(summary).toContainText("2");
  await expect(page.getByRole("article", { name: "Case case_A" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Case case_B" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Case case_C" })).toHaveCount(0);
  const cardA = page.getByRole("article", { name: "Case case_A" });
  await expect(cardA).toContainText("R2 · cutoff 170s");
  await expect(cardA).toContainText("cutoff 170s");
  await expect(cardA.locator(".shift-candidates")).not.toBeVisible();
  await cardA.getByText("조사 세부 정보").click();
  await expect(cardA.locator(".shift-candidates")).toContainText("LP_Pump_Ok");
  await expect(cardA.locator(".shift-candidates")).toContainText("CLF_Filter_Ok");
  await expect(cardA.locator(".shift-candidates")).not.toContainText("Human_Only_Track");
  await expect(cardA.locator(".shift-candidates")).not.toContainText(/(^|[ ·])F_Filter_Ok($|[ ·])/);
  await expect(cardA).toContainText("원인 가설");
  expect(investigationRequests).toContain("inv_case_A2");
  expect(investigationRequests).not.toContain("inv_case_A1");
  await expect(cardA).toContainText("미해결 업무 2건");
  await expect(cardA).toContainText("지지 1");
  await expect(cardA).toContainText("미평가 1");
  await expect(cardA).toContainText("수락됨");
  await expect(cardA).toContainText("인계 후 조사 변경: 있음");
  await expect(cardA).toContainText("새 분석: 추가됨");
  await expect(cardA).toContainText("인계 이후 조사 내용 변경");
  await expect(page.getByRole("article", { name: "Case case_B" })).toContainText("인계 수락 대기");
  await page.getByRole("button", { name: "내 담당" }).click();
  await expect(page.getByRole("article", { name: "Case case_A" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Case case_B" })).toHaveCount(0);
  await page.getByRole("textbox", { name: "담당자 / 교대" }).fill("Shift C");
  await expect(page.getByRole("article", { name: "Case case_B" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Case case_A" })).toHaveCount(0);
  await page.getByRole("button", { name: "인계 대기" }).click();
  await expect(page.getByRole("article", { name: "Case case_B" })).toBeVisible();
  await page.getByRole("button", { name: "최근 변경" }).click();
  await expect(page.getByRole("article", { name: "Case case_A" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Case case_B" })).toHaveCount(0);
  await page.getByRole("button", { name: "확인 필요", exact: true }).click();
  await expect(page.getByRole("article", { name: "Case case_A" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Case case_B" })).toBeVisible();
  await page.getByRole("combobox", { name: "Case sort" }).selectOption("unresolved");
  await expect(page.locator(".shift-case-card").first()).toHaveAttribute("aria-label", "Case case_A");
  await page.getByRole("button", { name: "전체 Case" }).click();
  await page.getByRole("combobox", { name: "Case status" }).selectOption("closed");
  await expect(page.getByRole("article", { name: "Case case_C" })).toBeVisible();
  await page.getByRole("combobox", { name: "Case status" }).selectOption("all");
  await page.getByRole("article", { name: "Case case_A" }).getByRole("button", { name: "Case 이어서 조사" }).click();
  await expect(page.getByRole("region", { name: "사건 상세" })).toBeVisible();
  await expect(page.getByRole("region", { name: "사건 상세" })).toContainText("Packet 발행 당시");
  await expect(page.getByRole("region", { name: "사건 상세" })).toContainText("case_A2");
  expect(resumeCalls).toBeGreaterThanOrEqual(3);
  expect(serverWorkspaceCalls).toBe(0);
});
