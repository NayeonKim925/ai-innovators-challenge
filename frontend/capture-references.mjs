import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
const dir = "../.lazyweb/quick-references/investigation-2026-09-17/references";
await mkdir(dir, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
for (const [name, url] of [
  ["linear", "https://linear.app/features"],
  ["metabase", "https://www.metabase.com/features/drill-through"],
  [
    "grafana",
    "https://grafana.com/docs/grafana/latest/visualizations/explore/",
  ],
]) {
  try {
    await page.goto(url, { waitUntil: "load", timeout: 30000 });
    await page
      .locator("h1")
      .first()
      .waitFor({ state: "visible", timeout: 10000 });
    await page.screenshot({
      path: `${dir}/${name}.png`,
      fullPage: false,
      animations: "disabled",
    });
    console.log(`${name}: ${page.url()}`);
  } catch (e) {
    console.log(`${name}: ${e.message}`);
  }
}
await browser.close();
