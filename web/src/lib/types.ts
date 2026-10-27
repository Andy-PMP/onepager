// The API response (backend/onepager/pipeline.py: assemble) and the samples built from it.

export type Status = "green" | "amber" | "red" | "unknown";
export type DimensionName = "schedule" | "budget" | "scope" | "risk";

export interface Dimension {
  dimension: DimensionName;
  status: Status;
  rule: string;
  reason: string;
  gaps: string[];
}

export interface RiskItem {
  summary: string;
  kind: string;
  impact: "high" | "medium" | "low" | null;
  owner: string | null;
  mitigation: string | null;
}

export interface OnePager {
  project_name: string | null;
  as_of_date: string | null;
  overall: Status;
  overall_reason: string;
  low_confidence: boolean;
  dimensions: Dimension[];
  gaps: string[];
  executive_summary: string;
  accomplishments: string[];
  next_steps: string[];
  risks: RiskItem[];
  asks: string[];
  /** Undecided choices the notes mention that aren't addressed to leadership. Missing in older responses. */
  open_decisions?: string[];
  warnings: string[];
  validation_problems: string[];
  markdown: string;
  meta: {
    model: string;
    usage: { input_tokens: number; output_tokens: number; calls: number };
    latency_ms: number;
  };
}

export interface Sample {
  id: string;
  name: string;
  format: string;
  notes: string;
  onepager: OnePager;
}
