"""Pre-generate the sample one-pagers that ship with the frontend (about 1 cent each).

    $env:MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    .\\.venv\\Scripts\\python scripts\\generate_samples.py

Writes samples/<id>.onepager.json. Refuses to write a sample whose statuses don't match its
labels, or that has validation warnings, so the site never ships a wrong example. Summary
checklist slips (e.g. a few words over the limit) are reported but don't block.

    .\\.venv\\Scripts\\python scripts\\generate_samples.py vendor-transition   # just one
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "evals")]

from onepager.bedrock import make_client  # noqa: E402
from onepager.pipeline import generate  # noqa: E402
from scoring import score_case  # noqa: E402


def main() -> None:
    model_id = os.environ.get("MODEL_ID")
    if not model_id:
        sys.exit("Set MODEL_ID to the Bedrock model or inference profile ID.")
    client = make_client(os.environ.get("AWS_REGION", "us-east-1"))
    failed = False
    only = set(sys.argv[1:])
    for labels_path in sorted((ROOT / "samples").glob("*.labels.json")):
        label = json.loads(labels_path.read_text(encoding="utf-8"))
        if only and label["id"] not in only:
            continue
        notes = labels_path.with_name(f"{label['id']}.txt").read_text(encoding="utf-8")
        p = generate(client, model_id, notes).onepager
        s = score_case(label, p, notes)
        problems = [f"{d} status wrong" for d, ok in s["status_hits"].items() if not ok] + p["warnings"]
        if problems:
            print(f"{label['id']}: NOT written: {problems}")
            failed = True
            continue
        labels_path.with_name(f"{label['id']}.onepager.json").write_text(
            json.dumps(p, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        note = f"; note: {'; '.join(s['summary_breaks'])}" if s["summary_breaks"] else ""
        print(f"{label['id']}: written ({p['overall']}, {p['meta']['latency_ms']} ms){note}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
