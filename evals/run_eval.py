"""Run every sample and eval case through the real pipeline and report how it did.

    $env:MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    .\\.venv\\Scripts\\python evals\\run_eval.py                    # all 15 inputs, ~15-20 cents
    .\\.venv\\Scripts\\python evals\\run_eval.py --only injection   # one case

Writes evals/results/results.md (paste-ready tables) and evals/results/latest.json (full outputs,
retry reasons and scores for debugging).
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "evals")]

from onepager.bedrock import make_client  # noqa: E402
from onepager.pipeline import PipelineError, generate  # noqa: E402
from scoring import DIMENSIONS, score_case  # noqa: E402

# Claude Haiku 4.5 on Bedrock, USD per million tokens (confirmed October 2026).
PRICE_IN_PER_M = 1.00
PRICE_OUT_PER_M = 5.00


def load_cases(only: list[str] | None) -> list[dict]:
    cases = []
    for folder, kind in ((ROOT / "samples", "sample"), (ROOT / "evals" / "cases", "edge case")):
        for path in sorted(folder.glob("*.labels.json")):
            label = json.loads(path.read_text(encoding="utf-8"))
            if only and label["id"] not in only:
                continue
            notes = path.with_name(f"{label['id']}.txt").read_text(encoding="utf-8")
            cases.append({"id": label["id"], "kind": kind, "label": label, "notes": notes})
    return cases


def run_case(client, model_id: str, case: dict) -> dict:
    started = time.monotonic()
    try:
        result = generate(client, model_id, case["notes"])
        onepager, usage, retry_reasons, error = result.onepager, result.usage.to_dict(), result.retry_reasons, None
    except PipelineError as e:
        onepager, usage, retry_reasons, error = None, {"input_tokens": 0, "output_tokens": 0, "calls": 0}, [], \
            f"{e} ({e.detail})"
    return {
        **{k: case[k] for k in ("id", "kind")},
        "latency_s": round(time.monotonic() - started, 1),
        "usage": usage,
        "error": error,
        "retry_reasons": retry_reasons,
        "score": score_case(case["label"], onepager, case["notes"]),
        "onepager": onepager,
    }


def cost(usage: dict) -> float:
    return usage["input_tokens"] / 1e6 * PRICE_IN_PER_M + usage["output_tokens"] / 1e6 * PRICE_OUT_PER_M


def pct(hits: int, total: int) -> str:
    return f"{hits}/{total} ({hits / total:.0%})" if total else "n/a"


def report(results: list[dict], model_id: str) -> str:
    n = len(results)
    scores = [r["score"] for r in results]
    risks_total = sum(len(s["risks_found"]) + len(s["risks_missed"]) for s in scores)
    asks_total = sum(len(s["asks_found"]) + len(s["asks_missed"]) for s in scores)
    unsupported_cases = sum(1 for s in scores if s["unsupported"])
    injection = [s["injection_pass"] for s in scores if s["injection_pass"] is not None]
    total_in = sum(r["usage"]["input_tokens"] for r in results)
    total_out = sum(r["usage"]["output_tokens"] for r in results)
    total_cost = sum(cost(r["usage"]) for r in results)
    ok = [r for r in results if not r["error"]]

    lines = [
        f"## Eval results ({n} inputs, {model_id}, {datetime.now(UTC):%Y-%m-%d})",
        "",
        "| Metric | Result |",
        "|---|---|",
        *[f"| Status accuracy: {d} | {pct(sum(s['status_hits'][d] for s in scores), n)} |" for d in DIMENSIONS],
        f"| Overall status correct | {pct(sum(s['overall_ok'] for s in scores), n)} |",
        f"| Low-confidence flag correct | {pct(sum(s['low_confidence_ok'] for s in scores), n)} |",
        f"| Risk recall (must-mention risks present) | "
        f"{pct(sum(len(s['risks_found']) for s in scores), risks_total)} |",
        f"| Asks included | {pct(sum(len(s['asks_found']) for s in scores), asks_total)} |",
        f"| Outputs with invented asks | {sum(1 for s in scores if s['invented_asks'])}/{n} |",
        f"| Outputs with unsupported figures or dates | {unsupported_cases}/{n} |",
        f"| Summary follows its checklist | {pct(sum(not s['summary_breaks'] for s in scores), n)} |",
        f"| Prompt injection resisted | {'pass' if injection and all(injection) else 'FAIL'} |",
        f"| Pipeline failures | {n - len(ok)}/{n} |",
        f"| Retries needed | {sum(1 for r in results if r['retry_reasons'])}/{n} |",
        f"| Avg latency | {sum(r['latency_s'] for r in ok) / max(len(ok), 1):.1f}s |",
        f"| Avg cost per generation | ${total_cost / max(len(ok), 1):.4f} |",
        "",
        "| Case | Overall (expected → got) | Dimensions right | Risks | Asks | Unsupported | Retry |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        s, label = r["score"], next(c["label"] for c in CASES if c["id"] == r["id"])
        expected = "/".join(label["expected_overall"]) if isinstance(label["expected_overall"], list) \
            else label["expected_overall"]
        got = r["onepager"]["overall"] if r["onepager"] else "ERROR"
        mark = "✅" if s["overall_ok"] else "❌"
        risks = f"{len(s['risks_found'])}/{len(s['risks_found']) + len(s['risks_missed'])}"
        asks = f"{len(s['asks_found'])}/{len(s['asks_found']) + len(s['asks_missed'])}"
        lines.append(f"| {r['id']} | {expected} → {got} {mark} | {sum(s['status_hits'].values())}/4 | {risks} | "
                     f"{asks} | {len(s['unsupported'])} | {'yes' if r['retry_reasons'] else ''} |")
    lines += ["", f"Tokens: {total_in:,} in / {total_out:,} out. Run cost: ${total_cost:.3f} "
                  f"(at ${PRICE_IN_PER_M:.2f} / ${PRICE_OUT_PER_M:.2f} per million tokens)."]
    return "\n".join(lines)


def problems(results: list[dict]) -> list[str]:
    """Plain-text list of everything that went wrong, for the console."""
    out = []
    for r in results:
        s = r["score"]
        if r["error"]:
            out.append(f"{r['id']}: ERROR {r['error']}")
            continue
        label = next(c["label"] for c in CASES if c["id"] == r["id"])
        out += [f"{r['id']}: {d} expected {label['expected'][d]}, got {s['got'][d]}"
                for d in DIMENSIONS if not s["status_hits"][d]]
        if not s["low_confidence_ok"]:
            out.append(f"{r['id']}: low_confidence expected {label['low_confidence']}")
        out += [f"{r['id']}: missing risk '{m}'" for m in s["risks_missed"]]
        out += [f"{r['id']}: missing ask '{m}'" for m in s["asks_missed"]]
        out += [f"{r['id']}: {u}" for u in s["unsupported"]]
        out += [f"{r['id']}: {b}" for b in s["summary_breaks"]]
        out += [f"{r['id']}: invented ask '{a}'" for a in s["invented_asks"]]
        out += [f"{r['id']}: retried because {reason}" for reason in r["retry_reasons"]]
    return out


CASES: list[dict] = []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", help="case ids to run")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--out", type=Path, default=ROOT / "evals" / "results")
    args = parser.parse_args()

    model_id = os.environ.get("MODEL_ID")
    if not model_id:
        sys.exit("Set MODEL_ID to the Bedrock model or inference profile ID.")

    CASES.extend(load_cases(args.only))
    client = make_client(args.region)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda c: run_case(client, model_id, c), CASES))

    args.out.mkdir(parents=True, exist_ok=True)
    markdown = report(results, model_id)
    (args.out / "results.md").write_text(markdown + "\n", encoding="utf-8")
    (args.out / "latest.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    sys.stdout.reconfigure(encoding="utf-8")
    print(markdown)
    issues = problems(results)
    print("\nIssues:" if issues else "\nNo issues.")
    print("\n".join(f"- {i}" for i in issues))


if __name__ == "__main__":
    main()
