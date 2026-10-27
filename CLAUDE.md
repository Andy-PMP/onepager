# One-Pager Generator

Paste messy project notes, get an executive one-pager with RAG status. Portfolio piece for amandapatricks.com. Full brief in [plan.md](plan.md).

**Never commit or push. The user does that.**

## Decisions
- Hosting: subdomain `onepager.amandapatricks.com`, built from this repo like Neighborly (`../nearby`): Astro + TS in `web/`, GitHub Pages via Actions, Namecheap CNAME. API at `api.amandapatricks.com` (SAM, `template.yaml`). CORS: `onepager.` subdomain + localhost.
- Model: Claude Haiku 4.5 on Bedrock via the US inference profile `us.anthropic.claude-haiku-4-5-20251001-v1:0` (us-east-1), passed in the `MODEL_ID` env var. Haiku 5.5 is listed but blocked for this account (needs a company account to purchase), so don't retry it unless the user says access changed.
- AWS: local CLI uses the `automation` IAM user (default profile, us-east-1) with an inline `onepager-bedrock-dev` policy (list models + InvokeModel on Haiku) and the managed `onepager-deploy` policy from `docs/deploy-policy.json` (too big to be inline). Deploy steps: `docs/deploy.md`. SAM CLI lives in `.venv-sam`; no `sam build` (no deps, CodeUri is `backend/`, so tests live in top-level `tests/`). `samconfig.toml` holds the IP salt and is gitignored.
- Lambda has no third-party deps (stdlib + boto3), so `sam build` on Windows doesn't need a container.
- Rules decide status, the LLM only extracts and writes. Thresholds live in `backend/onepager/thresholds.toml`.
- Facts convention: `None` = not mentioned, `[]` = notes say there are none. Rules rely on it for Unknown vs Green.
- OK to add prose table styling to `../mywebsite/src/pages/projects/[id].astro` for the project write-up (phase 8).
- Pause after phase 4 (evals) to show results before deploying.

## Deployed (phase 5, 2026-10-27)
- Stack `onepager` (us-east-1). API: `https://iw277o42g3.execute-api.us-east-1.amazonaws.com` (`POST /generate`), until `api.amandapatricks.com` is set up in phase 7.
- Log group `/aws/lambda/onepager-generate`; usage table `onepager-UsageTable-LCZJ7LKDD0TQ`.
- `sam deploy` asks for confirmation interactively, which the agent shell can't answer: run `sam deploy --no-execute-changeset`, review with `aws cloudformation describe-change-set`, then `aws cloudformation execute-change-set`.
- API Gateway throttling (2 rps / burst 5) is approximate; large bursts also hit the account's Lambda concurrency limit (503). The exact cost control is the DynamoDB caps.

## Environment
Windows 11, PowerShell. Python venv at `.venv` (local 3.14; code targets 3.12+).

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\ruff check backend

# One real run against Bedrock (costs ~1 cent)
$env:MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"; $env:PYTHONPATH = "backend"
.\.venv\Scripts\python -m onepager.cli samples\dc-migration.txt          # Markdown; add --json for everything
```
Eval (all 15 inputs, ~13 cents, ~1 min): `.\.venv\Scripts\python evals\run_eval.py` → `evals/results/results.md` + `latest.json`. `evals/results/baseline.md` is the first run before prompt tuning (keep for the project page's before/after). Runs at temperature 0 have been identical run-to-run, so a changed result means a changed prompt.

Prompts live in `backend/onepager/prompts/`. The write step only produces the executive summary (Haiku 4.5 garbled multi-array tool calls); lists come from extraction.
