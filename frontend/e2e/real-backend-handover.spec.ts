import { expect, test } from "@playwright/test";

test("real backend preserves the investigation across a shift handover", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page.getByRole("button", { name: /최근 알람 발생 시점으로 이동/ })).toBeVisible();
  await page.getByRole("button", { name: /최근 알람 발생 시점으로 이동/ }).click();
  await page.getByRole("button", { name: "조사 실행", exact: true }).click();
  await expect(page.locator(".candidate").first()).toBeVisible();

  await page.getByRole("button", { name: "확인 업무로 전환" }).click();
  await expect(page.getByRole("region", { name: "사건 인박스" })).toBeVisible();
  await expect(page.getByText("교대 인수인계 워크스페이스")).toBeVisible();

  const caseRegion = page.getByRole("region", { name: "사건 상세" });
  await expect(caseRegion).toContainText("현재 분석 Run");

  await caseRegion.getByLabel("작성자", { exact: true }).fill("Shift A");
  await caseRegion
    .getByLabel("관찰 원문", { exact: true })
    .fill("알람 이력 확인 완료. 현재 설비 상태에서 추가 진동 점검은 다음 교대에서 수행합니다.");
  await caseRegion.getByLabel("현재 설비 상태를 함께 확인한 기록입니다").check();
  await caseRegion.getByRole("button", { name: "관찰 기록" }).click();
  await expect(page.getByText("관찰 원문이 기록되었습니다.")).toBeVisible();

  await caseRegion.getByLabel("첫 Open Item 담당자", { exact: true }).fill("Shift B");
  await caseRegion.getByRole("button", { name: "담당자 지정" }).click();
  await expect(page.getByText("Open Item 담당자가 지정되었습니다.")).toBeVisible();

  await caseRegion.getByLabel("인계자", { exact: true }).fill("Shift A");
  await caseRegion.getByLabel("인수자", { exact: true }).fill("Shift B");
  await caseRegion.getByRole("button", { name: "사전 점검" }).click();
  await expect(page.getByText("인계 점검을 완료했습니다.")).toBeVisible();
  await expect(caseRegion.getByText("인계 점검 결과")).toBeVisible();

  await caseRegion.getByRole("button", { name: "Packet 발행" }).click();
  await expect(page.getByText(/최근 Handover Packet · published/)).toBeVisible();
  await expect(caseRegion).toContainText("Shift A → Shift B · published");
  const shiftWorkspace = page.getByRole("region", { name: "내 교대 업무" });
  await expect(shiftWorkspace).toContainText("인수 대기");
  await expect(shiftWorkspace).toContainText("내 Open Item");
  await expect(shiftWorkspace).toContainText("Shift B");

  const caseId = (
    await caseRegion.locator(".case-detail-heading p.mono").textContent()
  )?.trim();
  expect(caseId).toBeTruthy();

  const publishedCaseResponse = await page.request.get(`/api/cases/${caseId}`);
  expect(publishedCaseResponse.ok()).toBe(true);
  const publishedCase = await publishedCaseResponse.json();
  const publishedEvent = publishedCase.events.at(-1);
  expect(publishedEvent.event_type).toBe("handover_published");
  expect(publishedEvent.actor_id).toBe("e2e-shift-a");
  expect(publishedEvent.actor_role).toBe("operator");

  await caseRegion.getByRole("button", { name: "인수 확인" }).click();
  await expect(caseRegion).toContainText("Shift A → Shift B · accepted");

  const acceptedCaseResponse = await page.request.get(`/api/cases/${caseId}`);
  expect(acceptedCaseResponse.ok()).toBe(true);
  const acceptedCase = await acceptedCaseResponse.json();
  const acceptedEvent = acceptedCase.events.at(-1);
  expect(acceptedEvent.event_type).toBe("handover_accepted");
  expect(acceptedEvent.actor_id).toBe("e2e-shift-a");
  expect(acceptedEvent.actor_role).toBe("operator");
  expect(acceptedCase.handovers.at(-1).status).toBe("accepted");
});
