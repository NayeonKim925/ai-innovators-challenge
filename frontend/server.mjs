import { createReadStream } from "node:fs";
import { access, readFile, stat } from "node:fs/promises";
import { createServer as createHttpServer } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const BODY_LIMIT_BYTES = 64 * 1024;
const UPSTREAM_TIMEOUT_MS = 30_000;
const DEFAULT_PORT = 8080;
const DEFAULT_BACKEND_URL = "http://localhost:8000";

const currentDir = fileURLToPath(new URL(".", import.meta.url));

const MIME_TYPES = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".ico", "image/x-icon"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".map", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".txt", "text/plain; charset=utf-8"],
  [".webp", "image/webp"],
  [".woff", "font/woff"],
  [".woff2", "font/woff2"],
]);

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
]);

const API_ROUTE_ALLOWLIST = [
  { method: "GET", pattern: /^\/api\/health$/ },
  { method: "GET", pattern: /^\/api\/datasets$/ },
  { method: "GET", pattern: /^\/api\/incidents$/ },
  { method: "GET", pattern: /^\/api\/incidents\/[^/]+$/ },
  { method: "POST", pattern: /^\/api\/incidents\/[^/]+\/investigations$/ },
  { method: "POST", pattern: /^\/api\/incidents\/[^/]+\/cases$/ },
  { method: "GET", pattern: /^\/api\/investigations\/[^/]+$/ },
  { method: "POST", pattern: /^\/api\/investigations\/[^/]+\/reviews$/ },
  { method: "GET", pattern: /^\/api\/investigations\/[^/]+\/report$/ },
  { method: "POST", pattern: /^\/api\/investigations\/[^/]+\/chat$/ },
  { method: "GET", pattern: /^\/api\/cases$/ },
  { method: "GET", pattern: /^\/api\/cases\/[^/]+$/ },
  { method: "POST", pattern: /^\/api\/cases\/[^/]+\/observations$/ },
  { method: "POST", pattern: /^\/api\/cases\/[^/]+\/analysis-runs$/ },
  { method: "POST", pattern: /^\/api\/cases\/[^/]+\/open-items$/ },
  { method: "POST", pattern: /^\/api\/cases\/[^/]+\/open-items\/[^/]+\/updates$/ },
  { method: "POST", pattern: /^\/api\/cases\/[^/]+\/hypotheses\/[^/]+\/assessments$/ },
  { method: "GET", pattern: /^\/api\/cases\/[^/]+\/resume$/ },
  { method: "POST", pattern: /^\/api\/cases\/[^/]+\/chat$/ },
  { method: "POST", pattern: /^\/api\/cases\/[^/]+\/handover-checks$/ },
  { method: "POST", pattern: /^\/api\/cases\/[^/]+\/handovers$/ },
  { method: "POST", pattern: /^\/api\/cases\/[^/]+\/handovers\/[^/]+\/acceptance$/ },
  { method: "POST", pattern: /^\/api\/cases\/[^/]+\/handovers\/[^/]+\/change-requests$/ },
  {
    method: "POST",
    pattern: /^\/api\/cases\/[^/]+\/tasks\/[^/]+\/responses$/,
  },
  { method: "POST", pattern: /^\/api\/cases\/[^/]+\/reviews$/ },
];

function getConfig(overrides = {}) {
  const publicDir = resolve(
    overrides.publicDir ?? process.env.PUBLIC_DIR ?? join(currentDir, "dist"),
  );
  const backendUrl = new URL(
    overrides.backendUrl ?? process.env.BACKEND_URL ?? DEFAULT_BACKEND_URL,
  );
  const apiToken = overrides.apiToken ?? process.env.BACKEND_API_TOKEN ?? "";
  const timeoutMs = overrides.timeoutMs ?? UPSTREAM_TIMEOUT_MS;

  return { apiToken, backendUrl, publicDir, timeoutMs };
}

function sendJson(response, statusCode, payload, extraHeaders = {}) {
  response.writeHead(statusCode, {
    "cache-control": "no-store",
    "content-type": "application/json; charset=utf-8",
    ...extraHeaders,
  });
  response.end(JSON.stringify(payload));
}

function isApiRequest(pathname) {
  return pathname === "/api" || pathname.startsWith("/api/");
}

