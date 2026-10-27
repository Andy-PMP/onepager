"""Run the pipeline locally against Bedrock.

    $env:MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    .\\.venv\\Scripts\\python -m onepager.cli samples\\dc-migration.txt            # Markdown
    .\\.venv\\Scripts\\python -m onepager.cli samples\\dc-migration.txt --json     # full JSON
"""

import argparse
import json
import os
import sys
from pathlib import Path

from .bedrock import make_client
from .pipeline import PipelineError, generate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("notes", type=Path)
    parser.add_argument("--json", action="store_true", help="print the full one-pager JSON")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = parser.parse_args()

    model_id = os.environ.get("MODEL_ID")
    if not model_id:
        sys.exit("Set MODEL_ID to the Bedrock model or inference profile ID.")

    try:
        result = generate(make_client(args.region), model_id, args.notes.read_text(encoding="utf-8"))
    except PipelineError as e:
        sys.exit(f"{e} ({e.detail})")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result.onepager, indent=2) if args.json else result.onepager["markdown"])
    print(json.dumps(result.log), file=sys.stderr)


if __name__ == "__main__":
    main()
