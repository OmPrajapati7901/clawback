"""Types from CONTRACT.md. Keep in lockstep with it."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class LineItem(BaseModel):
    sku: str
    description: str
    qty: int
    unit_price: float
    amount: float


class Invoice(BaseModel):
    invoice_no: str
    vendor_name_raw: str
    invoice_date: str  # YYYY-MM-DD
    line_items: list[LineItem]
    total: float


class Tier(BaseModel):
    min_qty: int
    unit_price: float


class Clause(BaseModel):
    id: str
    title: str
    text: str


class ContractTerms(BaseModel):
    vendor_id: str
    effective_date: str
    rate_card: dict[str, float]
    escalator_max_pct: float | None
    volume_tiers: dict[str, list[Tier]]
    tier_type: Literal["all_units", "incremental"]
    included_skus: list[str]
    clauses: list[Clause]


FindingType = Literal[
    "ESCALATOR_EXCEEDED",
    "TIER_DISCOUNT_MISSED",
    "INCLUDED_ITEM_BILLED",
    "RATE_MISMATCH",
    "MATH_ERROR",
    "UNKNOWN_SKU",
]


class Finding(BaseModel):
    type: FindingType
    sku: str
    billed_amount: float
    expected_amount: float
    delta_usd: float
    clause_id: str = ""
    clause_quote: str = ""
    citation_verified: bool = False
    explanation: str = ""


class DisputeEmail(BaseModel):
    subject: str
    body: str


class RunResult(BaseModel):
    invoice_no: str
    version: str
    decision: Literal["APPROVE", "FLAG", "DISPUTE"]
    findings: list[Finding]
    total_delta_usd: float
    dispute_email: DisputeEmail | None
    run_status: Literal["ok", "failed"]
    trace_id: str | None


class StepEvent(BaseModel):
    step: str
    status: Literal["running", "ok", "error"]
    detail: str
    ms: int
    result: RunResult | None = None
