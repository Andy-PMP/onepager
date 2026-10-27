import type { DimensionName, OnePager, Status } from "./types";

export const MAX_CHARS = 6000;

// Claude Haiku 4.5 on Bedrock, USD per million tokens.
const PRICE_IN_PER_M = 1;
const PRICE_OUT_PER_M = 5;

export const STATUS_LABEL: Record<Status, string> = {
  green: "Green",
  amber: "Amber",
  red: "Red",
  unknown: "Unknown",
};

export const DIMENSION_LABEL: Record<DimensionName, string> = {
  schedule: "Schedule",
  budget: "Budget",
  scope: "Scope",
  risk: "Risk",
};

export function formatCount(n: number): string {
  return `${n.toLocaleString("en-US")} / ${MAX_CHARS.toLocaleString("en-US")}`;
}

/** "2026-10-15" → "15 October 2026" (UTC, so it never shifts a day). */
export function formatDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}

export function periodLine(p: OnePager): string | null {
  if (p.reporting_period) return `Reporting period: ${p.reporting_period}`;
  if (p.as_of_date) return `As of ${formatDate(p.as_of_date)}`;
  return null;
}

export function costCents(p: OnePager): number {
  const { input_tokens, output_tokens } = p.meta.usage;
  return ((input_tokens / 1e6) * PRICE_IN_PER_M + (output_tokens / 1e6) * PRICE_OUT_PER_M) * 100;
}

/** "Generated in 4.2s · 6,498 tokens · about 0.9¢" */
export function usageLine(p: OnePager): string {
  const tokens = p.meta.usage.input_tokens + p.meta.usage.output_tokens;
  return [
    `Generated in ${(p.meta.latency_ms / 1000).toFixed(1)}s`,
    `${tokens.toLocaleString("en-US")} tokens`,
    `about ${costCents(p).toFixed(1)}¢`,
  ].join(" · ");
}
