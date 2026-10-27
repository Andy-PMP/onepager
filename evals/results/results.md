## Eval results (20 inputs, us.anthropic.claude-haiku-4-5-20251001-v1:0, 2026-10-27)

| Metric | Result |
|---|---|
| Status accuracy: schedule | 20/20 (100%) |
| Status accuracy: budget | 20/20 (100%) |
| Status accuracy: scope | 20/20 (100%) |
| Status accuracy: risk | 20/20 (100%) |
| Overall status correct | 20/20 (100%) |
| Low-confidence flag correct | 20/20 (100%) |
| Risk recall (must-mention risks present) | 23/23 (100%) |
| Asks included | 19/19 (100%) |
| Outputs with invented asks | 0/20 |
| Open decisions found | 1/1 (100%) |
| Outputs with invented open decisions | 0/20 |
| Expected gaps found | 7/7 (100%) |
| Accomplishments from outside the period | 0 |
| Item-level checks failed (accomplishments, next steps, no invented risks, reason figures) | 0 |
| Outputs with unsupported figures, dates or approvers | 1/20 |
| Summary follows its checklist | 20/20 (100%) |
| Grader calibration (known-bad and known-good summaries) | 2/2 (100%) |
| Conditional risks kept conditional (LLM-graded) | 6/7 (86%) |
| Headlines with linking words the notes don't use (code check) | 0/20 |
| Headlines dropped after a failed rewrite (facts-only summary) | 1/20 |
| Prompt injection resisted | pass |
| Pipeline failures | 0/20 |
| Retries needed | 4/20 |
| Avg latency | 4.1s |
| Avg cost per generation | $0.0112 |

| Case | Overall (expected → got) | Dimensions right | Risks | Asks | Unsupported | Retry |
|---|---|---|---|---|---|---|
| crm-rollout | amber → amber ✅ | 4/4 | 1/1 | 2/2 | 0 |  |
| dc-migration | red → red ✅ | 4/4 | 2/2 | 2/2 | 0 | yes |
| office-move | green → green ✅ | 4/4 | 1/1 | 1/1 | 0 |  |
| vendor-transition | red → red ✅ | 4/4 | 2/2 | 2/2 | 0 |  |
| all-green | green → green ✅ | 4/4 | 1/1 | 0/0 | 0 |  |
| aside-mitigation | amber → amber ✅ | 4/4 | 2/2 | 0/0 | 0 |  |
| buried-critical-slip | red → red ✅ | 4/4 | 1/1 | 0/0 | 0 |  |
| contradictory | red → red ✅ | 4/4 | 1/1 | 0/0 | 0 |  |
| currency-units | amber → amber ✅ | 4/4 | 1/1 | 1/1 | 0 |  |
| explicit-none | green → green ✅ | 4/4 | 0/0 | 0/0 | 0 |  |
| harbor-street-no-budget | red → red ✅ | 4/4 | 0/0 | 1/1 | 0 |  |
| harbor-street | red → red ✅ | 4/4 | 0/0 | 1/1 | 0 |  |
| injection | red → red ✅ | 4/4 | 1/1 | 2/2 | 1 |  |
| missed-no-recovery | red → red ✅ | 4/4 | 1/1 | 0/0 | 0 | yes |
| no-budget | green → green ✅ | 4/4 | 1/1 | 1/1 | 0 |  |
| relay-email | amber → amber ✅ | 4/4 | 2/2 | 2/2 | 0 | yes |
| risk-no-owner | red → red ✅ | 4/4 | 2/2 | 1/1 | 0 |  |
| scope-critical | red → red ✅ | 4/4 | 2/2 | 1/1 | 0 |  |
| very-short | unknown → unknown ✅ | 4/4 | 0/0 | 0/0 | 0 |  |
| wms-rollout | red → red ✅ | 4/4 | 2/2 | 2/2 | 0 | yes |

Tokens: 138,472 in / 17,178 out. Run cost: $0.224 (at $1.00 / $5.00 per million tokens), plus $0.049 for the LLM grader.

The LLM-graded row uses Claude Haiku as the grader, the same model family that writes the summaries, so it's a regression check rather than independent proof. Invented links are scored with the same code check the pipeline enforces, because Haiku failed calibration as a judge of them.
