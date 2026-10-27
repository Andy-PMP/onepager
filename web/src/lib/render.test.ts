import { describe, expect, it } from "vitest";
import { chip, clipboardHtml, esc, renderExplanation, renderOnePager } from "./render";
import type { OnePager } from "./types";

const EVIL = `<img src=x onerror="alert(1)">`;

function onepager(overrides: Partial<OnePager> = {}): OnePager {
  return {
    project_name: "Atlas",
    reporting_period: null,
    as_of_date: "2026-10-15",
    overall: "red",
    overall_reason: "Worst known dimension: budget (red).",
    low_confidence: false,
    dimensions: [
      { dimension: "schedule", status: "green", rule: "schedule.on_track", reason: "No slips.", gaps: [] },
      { dimension: "budget", status: "red", rule: "budget.major_overrun", reason: "Forecast $120 vs $100.", gaps: [] },
      { dimension: "scope", status: "unknown", rule: "scope.not_mentioned", reason: "Not mentioned.", gaps: [] },
      { dimension: "risk", status: "amber", rule: "risk.high_managed", reason: "1 high item.", gaps: [] },
    ],
    gaps: ["No information on scope changes"],
    executive_summary: "Atlas is red.",
    accomplishments: ["Kickoff held"],
    next_steps: [],
    risks: [{ summary: "Vendor late", kind: "risk", impact: "high", owner: "Sam", mitigation: null }],
    asks: ["Approve overrun"],
    warnings: [],
    validation_problems: [],
    markdown: "# Atlas",
    meta: { model: "m", usage: { input_tokens: 5000, output_tokens: 1000, calls: 2 }, latency_ms: 4200 },
    ...overrides,
  };
}

describe("esc", () => {
  it("escapes every HTML-significant character", () => {
    expect(esc(`<a href="x" title='y'>&</a>`)).toBe("&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;");
  });
});

describe("renderOnePager", () => {
  it("never emits markup from the notes, in any field", () => {
    const p = onepager({
      project_name: EVIL,
      reporting_period: EVIL,
      executive_summary: EVIL,
      accomplishments: [EVIL],
      next_steps: [EVIL],
      asks: [EVIL],
      gaps: [EVIL],
      warnings: [EVIL],
      validation_problems: [EVIL],
      risks: [{ summary: EVIL, kind: "risk", impact: null, owner: EVIL, mitigation: EVIL }],
      dimensions: onepager().dimensions.map((d) => ({ ...d, reason: EVIL })),
    });
    for (const html of [renderOnePager(p, "live"), renderExplanation(p), clipboardHtml(p)]) {
      expect(html).not.toContain("<img");
      expect(html).toContain("&lt;img");
    }
  });

  it("shows every section with status labels as text, not just colour", () => {
    const html = renderOnePager(onepager(), "live");
    for (const text of ["Atlas", "As of 15 October 2026", "Executive summary", "Status by dimension",
      "Accomplishments this period", "Next steps", "Top risks and issues", "Decisions and asks for leadership",
      "Gaps in the notes"]) {
      expect(html).toContain(text);
    }
    expect(html).toContain(`chip chip-red chip-large`);
    expect(html).toMatch(/<span class="dot" aria-hidden="true"><\/span>Unknown/);
  });

  it("states missing owner and mitigation explicitly", () => {
    expect(renderOnePager(onepager(), "live")).toContain("High impact · Owner: Sam · Mitigation: not stated");
  });

  it("marks low confidence and warnings", () => {
    const html = renderOnePager(
      onepager({ low_confidence: true, warnings: ["Check figures."], validation_problems: ['Figure "9" isn\'t in the notes'] }),
      "live",
    );
    expect(html).toContain("Low confidence");
    expect(html).toContain("Check figures.");
    expect(html).toContain("Figure &quot;9&quot; isn&#39;t in the notes");
  });

  it("says where the result came from", () => {
    expect(renderOnePager(onepager(), "sample")).toContain("Pre-generated sample. No API call was made.");
    expect(renderOnePager(onepager(), "live")).toContain("Generated in 4.2s · 6,000 tokens · about 1.0¢");
  });

  it("uses the reporting period when there is one", () => {
    expect(renderOnePager(onepager({ reporting_period: "Week ending 9 October 2026" }), "live")).toContain(
      "Reporting period: Week ending 9 October 2026",
    );
  });

  it("handles empty lists", () => {
    const html = renderOnePager(onepager({ risks: [], asks: [], gaps: [] }), "live");
    expect(html).toContain("None listed.");
    expect(html).toContain("None.");
    expect(html).not.toContain("Gaps in the notes");
  });
});

describe("renderExplanation", () => {
  it("shows the rule that fired and the thresholds for each dimension", () => {
    const html = renderExplanation(onepager());
    expect(html).toContain("<code>budget.major_overrun</code>");
    expect(html).toContain("More than 10% over plan");
    expect(html).toContain("couldn't change the statuses");
  });
});

describe("clipboardHtml", () => {
  it("uses inline styles so the formatting survives pasting", () => {
    const html = clipboardHtml(onepager());
    expect(html).not.toContain("class=");
    expect(html).toContain("<table");
    expect(html).toContain("font-weight:600");
  });
});

describe("chip", () => {
  it("always includes the status word", () => {
    expect(chip("amber")).toContain(">Amber</span>");
  });
});
