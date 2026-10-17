# CLAWBACK — shared contract (frozen; only the human edits this file)

Clawback audits vendor invoices against vendor contracts, cites the clause, drafts disputes.
MONEY TALKS 2, Money Operations track. ALL DATA IS SYNTHETIC.

## Ownership

backend/ (incl. schemas.py, requirements.txt, scripts/) → Claude Code
frontend/, data/, eval/, tests/, Dockerfile, README.md → Codex, opencode
Never edit another owner's files.

## Data (data/)

vendors.json: [{"vendor_id","canonical_name","aliases":[...]}]   (5 fictional vendors)
contracts/{vendor_id}.md: 2–3 page agreement, clauses as "## 7.2 Price Adjustments"
invoices/{invoice_no}.json and .pdf (identical content)
labels.json: {"INV-1001": {"decision":"DISPUTE","findings":[{"type","sku","delta_usd"}]}}

## Types

LineItem {sku, description, qty:int, unit_price:float, amount:float}
Invoice {invoice_no, vendor_name_raw, invoice_date:"YYYY-MM-DD", line_items:[LineItem], total:float}
Tier {min_qty:int, unit_price:float}
ContractTerms {vendor_id, effective_date, rate_card:{sku:unit_price}, escalator_max_pct:float|null,
  volume_tiers:{sku:[Tier]}, tier_type:"all_units"|"incremental", included_skus:[sku],
  clauses:[{id,title,text}]}
FindingType: ESCALATOR_EXCEEDED | TIER_DISCOUNT_MISSED | INCLUDED_ITEM_BILLED | RATE_MISMATCH | MATH_ERROR | UNKNOWN_SKU
Finding {type, sku, billed_amount, expected_amount, delta_usd, clause_id, clause_quote, citation_verified:bool, explanation}
RunResult {invoice_no, version, decision:"APPROVE"|"FLAG"|"DISPUTE", findings:[Finding], total_delta_usd,
  dispute_email:{subject,body}|null, run_status:"ok"|"failed", trace_id:str|null}
StepEvent {step, status:"running"|"ok"|"error", detail:str, ms:int, result:RunResult|null}

## Pricing semantics (ground truth)

- n = full contract years between effective_date and invoice_date.
- rate_card SKUs: if escalator_max_pct set, max unit price = round(rate*(1+pct)^n, 2); billed above → ESCALATOR_EXCEEDED.
  If escalator null, billed above rate → RATE_MISMATCH.
- volume_tiers SKUs (never escalated): expected amount from qty on that line. all_units = whole qty at the
  highest tier reached; incremental = each band at its own price. Billed above → TIER_DISCOUNT_MISSED.
- included_skus billed with amount > 0 → INCLUDED_ITEM_BILLED (expected 0).
- qty*unit_price ≠ amount (±0.01) or sum(amounts) ≠ total → MATH_ERROR (delta = billed − correct).
- SKU not in contract → UNKNOWN_SKU (delta 0).
- Only overbilling counts; tolerance $0.50 per line.
- Decision: no findings → APPROVE; total delta > 250 → DISPUTE; else FLAG.

## Python interface

backend.pipeline.run_invoice(invoice_path:str, version:str="v1", expected:dict|None=None) -> Iterator[StepEvent]
Final event: step="result" with result=RunResult. If expected is given, a traced "grade" step compares
decision + finding (type, sku); mismatch → run_status="failed" and the PRISM run is marked failed.

## HTTP API

POST /api/invoices (multipart .pdf/.json) → {"invoice_no"}
GET  /api/invoices → [{invoice_no, vendor, invoice_date, total, decision, total_delta_usd, status}]
GET  /api/invoices/{no} → {invoice, result: RunResult|null}
GET  /api/invoices/{no}/process?version=v1 → text/event-stream of StepEvent JSON
GET  /api/contracts/{vendor_id} → {text, terms: ContractTerms}
GET  /api/stats → {recovered_usd, invoices, disputes, flags, approvals}
frontend/ is served as static files at "/".
