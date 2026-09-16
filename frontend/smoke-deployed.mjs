// Bounded post-deploy check. Creates one deterministic investigation, no review or LLM call.
import { chromium, expect } from "@playwright/test";
const url = process.env.UI_TEST_URL;
if (!url?.startsWith("https://"))
  throw new Error("UI_TEST_URL must be the deployed HTTPS frontend");
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH,
});
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const response = await page.goto(url, {
    waitUntil: "networkidle",
    timeout: 45000,
  });
  await expect(page).toHaveTitle("Cluephase 클루페이즈 · 제조 이상 조사 워크스페이스");
  await expect(page.getByRole("link", { name: "Cluephase 클루페이즈 · 조사 홈" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "조사 워크스페이스" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "조사 실행", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: /최근 알람 발생 시점으로 이동/ })
    .click();
  const investigationResponse = page.waitForResponse(
    (r) => r.request().method() === "POST" && /\/investigations$/.test(r.url()),
  );
  await page.getByRole("button", { name: "조사 실행", exact: true }).click();
  const result = await investigationResponse;
  await expect(page.locator(".candidate").first()).toBeVisible({
    timeout: 35000,
  });
  await page.screenshot({
    path: "../docs/ui/deployed-workspace.png",
    fullPage: true,
  });
  const body = await result.json();
  if (errors.length) throw new Error(errors.join("\n"));
  console.log(
    JSON.stringify({
      url,
      http: response.status(),
      investigationHttp: result.status(),
      candidateCount: body.candidates.length,
      evidenceCount: body.evidence.length,
      llmStatus: body.llm_status,
      browserErrors: errors.length,
    }),
  );
} finally {
  await browser.close();
}
