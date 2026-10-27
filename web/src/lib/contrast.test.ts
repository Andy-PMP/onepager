// WCAG AA contrast for every colour pairing the UI uses, in light and dark, read straight from
// global.css so a palette tweak can't silently break accessibility.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(fileURLToPath(new URL("../styles/global.css", import.meta.url)), "utf8");

function tokens(blockStart: string): Record<string, string> {
  const start = css.indexOf(blockStart);
  if (start < 0) throw new Error(`block not found: ${blockStart}`);
  const body = css.slice(start, css.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1]!, m[2]!]));
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

// [foreground, background, minimum ratio, where it's used]
const PAIRS: [string, string, number, string][] = [
  ["text", "bg", 4.5, "body text"],
  ["text", "surface", 4.5, "panels, the one-pager"],
  ["muted", "bg", 4.5, "footer, captions"],
  ["muted", "surface", 4.5, "notes, risk details, provenance"],
  ["accent", "bg", 4.5, "links, eyebrow"],
  ["accent", "surface", 4.5, "links in panels"],
  ["accent-text", "accent", 4.5, "primary button"],
  ["text", "accent-soft", 4.5, "notice, selected sample"],
  ["text", "amber-soft", 4.5, "warning and low-confidence banners"],
  ["text", "unknown-soft", 4.5, "gaps box"],
  ["green", "green-soft", 4.5, "Green chip"],
  ["amber", "amber-soft", 4.5, "Amber chip"],
  ["red", "red-soft", 4.5, "Red chip"],
  ["unknown", "unknown-soft", 4.5, "Unknown chip"],
  ["red", "surface", 4.5, "over-limit counter, error message"],
  ["control-border", "bg", 3, "textarea outline (WCAG 1.4.11)"],
];

const THEMES = {
  light: tokens(":root {"),
  "dark (device setting)": tokens(':root:not([data-theme="light"]) {'),
  "dark (toggle)": tokens(':root[data-theme="dark"] {'),
};

describe.each(Object.entries(THEMES))("%s theme", (_, t) => {
  it.each(PAIRS)("%s on %s ≥ %s:1 (%s)", (fg, bg, min) => {
    expect(t[fg], `missing --${fg}`).toBeDefined();
    expect(t[bg], `missing --${bg}`).toBeDefined();
    expect(contrast(t[fg]!, t[bg]!)).toBeGreaterThanOrEqual(min);
  });
});

describe("dark blocks", () => {
  it("are identical (device setting vs toggle)", () => {
    expect(THEMES["dark (toggle)"]).toEqual(THEMES["dark (device setting)"]);
  });
});
