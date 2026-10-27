// Checks on what ships with the site: the pre-generated samples and the rules copy.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { formatCount, formatDate } from "./format";
import { THRESHOLDS } from "./rules";
import { SAMPLE_ORDER, loadSamples, samplesDir } from "./samples";

describe("shipped samples", () => {
  const samples = loadSamples();

  it("loads all four in order with readable names", () => {
    expect(samples.map((s) => s.id)).toEqual(SAMPLE_ORDER);
    expect(samples[0]!.name).toBe("Data center migration");
    expect(samples[0]!.format).toBe("Raw meeting notes");
  });

  it.each(SAMPLE_ORDER)("%s matches its labels and has no warnings", (id) => {
    const sample = samples.find((s) => s.id === id)!;
    const labels = JSON.parse(readFileSync(resolve(samplesDir(), `${id}.labels.json`), "utf8")) as {
      expected: Record<string, string | string[]>;
      expected_overall: string;
    };
    for (const d of sample.onepager.dimensions) {
      expect([labels.expected[d.dimension]].flat()).toContain(d.status);
    }
    expect(sample.onepager.overall).toBe(labels.expected_overall);
    expect(sample.onepager.warnings).toEqual([]);
  });

  it("are fictional inputs under the size limit", () => {
    for (const s of samples) expect(s.notes.length).toBeLessThanOrEqual(6000);
  });
});

describe("rules copy", () => {
  it("uses the same numbers as backend/onepager/thresholds.toml", () => {
    const toml = readFileSync(resolve(process.cwd(), "..", "backend", "onepager", "thresholds.toml"), "utf8");
    const value = (key: string) => Number(toml.match(new RegExp(`^${key}\\s*=\\s*(\\d+)`, "m"))![1]);
    expect(THRESHOLDS).toEqual({
      criticalSlipRedDays: value("critical_slip_red_days"),
      budgetGreenMaxPct: value("green_max_overrun_pct"),
      budgetAmberMaxPct: value("amber_max_overrun_pct"),
      lowConfidenceUnknownCount: value("low_confidence_unknown_count"),
    });
  });
});

describe("format", () => {
  it("formats the counter and dates", () => {
    expect(formatCount(1234)).toBe("1,234 / 6,000");
    expect(formatDate("2026-10-15")).toBe("15 October 2026");
    expect(formatDate("not a date")).toBe("not a date");
  });
});
