import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { request as httpRequest } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import { createAppServer } from "./server.mjs";

async function listen(server) {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  return `http://127.0.0.1:${address.port}`;
}

async function withPublicDir(callback) {
  const publicDir = await mkdtemp(join(tmpdir(), "mfg-ui-"));
  await writeFile(
    join(publicDir, "index.html"),
    '<!doctype html><html><body><div id="root">app-shell</div></body></html>',
  );
  await writeFile(join(publicDir, "app.txt"), "plain file");
  await mkdir(join(publicDir, "assets"));
  await writeFile(
    join(publicDir, "assets", "app.12345678.js"),
    "console.log('hashed')",
  );
  try {
    await callback(publicDir);
  } finally {
    await rm(publicDir, { force: true, recursive: true });
  }
}

async function withBackend(handler, callback) {
  const requests = [];
  const backend = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) {
      chunks.push(chunk);
    }
    const body = Buffer.concat(chunks).toString("utf8");
    requests.push({
      body,
      headers: request.headers,
      method: request.method,
      url: request.url,
    });
    await handler(request, response, body);
  });
  const backendUrl = await listen(backend);
  try {
    await callback(backendUrl, requests);
  } finally {
    await new Promise((resolve) => backend.close(resolve));
  }
}

async function withApp(options, callback) {
  const app = createAppServer(options);
  const origin = await listen(app);
  try {
    await callback(origin);
  } finally {
    await new Promise((resolve) => app.close(resolve));
  }
}

async function rawRequest(origin, options = {}) {
  const originUrl = new URL(origin);
  const body = options.body ?? "";
  return await new Promise((resolve, reject) => {
    const request = httpRequest(
      {
        headers: options.headers,
        hostname: originUrl.hostname,
        method: options.method ?? "GET",
        path: options.path ?? "/",
        port: originUrl.port,
        protocol: originUrl.protocol,
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => {
          resolve({
            body: Buffer.concat(chunks).toString("utf8"),
            headers: response.headers,
            statusCode: response.statusCode,
          });
        });
      },
    );
    request.on("error", reject);
    if (body) {
      request.write(body);
    }
    request.end();
  });
}

test("serves health checks and static SPA files", async () => {
  await withPublicDir(async (publicDir) => {
    await withApp({ publicDir }, async (origin) => {
      const health = await fetch(`${origin}/_stcore/health`);
      assert.equal(health.status, 200);
      assert.deepEqual(await health.json(), { status: "ok" });

      const index = await fetch(`${origin}/`);
      assert.equal(index.status, 200);
      assert.equal(index.headers.get("cache-control"), "no-cache");
      assert.match(await index.text(), /app-shell/);

      const fallback = await fetch(`${origin}/investigations/abc`);
      assert.equal(fallback.status, 200);
      assert.match(await fallback.text(), /app-shell/);
    });
  });
});

test("sets immutable cache only for hashed assets", async () => {
  await withPublicDir(async (publicDir) => {
    await withApp({ publicDir }, async (origin) => {
      const plain = await fetch(`${origin}/app.txt`);
      assert.equal(plain.status, 200);
      assert.equal(plain.headers.get("cache-control"), "no-cache");

      const hashed = await fetch(`${origin}/assets/app.12345678.js`);
      assert.equal(hashed.status, 200);
      assert.equal(
        hashed.headers.get("cache-control"),
        "public, max-age=31536000, immutable",
      );
    });
  });
});

test("proxies allowlisted API paths with server-side backend token only", async () => {
  await withBackend(
    (request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: true }));
    },
    async (backendUrl, requests) => {
      await withPublicDir(async (publicDir) => {
        await withApp(
          { apiToken: "server-secret", backendUrl, publicDir },
          async (origin) => {
            const response = await fetch(`${origin}/api/health`);
            assert.equal(response.status, 200);
            assert.deepEqual(await response.json(), { ok: true });
            assert.equal(requests.length, 1);
            assert.equal(requests[0].url, "/api/health");
            assert.equal(
              requests[0].headers.authorization,
              "Bearer server-secret",
            );
            assert.equal(response.headers.get("authorization"), null);
            assert.doesNotMatch(
              JSON.stringify(Object.fromEntries(response.headers)),
              /server-secret/,
            );
          },
        );
      });
    },
  );
});

test("does not proxy unknown API routes with backend credentials", async () => {
  await withBackend(
    (request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ shouldNotReach: true }));
    },
    async (backendUrl, requests) => {
      await withPublicDir(async (publicDir) => {
        await withApp(
          { apiToken: "server-secret", backendUrl, publicDir },
          async (origin) => {
            const response = await fetch(`${origin}/api/admin/export`);
            assert.equal(response.status, 404);
            assert.equal(requests.length, 0);
            assert.doesNotMatch(await response.text(), /server-secret/);

            const encodedSlash = await fetch(
              `${origin}/api/incidents/incident%2Fsecret`,
            );
            assert.equal(encodedSlash.status, 404);
            assert.equal(requests.length, 0);
          },
        );
      });
    },
  );
});

