"""Build frontend/mock/*.json fixtures for ?mock=1 mode. Stdlib only.

Numbers, clause quotes and explanations come from the dataset's ground truth
(data/generator/expected_findings.json + terms_ground_truth.json), so the mock UI
shows exactly what a correct live run produces.

run-INV-1001.json is written here as a fallback; tests/capture_mock.py overwrites
it with a real pipeline run when one is available.

Run from the repo root:  python3 tests/build_mock.py
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MOCK = ROOT / "frontend" / "mock"

LIST = ["INV-1001", "INV-1005", "INV-1003", "INV-1007"]  # one row per decision state
PENDING = {"INV-1007"}  # opens as "pending" so the mock replays a live run

STEP_ORDER = ["parse_invoice", "resolve_vendor", "load_contract_terms", "compute_expected",
              "compare_lines", "explain_findings", "verify_citations", "decide_and_draft", "grade"]

MS = {
    "INV-1001": {"parse_invoice": 34, "resolve_vendor": 2, "load_contract_terms": 3120,
                 "compute_expected": 5, "compare_lines": 4, "explain_findings": 4480,
                 "verify_citations": 3, "decide_and_draft": 5910, "grade": 2},
    "INV-1003": {"parse_invoice": 31, "resolve_vendor": 1, "load_contract_terms": 46,
                 "compute_expected": 4, "compare_lines": 3, "explain_findings": 22,
                 "verify_citations": 2, "decide_and_draft": 9, "grade": 2},
    "INV-1005": {"parse_invoice": 27, "resolve_vendor": 1, "load_contract_terms": 41,
                 "compute_expected": 3, "compare_lines": 3, "explain_findings": 2140,
                 "verify_citations": 2, "decide_and_draft": 1480, "grade": 2},
    "INV-1007": {"parse_invoice": 39, "resolve_vendor": 2, "load_contract_terms": 3870,
                 "compute_expected": 5, "compare_lines": 4, "explain_findings": 3310,
                 "verify_citations": 3, "decide_and_draft": 5220, "grade": 2},
}

EMAIL_FALLBACK = {
    "INV-1001": {
        "subject": "Invoice INV-1001 — rate increase above the contract ceiling",
        "body": ("Hello,\n\n"
                 "We reviewed invoice INV-1001 dated 2026-07-10 against our Master Services Agreement.\n"
                 "Expedited next-day delivery (SKU FR-200) is billed at $107.84 per unit, while Section 7.2 "
                 "allows no more than $105.84 per unit after two annual adjustments.\n\n"
                 "- FR-200: 2,090 units billed at $107.84, $221,205.60 allowed, overcharge $4,180.00 (Section 7.2)\n\n"
                 "Total overcharge: $4,180.00\n\n"
                 "Please send a corrected invoice or credit memo for $4,180.00.\n\nAccounts Payable"),
    },
    "INV-1007": {
        "subject": "Invoice INV-1007 — HC-300 billed above the contract rate",
        "body": ("Hello,\n\n"
                 "We reviewed invoice INV-1007 against our Master Services Agreement. Managed PostgreSQL "
                 "instances (SKU HC-300) are billed at $335.00 per instance-month, while Section 3.2 fixes the "
                 "rate at $310.00 per instance-month.\n\n"
                 "- HC-300: 12 instance-months billed at $335.00, $3,720.00 allowed, overcharge $300.00 (Section 3.2)\n\n"
                 "Total overcharge: $300.00\n\n"
                 "Please send a corrected invoice or credit memo for $300.00.\n\nAccounts Payable"),
    },
}


def split_clauses(text: str) -> list[dict]:
    heads = list(re.finditer(r"^##\s+(\d+(?:\.\d+)*)\.?\s+(.+?)\s*$", text, re.M))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append({"id": m.group(1), "title": m.group(2), "text": text[m.end():end].strip()})
    return out


def norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def contract_years(effective: str, invoice: str) -> int:
    e, i = date.fromisoformat(effective), date.fromisoformat(invoice)
    return max(i.year - e.year - ((i.month, i.day) < (e.month, e.day)), 0)


def build_events(inv: dict, result: dict, ms: dict[str, int]) -> list[dict]:
    n_lines, total = len(inv["line_items"]), inv["total"]
    n_find, delta, decision = len(result["findings"]), result["total_delta_usd"], result["decision"]
    details = {
        "parse_invoice": f"{inv['invoice_no']}: {n_lines} lines, total ${total:,.2f}",
        "resolve_vendor": f"{inv['vendor_name_raw']!r} \u2192 {result['_vendor_id']}",
        "load_contract_terms": f"{result['_vendor_id']}: extracted terms, {result['_clauses']} clauses",
        "compute_expected": f"{n_lines} lines priced, contract year {result['_years']}",
        "compare_lines": f"{n_find} findings, delta ${delta:,.2f}",
        "explain_findings": "no findings" if n_find == 0 else f"explained {n_find}/{n_find}",
        "verify_citations": f"{n_find}/{n_find} citations verified",
        "decide_and_draft": f"{decision}, total delta ${delta:,.2f}",
        "grade": "matches label",
    }
    events = []
    for step in STEP_ORDER:
        events.append({"step": step, "status": "running", "detail": "", "ms": 0, "result": None})
        events.append({"step": step, "status": "ok", "detail": details[step],
                       "ms": ms.get(step, 3), "result": None})
    payload = {k: v for k, v in result.items() if not k.startswith("_")}
    events.append({"step": "result", "status": "ok", "detail": decision, "ms": 0, "result": payload})
    return events


def main() -> None:
    MOCK.mkdir(parents=True, exist_ok=True)
    vendors = json.loads((DATA / "vendors.json").read_text())
    vmap = {}
    for v in vendors:
        for name in [v["canonical_name"], *v.get("aliases", [])]:
            vmap[norm_key(name)] = v
    expected = json.loads((DATA / "generator" / "expected_findings.json").read_text())
    truth = json.loads((DATA / "generator" / "terms_ground_truth.json").read_text())

    rows = []
    stats = {"recovered_usd": 0.0, "invoices": len(LIST), "disputes": 0, "flags": 0, "approvals": 0}
    contracts_done: set[str] = set()

    for no in LIST:
        inv = json.loads((DATA / "invoices" / f"{no}.json").read_text())
        vendor = vmap[norm_key(inv["vendor_name_raw"])]
        vid = vendor["vendor_id"]
        pending = no in PENDING
        exp = expected[no]

        fixture = {
            "invoice_no": no, "version": "v1", "decision": exp["decision"],
            "findings": exp["findings"], "total_delta_usd": exp["total_delta_usd"],
            "dispute_email": EMAIL_FALLBACK.get(no), "run_status": "ok", "trace_id": str(uuid.uuid4()),
        }
        # stored result shown on open; pending invoices have none
        (MOCK / f"invoice-{no}.json").write_text(
            json.dumps({"invoice": inv, "result": None if pending else fixture}, indent=2))

        rows.append({
            "invoice_no": no, "vendor": vendor["canonical_name"], "invoice_date": inv["invoice_date"],
            "total": inv["total"], "decision": None if pending else fixture["decision"],
            "total_delta_usd": None if pending else fixture["total_delta_usd"],
            "status": "pending" if pending else "ok",
        })
        if not pending:
            stats[{"APPROVE": "approvals", "FLAG": "flags", "DISPUTE": "disputes"}[fixture["decision"]]] += 1
            if fixture["decision"] == "DISPUTE":
                stats["recovered_usd"] += fixture["total_delta_usd"]

        if vid not in contracts_done:
            text = (DATA / "contracts" / f"{vid}.md").read_text()
            terms = {**truth[vid], "clauses": split_clauses(text)}
            (MOCK / f"contract-{vid}.json").write_text(json.dumps({"text": text, "terms": terms}, indent=2))
            contracts_done.add(vid)

        enriched = {**fixture, "_vendor_id": vid, "_clauses": len(split_clauses(
            (DATA / "contracts" / f"{vid}.md").read_text())),
            "_years": contract_years(truth[vid]["effective_date"], inv["invoice_date"])}
        run_file = MOCK / f"run-{no}.json"
        if no == "INV-1001" and run_file.exists():
            print("keeping existing run-INV-1001.json (real capture)")
        else:
            run_file.write_text(json.dumps(build_events(inv, enriched, MS[no]), indent=2))

    stats["recovered_usd"] = round(stats["recovered_usd"], 2)
    (MOCK / "invoices.json").write_text(json.dumps(rows, indent=2))
    (MOCK / "stats.json").write_text(json.dumps(stats, indent=2))
    print(f"wrote {len(rows)} rows, {len(contracts_done)} contracts -> {MOCK}")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
