"""Independent, pure-Python implementation of the pricing semantics in CONTRACT.md.

This module is the ground truth behind ``data/labels.json``. It deliberately
imports nothing from ``backend/`` so that the backend's own implementation is a
genuine second opinion: if the two disagree, the dataset or the backend is wrong.

Semantics implemented (CONTRACT.md, "Pricing semantics (ground truth)"):

* ``n`` = number of anniversaries of the contract ``effective_date`` that have
  passed on or before the invoice date ("full contract years").
* rate-card SKUs: with an escalator the ceiling is ``round(rate*(1+pct)**n, 2)``;
  without one the contract rate is the ceiling.
* volume-tier SKUs are never escalated. ``all_units`` bills the whole quantity at
  the highest tier reached, ``incremental`` bills each band at its own price.
  Band ``i`` covers ``[min_qty_i, min_qty_{i+1} - 1]``.
* included SKUs must not be billed at all.
* money is rounded half-up to cents; overbilling counts only above the $0.50
  per-line tolerance.

Run standalone for a quick audit of the checked-in dataset::

    python data/generator/reference_pricing.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")
TOLERANCE = Decimal("0.50")
DISPUTE_THRESHOLD = Decimal("250.00")

FINDING_TYPES = (
    "ESCALATOR_EXCEEDED",
    "TIER_DISCOUNT_MISSED",
    "INCLUDED_ITEM_BILLED",
    "RATE_MISMATCH",
    "MATH_ERROR",
    "UNKNOWN_SKU",
)

# Which clause each finding type is cited from (clause ids are per-contract, but
# every contract in this dataset uses the same skeleton).
CLAUSE_FOR_TYPE = {
    "ESCALATOR_EXCEEDED": "7.2",
    "RATE_MISMATCH": "3.2",
    "TIER_DISCOUNT_MISSED": "4.1",
    "INCLUDED_ITEM_BILLED": "5.1",
    "MATH_ERROR": "3.1",
    "UNKNOWN_SKU": "2.1",
}

# Sentence keywords used to pull an exact quote out of the cited clause.
_QUOTE_HINTS = {
    "ESCALATOR_EXCEEDED": ("percent",),
    "RATE_MISMATCH": (),
    "TIER_DISCOUNT_MISSED": (),
    "INCLUDED_ITEM_BILLED": (),
    "MATH_ERROR": ("quantity",),
    "UNKNOWN_SKU": ("only", "other charges"),
}


# --------------------------------------------------------------------------- #
# money + dates
# --------------------------------------------------------------------------- #
def money(value: Any) -> Decimal:
    """Round any numeric value half-up to whole cents."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def usd(value: Any) -> str:
    return f"${money(value):,.2f}"


def parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def add_years(day: date, years: int) -> date:
    """Add whole years, clamping Feb 29 to Feb 28."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def full_contract_years(effective_date: str | date, invoice_date: str | date) -> int:
    """Number of contract anniversaries passed on or before the invoice date."""
    eff, inv = parse_date(effective_date), parse_date(invoice_date)
    if inv < eff:
        return -1
    n = 0
    while add_years(eff, n + 1) <= inv:
        n += 1
    return n


def day_based_years(effective_date: str | date, invoice_date: str | date) -> int:
    """Alternative reading of ``n``. Used only by the generator's cross-checks."""
    eff, inv = parse_date(effective_date), parse_date(invoice_date)
    if inv < eff:
        return -1
    return int((inv - eff).days // 365.25)


def escalated_unit_price(rate: Any, escalator_max_pct: Any, n: int) -> Decimal:
    """CONTRACT: max unit price = round(rate * (1 + pct) ** n, 2)."""
    raw = float(rate) * (1.0 + float(escalator_max_pct)) ** n
    return money(raw)


def is_rounding_tie(value: Any) -> bool:
    """True when half-up and half-even rounding of ``value`` disagree."""
    dec = Decimal(str(value))
    shifted = (dec * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    half_up = Decimal(shifted) / 100
    half_even = (dec * 100).quantize(Decimal("1"), rounding="ROUND_HALF_EVEN") / 100
    return half_up != half_even


# --------------------------------------------------------------------------- #
# contract helpers
# --------------------------------------------------------------------------- #
def contract_skus(terms: dict) -> set[str]:
    return set(terms.get("rate_card", {})) | set(terms.get("volume_tiers", {})) | set(
        terms.get("included_skus", [])
    )


def rate_ceiling(sku: str, terms: dict, n: int) -> Decimal:
    rate = terms["rate_card"][sku]
    pct = terms.get("escalator_max_pct")
    if pct:
        return escalated_unit_price(rate, pct, n)
    return money(rate)


def tier_amount_raw(tiers: list[dict], qty: int, tier_type: str) -> Decimal:
    """Exact, unrounded expected amount for a tiered line."""
    bands = sorted(tiers, key=lambda t: t["min_qty"])
    if tier_type == "all_units":
        reached = None
        for band in bands:
            if qty >= band["min_qty"]:
                reached = band
        if reached is None:
            return Decimal("0.00")
        return Decimal(str(reached["unit_price"])) * qty

    total = Decimal("0")
    for index, band in enumerate(bands):
        if qty < band["min_qty"]:
            break
        upper = bands[index + 1]["min_qty"] - 1 if index + 1 < len(bands) else qty
        count = min(qty, upper) - band["min_qty"] + 1
        total += Decimal(str(band["unit_price"])) * count
    return total


def tier_expected_amount(tiers: list[dict], qty: int, tier_type: str) -> Decimal:
    return money(tier_amount_raw(tiers, qty, tier_type))


def clause_by_id(terms: dict, clause_id: str) -> dict | None:
    for clause in terms.get("clauses", []):
        if clause["id"] == clause_id:
            return clause
    return None


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=\.)\s+", text.strip()) if s.strip()]


def pick_quote(clause_text: str, sku: str | None, hints: tuple[str, ...]) -> str:
    """Pick the exact sentence that proves a finding (always a substring of the clause)."""
    sentences = _sentences(clause_text)
    if sku:
        for sentence in sentences:
            if sku.lower() in sentence.lower():
                return sentence
    for hint in hints:
        for sentence in sentences:
            if hint in sentence.lower():
                return sentence
    return sentences[0] if sentences else clause_text.strip()


# --------------------------------------------------------------------------- #
# the audit
# --------------------------------------------------------------------------- #
def _finding(
    terms: dict,
    finding_type: str,
    sku: str,
    billed_amount: Decimal,
    expected_amount: Decimal,
    delta: Decimal,
    explanation: str,
) -> dict:
    clause_id = CLAUSE_FOR_TYPE[finding_type]
    clause = clause_by_id(terms, clause_id) or {"text": ""}
    quote = pick_quote(clause["text"], sku if finding_type != "UNKNOWN_SKU" else None,
                       _QUOTE_HINTS[finding_type])
    return {
        "type": finding_type,
        "sku": sku,
        "billed_amount": float(money(billed_amount)),
        "expected_amount": float(money(expected_amount)),
        "delta_usd": float(money(delta)),
        "clause_id": clause_id,
        "clause_quote": quote,
        "citation_verified": quote in clause["text"],
        "explanation": explanation,
    }


def _audit_line(line: dict, terms: dict, n: int) -> dict | None:
    sku = line["sku"]
    qty = int(line["qty"])
    unit = Decimal(str(line["unit_price"]))
    amount = Decimal(str(line["amount"]))

    rate_card = terms.get("rate_card", {})
    tiers = terms.get("volume_tiers", {})
    included = set(terms.get("included_skus", []))

    if sku not in contract_skus(terms):
        return _finding(
            terms,
            "UNKNOWN_SKU",
            sku,
            amount,
            amount,
            Decimal("0.00"),
            f"SKU {sku} does not appear anywhere in the agreement for this vendor, so it cannot be priced.",
        )

    if sku in included:
        delta = amount
        if delta > TOLERANCE:
            return _finding(
                terms,
                "INCLUDED_ITEM_BILLED",
                sku,
                amount,
                Decimal("0.00"),
                delta,
                f"{sku} is included in the contracted rates and must not be billed separately.",
            )
        return None

    if sku in tiers:
        expected = tier_expected_amount(tiers[sku], qty, terms.get("tier_type", "incremental"))
        delta = amount - expected
        if delta > TOLERANCE:
            return _finding(
                terms,
                "TIER_DISCOUNT_MISSED",
                sku,
                amount,
                expected,
                delta,
                f"{qty} units reach a lower volume band; the line was billed at {usd(unit)} per unit "
                f"instead of {usd(expected)} for the quantity invoiced.",
            )
        return None

    if sku in rate_card:
        ceiling = rate_ceiling(sku, terms, n)
        over_unit = unit - ceiling
        delta = over_unit * qty
        if over_unit > 0 and delta > TOLERANCE:
            if terms.get("escalator_max_pct"):
                return _finding(
                    terms,
                    "ESCALATOR_EXCEEDED",
                    sku,
                    amount,
                    money(ceiling * qty),
                    delta,
                    f"{sku} billed at {usd(unit)} per unit; after {n} full contract year(s) the "
                    f"agreement allows at most {usd(ceiling)}.",
                )
            return _finding(
                terms,
                "RATE_MISMATCH",
                sku,
                amount,
                money(ceiling * qty),
                delta,
                f"{sku} billed at {usd(unit)} per unit; the agreement fixes the rate at {usd(ceiling)}.",
            )
        return None

    return None


def _math_finding(line: dict, terms: dict) -> dict | None:
    qty = int(line["qty"])
    unit = Decimal(str(line["unit_price"]))
    amount = Decimal(str(line["amount"]))
    computed = money(unit * qty)
    if abs(amount - computed) <= Decimal("0.01"):
        return None
    delta = amount - computed
    if delta <= TOLERANCE:
        return None
    return _finding(
        terms,
        "MATH_ERROR",
        line["sku"],
        amount,
        computed,
        delta,
        f"{qty} x {usd(unit)} equals {usd(computed)}, but the line bills {usd(amount)}.",
    )


def audit_invoice(invoice: dict, terms: dict) -> dict:
    """Return {"decision", "findings", "total_delta_usd"} for one invoice."""
    n = full_contract_years(terms["effective_date"], invoice["invoice_date"])
    findings = []
    for line in invoice["line_items"]:
        finding = _audit_line(line, terms, n)
        if finding is None:
            finding = _math_finding(line, terms)
        if finding is not None:
            findings.append(finding)

    total_delta = money(sum((Decimal(str(f["delta_usd"])) for f in findings), Decimal("0")))
    if not findings:
        decision = "APPROVE"
    elif total_delta > DISPUTE_THRESHOLD:
        decision = "DISPUTE"
    else:
        decision = "FLAG"
    return {"decision": decision, "findings": findings, "total_delta_usd": float(total_delta)}


def labels_for(invoice: dict, terms: dict) -> dict:
    """labels.json entry: decision plus (type, sku, delta) per finding."""
    result = audit_invoice(invoice, terms)
    return {
        "decision": result["decision"],
        "findings": [
            {"type": f["type"], "sku": f["sku"], "delta_usd": f["delta_usd"]}
            for f in result["findings"]
        ],
    }


# --------------------------------------------------------------------------- #
# CLI: rebuild labels.json and/or print the audit table
# --------------------------------------------------------------------------- #
def _load_dataset(data_dir: str) -> tuple[dict, dict]:
    with open(os.path.join(data_dir, "vendors.json"), encoding="utf-8") as handle:
        vendors = {v["vendor_id"]: v for v in json.load(handle)}
    invoices = {}
    inv_dir = os.path.join(data_dir, "invoices")
    for name in sorted(os.listdir(inv_dir)):
        if name.endswith(".json"):
            with open(os.path.join(inv_dir, name), encoding="utf-8") as handle:
                invoice = json.load(handle)
            invoices[invoice["invoice_no"]] = invoice
    with open(os.path.join(data_dir, "generator", "terms_ground_truth.json"), encoding="utf-8") as handle:
        terms = json.load(handle)
    return vendors, terms, invoices  # type: ignore[return-value]


def resolve_vendor(vendors: dict, raw_name: str) -> str | None:
    """Normalising lookup: exact, alias, then loose suffix/punctuation matching."""
    def norm(text: str) -> str:
        text = text.lower().replace("&", "and")
        text = re.sub(r"[^a-z0-9 ]+", " ", text)
        text = re.sub(r"\b(llc|inc|co|corp|ltd|company)\b", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    target = norm(raw_name)
    for vendor_id, vendor in vendors.items():
        if norm(vendor["canonical_name"]) == target:
            return vendor_id
    for vendor_id, vendor in vendors.items():
        if any(norm(alias) == target for alias in vendor["aliases"]):
            return vendor_id
    for vendor_id, vendor in vendors.items():
        if norm(vendor["canonical_name"]) in target or target in norm(vendor["canonical_name"]):
            return vendor_id
    return None


def main(argv: list[str]) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.dirname(here)
    vendors, terms, invoices = _load_dataset(data_dir)

    rows = []
    labels = {}
    for invoice_no in sorted(invoices):
        invoice = invoices[invoice_no]
        vendor_id = resolve_vendor(vendors, invoice["vendor_name_raw"])
        entry = labels_for(invoice, terms[vendor_id])
        labels[invoice_no] = entry
        rows.append((invoice_no, invoice["vendor_name_raw"], entry))

    labels_path = os.path.join(data_dir, "labels.json")
    if "--write" in argv or "--write-only" in argv:
        with open(labels_path, "w", encoding="utf-8") as handle:
            json.dump(labels, handle, indent=2, sort_keys=True)
            handle.write("\n")
        if "--write-only" in argv:
            return 0

    counts = {"APPROVE": 0, "FLAG": 0, "DISPUTE": 0}
    for _, _, entry in rows:
        counts[entry["decision"]] += 1
    print(f"{'INVOICE':<10}{'VENDOR (as written on the bill)':<36}{'DECISION':<10}DELTA")
    for invoice_no, raw_name, entry in rows:
        delta = money(sum((Decimal(str(f['delta_usd'])) for f in entry['findings']), Decimal('0')))
        print(f"{invoice_no:<10}{raw_name:<36}{entry['decision']:<10}{usd(delta)}")
    print(f"\n{len(rows)} invoices | APPROVE {counts['APPROVE']} | FLAG {counts['FLAG']} | DISPUTE {counts['DISPUTE']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
