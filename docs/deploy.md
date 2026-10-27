# Deploying the API

Everything runs in **us-east-1** in account `733294945955`, deployed by the `automation` IAM user.

## One-time setup

### 1. Deployment permissions for `automation`

The policy in [deploy-policy.json](deploy-policy.json) is too large to add inline (IAM caps a user's inline policies at 2,048 characters), so create it as a managed policy:

1. Sign in as your admin user. Go to **IAM → Policies → Create policy → JSON**, paste `deploy-policy.json`, name it `onepager-deploy`.
2. **IAM → Users → automation → Add permissions → Attach policies directly**, select `onepager-deploy`.

The policy editor flags `apigateway:TagResource` and `apigateway:UntagResource` as unrecognized. Keep them and save anyway: CloudFormation needs `TagResource` to create the API stage, and the first deploy failed without it.

Every resource is scoped to names starting with `onepager` (plus SAM's own artifact bucket and stack). One caveat that comes with any deploy permission: a user who can create IAM roles and pass them to Lambda could, in principle, deploy a function with more access than they have. Here roles are limited to `onepager-*` and can only be passed to Lambda, which narrows that, but treat the `automation` access keys as sensitive.

### 2. SAM CLI and config

```powershell
py -3.14 -m venv .venv-sam
.\.venv-sam\Scripts\python -m pip install aws-sam-cli
```

`samconfig.toml` holds the IP-hash salt, so it's gitignored. It already exists on the original dev machine. Only on a fresh clone do you need to create it:

```powershell
.\.venv\Scripts\python scripts\make_samconfig.py   # won't overwrite an existing file
```

Reuse the same salt on every deploy; a new salt resets every visitor's daily count.

### 3. Budget alert ($5/month)

Budgets need billing access, so do this as your admin user in the console:

1. **Billing and Cost Management → Budgets → Create budget**.
2. Choose **Use a template → Monthly cost budget**.
3. Name `monthly-5-usd`, amount **$5.00**, your email address.
4. Create. The template emails you when actual spend passes 85% and 100%, and when forecast spend is expected to pass 100%.

This budget covers the whole account, not only this project. At the default caps the API's worst case is roughly $1/day if the daily cap is hit every day.

## Deploy

```powershell
$env:SAM_CLI_TELEMETRY = "0"
.\.venv-sam\Scripts\sam validate --lint
.\.venv-sam\Scripts\sam deploy           # shows the change set and asks before applying
```

No `sam build` step: the function has no third-party dependencies, so SAM zips `backend/` as is.

The `ApiUrl` output is the base URL until the custom domain is set up. Smoke test:

```powershell
$api = "<ApiUrl output>"
Invoke-RestMethod -Method Post -Uri "$api/generate" -ContentType "application/json" `
  -Body (@{ notes = Get-Content samples\office-move.txt -Raw } | ConvertTo-Json)
```

## What's deployed

| Resource | Settings |
|---|---|
| HTTP API | `POST /generate`; throttled to 2 req/s, burst 5; CORS for the site and localhost |
| Lambda | Python 3.13, arm64, 256 MB, 28s timeout (API Gateway's limit is 30s) |
| IAM role | `bedrock:InvokeModel` on the configured inference profile and its model only; `dynamodb:UpdateItem` on the usage table only |
| DynamoDB | On-demand; per-visitor and daily counters; TTL deletes visitor items after 48 hours |
| Log group | 14-day retention; logs hold sizes, tokens, latency, outcome and rule IDs, never notes or output |

Caps are parameters: `DailyCap` (100) and `PerVisitorCap` (5). Change them with `sam deploy --parameter-overrides DailyCap=50 IpHashSalt=...`, or in `samconfig.toml`.
