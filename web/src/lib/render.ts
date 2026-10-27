// Builds the one-pager as HTML strings. Every value from the API passes through esc(): the
// output repeats text from the user's notes, which may contain markup.

import { DIMENSION_LABEL, STATUS_LABEL, periodLine, usageLine } from "./format";
import { OVERALL_RULE, RULES } from "./rules";
import type { OnePager, RiskItem, Status } from "./types";

export function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

export function chip(status: Status, size: "" | "large" = ""): string {
  return `<span class="chip chip-${status}${size ? ` chip-${size}` : ""}"><span class="dot" aria-hidden="true"></span>${STATUS_LABEL[status]}</span>`;
}

function list(items: string[], empty: string): string {
  if (!items.length) return `<p class="empty">${esc(empty)}</p>`;
  return `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
}

function riskMeta(r: RiskItem): string {
  const parts = [
    r.impact ? `${r.impact[0]!.toUpperCase()}${r.impact.slice(1)} impact` : "Impact not stated",
    `Owner: ${r.owner ?? "not stated"}`,
    `Mitigation: ${r.mitigation ?? "not stated"}`,
  ];
  return parts.map((x) => esc(x)).join(" · ");
}

/** The one-pager itself: what gets printed and copied. */
export function renderOnePager(p: OnePager, source: "sample" | "live"): string {
  const period = periodLine(p);
  const title = p.project_name ?? "Project status";
  const lowConfidence = p.low_confidence
    ? `<p class="low-confidence">Low confidence: the notes don't cover enough to be sure.</p>`
    : "";
  const warnings = p.warnings.length
    ? `<div class="warning" role="note"><strong>Check before using.</strong> ${p.warnings.map(esc).join(" ")}${
        p.validation_problems.length
          ? `<ul>${p.validation_problems.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`
          : ""
      }</div>`
    : "";
  const dims = p.dimensions
    .map(
      (d) =>
        `<tr><th scope="row">${DIMENSION_LABEL[d.dimension]}</th><td>${chip(d.status)}</td><td>${esc(d.reason)}</td></tr>`,
    )
    .join("");
  const risks = p.risks.length
    ? `<ul class="risks">${p.risks
        .map((r) => `<li><p class="risk-summary">${esc(r.summary)}</p><p class="risk-meta">${riskMeta(r)}</p></li>`)
        .join("")}</ul>`
    : `<p class="empty">None listed.</p>`;
  const gaps = p.gaps.length
    ? `<section class="gaps"><h3>Gaps in the notes</h3><p class="section-note">What a real status report would also need.</p>${list(p.gaps, "")}</section>`
    : "";
  const provenance =
    source === "sample" ? "Pre-generated sample. No API call was made." : esc(usageLine(p));

  return `<article class="doc" aria-labelledby="doc-title">
  <header class="doc-head">
    <div>
      ${period ? `<p class="doc-period">${esc(period)}</p>` : ""}
      <h2 id="doc-title">${esc(title)}</h2>
    </div>
    <div class="overall">
      <span class="overall-label">Overall status</span>
      ${chip(p.overall, "large")}
    </div>
  </header>
  ${lowConfidence}
  ${warnings}
  <section><h3>Executive summary</h3><p class="summary">${esc(p.executive_summary)}</p></section>
  <section>
    <h3>Status by dimension</h3>
    <div class="table-wrap"><table class="dims">
      <thead><tr><th scope="col">Dimension</th><th scope="col">Status</th><th scope="col">Why</th></tr></thead>
      <tbody>${dims}</tbody>
    </table></div>
  </section>
  <div class="two-col">
    <section><h3>Accomplishments this period</h3>${list(p.accomplishments, "None listed.")}</section>
    <section><h3>Next steps</h3>${list(p.next_steps, "None listed.")}</section>
  </div>
  <section><h3>Top risks and issues</h3>${risks}</section>
  <section><h3>Decisions and asks for leadership</h3>${list(p.asks, "None.")}</section>
  ${gaps}
  <p class="provenance">${provenance}</p>
</article>`;
}

/** The "How status was decided" panel: which rule fired for each dimension. */
export function renderExplanation(p: OnePager): string {
  const rows = p.dimensions
    .map((d) => {
      const rule = RULES[d.dimension];
      return `<li>
  <p class="explain-head"><strong>${DIMENSION_LABEL[d.dimension]}</strong> ${chip(d.status)} <code>${esc(d.rule)}</code></p>
  <p>${esc(d.reason)}</p>
  <p class="explain-rules">Green: ${esc(rule.green)}. Amber: ${esc(rule.amber)}. Red: ${esc(rule.red)}. Unknown: no data in the notes.</p>
</li>`;
    })
    .join("");
  return `<ol class="explain">${rows}</ol>
<p><strong>Overall: ${STATUS_LABEL[p.overall]}.</strong> ${esc(p.overall_reason)} ${esc(OVERALL_RULE)}</p>
<p class="section-note">These statuses come from fixed rules in code, applied to facts the AI extracted from the notes. The AI wrote the summary but couldn't change the statuses.</p>`;
}

// --- Rich copy for Word, Outlook and Google Docs: inline styles, since pasted HTML loses classes ---

const PASTE_COLORS: Record<Status, [string, string]> = {
  green: ["#1e6b34", "#e3f2e8"],
  amber: ["#7a4f00", "#fbefd5"],
  red: ["#a32019", "#fbe4e2"],
  unknown: ["#4a5060", "#eceef2"],
};

function pasteChip(status: Status): string {
  const [fg, bg] = PASTE_COLORS[status];
  return `<span style="color:${fg};background:${bg};font-weight:600;padding:1px 6px;border-radius:4px">${STATUS_LABEL[status]}</span>`;
}

export function clipboardHtml(p: OnePager): string {
  const cell = "border:1px solid #ccc;padding:4px 8px;text-align:left;vertical-align:top";
  const ul = (items: string[], empty: string) =>
    items.length ? `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p><i>${empty}</i></p>`;
  const period = periodLine(p);
  return `<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt">
<h1>${esc(p.project_name ?? "Project status")}</h1>
<p>${period ? `${esc(period)}<br>` : ""}<b>Overall status:</b> ${pasteChip(p.overall)}${p.low_confidence ? " (low confidence)" : ""}</p>
<h2>Executive summary</h2><p>${esc(p.executive_summary)}</p>
<h2>Status by dimension</h2>
<table style="border-collapse:collapse"><tr><th style="${cell}">Dimension</th><th style="${cell}">Status</th><th style="${cell}">Why</th></tr>
${p.dimensions.map((d) => `<tr><td style="${cell}">${DIMENSION_LABEL[d.dimension]}</td><td style="${cell}">${pasteChip(d.status)}</td><td style="${cell}">${esc(d.reason)}</td></tr>`).join("\n")}
</table>
<h2>Accomplishments this period</h2>${ul(p.accomplishments, "None listed")}
<h2>Next steps</h2>${ul(p.next_steps, "None listed")}
<h2>Top risks and issues</h2>${
    p.risks.length
      ? `<ul>${p.risks.map((r) => `<li><b>${esc(r.summary)}</b><br>${riskMeta(r)}</li>`).join("")}</ul>`
      : "<p><i>None listed</i></p>"
  }
<h2>Decisions and asks for leadership</h2>${ul(p.asks, "None")}
${p.gaps.length ? `<h2>Gaps in the notes</h2>${ul(p.gaps, "")}` : ""}
</div>`;
}
