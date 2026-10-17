"""Run invoices end to end, graded against data/labels.json when a label exists.

backend/.venv/bin/python -m backend.scripts.run_invoices data/invoices/INV-1001.json [...]
"""
import json
import sys
from pathlib import Path

from backend import tracing
from backend.pipeline import run_invoice
from backend.steps import DATA


def main(paths: list[str], version: str = "v1") -> None:
    labels_path = DATA / "labels.json"
    labels = json.loads(labels_path.read_text()) if labels_path.exists() else {}
    for path in paths:
        print(f"\n=== {path} ({version})")
        for ev in run_invoice(path, version=version, expected=labels.get(Path(path).stem)):
            if ev.status == "running":
                continue
            if ev.result:
                print(ev.result.model_dump_json(indent=2))
            else:
                print(f"  {ev.status:5} {ev.step:20} {ev.ms:6}ms  {ev.detail}")
    tracing.shutdown()


if __name__ == "__main__":
    args = sys.argv[1:]
    version = "v1"
    if args and args[0].startswith("--version="):
        version = args.pop(0).split("=", 1)[1]
    main(args, version)
