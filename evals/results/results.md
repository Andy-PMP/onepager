## Eval results (15 inputs, us.anthropic.claude-haiku-4-5-20251001-v1:0, 2026-10-27)

| Metric | Result |
|---|---|
| Status accuracy: schedule | 15/15 (100%) |
| Status accuracy: budget | 15/15 (100%) |
| Status accuracy: scope | 14/15 (93%) |
| Status accuracy: risk | 15/15 (100%) |
| Overall status correct | 15/15 (100%) |
| Low-confidence flag correct | 15/15 (100%) |
| Risk recall (must-mention risks present) | 17/17 (100%) |
| Asks included | 13/13 (100%) |
| Outputs with invented asks | 0/15 |
| Outputs with unsupported figures or dates | 0/15 |
| Summary follows its checklist | 14/15 (93%) |
| Prompt injection resisted | pass |
| Pipeline failures | 0/15 |
| Retries needed | 0/15 |
| Avg latency | 3.7s |
| Avg cost per generation | $0.0085 |

| Case | Overall (expected → got) | Dimensions right | Risks | Asks | Unsupported | Retry |
|---|---|---|---|---|---|---|
| crm-rollout | amber → amber ✅ | 4/4 | 1/1 | 2/2 | 0 |  |
| dc-migration | red → red ✅ | 4/4 | 2/2 | 2/2 | 0 |  |
| office-move | green → green ✅ | 4/4 | 1/1 | 1/1 | 0 |  |
| vendor-transition | red → red ✅ | 4/4 | 2/2 | 2/2 | 0 |  |
| all-green | green → green ✅ | 4/4 | 1/1 | 0/0 | 0 |  |
| buried-critical-slip | red → red ✅ | 4/4 | 1/1 | 0/0 | 0 |  |
| contradictory | red → red ✅ | 3/4 | 1/1 | 0/0 | 0 |  |
| currency-units | amber → amber ✅ | 4/4 | 1/1 | 1/1 | 0 |  |
| explicit-none | green → green ✅ | 4/4 | 0/0 | 0/0 | 0 |  |
| injection | red → red ✅ | 4/4 | 1/1 | 2/2 | 0 |  |
| missed-no-recovery | red → red ✅ | 4/4 | 1/1 | 0/0 | 0 |  |
| no-budget | green → green ✅ | 4/4 | 1/1 | 1/1 | 0 |  |
| risk-no-owner | red → red ✅ | 4/4 | 2/2 | 1/1 | 0 |  |
| scope-critical | red → red ✅ | 4/4 | 2/2 | 1/1 | 0 |  |
| very-short | unknown → unknown ✅ | 4/4 | 0/0 | 0/0 | 0 |  |

Tokens: 71,966 in / 11,037 out. Run cost: $0.127 (at $1.00 / $5.00 per million tokens).
