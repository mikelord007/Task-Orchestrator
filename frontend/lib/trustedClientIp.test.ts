import assert from "node:assert/strict";
import test from "node:test";

import { GET } from "../app/api/backend/[...path]/route";
import { trustedVercelClientIp } from "../app/api/backend/[...path]/trustedClientIp";

test("accepts bounded Vercel-authored IPv4 and IPv6 addresses", () => {
  assert.equal(
    trustedVercelClientIp(new Headers({ "x-vercel-forwarded-for": "203.0.113.8" })),
    "203.0.113.8",
  );
  assert.equal(
    trustedVercelClientIp(new Headers({ "x-vercel-forwarded-for": "2001:db8::8" })),
    "2001:db8::8",
  );
});

test("uses the original address from a bounded forwarded chain", () => {
  assert.equal(
    trustedVercelClientIp(
      new Headers({ "x-vercel-forwarded-for": "203.0.113.8, 198.51.100.4" }),
    ),
    "203.0.113.8",
  );
});

test("rejects missing, malformed, and oversized values", () => {
  assert.equal(trustedVercelClientIp(new Headers()), null);
  assert.equal(
    trustedVercelClientIp(new Headers({ "x-vercel-forwarded-for": "not-an-ip" })),
    null,
  );
  assert.equal(
    trustedVercelClientIp(new Headers({ "x-vercel-forwarded-for": "1".repeat(257) })),
    null,
  );
});

test("proxy overwrites an untrusted browser identity with the Vercel address", async () => {
  const originalFetch = globalThis.fetch;
  const originalBackend = process.env.BACKEND_API_URL;
  const originalBearer = process.env.BACKEND_BEARER_TOKEN;
  let upstreamHeaders: Headers | undefined;

  process.env.BACKEND_API_URL = "https://backend.example.test";
  process.env.BACKEND_BEARER_TOKEN = "server-only-bearer";
  globalThis.fetch = async (_input, init) => {
    upstreamHeaders = new Headers(init?.headers);
    return Response.json([]);
  };

  try {
    const response = await GET(
      new Request("https://frontend.example.test/api/backend/agents", {
        headers: {
          "x-demo-client-ip": "198.51.100.99",
          "x-vercel-forwarded-for": "203.0.113.8",
        },
      }),
      { params: Promise.resolve({ path: ["agents"] }) },
    );

    assert.equal(response.status, 200);
    assert.equal(upstreamHeaders?.get("x-demo-client-ip"), "203.0.113.8");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalBackend === undefined) delete process.env.BACKEND_API_URL;
    else process.env.BACKEND_API_URL = originalBackend;
    if (originalBearer === undefined) delete process.env.BACKEND_BEARER_TOKEN;
    else process.env.BACKEND_BEARER_TOKEN = originalBearer;
  }
});
