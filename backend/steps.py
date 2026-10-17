"""Pipeline steps. Each is traced to PRISM as its own step and accepts `version`.

Call as step_fn(run, *args, version=...) → Outcome. Exceptions propagate (traced as errors);
non-fatal problems call tracing.current_step().error(msg) and show up as Outcome.error.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Callable

import pdfplumber
from pydantic import BaseModel

from backend import db, pricing, tracing
from backend.llm import complete_json
from backend.schemas import Clause, ContractTerms, DisputeEmail, Finding, Invoice, RunResult, Tier

DATA = Path(os.getenv("CLAWBACK_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")


@dataclass
class Outcome:
    value: Any
    ms: int
    detail: str
    error: str | None


def traced(name: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(run: tracing.Run, *args: Any, version: str = "v1", **kw: Any) -> Outcome:
            with tracing.step(run, name, {"version": version, "args": list(args), **kw}) as s:
                value = fn(*args, version=version, **kw)
                s.output(value)
            return Outcome(value, s.ms, s.detail, s.error_msg)
        return wrapper
    return deco


def _detail(msg: str) -> None:
    s = tracing.current_step()
    if s:
        s.detail = msg


def _fail(msg: str) -> None:
    s = tracing.current_step()
    if s:
        s.error(msg)


# ---------- data access ----------

def load_vendors() -> list[dict]:
    return json.loads((DATA / "vendors.json").read_text())


def contract_text(vendor_id: str) -> str:
    return (DATA / "contracts" / f"{vendor_id}.md").read_text()


def split_clauses(text: str) -> list[Clause]:
    """Clauses are headed "## 7.2 Price Adjustments"; body runs to the next ## heading."""
    heads = list(re.finditer(r"^##\s+(\d+(?:\.\d+)*)\.?\s+(.+?)\s*$", text, re.M))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append(Clause(id=m.group(1), title=m.group(2), text=text[m.end():end].strip()))
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# ---------- steps ----------

@traced("parse_invoice")
def parse_invoice(path: str, version: str = "v1") -> Invoice:
    p = Path(path)
    if p.suffix.lower() == ".json":
        inv = Invoice.model_validate_json(p.read_text())
    else:
        with pdfplumber.open(p) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        inv = complete_json(
            "You extract structured data from vendor invoices. Copy values exactly as printed; "
            "dates as YYYY-MM-DD; numbers without currency symbols or thousands separators.",
            f"Invoice text:\n\n{text}",
            Invoice,
        )
    _detail(f"{inv.invoice_no}: {len(inv.line_items)} lines, total ${inv.total:,.2f}")
    return inv


def match_vendor(vendor_name_raw: str) -> dict | None:
    """Case/punctuation-insensitive exact match against canonical_name and aliases."""
    key = re.sub(r"[^a-z0-9]+", " ", vendor_name_raw.lower()).strip()
    for v in load_vendors():
        names = [v["canonical_name"], *v.get("aliases", [])]
        if any(re.sub(r"[^a-z0-9]+", " ", n.lower()).strip() == key for n in names):
            return v
    return None


@traced("resolve_vendor")
def resolve_vendor(vendor_name_raw: str, version: str = "v1") -> dict:
    v = match_vendor(vendor_name_raw)
    if v is None:
        raise LookupError(f"no vendor matches {vendor_name_raw!r}")
    _detail(f"{vendor_name_raw!r} → {v['vendor_id']}")
    return v


class _ExtractedTerms(BaseModel):
    effective_date: str
    rate_card: dict[str, float]
    escalator_max_pct: float | None
    volume_tiers: dict[str, list[Tier]]
    tier_type: str
    included_skus: list[str]


TERMS_PROMPT = """You extract pricing terms from a vendor contract.
- effective_date: the agreement's effective date, YYYY-MM-DD.
- rate_card: SKU -> base unit price (USD) for SKUs with a fixed per-unit price.
- escalator_max_pct: maximum annual price increase as a FRACTION (3% -> 0.03); null if the contract has no escalation cap.
- volume_tiers: SKU -> list of {min_qty, unit_price} for SKUs with quantity-based pricing.
- tier_type: "all_units" if the whole quantity gets the tier price reached, "incremental" if each band is priced separately. Use "all_units" if there are no tiers.
- included_skus: SKUs the contract says are included at no additional charge."""


@traced("load_contract_terms")
def load_contract_terms(vendor_id: str, version: str = "v1") -> ContractTerms:
    text = contract_text(vendor_id)
    sha = hashlib.sha256(text.encode()).hexdigest()
    terms = db.get_terms(vendor_id, version, sha)
    if terms:
        _detail(f"{vendor_id}: cached terms, {len(terms.clauses)} clauses")
        return terms
    ext = complete_json(TERMS_PROMPT, f"Contract:\n\n{text}", _ExtractedTerms)
    terms = ContractTerms(vendor_id=vendor_id, clauses=split_clauses(text), **ext.model_dump())
    db.save_terms(terms, version, sha, text)
    _detail(f"{vendor_id}: extracted {len(terms.rate_card)} rates, {len(terms.volume_tiers)} tiered, "
            f"{len(terms.included_skus)} included, {len(terms.clauses)} clauses")
    return terms