function isAllowedApiRoute(method, pathname) {
  if (/%2f|%5c/i.test(pathname)) {
    return false;
  }

  try {
    decodeURIComponent(pathname);
  } catch {
    return false;
  }

  return API_ROUTE_ALLOWLIST.some(
    (route) => route.method === method && route.pattern.test(pathname),
  );
}

function isHealthRequest(pathname) {
  return pathname === "/healthz" || pathname === "/_stcore/health";
}

function hasSameOrigin(request) {
  const origin = request.headers.origin;
  const host = request.headers.host;
  if (!origin || !host) {
    return false;
  }

  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

function assertSafeStaticPath(publicDir, pathname) {
  let decodedPathname;
  try {
    decodedPathname = decodeURIComponent(pathname);
  } catch {
    return null;
  }
  if (decodedPathname.split(/[\\/]+/).includes("..")) {
    return null;
  }

  const normalizedPath = normalize(decodedPathname);
  if (
    normalizedPath.startsWith("..") ||
    normalizedPath.includes(`${sep}..${sep}`)
  ) {
    return null;
  }
  const relativePath =
    normalizedPath === sep
      ? "index.html"
      : normalizedPath.replace(/^[/\\]+/, "");
  const filePath = resolve(publicDir, relativePath);
  const rootWithSep = publicDir.endsWith(sep)
    ? publicDir
    : `${publicDir}${sep}`;

  if (filePath !== publicDir && !filePath.startsWith(rootWithSep)) {
    return null;
  }

  return filePath;
}

async function readRequestBody(request) {
  const contentLength = Number(request.headers["content-length"] ?? 0);
  if (contentLength > BODY_LIMIT_BYTES) {
    const error = new Error("Request body too large");
    error.statusCode = 413;
    throw error;
  }

  const chunks = [];
  let received = 0;
  for await (const chunk of request) {
    received += chunk.length;
    if (received > BODY_LIMIT_BYTES) {
      const error = new Error("Request body too large");
      error.statusCode = 413;
      throw error;
    }
    chunks.push(chunk);
  }

  return Buffer.concat(chunks);
}

function copyProxyHeaders(request, apiToken) {
  const headers = new Headers();
  for (const [name, value] of Object.entries(request.headers)) {
    const lowerName = name.toLowerCase();
    if (HOP_BY_HOP_HEADERS.has(lowerName) || lowerName === "origin") {
      continue;
    }
    if (lowerName === "authorization" || lowerName === "x-api-key") {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        headers.append(name, item);
      }
    } else if (value !== undefined) {
      headers.set(name, value);
    }
  }

  if (apiToken) {
    headers.set("authorization", `Bearer ${apiToken}`);
  }

  return headers;
}

async function proxyApiRequest(request, response, config) {
  const requestUrl = new URL(request.url, "http://localhost");
  if (!isApiRequest(requestUrl.pathname)) {
    sendJson(response, 404, { detail: "Not Found" });
    return;
  }

  if (!isAllowedApiRoute(request.method ?? "", requestUrl.pathname)) {
    sendJson(response, 404, { detail: "Not Found" });
    return;
  }

  if (request.method === "POST" && !hasSameOrigin(request)) {
    sendJson(response, 403, { detail: "Same-origin request required" });
    return;
  }

  let body;
  try {
    body = await readRequestBody(request);
  } catch (error) {
    sendJson(response, error.statusCode ?? 400, { detail: error.message });
    return;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), config.timeoutMs);
  const upstreamUrl = new URL(
    `${requestUrl.pathname}${requestUrl.search}`,
    config.backendUrl,
  );

  try {
    const upstreamResponse = await fetch(upstreamUrl, {
      body: ["GET", "HEAD"].includes(request.method ?? "") ? undefined : body,
      headers: copyProxyHeaders(request, config.apiToken),
      method: request.method,
      redirect: "manual",
      signal: controller.signal,
    });

    const responseHeaders = {};
    upstreamResponse.headers.forEach((value, name) => {
      if (!HOP_BY_HOP_HEADERS.has(name.toLowerCase())) {
        responseHeaders[name] = value;
      }
    });
    responseHeaders["cache-control"] = "no-store";

    response.writeHead(upstreamResponse.status, responseHeaders);
    if (upstreamResponse.body) {
      for await (const chunk of upstreamResponse.body) {
        response.write(chunk);
      }
    }
    response.end();
  } catch (error) {
    const statusCode = error.name === "AbortError" ? 504 : 502;
    sendJson(response, statusCode, {
      detail:
        statusCode === 504
          ? "Upstream request timed out"
          : "Upstream service unavailable",
    });
  } finally {
    clearTimeout(timeout);
  }
}

