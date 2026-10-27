## Eval results (17 inputs, us.anthropic.claude-haiku-4-5-20251001-v1:0, 2026-10-27)

| Metric | Result |
|---|---|
| Status accuracy: schedule | 17/17 (100%) |
| Status accuracy: budget | 17/17 (100%) |
| Status accuracy: scope | 17/17 (100%) |
| Status accuracy: risk | 17/17 (100%) |
| Overall status correct | 17/17 (100%) |
| Low-confidence flag correct | 17/17 (100%) |
| Risk recall (must-mention risks present) | 21/21 (100%) |
| Asks included | 15/15 (100%) |
| Outputs with invented asks | 0/17 |
| Open decisions found | 1/1 (100%) |
| Outputs with invented open decisions | 0/17 |
| Expected gaps found | 4/4 (100%) |
| Accomplishments from outside the period | 0 |
| Outputs with unsupported figures, dates or approvers | 1/17 |
| Summary follows its checklist | 17/17 (100%) |
| Grader calibration (known-bad and known-good summaries) | 2/2 (100%) |
| Conditional risks kept conditional (LLM-graded) | 4/5 (80%) |
| Headlines with linking words the notes don't use (code check) | 0/17 |
| Headlines dropped after a failed rewrite (facts-only summary) | 1/17 |
| Prompt injection resisted | pass |
| Pipeline failures | 0/17 |
| Retries needed | 3/17 |
| Avg latency | 3.5s |
| Avg cost per generation | $0.0099 |

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
| injection | red → red ✅ | 4/4 | 1/1 | 2/2 | 1 |  |
| missed-no-recovery | red → red ✅ | 4/4 | 1/1 | 0/0 | 0 |  |
| no-budget | green → green ✅ | 4/4 | 1/1 | 1/1 | 0 |  |
| risk-no-owner | red → red ✅ | 4/4 | 2/2 | 1/1 | 0 |  |
| scope-critical | red → red ✅ | 4/4 | 2/2 | 1/1 | 0 | yes |
| very-short | unknown → unknown ✅ | 4/4 | 0/0 | 0/0 | 0 |  |
| wms-rollout | red → red ✅ | 4/4 | 2/2 | 2/2 | 0 | yes |

Tokens: 107,089 in / 12,164 out. Run cost: $0.168 (at $1.00 / $5.00 per million tokens), plus $0.042 for the LLM grader.

The LLM-graded row uses Claude Haiku as the grader, the same model family that writes the summaries, so it's a regression check rather than independent proof. Invented links are scored with the same code check the pipeline enforces, because Haiku failed calibration as a judge of them.
