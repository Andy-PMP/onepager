// Plain-language copy of the status rules for the "How status was decided" panel.
// The numbers must match backend/onepager/thresholds.toml; rules.test.ts checks that they do.

import type { DimensionName } from "./types";

export const THRESHOLDS = {
  criticalSlipRedDays: 14,
  budgetGreenMaxPct: 5,
  budgetAmberMaxPct: 10,
  lowConfidenceUnknownCount: 2,
};

const t = THRESHOLDS;

export const RULES: Record<DimensionName, { green: string; amber: string; red: string }> = {
  schedule: {
    green: "No milestone has slipped",
    amber: `A slip of up to ${t.criticalSlipRedDays} days, or any slip on a non-critical milestone`,
    red: `A critical milestone slipped more than ${t.criticalSlipRedDays} days, or a date was missed with no recovery plan`,
  },
  budget: {
    green: `Forecast within ${t.budgetGreenMaxPct}% of plan (or under)`,
    amber: `${t.budgetGreenMaxPct}–${t.budgetAmberMaxPct}% over plan`,
    red: `More than ${t.budgetAmberMaxPct}% over plan`,
  },
  scope: {
    green: "No unapproved changes",
    amber: "Change requests pending approval",
    red: "An unapproved change lands on a critical milestone",
  },
  risk: {
    green: "No open high-impact risks or issues",
    amber: "High-impact items, each with an owner and a mitigation",
    red: "A high-impact item is missing an owner or a mitigation",
  },
};

export const OVERALL_RULE =
  `Overall is the worst known dimension. A dimension with no data is Unknown, and ` +
  `${t.lowConfidenceUnknownCount} or more Unknowns make the overall status low-confidence.`;