function isImmutableAsset(filePath) {
  const filename = filePath.split(sep).at(-1) ?? "";
  return (
    /\.[a-zA-Z0-9_-]{8,}\./.test(filename) &&
    filePath.includes(`${sep}assets${sep}`)
  );
}

async function sendStaticFile(response, filePath) {
  const fileStat = await stat(filePath);
  if (!fileStat.isFile()) {
    sendJson(response, 404, { detail: "Not Found" });
    return;
  }

  const headers = {
    "content-length": fileStat.size,
    "content-type":
      MIME_TYPES.get(extname(filePath)) ?? "application/octet-stream",
    "x-content-type-options": "nosniff",
  };
  if (isImmutableAsset(filePath)) {
    headers["cache-control"] = "public, max-age=31536000, immutable";
  } else {
    headers["cache-control"] = "no-cache";
  }

  response.writeHead(200, headers);
  createReadStream(filePath).pipe(response);
}

async function serveStaticRequest(request, response, config) {
  if (!["GET", "HEAD"].includes(request.method ?? "")) {
    response.writeHead(405, {
      allow: "GET, HEAD",
      "cache-control": "no-store",
    });
    response.end();
    return;
  }

  const requestUrl = new URL(request.url, "http://localhost");
  const filePath = assertSafeStaticPath(config.publicDir, requestUrl.pathname);
  if (!filePath) {
    sendJson(response, 400, { detail: "Invalid path" });
    return;
  }

  try {
    await access(filePath);
    if (request.method === "HEAD") {
      const fileStat = await stat(filePath);
      response.writeHead(200, {
        "cache-control": isImmutableAsset(filePath)
          ? "public, max-age=31536000, immutable"
          : "no-cache",
        "content-length": fileStat.size,
        "content-type":
          MIME_TYPES.get(extname(filePath)) ?? "application/octet-stream",
        "x-content-type-options": "nosniff",
      });
      response.end();
      return;
    }
    await sendStaticFile(response, filePath);
  } catch {
    const fallbackPath = join(config.publicDir, "index.html");
    try {
      const html = await readFile(fallbackPath);
      response.writeHead(200, {
        "cache-control": "no-cache",
        "content-length": html.length,
        "content-type": "text/html; charset=utf-8",
        "x-content-type-options": "nosniff",
      });
      response.end(html);
    } catch {
      sendJson(response, 404, { detail: "Frontend bundle not found" });
    }
  }
}

export function createAppServer(overrides = {}) {
  const config = getConfig(overrides);

  return createHttpServer(async (request, response) => {
    response.setHeader("x-content-type-options", "nosniff");
    response.setHeader("referrer-policy", "no-referrer");
    response.setHeader(
      "content-security-policy",
      "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    );
    // Check the raw target before WHATWG URL normalizes encoded dot segments.
    try {
      const rawPath = decodeURIComponent((request.url ?? "/").split("?")[0]);
      if (
        !rawPath.startsWith("/") ||
        rawPath.startsWith("//") ||
        rawPath.includes("\\") ||
        rawPath.includes("\0") ||
        rawPath.split("/").includes("..")
      ) {
        sendJson(response, 400, { detail: "Invalid path" });
        return;
      }
    } catch {
      sendJson(response, 400, { detail: "Invalid path" });
      return;
    }
    const requestUrl = new URL(request.url ?? "/", "http://localhost");

    if (isHealthRequest(requestUrl.pathname)) {
      sendJson(response, 200, { status: "ok" });
      return;
    }

    if (isApiRequest(requestUrl.pathname)) {
      await proxyApiRequest(request, response, config);
      return;
    }

    await serveStaticRequest(request, response, config);
  });
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  const port = Number(process.env.PORT ?? DEFAULT_PORT);
  const server = createAppServer();
  server.listen(port, "0.0.0.0", () => {
    console.log(`frontend server listening on :${port}`);
  });
}