@traced("compute_expected")
def compute_expected(invoice: Invoice, terms: ContractTerms, version: str = "v1") -> list[dict]:
    n = pricing.contract_years(terms.effective_date, invoice.invoice_date)
    rows = []
    for li in invoice.line_items:
        rule, billed, expected = pricing.expected_line(li, terms, n)
        rows.append({"sku": li.sku, "qty": li.qty, "rule": rule, "billed": billed, "expected": expected})
    _detail(f"{len(rows)} lines priced, contract year {n}")
    return rows


@traced("compare_lines")
def compare_lines(invoice: Invoice, terms: ContractTerms, version: str = "v1") -> list[Finding]:
    findings = pricing.check_invoice(invoice, terms)
    _detail(f"{len(findings)} findings, delta ${pricing.total_delta(findings):,.2f}")
    return findings


class _Explanation(BaseModel):
    index: int
    clause_id: str
    clause_quote: str
    explanation: str


class _Explanations(BaseModel):
    items: list[_Explanation]


@traced("explain_findings")
def explain_findings(findings: list[Finding], terms: ContractTerms, version: str = "v1") -> list[Finding]:
    if not findings:
        _detail("no findings")
        return findings
    clauses = "\n\n".join(f"## {c.id} {c.title}\n{c.text}" for c in terms.clauses)
    rows = "\n".join(
        f"[{i}] {f.type} sku={f.sku} billed=${f.billed_amount:.2f} expected=${f.expected_amount:.2f} "
        f"delta=${f.delta_usd:.2f}" for i, f in enumerate(findings)
    )
    out = complete_json(
        "You are an accounts-payable auditor. For each finding, choose the single contract clause that governs it, "
        "quote the relevant sentence(s) from that clause VERBATIM (exact characters, no paraphrase, no ellipses), "
        "and write a 1-2 sentence plain-English explanation of the overcharge using the dollar amounts given.",
        f"Contract clauses:\n\n{clauses}\n\nFindings:\n{rows}\n\nReturn one item per finding index.",
        _Explanations,
    )
    by_index = {e.index: e for e in out.items}
    result = []
    for i, f in enumerate(findings):
        e = by_index.get(i)
        result.append(f.model_copy(update={"clause_id": e.clause_id, "clause_quote": e.clause_quote,
                                           "explanation": e.explanation} if e else {}))
    _detail(f"explained {len(by_index)}/{len(findings)}")
    return result


@traced("verify_citations")
def verify_citations(findings: list[Finding], vendor_id: str, version: str = "v1") -> list[Finding]:
    text = _norm(contract_text(vendor_id))
    result = [f.model_copy(update={"citation_verified": bool(f.clause_quote) and _norm(f.clause_quote) in text})
              for f in findings]
    bad = [f"{f.type}/{f.sku} (clause {f.clause_id})" for f in result if not f.citation_verified]
    if bad:
        _fail(f"unverified citations: {', '.join(bad)}")
    _detail(f"{len(result) - len(bad)}/{len(result)} citations verified")
    return result


@traced("decide_and_draft")
def decide_and_draft(
    invoice: Invoice, vendor: dict, findings: list[Finding], version: str = "v1"
) -> tuple[str, DisputeEmail | None]:
    decision = pricing.decide(findings)
    total = pricing.total_delta(findings)
    email = None
    if decision == "DISPUTE":
        rows = "\n".join(
            f"- {f.type} on {f.sku}: billed ${f.billed_amount:,.2f}, contract allows ${f.expected_amount:,.2f}, "
            f"overcharge ${f.delta_usd:,.2f} (clause {f.clause_id}: \"{f.clause_quote}\")" for f in findings
        )
        email = complete_json(
            "You write accounts-payable dispute emails to vendors: firm, polite, concise. Cite each clause id and "
            "dollar amount, state the total overcharge, and request a corrected invoice or credit memo. "
            "Sign off as 'Accounts Payable'.",
            f"Vendor: {vendor['canonical_name']}\nInvoice: {invoice.invoice_no} dated {invoice.invoice_date}\n"
            f"Total overcharge: ${total:,.2f}\nFindings:\n{rows}",
            DisputeEmail,
        )
    _detail(f"{decision}, total delta ${total:,.2f}")
    return decision, email


@traced("grade")
def grade(result: RunResult, expected: dict, version: str = "v1") -> dict:
    got = {(f.type, f.sku) for f in result.findings}
    want = {(f["type"], f["sku"]) for f in expected.get("findings", [])}
    report = {
        "decision_ok": result.decision == expected.get("decision"),
        "missing": sorted(want - got),
        "unexpected": sorted(got - want),
    }
    report["passed"] = report["decision_ok"] and not report["missing"] and not report["unexpected"]
    if not report["passed"]:
        _fail(f"grade failed: decision {result.decision} vs {expected.get('decision')}, "
              f"missing {report['missing']}, unexpected {report['unexpected']}")
    else:
        _detail("matches label")
    return report
