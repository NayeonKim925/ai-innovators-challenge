import { test, expect } from "@playwright/test";

test("real data: investigate, inspect evidence, review, ask, export, restore", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/");
  await page.getByRole("button", { name: "새 사건 분석" }).click();
  await expect(page).toHaveTitle("Continuum 컨티뉴엄 · 제조 이상 조사·교대 연속성 워크스페이스");
  await expect(page.getByRole("link", { name: "Continuum 컨티뉴엄 · 조사 홈" })).toBeVisible();
  await expect(page.locator('meta[name="description"]')).toHaveAttribute("content", /Continuum\(컨티뉴엄\)/);
  await expect(
    page.getByRole("button", { name: "조사 실행", exact: true }),
  ).toBeEnabled();
  await expect(page.locator("tbody tr")).toHaveCount(100);
  await page.screenshot({
    path: "../docs/ui/desktop-workspace.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "조사 실행", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "우선 확인할 원인 후보" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "이 시점에는 원인 후보를 제안할 수 없습니다",
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: /최근 알람 발생 시점으로 이동/ })
    .click();
  await page.getByRole("button", { name: "조사 실행", exact: true }).click();
  await expect(page.locator(".candidate").first()).toBeVisible();
  await page.screenshot({
    path: "../docs/ui/desktop-results.png",
    fullPage: true,
  });
  await page.getByRole("tab", { name: "전문가 검토" }).click();
  await page.getByLabel("검토자", { exact: true }).fill("UI 검증");
  await page
    .getByLabel("검토 의견")
    .fill("공개 데이터 기반 UI 검증 기록입니다. 실제 공정 판단이 아닙니다.");
  await page.getByRole("button", { name: "검토 승인" }).click();
  await expect(page.getByText("전문가 검토가 저장되었습니다.")).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "보고서", exact: true }).click();
  const report = await download;
  expect(report.suggestedFilename()).toMatch(/^continuum-handover-.*\.md$/);
  const stream = await report.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  const reportText = Buffer.concat(chunks).toString("utf8");
  expect(reportText).toContain("# Continuum · 제조 이상 조사·교대 인수인계 보고서");
  expect(reportText).toContain("근무는 끝나도, 조사는 끊기면 안 됩니다.");
  expect(reportText).toContain("확정된 원인이나 설비 조작 지시가 아닙니다.");
  await page.getByRole("tab", { name: "근거에 질문" }).click();
  await page
    .getByLabel("조사 질문", { exact: true })
    .fill("첫 번째 후보의 근거를 설명해 주세요.");
  await page.getByRole("button", { name: "질문 보내기" }).click();
  await expect(page.locator(".chat-answer")).toBeVisible();
  await page.getByRole("button", { name: /^조사 기록/ }).click();
  await page.locator(".history-item").first().click();
  await expect(
    page.getByRole("heading", { name: "우선 확인할 원인 후보" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "전문가 검토" }).click();
  await expect(page.locator(".review-entry")).toHaveCount(1);
  expect(errors).toEqual([]);
  await page.getByRole("button", { name: "사용 안내", exact: true }).click();
  await expect(page.locator(".guide-brand")).toContainText("Continuum");
  await expect(page.locator(".brand-tagline")).toHaveText("근무는 끝나도, 조사는 끊기면 안 됩니다.");
  await page.locator(".guide-brand img").evaluate((image: HTMLImageElement) => image.decode());
  await page.screenshot({ path: "../docs/ui/brand-guide.png", fullPage: true });
});

test("mobile: layout, search, empty dataset and keyboard navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "새 사건 분석" }).click();
  await expect(page.getByRole("link", { name: "Continuum 컨티뉴엄 · 조사 홈" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "조사 실행", exact: true }),
  ).toBeEnabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../docs/ui/mobile-workspace.png",
    fullPage: true,
  });
  await page.getByLabel("사건 ID 검색").fill("not-found");
  await expect(
    page.getByRole("heading", { name: "검색 결과 없음" }),
  ).toBeVisible();
  await page.getByLabel("데이터셋", { exact: true }).selectOption("metal_etch");
  await page.getByLabel("사건 ID 검색").fill("");
  await expect(
    page.getByRole("heading", { name: "준비된 사건 없음" }),
  ).toBeVisible();
  await page.getByLabel("데이터셋", { exact: true }).selectOption("causrca");
  await expect(
    page.getByRole("button", { name: "조사 실행", exact: true }),
  ).toBeEnabled();
  await page.keyboard.press("Control+Home");
  await page.goto("/");
  await page.getByRole("button", { name: "새 사건 분석" }).click();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "본문으로 이동" })).toBeFocused();
});

test("API failure is actionable and retry recovers", async ({ page }) => {
  await page.route("**/api/incidents?*", (r) =>
    r.fulfill({ status: 503, contentType: "application/json", body: "{}" }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "새 사건 분석" }).click();
  await expect(page.getByRole("alert")).toContainText("서비스가 준비 중");
  await page.unroute("**/api/incidents?*");
  await page.getByRole("button", { name: "다시 시도" }).click();
  await expect(
    page.getByRole("button", { name: "조사 실행", exact: true }),
  ).toBeEnabled();
});

test("case orchestration requires evidence confirmation before closure", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("button", { name: "새 사건 분석" }).click();
  await page
    .getByRole("button", { name: /최근 알람 발생 시점으로 이동/ })
    .click();
  await page.getByRole("button", { name: "조사 실행", exact: true }).click();
  await expect(page.locator(".candidate").first()).toBeVisible();
  await page.getByRole("button", { name: "확인 업무로 전환" }).click();

  await expect(
    page.getByRole("region", { name: "Case 목록과 상세" }),
  ).toBeVisible();
  await expect(page.getByText("확인 업무")).toBeVisible();
  await page.locator(".task-form input").fill("E2E 공정 전문가");
  await page.locator(".task-form textarea").fill("공개 데이터 기반 확인 기록입니다.");
  await page.getByRole("button", { name: "응답 기록" }).click();

  await expect(page.getByText("최종 검토가 남아 있습니다")).toBeVisible();
  await page.getByPlaceholder("최종 검토자").fill("E2E 검토자");
  await page.getByRole("button", { name: "검토 승인 후 종료" }).click();
  await expect(
    page
      .getByRole("region", { name: "사건 상세" })
      .getByText("종료됨", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("전문가 승인 후 사건을 종료했습니다.")).toBeVisible();
  expect(errors).toEqual([]);
});

test("ledger summary and case navigation remain usable at narrow widths", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "새 사건 분석" }).click();
  const summary = page.getByLabel("조사 환경 요약");
  await expect(summary).toContainText("분석 데이터");
  await expect(summary).toContainText("진단 시점 이후 데이터 제외");
  await expect(page.locator(".incident-item").first()).toBeEnabled();
  await page.locator(".incident-item").nth(1).click();
  await expect(page.locator(".incident-item").nth(1)).toHaveAttribute("aria-pressed", "true");
  for (const width of [320, 390, 900, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.getByRole("button", { name: "조사 실행", exact: true })).toBeEnabled();
  }
  await page.getByRole("button", { name: /최근 알람 발생 시점으로 이동/ }).click();
  await page.getByRole("button", { name: "조사 실행", exact: true }).click();
  await expect(page.locator(".candidate").first()).toBeVisible();
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.locator(".evidence-panel")).toBeVisible();
  }
  await page.screenshot({ path: "../docs/ui/mobile-results.png", fullPage: true });
});
