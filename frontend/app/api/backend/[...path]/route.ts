import { allowRequest } from "./policy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 30;

const MAX_REQUEST_BYTES = 64 * 1024;
const MAX_RESPONSE_BYTES = 4 * 1024 * 1024;
const UPSTREAM_TIMEOUT_MS = 20_000;

type RouteContext = { params: Promise<{ path: string[] }> };

function error(status: number, message: string): Response {
  return Response.json(
    { detail: message },
    {
      status,
      headers: {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    },
  );
}

function backendBase(): URL | null {
  const raw = process.env.BACKEND_API_URL;
  if (!raw) return null;

  try {
    const url = new URL(raw);
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}

async function boundedBody(request: Request): Promise<Uint8Array | null> {
  if (!request.body) return null;

  const declaredLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_REQUEST_BYTES) {
    throw new RangeError("request body too large");
  }

  return readBounded(request.body, MAX_REQUEST_BYTES);
}

async function readBounded(
  stream: ReadableStream<Uint8Array>,
  maximumBytes: number,
): Promise<Uint8Array> {
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > maximumBytes) {
        await reader.cancel();
        throw new RangeError("body too large");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const body = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

async function proxy(request: Request, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const incomingUrl = new URL(request.url);
  const allowed = allowRequest(request.method, path, incomingUrl.searchParams);
  if (!allowed) return error(404, "backend route not available");
  if (allowed.requiresModel && process.env.ENABLE_LIVE_MODEL_CALLS !== "1") {
    return error(503, "live model calls are disabled");
  }

  const base = backendBase();
  const bearer = process.env.BACKEND_BEARER_TOKEN?.trim();
  if (!base || !bearer || bearer.length > 4096 || /[\r\n]/.test(bearer)) {
    return error(503, "backend integration is not configured");
  }

  const upstream = new URL(base.toString());
  upstream.pathname = `${base.pathname.replace(/\/$/, "")}/${allowed.pathname}`;
  upstream.search = allowed.search;

  let body: Uint8Array | null = null;
  try {
    body = request.method === "POST" ? await boundedBody(request) : null;
  } catch (cause) {
    if (cause instanceof RangeError) return error(413, "request body too large");
    return error(400, "could not read request body");
  }

  if (body?.byteLength) {
    const contentType = request.headers.get("content-type")?.split(";", 1)[0].trim();
    if (contentType !== "application/json") return error(415, "only JSON request bodies are accepted");
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  request.signal.addEventListener("abort", () => controller.abort(), { once: true });

  try {
    const upstreamResponse = await fetch(upstream, {
      method: request.method,
      body: body?.byteLength ? new TextDecoder().decode(body) : undefined,
      headers: {
        Accept: "application/json, text/plain;q=0.9",
        Authorization: `Bearer ${bearer}`,
        ...(body?.byteLength ? { "Content-Type": "application/json" } : {}),
      },
      cache: "no-store",
      redirect: "manual",
      signal: controller.signal,
    });

    if (upstreamResponse.status >= 300 && upstreamResponse.status < 400) {
      return error(502, "backend redirect rejected");
    }

    const declaredLength = Number(upstreamResponse.headers.get("content-length"));
    if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
      return error(502, "backend response too large");
    }
    let responseBody: Uint8Array;
    try {
      responseBody = upstreamResponse.body
        ? await readBounded(upstreamResponse.body, MAX_RESPONSE_BYTES)
        : new Uint8Array();
    } catch (cause) {
      if (cause instanceof RangeError) return error(502, "backend response too large");
      throw cause;
    }

    const contentType = upstreamResponse.headers.get("content-type") ?? "application/json";
    return new Response(new TextDecoder().decode(responseBody), {
      status: upstreamResponse.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": contentType,
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (cause) {
    if (controller.signal.aborted) return error(504, "backend request timed out");
    console.error("Backend proxy request failed", cause instanceof Error ? cause.message : "unknown error");
    return error(502, "backend request failed");
  } finally {
    clearTimeout(timeout);
  }
}

export const GET = proxy;
export const POST = proxy;
