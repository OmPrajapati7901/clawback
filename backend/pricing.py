"""Pricing semantics from CONTRACT.md. Pure Python, no LLM, all money math lives here."""
from __future__ import annotations

from datetime import date

from backend.schemas import ContractTerms, Finding, Invoice, LineItem, Tier

LINE_TOLERANCE = 0.50
DISPUTE_THRESHOLD = 250.0
TOTAL_SKU = "TOTAL"  # sku used for an invoice-level MATH_ERROR (sum(amounts) != total)


def contract_years(effective_date: str, invoice_date: str) -> int:
    eff, inv = date.fromisoformat(effective_date), date.fromisoformat(invoice_date)
    n = inv.year - eff.year - ((inv.month, inv.day) < (eff.month, eff.day))
    return max(n, 0)


def max_escalated_price(rate: float, pct: float, n: int) -> float:
    return round(rate * (1 + pct) ** n, 2)


def tier_amount(qty: int, tiers: list[Tier], tier_type: str) -> float:
    tiers = sorted(tiers, key=lambda t: t.min_qty)
    if tier_type == "all_units":
        reached = [t for t in tiers if t.min_qty <= qty] or tiers[:1]
        return round(qty * reached[-1].unit_price, 2)
    total = 0.0
    for i, t in enumerate(tiers):
        lo = max(t.min_qty, 1)
        hi = tiers[i + 1].min_qty - 1 if i + 1 < len(tiers) else qty
        units = max(0, min(qty, hi) - lo + 1)
        total += units * t.unit_price
    return round(total, 2)


def _finding(type_: str, sku: str, billed: float, expected: float) -> Finding:
    return Finding(
        type=type_, sku=sku, billed_amount=round(billed, 2),
        expected_amount=round(expected, 2), delta_usd=round(billed - expected, 2),
    )


def expected_line(li: LineItem, terms: ContractTerms, n: int) -> tuple[str, float, float]:
    """(finding type if overbilled, billed, expected) under the rule governing this line.

    Price rules compare qty*unit_price, so a bad `amount` is counted once, as MATH_ERROR.
    """
    priced = round(li.qty * li.unit_price, 2)
    if li.sku in terms.included_skus:
        return "INCLUDED_ITEM_BILLED", li.amount, 0.0
    if li.sku in terms.volume_tiers:
        return "TIER_DISCOUNT_MISSED", priced, tier_amount(li.qty, terms.volume_tiers[li.sku], terms.tier_type)
    if li.sku in terms.rate_card:
        rate = terms.rate_card[li.sku]
        if terms.escalator_max_pct is not None:
            return "ESCALATOR_EXCEEDED", priced, round(li.qty * max_escalated_price(rate, terms.escalator_max_pct, n), 2)
        return "RATE_MISMATCH", priced, round(li.qty * rate, 2)
    return "UNKNOWN_SKU", li.amount, li.amount


def check_invoice(invoice: Invoice, terms: ContractTerms) -> list[Finding]:
    """Overbilling findings (no clause/explanation yet)."""
    n = contract_years(terms.effective_date, invoice.invoice_date)
    out: list[Finding] = []
    for li in invoice.line_items:
        priced = round(li.qty * li.unit_price, 2)
        if li.amount - priced > LINE_TOLERANCE:
            out.append(_finding("MATH_ERROR", li.sku, li.amount, priced))
        kind, billed, expected = expected_line(li, terms, n)
        if kind == "UNKNOWN_SKU" or (kind == "INCLUDED_ITEM_BILLED" and billed > 0):
            out.append(_finding(kind, li.sku, billed, expected))
        elif kind != "INCLUDED_ITEM_BILLED" and billed - expected > LINE_TOLERANCE:
            out.append(_finding(kind, li.sku, billed, expected))

    line_sum = round(sum(li.amount for li in invoice.line_items), 2)
    if invoice.total - line_sum > LINE_TOLERANCE:
        out.append(_finding("MATH_ERROR", TOTAL_SKU, invoice.total, line_sum))
    return out


def total_delta(findings: list[Finding]) -> float:
    return round(sum(f.delta_usd for f in findings), 2)


def decide(findings: list[Finding]) -> str:
    if not findings:
        return "APPROVE"
    return "DISPUTE" if total_delta(findings) > DISPUTE_THRESHOLD else "FLAG"
