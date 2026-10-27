import { describe, expect, it } from "vitest";
import { generateOnePager } from "./api";

function fakeFetch(status: number, body: unknown, raw = false): typeof fetch {
  return (async () =>
    new Response(raw ? String(body) : JSON.stringify(body), {
      status,
      headers: { "content-type": raw ? "text/html" : "application/json" },
    })) as typeof fetch;
}

describe("generateOnePager", () => {
  it("sends the notes as JSON to /generate", async () => {
    let seen: { url: string; init: RequestInit } | null = null;
    const fetchFn = (async (url: string, init: RequestInit) => {
      seen = { url, init };
      return new Response(JSON.stringify({ dimensions: [] }), { status: 200 });
    }) as unknown as typeof fetch;
    const result = await generateOnePager("https://api.example.com/", "my notes", fetchFn);
    expect(result.ok).toBe(true);
    expect(seen!.url).toBe("https://api.example.com/generate");
    expect(seen!.init.method).toBe("POST");
    expect(JSON.parse(seen!.init.body as string)).toEqual({ notes: "my notes" });
  });

  it("passes through our own error messages (400, caps, pipeline failures)", async () => {
    for (const [status, error] of [
      [400, "Notes are limited to 6,000 characters."],
      [429, "You've used today's 5 generations. Try a sample, or come back tomorrow."],
      [502, "Couldn't read the notes. Please try again, or try a sample."],
    ] as const) {
      expect(await generateOnePager("x", "n", fakeFetch(status, { error }))).toEqual({ ok: false, message: error });
    }
  });

  it("replaces API Gateway's own wording", async () => {
    const throttled = await generateOnePager("x", "n", fakeFetch(429, { message: "Too Many Requests" }));
    expect(throttled).toEqual({ ok: false, message: expect.stringContaining("Wait a few seconds") });
    const unavailable = await generateOnePager("x", "n", fakeFetch(503, { message: "Service Unavailable" }));
    expect(unavailable).toEqual({ ok: false, message: expect.stringContaining("try a sample") });
  });

  it("handles non-JSON responses", async () => {
    const result = await generateOnePager("x", "n", fakeFetch(500, "<html>oops</html>", true));
    expect(result.ok).toBe(false);
  });

  it("handles network failures", async () => {
    const fetchFn = (async () => {
      throw new TypeError("Failed to fetch");
    }) as typeof fetch;
    expect(await generateOnePager("x", "n", fetchFn)).toEqual({
      ok: false,
      message: expect.stringContaining("Couldn't reach"),
    });
  });

  it("times out", async () => {
    const fetchFn = ((_: string, init: RequestInit) =>
      new Promise((_, reject) =>
        init.signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))),
      )) as unknown as typeof fetch;
    expect(await generateOnePager("x", "n", fetchFn, 10)).toEqual({
      ok: false,
      message: expect.stringContaining("took too long"),
    });
  });
});