test("requires same-origin Origin header for proxied POST requests", async () => {
  await withBackend(
    (request, response) => {
      response.writeHead(201, { "content-type": "application/json" });
      response.end(JSON.stringify({ bodyAccepted: true }));
    },
    async (backendUrl, requests) => {
      await withPublicDir(async (publicDir) => {
        await withApp({ backendUrl, publicDir }, async (origin) => {
          const denied = await fetch(
            `${origin}/api/incidents/1/investigations`,
            {
              body: "{}",
              headers: {
                "content-type": "application/json",
                origin: "https://evil.example",
              },
              method: "POST",
            },
          );
          assert.equal(denied.status, 403);
          assert.equal(requests.length, 0);

          const accepted = await fetch(
            `${origin}/api/incidents/1/investigations`,
            {
              body: '{"run":true}',
              headers: { "content-type": "application/json", origin },
              method: "POST",
            },
          );
          assert.equal(accepted.status, 201);
          assert.deepEqual(await accepted.json(), { bodyAccepted: true });
          assert.equal(requests.length, 1);
          assert.equal(requests[0].body, '{"run":true}');
        });
      });
    },
  );
});

test("proxies the case-orchestration API contract", async () => {
  await withBackend(
    (request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: true }));
    },
    async (backendUrl, requests) => {
      await withPublicDir(async (publicDir) => {
        await withApp({ backendUrl, publicDir }, async (origin) => {
          const routes = [
            { method: "GET", path: "/api/cases" },
            { method: "GET", path: "/api/shift-workspace?assignee=Shift%20B&status=action_required" },
            { method: "GET", path: "/api/cases/case-1" },
            { method: "GET", path: "/api/cases/case-1/structuring-proposals" },
            { method: "POST", path: "/api/incidents/1/cases" },
            { method: "POST", path: "/api/cases/case-1/structuring-proposals" },
            {
              method: "POST",
              path: "/api/cases/case-1/structuring-proposals/proposal-1/accept",
            },
            {
              method: "POST",
              path: "/api/cases/case-1/structuring-proposals/proposal-1/dismiss",
            },
            {
              method: "POST",
              path: "/api/cases/case-1/tasks/task-1/responses",
            },
            { method: "POST", path: "/api/cases/case-1/reviews" },
            { method: "GET", path: "/api/cases/case-1/resume" },
            { method: "POST", path: "/api/cases/case-1/observations" },
            { method: "POST", path: "/api/cases/case-1/analysis-runs" },
            { method: "POST", path: "/api/cases/case-1/open-items" },
            { method: "POST", path: "/api/cases/case-1/open-items/item-1/updates" },
            { method: "POST", path: "/api/cases/case-1/hypotheses/hyp-1/assessments" },
            { method: "POST", path: "/api/cases/case-1/handover-checks" },
            { method: "POST", path: "/api/cases/case-1/chat" },
            { method: "POST", path: "/api/cases/case-1/handovers" },
            { method: "POST", path: "/api/cases/case-1/handovers/h-1/acceptance" },
            { method: "POST", path: "/api/cases/case-1/handovers/h-1/change-requests" },
          ];

          for (const route of routes) {
            const response = await fetch(`${origin}${route.path}`, {
              body: route.method === "POST" ? "{}" : undefined,
              headers:
                route.method === "POST"
                  ? { "content-type": "application/json", origin }
                  : undefined,
              method: route.method,
            });
            assert.equal(response.status, 200, `${route.method} ${route.path}`);
          }

          assert.deepEqual(
            requests.map((request) => request.url),
            routes.map((route) => route.path),
          );
        });
      });
    },
  );
});

test("accepts POST through an ingress when Origin and Host match", async () => {
  await withBackend(
    (request, response) => {
      response.writeHead(202, { "content-type": "application/json" });
      response.end(JSON.stringify({ accepted: true }));
    },
    async (backendUrl, requests) => {
      await withPublicDir(async (publicDir) => {
        await withApp({ backendUrl, publicDir }, async (origin) => {
          const response = await rawRequest(origin, {
            body: "{}",
            headers: {
              "content-length": "2",
              "content-type": "application/json",
              host: "frontend.example.com",
              origin: "https://frontend.example.com",
            },
            method: "POST",
            path: "/api/investigations/inv-1/chat",
          });
          assert.equal(response.statusCode, 202);
          assert.deepEqual(JSON.parse(response.body), { accepted: true });
          assert.equal(requests.length, 1);
          assert.equal(requests[0].url, "/api/investigations/inv-1/chat");
        });
      });
    },
  );
});

test("rejects oversized proxied bodies before hitting upstream", async () => {
  await withBackend(
    (request, response) => {
      response.writeHead(200);
      response.end("unexpected");
    },
    async (backendUrl, requests) => {
      await withPublicDir(async (publicDir) => {
        await withApp({ backendUrl, publicDir }, async (origin) => {
          const response = await fetch(
            `${origin}/api/incidents/1/investigations`,
            {
              body: "x".repeat(65 * 1024),
              headers: { origin },
              method: "POST",
            },
          );
          assert.equal(response.status, 413);
          assert.equal(requests.length, 0);
        });
      });
    },
  );
});

test("does not expose upstream failures or allow path traversal", async () => {
  await withBackend(
    (request, response) => {
      response.destroy(new Error("server-secret"));
    },
    async (backendUrl) => {
      await withPublicDir(async (publicDir) => {
        await withApp(
          { apiToken: "server-secret", backendUrl, publicDir },
          async (origin) => {
            const upstreamFailure = await fetch(`${origin}/api/health`);
            assert.equal(upstreamFailure.status, 502);
            assert.doesNotMatch(await upstreamFailure.text(), /server-secret/);

            const traversal = await rawRequest(origin, {
              path: "/%2e%2e/%2e%2e/etc/passwd",
            });
            assert.equal(traversal.statusCode, 400);
            assert.deepEqual(JSON.parse(traversal.body), {
              detail: "Invalid path",
            });
          },
        );
      });
    },
  );
});
