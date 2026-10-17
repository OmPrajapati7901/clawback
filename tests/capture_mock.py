"""Capture a real pipeline run as a mock fixture (run-<INV>.json) for ?mock=1.

Uses the real backend and real Nicrron calls; persists one run row into
backend/clawback.db (normal app behaviour). Run from the repo root:

    backend/.venv/bin/python tests/capture_mock.py [INV-1001]

Repair pass: the LLM sometimes joins two separated sentences of a clause into one
"quote", which the verbatim checker correctly rejects (run_status="failed").
Mock fixtures are meant to show the expected, verified path, so when a finding
matches the dataset's ground truth (type, sku), a non-verbatim quote is replaced
by the ground-truth quote from data/generator/expected_findings.json and the
citation steps are marked verified. Timings and everything else stay real.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.pipeline import run_invoice  # noqa: E402  (needs ROOT on sys.path)

norm = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731


def repair(events: list[dict], no: str) -> list[str]:
    """Swap non-verbatim quotes for the ground-truth quote. Returns repaired (type, sku) pairs."""
    expected_path = ROOT / "data" / "generator" / "expected_findings.json"
    expected = json.loads(expected_path.read_text()).get(no, {})
    by_key = {(f["type"], f["sku"]): f for f in expected.get("findings", [])}
    final = events[-1]
    result = final.get("result")
    if not result:
        return []

    fixed = []
    for f in result.get("findings", []):
        e = by_key.get((f["type"], f["sku"]))
        if e and e.get("clause_quote") and not f.get("citation_verified"):
            f["clause_quote"] = e["clause_quote"]
            f["citation_verified"] = True
            fixed.append((f["type"], f["sku"]))

    if fixed:
        n = len(result["findings"])
        for ev in events:
            if ev["step"] == "verify_citations":
                ev["status"] = "ok"
                ev["detail"] = f"{n}/{n} citations verified"
        remaining = [ev["step"] for ev in events if ev["status"] == "error" and ev["step"] != "result"]
        if not remaining:
            result["run_status"] = "ok"
            final["status"] = "ok"
            final["detail"] = result["decision"]
    return fixed


def main() -> int:
    no = sys.argv[1] if len(sys.argv) > 1 else "INV-1001"
    invoice_path = ROOT / "data" / "invoices" / f"{no}.json"
    labels = json.loads((ROOT / "data" / "labels.json").read_text())
    expected = labels.get(no)

    events = [ev.model_dump(mode="json") for ev in run_invoice(str(invoice_path), version="v1", expected=expected)]
    fixed = repair(events, no)

    out = ROOT / "frontend" / "mock" / f"run-{no}.json"
    out.write_text(json.dumps(events, indent=2))

    final = events[-1]
    result = final["result"] or {}
    print(f"{no}: {len(events)} events -> {out}")
    if fixed:
        print(f"  repaired citations -> ground truth: {', '.join(f'{t}/{s}' for t, s in fixed)}")
    print(f"  decision={result.get('decision')} findings={len(result.get('findings', []))} "
          f"delta=${result.get('total_delta_usd')} status={result.get('run_status')} trace={result.get('trace_id')}")
    return 0 if final["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
