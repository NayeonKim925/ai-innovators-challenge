import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { brand } from "./src/brand.ts";

test("static metadata stays aligned with the public brand contract", async () => {
  const html = await readFile(new URL("./index.html", import.meta.url), "utf8");
  assert.ok(html.includes(`<title>${brand.name} ${brand.koreanName} · ${brand.descriptor}</title>`));
  assert.ok(html.includes(`name="description" content="${brand.description}"`));
  assert.ok(html.includes(`property="og:site_name" content="${brand.name}"`));
  assert.ok(html.includes(`property="og:title" content="${brand.name} · ${brand.tagline}"`));
  assert.ok(!html.includes("CausePilot"));
});
