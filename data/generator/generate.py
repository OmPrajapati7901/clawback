"""Build the complete synthetic dataset for Clawback.

    python data/generator/generate.py                  # build, check, print the summary table
    python data/generator/generate.py --check-determinism   # build twice, compare bytes

Outputs (all overwritten on each run, all deterministic for a given seed):

    data/vendors.json                      five fictional vendors
    data/contracts/{vendor_id}.md          2-3 page agreements, numbered clauses
    data/invoices/{invoice_no}.json        invoice, per CONTRACT.md
    data/invoices/{invoice_no}.pdf         the same invoice as a clean PDF (reportlab)
    data/labels.json                       decision + findings per invoice
    data/generator/terms_ground_truth.json  ContractTerms per vendor (internal, for eval/tests)
    data/generator/expected_findings.json   full expected findings (internal, for eval/tests)

No model calls are made here, so there is nothing to trace to PRISM.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import timedelta
from decimal import Decimal

from faker import Faker
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import contract_specs as specs
import invoice_specs
import reference_pricing as pricing

INTERNAL_TERMS = "terms_ground_truth.json"
INTERNAL_EXPECTED = "expected_findings.json"

DECISION_ORDER = ("APPROVE", "FLAG", "DISPUTE")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def money_text(value) -> str:
    return f"${pricing.money(value):,.2f}"


def money_float(value) -> float:
    return float(pricing.money(value))


def canvas_maker_for(invoice_date: str):
    """Deterministic canvas: invariant bytes, creation date pinned to the invoice date."""

    def maker(*args, **kwargs):
        kwargs["invariant"] = 1
        canv = pdf_canvas.Canvas(*args, **kwargs)
        stamp = pricing.parse_date(invoice_date)
        canv._doc.info._dateFormatter = lambda *ignored: "D:%04d%02d%02d000000+00'00'" % (
            stamp.year,
            stamp.month,
            stamp.day,
        )
        return canv

    return maker


def fake_context(seed: int, vendors: list[dict]) -> dict:
    fake = Faker("en_US")
    fake.seed_instance(seed)
    ctx = {
        "buyer": {
            "address": f"{fake.street_address()}, {fake.city()}, {fake.state_abbr()} {fake.postcode()}",
            "ap_contact": f"{fake.name()}, Accounts Payable",
        },
        "sites": {},
        "vendors": {},
    }
    for vendor in vendors:  # fixed iteration order keeps Faker deterministic
        ctx["sites"][vendor["vendor_id"]] = (
            f"Receiving — {fake.city()} {fake.building_number()} Distribution Center"
        )
        ctx["vendors"][vendor["vendor_id"]] = {
            "contact": f"{fake.name()}, {vendor['role']} Accounts Receivable",
            "remit": f"{fake.street_address()}, {fake.city()}, {fake.state_abbr()} {fake.postcode()}",
        }
    return ctx


def build_lines(spec: dict, vendor_id: str) -> list[dict]:
    lines = []
    for entry in spec["lines"]:
        sku, qty = entry[0], int(entry[1])
        unit = entry[2] if len(entry) > 2 else None
        amount = entry[3] if len(entry) > 3 else None
        description = entry[4] if len(entry) > 4 else None

        if unit is None:
            unit = specs.contract_price(vendor_id, sku)
            if unit is None:
                raise ValueError(f"{spec['invoice_no']}: no contract price for {sku}, give one explicitly")
        amount = float(pricing.money(Decimal(str(unit)) * qty)) if amount is None else float(amount)
        lines.append(
            {
                "sku": sku,
                "description": description or specs.sku_description(vendor_id, sku),
                "qty": qty,
                "unit_price": float(unit),
                "amount": amount,
            }
        )
    return lines


def build_invoices(seed: int, terms: dict) -> list[dict]:
    invoices = []
    for spec in invoice_specs.INVOICES:
        lines = build_lines(spec, spec["vendor_id"])
        total = money_float(sum((Decimal(str(line["amount"])) for line in lines), Decimal("0")))
        invoice = {
            "invoice_no": spec["invoice_no"],
            "vendor_name_raw": spec["name"],
            "invoice_date": spec["invoice_date"],
            "line_items": lines,
            "total": total,
        }
        audit = pricing.audit_invoice(invoice, terms[spec["vendor_id"]])
        invoices.append(
            {
                "spec": spec,
                "invoice": invoice,
                "audit": audit,
                "labels": pricing.labels_for(invoice, terms[spec["vendor_id"]]),
            }
        )
    return invoices


# --------------------------------------------------------------------------- #
# PDF rendering
# --------------------------------------------------------------------------- #
def build_pdf(entry: dict, ctx: dict, terms: dict) -> bytes:
    invoice = entry["invoice"]
    spec = entry["spec"]
    vendor = specs.VENDORS_BY_ID[spec["vendor_id"]]

    styles = {
        "name": ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=13, leading=16),
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20, leading=24),
        "small": ParagraphStyle(
            "small", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=colors.HexColor("#3d3d3d")
        ),
    }

    due = pricing.parse_date(invoice["invoice_date"]) + timedelta(days=vendor["payment_days"])
    effective = specs.long_date(vendor["effective_date"])
    left = [
        Paragraph(invoice["vendor_name_raw"], styles["name"]),
        Paragraph(vendor["address"], styles["small"]),
        Paragraph(ctx["vendors"][vendor["vendor_id"]]["contact"], styles["small"]),
    ]
    right = [
        Paragraph("INVOICE", styles["title"]),
        Paragraph(f"Invoice No: {invoice['invoice_no']}", styles["small"]),
        Paragraph(f"Invoice Date: {invoice['invoice_date']}", styles["small"]),
        Paragraph(f"Due Date: {due.isoformat()}", styles["small"]),
        Paragraph(f"PO Number: {spec['po']}", styles["small"]),
    ]
    header = Table([[left, right]], colWidths=[4.3 * inch, 2.7 * inch])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))

    bill_to = [
        Paragraph("<b>Bill To</b>", styles["small"]),
        Paragraph(specs.BUYER_NAME, styles["small"]),
        Paragraph(ctx["buyer"]["address"], styles["small"]),
    ]
    ship_to = [
        Paragraph("<b>Ship To</b>", styles["small"]),
        Paragraph(ctx["sites"][vendor["vendor_id"]], styles["small"]),
        Paragraph("Attn: " + ctx["buyer"]["ap_contact"], styles["small"]),
    ]
    parties = Table([[bill_to, ship_to]], colWidths=[3.5 * inch, 3.5 * inch])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))

    rows = [["SKU", "Description", "Qty", "Unit Price", "Amount"]]
    for line in invoice["line_items"]:
        rows.append(
            [
                line["sku"],
                line["description"],
                f"{line['qty']:,}",
                specs.unit_price_text(line["unit_price"]),
                money_text(line["amount"]),
            ]
        )
    rows.append(["", "", "", "Subtotal", money_text(invoice["total"])])
    rows.append(["", "", "", "Total Due", money_text(invoice["total"])])

    table = Table(rows, colWidths=[0.85 * inch, 3.15 * inch, 0.75 * inch, 1.05 * inch, 1.2 * inch], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -3), "Helvetica"),
                ("FONTNAME", (0, -2), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.HexColor("#9aa5b1")),
                ("LINEABOVE", (0, -2), (-1, -2), 0.5, colors.HexColor("#9aa5b1")),
                ("LINEABOVE", (0, -1), (-1, -1), 1.0, colors.HexColor("#333333")),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (1, 0), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    footer = Paragraph(
        f"Payment terms: net {vendor['payment_days']} days from invoice date. Please reference invoice "
        f"{invoice['invoice_no']} on all payments and remit to {ctx['vendors'][vendor['vendor_id']]['remit']}. "
        f"Rates, volume bands and included services are governed by the Master Services Agreement between "
        f"{specs.BUYER_NAME} and {vendor['canonical_name']} effective {effective}. "
        f"Questions about this invoice: {ctx['vendors'][vendor['vendor_id']]['contact']}.",
        styles["small"],
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title=invoice["invoice_no"],
        author=invoice["vendor_name_raw"],
        subject=f"Invoice {invoice['invoice_no']} — {terms['vendor_id']}",
        creator="Clawback synthetic data generator",
    )
    doc.build(
        [header, Spacer(1, 18), parties, Spacer(1, 18), table, Spacer(1, 16), footer],
        canvasmaker=canvas_maker_for(invoice["invoice_date"]),
    )
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# dataset assembly + writing
# --------------------------------------------------------------------------- #
def build_dataset(seed: int) -> dict:
    terms = specs.all_terms()
    ctx = fake_context(seed, specs.VENDORS)
    entries = build_invoices(seed, terms)
    for entry in entries:
        entry["pdf"] = build_pdf(entry, ctx, terms[entry["spec"]["vendor_id"]])
    return {
        "vendors": specs.vendor_list_json(),
        "terms": terms,
        "contracts": {
            vendor["vendor_id"]: specs.build_markdown(vendor, terms[vendor["vendor_id"]])
            for vendor in specs.VENDORS
        },
        "entries": entries,
        "context": ctx,
    }


def dataset_files(dataset: dict, data_dir: str) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    files["vendors.json"] = json.dumps(dataset["vendors"], indent=2) + "\n"
    files["labels.json"] = (
        json.dumps(
            {entry["invoice"]["invoice_no"]: entry["labels"] for entry in dataset["entries"]},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    files[f"generator/{INTERNAL_TERMS}"] = json.dumps(dataset["terms"], indent=2, sort_keys=True) + "\n"
    expected = {
        entry["invoice"]["invoice_no"]: {
            "decision": entry["audit"]["decision"],
            "total_delta_usd": entry["audit"]["total_delta_usd"],
            "planted": (
                {"type": entry["spec"]["planted"][0], "sku": entry["spec"]["planted"][1]}
                if entry["spec"]["planted"]
                else None
            ),
            "findings": entry["audit"]["findings"],
        }
        for entry in dataset["entries"]
    }
    files[f"generator/{INTERNAL_EXPECTED}"] = json.dumps(expected, indent=2, sort_keys=True) + "\n"
    for vendor_id, markdown in dataset["contracts"].items():
        files[f"contracts/{vendor_id}.md"] = markdown
    for entry in dataset["entries"]:
        invoice_no = entry["invoice"]["invoice_no"]
        files[f"invoices/{invoice_no}.json"] = json.dumps(entry["invoice"], indent=2) + "\n"
        files[f"invoices/{invoice_no}.pdf"] = entry["pdf"]
    return files


def write_dataset(dataset: dict, data_dir: str) -> None:
    for relative, content in dataset_files(dataset, data_dir).items():
        path = os.path.join(data_dir, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if isinstance(content, bytes):
            with open(path, "wb") as handle:
                handle.write(content)
        else:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)


# --------------------------------------------------------------------------- #
# self-checks
# --------------------------------------------------------------------------- #
def run_checks(dataset: dict) -> list[str]:
    failures: list[str] = []
    entries = dataset["entries"]
    terms = dataset["terms"]
    vendors = specs.VENDORS_BY_ID

    def check(ok: bool, label: str, detail: str = "") -> None:
        if not ok:
            failures.append(f"{label}{': ' + detail if detail else ''}")

    invoices = [entry["invoice"] for entry in entries]
    planted = [entry["spec"]["planted"] for entry in entries]
    clean = [entry for entry in entries if entry["spec"]["planted"] is None]

    check(len(entries) == 30, "invoice count", str(len(entries)))
    check(len(invoices) == len({invoice["invoice_no"] for invoice in invoices}), "invoice numbers unique")
    check(len(clean) == 12, "clean invoice count", str(len(clean)))
    check(len(planted) - len(clean) == 18, "planted invoice count", str(len(planted) - len(clean)))

    type_counts: dict[str, int] = {name: 0 for name in pricing.FINDING_TYPES}
    for entry in entries:
        for finding in entry["audit"]["findings"]:
            type_counts[finding["type"]] = type_counts.get(finding["type"], 0) + 1
    for name in pricing.FINDING_TYPES:
        check(type_counts.get(name) == 3, f"finding type spread {name}", str(type_counts.get(name)))

    # exactly one finding per planted invoice, of the planted type and SKU
    for entry in entries:
        spec = entry["spec"]
        findings = entry["audit"]["findings"]
        if spec["planted"] is None:
            check(not findings, f"{spec['invoice_no']} should be clean", str([f["sku"] for f in findings]))
            check(entry["audit"]["decision"] == "APPROVE", f"{spec['invoice_no']} decision", entry["audit"]["decision"])
        else:
            check(len(findings) == 1, f"{spec['invoice_no']} finding count", str(len(findings)))
            if findings:
                got = (findings[0]["type"], findings[0]["sku"])
                check(got == spec["planted"], f"{spec['invoice_no']} planted issue", f"{got} != {spec['planted']}")
                if findings[0]["type"] != "UNKNOWN_SKU":
                    check(findings[0]["delta_usd"] > 0.50, f"{spec['invoice_no']} delta above tolerance")
                    check(findings[0]["delta_usd"] == entry["audit"]["total_delta_usd"],
                          f"{spec['invoice_no']} delta equals the invoice delta")
                check(findings[0]["citation_verified"], f"{spec['invoice_no']} citation",
                      findings[0]["clause_quote"][:40])
                clause = pricing.clause_by_id(terms[spec["vendor_id"]], findings[0]["clause_id"])
                check(clause is not None and findings[0]["clause_quote"] in clause["text"],
                      f"{spec['invoice_no']} quote is an exact substring")
            expected_decision = "DISPUTE" if entry["audit"]["total_delta_usd"] > 250 else "FLAG"
            check(entry["audit"]["decision"] == expected_decision, f"{spec['invoice_no']} decision rule")
    check(all(not e["audit"]["findings"] for e in clean), "clean invoices have no findings")

    # anniversary behaviour
    anniversary = {e["spec"]["invoice_no"]: e for e in entries if e["spec"]["invoice_no"] in {"INV-1002", "INV-1003"}}
    for invoice_no, entry in anniversary.items():
        invoice_date = pricing.parse_date(entry["invoice"]["invoice_date"])
        effective = pricing.parse_date(terms[entry["spec"]["vendor_id"]]["effective_date"])
        gap = min(abs((invoice_date - pricing.add_years(effective, n)).days) for n in (1, 2, 3))
        check(gap <= 14, f"{invoice_no} is within 14 days of an anniversary", f"{gap} days")
        calendar_n = pricing.full_contract_years(effective, invoice_date)
        day_n = pricing.day_based_years(effective, invoice_date)
        check(calendar_n == day_n, f"{invoice_no} n agrees across readings", f"{calendar_n} vs {day_n}")
    check(pricing.full_contract_years("2024-06-01", "2026-05-27") == 1, "INV-1002 sits in year 1")
    check(pricing.full_contract_years("2024-06-01", "2026-06-05") == 2, "INV-1003 sits in year 2")

    # rounding-mode independence
    for vendor in specs.VENDORS:
        pct = vendor["escalator_max_pct"]
        if pct:
            for sku, rate in vendor["rate_card"].items():
                for n in range(0, 4):
                    raw = float(rate) * (1.0 + pct) ** n
                    check(not pricing.is_rounding_tie(raw), f"no rounding tie for {sku} at n={n}", str(raw))
    for entry in entries:
        vendor_id = entry["spec"]["vendor_id"]
        for line in entry["invoice"]["line_items"]:
            tiers = terms[vendor_id]["volume_tiers"].get(line["sku"])
            if tiers:
                raw = pricing.tier_amount_raw(tiers, line["qty"], terms[vendor_id]["tier_type"])
                check(not pricing.is_rounding_tie(raw), f"{entry['spec']['invoice_no']} tier amount tie", str(raw))

    # pricing-structure invariants
    for vendor_id, vendor_terms in terms.items():
        rate_card = set(vendor_terms["rate_card"])
        tiers = set(vendor_terms["volume_tiers"])
        included = set(vendor_terms["included_skus"])
        check(not (rate_card & tiers), f"{vendor_id}: no SKU is both rate card and tiered")
        check(not (rate_card & included), f"{vendor_id}: no SKU is both rate card and included")
        check(not (tiers & included), f"{vendor_id}: no SKU is both tiered and included")

    tiered_vendors = [v for v in specs.VENDORS if v["volume_tiers"]]
    check(len([v for v in tiered_vendors if v["tier_type"] == "incremental"]) >= 2, "at least two incremental contracts")
    check(any(v["tier_type"] == "all_units" for v in tiered_vendors), "at least one all-units contract")
    check(any(v["escalator_max_pct"] for v in specs.VENDORS), "some contracts cap increases")
    check(any(not v["escalator_max_pct"] for v in specs.VENDORS), "some contracts fix prices")

    # prose <-> terms consistency
    for vendor in specs.VENDORS:
        vendor_terms = terms[vendor["vendor_id"]]
        clauses = {clause["id"]: clause["text"] for clause in vendor_terms["clauses"]}
        markdown = dataset["contracts"][vendor["vendor_id"]]
        for header in ("## 7.2 Price Adjustments", "## 3.2 Rates and Charges", "## 4.1", "## 5.1"):
            check(header in markdown, f"{vendor['vendor_id']} has clause {header}")
        for sku, price in vendor_terms["rate_card"].items():
            check(specs.unit_price_text(price) in clauses["3.2"], f"{vendor['vendor_id']} prose price {sku}")
            check(sku in clauses["3.2"], f"{vendor['vendor_id']} prose sku {sku}")
        for sku, bands in vendor_terms["volume_tiers"].items():
            check(sku in clauses["4.1"], f"{vendor['vendor_id']} band sku {sku}")
            for band in bands:
                check(specs.unit_price_text(band["unit_price"]) in clauses["4.1"],
                      f"{vendor['vendor_id']} band price {sku} {band['unit_price']}")
        for sku in vendor_terms["included_skus"]:
            check(sku in clauses["5.1"], f"{vendor['vendor_id']} included sku {sku}")
        pct = vendor_terms["escalator_max_pct"]
        if pct:
            as_text = f"{pct * 100:.1f}%"
            check(as_text in clauses["7.2"], f"{vendor['vendor_id']} escalator prose", as_text)
        else:
            check("fixed for the entire Term" in clauses["7.2"] or "firm and fixed" in clauses["7.2"],
                  f"{vendor['vendor_id']} fixed-price prose")
        # every SKU that an invoice bills must exist in the contract, except planted unknowns
        for entry in dataset["entries"]:
            if entry["spec"]["vendor_id"] != vendor["vendor_id"]:
                continue
            planted_skus = (
                {entry["spec"]["planted"][1]} if entry["spec"]["planted"] and entry["spec"]["planted"][0] == "UNKNOWN_SKU" else set()
            )
            for line in entry["invoice"]["line_items"]:
                if line["sku"] in planted_skus:
                    continue
                check(line["sku"] in pricing.contract_skus(vendor_terms),
                      f"{entry['spec']['invoice_no']} bills {line['sku']} which is not in the contract")

    # vendor-name matching
    vendors_json = {vendor["vendor_id"]: vendor for vendor in dataset["vendors"]}
    off_list = 0
    for entry in entries:
        spec = entry["spec"]
        resolved = pricing.resolve_vendor(vendors_json, spec["name"])
        check(resolved == spec["vendor_id"], f"{spec['invoice_no']} vendor resolution", str(resolved))
        vendor = vendors_json[spec["vendor_id"]]
        known = {vendor["canonical_name"], *vendor["aliases"]}
        if spec["name"] not in known:
            off_list += 1
            check(spec["name"] not in known, f"{spec['invoice_no']} variant is off-list")
    check(off_list >= 5, "a few invoices use off-list name variants", str(off_list))

    # invoice hygiene
    for entry in entries:
        spec, invoice, vendor = entry["spec"], entry["invoice"], vendors[entry["spec"]["vendor_id"]]
        check(2 <= len(invoice["line_items"]) <= 5, f"{invoice['invoice_no']} line count")
        check(all(line["description"] for line in invoice["line_items"]), f"{invoice['invoice_no']} descriptions")
        total = pricing.money(sum((Decimal(str(l["amount"])) for l in invoice["line_items"]), Decimal("0")))
        check(pricing.money(invoice["total"]) == total, f"{invoice['invoice_no']} total is the sum of lines")
        start = pricing.parse_date(vendor["effective_date"])
        end = pricing.add_years(start, vendor["term_years"])
        invoice_date = pricing.parse_date(invoice["invoice_date"])
        check(start <= invoice_date <= end, f"{invoice['invoice_no']} date inside the Term")
        check(spec["po"].startswith(vendor["po_prefix"]), f"{invoice['invoice_no']} PO prefix")
        check(len(entry["pdf"]) > 2000, f"{invoice['invoice_no']} pdf written")
        check(entry["pdf"][:5] == b"%PDF-", f"{invoice['invoice_no']} pdf header")
    return failures


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def print_summary(dataset: dict) -> None:
    entries = dataset["entries"]
    print(f"{'INVOICE':<9} {'VENDOR NAME AS BILLED':<36} {'PLANTED ISSUE':<33} {'DECISION':<9} DELTA")
    print("-" * 106)
    for entry in entries:
        spec = entry["spec"]
        planted = f"{spec['planted'][0]} {spec['planted'][1]}" if spec["planted"] else "— clean —"
        delta = money_text(entry["audit"]["total_delta_usd"]) if entry["audit"]["findings"] else "—"
        print(
            f"{spec['invoice_no']:<9} {spec['name'][:36]:<36} {planted[:33]:<33} "
            f"{entry['audit']['decision']:<9} {delta:>11}"
        )
    print("-" * 106)

    counts = {decision: sum(1 for e in entries if e["audit"]["decision"] == decision) for decision in DECISION_ORDER}
    deltas = {e["spec"]["invoice_no"]: e["audit"]["total_delta_usd"] for e in entries}
    type_counts: dict[str, int] = {name: 0 for name in pricing.FINDING_TYPES}
    for entry in entries:
        for finding in entry["audit"]["findings"]:
            type_counts[finding["type"]] += 1
    total = pricing.money(sum((Decimal(str(delta)) for delta in deltas.values()), Decimal("0")))
    clean = sum(1 for e in entries if not e["audit"]["findings"])
    print(
        f"{len(entries)} invoices | clean {clean} | one planted issue {len(entries) - clean} | "
        f"APPROVE {counts['APPROVE']} FLAG {counts['FLAG']} DISPUTE {counts['DISPUTE']} | "
        f"total delta {money_text(total)}"
    )
    print("findings by type: " + ", ".join(f"{name} {type_counts[name]}" for name in pricing.FINDING_TYPES))
    for vendor in specs.VENDORS:
        vendor_entries = [e for e in entries if e["spec"]["vendor_id"] == vendor["vendor_id"]]
        vendor_total = pricing.money(
            sum((Decimal(str(e["audit"]["total_delta_usd"])) for e in vendor_entries), Decimal("0"))
        )
        print(f"  {vendor['vendor_id']:<24} {len(vendor_entries)} invoices  delta {money_text(vendor_total)}")


def dir_fingerprint(path: str) -> dict[str, str]:
    fingerprints = {}
    for root, _dirs, names in os.walk(path):
        for name in sorted(names):
            full = os.path.join(root, name)
            relative = os.path.relpath(full, path)
            with open(full, "rb") as handle:
                fingerprints[relative] = hashlib.sha256(handle.read()).hexdigest()
    return fingerprints


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="Generate the Clawback synthetic dataset.")
    parser.add_argument("--data-dir", default=os.path.dirname(here), help="where data/ lives")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--check-determinism", action="store_true", help="build twice and compare bytes")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    dataset = build_dataset(args.seed)
    if args.check_determinism:
        first, second = tempfile.mkdtemp(prefix="clawback-a-"), tempfile.mkdtemp(prefix="clawback-b-")
        try:
            for target in (first, second):
                write_dataset(build_dataset(args.seed), target)
            same = dir_fingerprint(first) == dir_fingerprint(second)
        finally:
            shutil.rmtree(first, ignore_errors=True)
            shutil.rmtree(second, ignore_errors=True)
        print(f"determinism (seed {args.seed}): {'identical bytes on both builds' if same else 'DIFFERS'}")
        if not same:
            return 1

    failures = run_checks(dataset)
    if not args.quiet:
        print_summary(dataset)
    if failures:
        print(f"\n{len(failures)} self-check failure(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    if not args.check_determinism:
        write_dataset(dataset, args.data_dir)
        print(f"\nwrote {len(dataset['entries'])} invoices, {len(dataset['contracts'])} contracts, "
              f"vendors.json and labels.json to {args.data_dir}")
    print("all self-checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
