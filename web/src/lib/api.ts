// Calls POST /generate and turns every failure into a message a visitor can act on.

import type { OnePager } from "./types";

export type GenerateResult = { ok: true; onepager: OnePager } | { ok: false; message: string };

export const TIMEOUT_MS = 35_000;

const MESSAGES = {
  throttled: "Too many requests right now. Wait a few seconds and try again.",
  server: "The generator had a problem. Please try again, or try a sample.",
  network: "Couldn't reach the generator. Check your connection, or try a sample.",
  timeout: "That took too long. Please try again, or try a sample.",
};

export async function generateOnePager(
  apiBase: string,
  notes: string,
  fetchFn: typeof fetch = fetch,
  timeoutMs = TIMEOUT_MS,
): Promise<GenerateResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetchFn(`${apiBase.replace(/\/$/, "")}/generate`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ notes }),
      signal: controller.signal,
    });
  } catch (e) {
    return { ok: false, message: (e as Error).name === "AbortError" ? MESSAGES.timeout : MESSAGES.network };
  } finally {
    clearTimeout(timer);
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // non-JSON error page; fall through to the generic messages
  }
  if (response.ok && body && typeof body === "object" && "dimensions" in body) {
    return { ok: true, onepager: body as OnePager };
  }
  // Our handler returns {"error": "..."} written for visitors. API Gateway's own throttle
  // and error responses return {"message": "..."} in AWS wording, so those get our text instead.
  const error = body && typeof body === "object" && "error" in body ? String(body.error) : null;
  if (error) return { ok: false, message: error };
  return { ok: false, message: response.status === 429 ? MESSAGES.throttled : MESSAGES.server };
}
