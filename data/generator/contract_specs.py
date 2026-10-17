"""Hand-authored, structured source of truth for the five synthetic vendors.

Everything the generator emits about contracts and prices comes from this file:

* ``vendors.json``            -> ``vendor_id``, ``canonical_name``, ``aliases``
* ``contracts/{vendor_id}.md`` -> ``build_markdown()`` (prose, clause ids, no key-value lists)
* ``terms_ground_truth.json``  -> ``build_terms()`` (CONTRACT.md ``ContractTerms`` shape)
* invoice line descriptions    -> ``SKU_META``

The contract prose interpolates its numbers from the same structures that the
pricing engine reads, so the markdown and ``labels.json`` can never drift apart.
All vendors, people and addresses are fictional.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

from reference_pricing import money, usd

BUYER_NAME = "Harborline Industries, Inc."
BUYER_BLURB = "a Delaware corporation with its principal place of business in Cleveland, Ohio"

_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_YEAR_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def long_date(iso: str) -> str:
    year, month, day = (int(part) for part in iso.split("-"))
    return f"{_MONTHS[month - 1]} {day}, {year}"


def unit_price_text(price: Any) -> str:
    """$2,500.00 and $42.40, but $0.015 for sub-cent storage rates."""
    dec = abs(Decimal(str(price)))
    whole = int(dec)
    fraction = format(dec - whole, "f").split(".")[1].rstrip("0")
    fraction = fraction.ljust(2, "0")
    sign = "-" if Decimal(str(price)) < 0 else ""
    return f"{sign}${whole:,}.{fraction}"


# --------------------------------------------------------------------------- #
# vendor definitions
# --------------------------------------------------------------------------- #
VENDORS: list[dict[str, Any]] = [
    {
        "vendor_id": "corvina_freight",
        "canonical_name": "Corvina Freight Systems LLC",
        "aliases": ["Corvina Freight", "Corvina Freight Systems"],
        "address": "4180 Harbor Ridge Road, Suite 200, Toledo, Ohio 43604",
        "industry": "freight and drayage",
        "industry_label": "Freight, expedited delivery and drayage services",
        "role": "Carrier",
        "entity_kind": "an Ohio limited liability company",
        "duty": (
            "less-than-truckload transportation, expedited delivery and container drayage "
            "services to the Customer distribution centers listed in Exhibit A"
        ),
        "service_standard": (
            "Carrier shall pick up and deliver at least ninety-six percent (96%) of scheduled "
            "stops inside the committed window. A missed window that is not caused by weather, "
            "Customer delay or a documented road closure earns a service credit equal to the "
            "line charge for the affected shipment"
        ),
        "effective_date": "2024-06-01",
        "term_years": 3,
        "payment_days": 30,
        "dispute_days": 15,
        "audit_months": 12,
        "notice_days": 60,
        "governing_law": "the State of Ohio",
        "po_prefix": "HL-FR-",
        "rate_verb": "is billed at",
        "escalator_max_pct": 0.05,
        "tier_type": "incremental",
        "rate_card": {
            "FR-100": 42.40,
            "FR-200": 96.00,
            "FR-300": 185.00,
            "FR-400": 12.80,
        },
        "volume_tiers": {},
        "included_skus": ["FR-900", "FR-901"],
        "sku_meta": {
            "FR-100": {
                "description": "Palletized LTL freight, dry van, origin to destination",
                "clause": "Palletized less-than-truckload freight (SKU FR-100)",
                "unit": "pallet",
                "unit_one": "per pallet",
            },
            "FR-200": {
                "description": "Expedited next-day delivery, committed window",
                "clause": "Expedited next-day delivery (SKU FR-200)",
                "unit": "shipment",
                "unit_one": "per shipment",
            },
            "FR-300": {
                "description": "Container drayage, port to customer warehouse",
                "clause": "Container drayage (SKU FR-300)",
                "unit": "container",
                "unit_one": "per container",
            },
            "FR-400": {
                "description": "Cross-dock handling and palletization",
                "clause": "Cross-dock handling and palletization (SKU FR-400)",
                "unit": "pallet",
                "unit_one": "per pallet handled",
            },
            "FR-900": {
                "description": "Monthly logistics performance reporting",
                "clause": "monthly logistics performance reporting (SKU FR-900)",
                "unit": "month",
                "unit_one": "per month",
            },
            "FR-901": {
                "description": "Fuel surcharge administration",
                "clause": "fuel surcharge administration (SKU FR-901)",
                "unit": "month",
                "unit_one": "per month",
            },
        },
        "bands_prose": (
            "The rates in Section 3.2 are flat rates. This Agreement contains no volume-based rate "
            "bands, tiered pricing, minimum quantity commitment or rebate mechanism, and the number "
            "of pallets, shipments or containers dispatched in any month does not change a unit rate."
        ),
        "included_prose": (
            "The following services are included in the rates set out in Section 3.2 and must not be "
            "billed separately: monthly logistics performance reporting (SKU FR-900), which covers "
            "tracking, on-time performance and exception reporting; and fuel surcharge administration "
            "(SKU FR-901), which covers the calculation, audit and application of the fuel index used "
            "under this Agreement. Carrier's fuel cost recovery is fully expressed in the rates in "
            "Section 3.2."
        ),
        "mechanism_prose": (
            "The rates in Section 3.2 change only as provided in Section 7.2. Any other change, "
            "including a change driven by fuel indices, equipment availability, lane distance or "
            "accessorial practice, requires a written amendment signed by both Parties and takes "
            "effect only for shipments dispatched after the amendment date."
        ),
        "adjustment_prose": (
            "On each anniversary of the Effective Date, Carrier may adjust the unit rates set out in "
            "Section 3.2 by no more than five percent (5.0%) of the rate in effect immediately before "
            "that anniversary, compounded annually over the Term. An adjustment takes effect only on "
            "the anniversary on which it is applied and may not be applied retroactively to any "
            "shipment dispatched before that date. A rate increase above the five percent (5.0%) "
            "ceiling in any contract year is not chargeable, and Customer may treat any invoice line "
            "that applies such an increase as an overcharge."
        ),
    },
    {
        "vendor_id": "heliotrope_cloud",
        "canonical_name": "Heliotrope Cloud Hosting, Inc.",
        "aliases": ["Heliotrope Cloud", "Heliotrope Hosting"],
        "address": "77 Beacon Works Avenue, Floor 9, Wilmington, Delaware 19801",
        "industry": "cloud hosting",
        "industry_label": "Managed cloud hosting services",
        "role": "Provider",
        "entity_kind": "a Delaware corporation",
        "duty": (
            "managed cloud hosting, compute instances, object storage, managed PostgreSQL and "
            "bandwidth services delivered from the region Customer selects in the service console"
        ),
        "service_standard": (
            "Provider shall make compute and managed database services available at least "
            "ninety-nine and ninety-five hundredths percent (99.95%) of the time in each calendar "
            "month. Availability shortfalls earn service credits as set out in Exhibit C, and those "
            "credits are the sole remedy for an availability shortfall"
        ),
        "effective_date": "2025-02-01",
        "term_years": 3,
        "payment_days": 30,
        "dispute_days": 30,
        "audit_months": 24,
        "notice_days": 90,
        "governing_law": "the State of Delaware",
        "po_prefix": "HL-HC-",
        "rate_verb": "is charged at",
        "escalator_max_pct": None,
        "tier_type": "incremental",
        "rate_card": {
            "HC-100": 0.42,
            "HC-300": 310.00,
            "HC-400": 0.09,
            "HC-500": 0.05,
        },
        "volume_tiers": {
            "HC-200": [
                {"min_qty": 1, "unit_price": 0.02},
                {"min_qty": 50000, "unit_price": 0.015},
                {"min_qty": 250000, "unit_price": 0.01},
            ]
        },
        "included_skus": ["HC-900", "HC-901"],
        "sku_meta": {
            "HC-100": {
                "description": "Compute instance, standard tier, Linux",
                "clause": "A standard compute instance (SKU HC-100)",
                "unit": "instance-hour",
                "unit_one": "per instance-hour",
            },
            "HC-200": {
                "description": "Object storage, standard durability",
                "clause": "Object storage (SKU HC-200)",
                "unit": "GB-month",
                "unit_one": "per GB-month",
            },
            "HC-300": {
                "description": "Managed PostgreSQL instance, single region",
                "clause": "A managed PostgreSQL instance (SKU HC-300)",
                "unit": "instance-month",
                "unit_one": "per instance-month",
            },
            "HC-400": {
                "description": "Bandwidth overage beyond the committed allowance",
                "clause": "Bandwidth overage beyond the committed allowance (SKU HC-400)",
                "unit": "GB",
                "unit_one": "per GB of overage",
            },
            "HC-500": {
                "description": "Snapshot storage retention",
                "clause": "Snapshot storage retention (SKU HC-500)",
                "unit": "GB-month",
                "unit_one": "per GB-month",
            },
            "HC-900": {
                "description": "Standard support, business hours",
                "clause": "standard support during business hours (SKU HC-900)",
                "unit": "month",
                "unit_one": "per month",
            },
            "HC-901": {
                "description": "Monthly usage and billing reporting",
                "clause": "monthly usage and billing reporting (SKU HC-901)",
                "unit": "month",
                "unit_one": "per month",
            },
        },
        "bands_prose": (
            "Charges for object storage (SKU HC-200) are calculated incrementally rather than on the "
            "whole quantity. The first 49,999 GB-months billed on a line are charged at $0.02 per "
            "GB-month, and the reduced rate of $0.015 per GB-month applies only to units in excess of "
            "the first 49,999 GB-months on that line. A further reduction to $0.01 per GB-month applies "
            "to units in excess of the first 249,999 GB-months on the same line. A line may not be "
            "split, combined or re-billed to move units between bands, and quantities on separate lines "
            "are not aggregated for the purpose of reaching a band."
        ),
        "included_prose": (
            "Standard support during business hours (SKU HC-900) and monthly usage and billing "
            "reporting (SKU HC-901) are included in the rates in Section 3.2 and in the storage charges "
            "in Section 4.1. Neither may be billed as a separate line item, and neither may be added as "
            "a percentage surcharge on platform charges."
        ),
        "mechanism_prose": (
            "Provider may change platform architecture, instance families or storage media at any time "
            "provided that the rates in Section 3.2 and the bands in Section 4.1 are not increased. "
            "Service credits under Section 2.2 and taxes are the only amounts that may appear on an "
            "invoice in addition to the charges calculated from Section 3.2 and Section 4.1."
        ),
        "adjustment_prose": (
            "The rates in Section 3.2 and the storage bands in Section 4.1 are firm and fixed for the "
            "entire Term. Provider shall not increase any rate, remove any band discount or introduce a "
            "platform fee, minimum commitment or index adjustment during the Term. A unit price on an "
            "invoice that exceeds the rate stated in Section 3.2 is incorrect and is not payable as "
            "billed."
        ),
    },
    {
        "vendor_id": "brightloom_facilities",
        "canonical_name": "Brightloom Facilities Services",
        "aliases": ["Brightloom Facilities", "Brightloom Services"],
        "address": "2201 Westfield Industrial Parkway, Naperville, Illinois 60540",
        "industry": "facilities management",
        "industry_label": "Facilities management services",
        "role": "Contractor",
        "entity_kind": "an Illinois corporation",
        "duty": (
            "janitorial, hard-floor care, landscaping and HVAC preventive maintenance services at the "
            "Customer facilities listed in Exhibit A"
        ),
        "service_standard": (
            "Contractor shall complete a quarterly quality inspection at each site and shall score at "
            "least eighty-five percent (85%) on the inspection checklist. A site that scores below that "
            "threshold is re-performed within five (5) business days at no additional charge"
        ),
        "effective_date": "2024-01-15",
        "term_years": 3,
        "payment_days": 45,
        "dispute_days": 20,
        "audit_months": 12,
        "notice_days": 60,
        "governing_law": "the State of Illinois",
        "po_prefix": "HL-BF-",
        "rate_verb": "carries a rate of",
        "escalator_max_pct": 0.03,
        "tier_type": "incremental",
        "rate_card": {
            "BF-100": 185.00,
            "BF-200": 420.00,
            "BF-300": 140.00,
            "BF-400": 250.00,
        },
        "volume_tiers": {
            "BF-500": [
                {"min_qty": 1, "unit_price": 0.14},
                {"min_qty": 20000, "unit_price": 0.11},
                {"min_qty": 75000, "unit_price": 0.085},
            ]
        },
        "included_skus": ["BF-900", "BF-901"],
        "sku_meta": {
            "BF-100": {
                "description": "Janitorial service visit, standard site",
                "clause": "A standard janitorial service visit (SKU BF-100)",
                "unit": "visit",
                "unit_one": "per visit",
            },
            "BF-200": {
                "description": "HVAC preventive maintenance, rooftop unit",
                "clause": "HVAC preventive maintenance on a rooftop unit (SKU BF-200)",
                "unit": "unit",
                "unit_one": "per rooftop unit serviced",
            },
            "BF-300": {
                "description": "Landscaping service visit, grounds maintenance",
                "clause": "A landscaping service visit (SKU BF-300)",
                "unit": "visit",
                "unit_one": "per visit",
            },
            "BF-400": {
                "description": "Emergency maintenance callout, after hours",
                "clause": "An emergency maintenance callout (SKU BF-400)",
                "unit": "call",
                "unit_one": "per callout",
            },
            "BF-500": {
                "description": "Hard-floor care and refinishing, measured area",
                "clause": "Hard-floor care and refinishing (SKU BF-500)",
                "unit": "square foot",
                "unit_one": "per square foot",
            },
            "BF-900": {
                "description": "Restroom consumables and paper products",
                "clause": "restroom consumables and paper products (SKU BF-900)",
                "unit": "month",
                "unit_one": "per month",
            },
            "BF-901": {
                "description": "Monthly service report and inspection log",
                "clause": "the monthly service report and inspection log (SKU BF-901)",
                "unit": "month",
                "unit_one": "per month",
            },
        },
        "bands_prose": (
            "Floor care (SKU BF-500) is billed by measured area in three bands. The first 19,999 "
            "square feet billed on a line carry a rate of $0.14 per square foot; every square foot from "
            "the 20,000th through the 74,999th on that line carries a rate of $0.11 per square foot; "
            "and every square foot from the 75,000th onward on that line carries a rate of $0.085 per "
            "square foot. Each square foot is billed in exactly one band, and the lower band rates do "
            "not apply to the whole quantity."
        ),
        "included_prose": (
            "Restroom consumables and paper products (SKU BF-900) are included in the janitorial rate "
            "for every site, and the monthly service report and inspection log (SKU BF-901) is included "
            "in the preventive maintenance and landscaping rates. Neither SKU may be billed separately, "
            "and a consumables charge may not be added as a percentage of the janitorial rate."
        ),
        "mechanism_prose": (
            "Rates are stated per visit, per rooftop unit, per callout or per square foot as indicated "
            "in Section 3.2 and Section 4.1. An emergency callout outside business hours is billed at "
            "the rate in Section 3.2 with no travel-time, fuel or administrative additive."
        ),
        "adjustment_prose": (
            "Contractor may adjust the rates in Section 3.2 once per contract year by written notice "
            "given at least thirty (30) days before the anniversary of the Effective Date, subject to a "
            "ceiling of three percent (3.0%) of the rate in effect immediately before that anniversary, "
            "compounded annually over the Term. The floor-care band rates in Section 4.1 are not subject "
            "to any annual adjustment and remain fixed for the Term. A rate may not be raised more than "
            "once in any twelve (12) month period and may not be applied retroactively."
        ),
    },
    {
        "vendor_id": "pinecrest_supply",
        "canonical_name": "Pinecrest Office Supply Company",
        "aliases": ["Pinecrest Supply", "Pinecrest Office"],
        "address": "9040 Riverbend Commerce Court, Portland, Oregon 97203",
        "industry": "office supplies",
        "industry_label": "Office supply, breakroom and furniture products",
        "role": "Supplier",
        "entity_kind": "an Oregon corporation",
        "duty": (
            "office supplies, breakroom products, paper and furniture delivered to the Customer "
            "ordering locations listed in Exhibit A"
        ),
        "service_standard": (
            "Supplier shall deliver stocked items by the next business day for orders released before "
            "3:00 p.m. local time and shall maintain a fill rate of at least ninety-eight percent (98%) "
            "measured monthly. Backordered lines are reported to Customer within one business day"
        ),
        "effective_date": "2024-09-01",
        "term_years": 3,
        "payment_days": 30,
        "dispute_days": 15,
        "audit_months": 12,
        "notice_days": 30,
        "governing_law": "the State of Oregon",
        "po_prefix": "HL-PS-",
        "rate_verb": "is priced at",
        "escalator_max_pct": None,
        "tier_type": "all_units",
        "rate_card": {
            "PS-200": 92.50,
            "PS-300": 46.75,
            "PS-400": 215.00,
            "PS-500": 168.00,
        },
        "volume_tiers": {
            "PS-100": [
                {"min_qty": 1, "unit_price": 38.40},
                {"min_qty": 50, "unit_price": 34.25},
                {"min_qty": 200, "unit_price": 29.90},
            ]
        },
        "included_skus": ["PS-900", "PS-901"],
        "sku_meta": {
            "PS-100": {
                "description": "Multipurpose copy paper, 20 lb, 10-ream case",
                "clause": "Multipurpose copy paper (SKU PS-100)",
                "unit": "case",
                "unit_one": "per case",
            },
            "PS-200": {
                "description": "Printer toner cartridge, black, high yield",
                "clause": "A high-yield black toner cartridge (SKU PS-200)",
                "unit": "cartridge",
                "unit_one": "per cartridge",
            },
            "PS-300": {
                "description": "Breakroom supply box, assorted",
                "clause": "A breakroom supply box (SKU PS-300)",
                "unit": "box",
                "unit_one": "per box",
            },
            "PS-400": {
                "description": "Ergonomic task chair, mid-back",
                "clause": "An ergonomic task chair (SKU PS-400)",
                "unit": "unit",
                "unit_one": "per chair",
            },
            "PS-500": {
                "description": "Two-drawer filing cabinet, letter size",
                "clause": "A two-drawer filing cabinet (SKU PS-500)",
                "unit": "unit",
                "unit_one": "per cabinet",
            },
            "PS-900": {
                "description": "Standard delivery and inside placement",
                "clause": "standard delivery and inside placement (SKU PS-900)",
                "unit": "month",
                "unit_one": "per month",
            },
            "PS-901": {
                "description": "Monthly spend and usage report",
                "clause": "the monthly spend and usage report (SKU PS-901)",
                "unit": "month",
                "unit_one": "per month",
            },
        },
        "bands_prose": (
            "Copy paper (SKU PS-100) is priced at $38.40 per case before volume discounts and is billed "
            "on a whole-line basis. When the quantity billed on a single invoice line reaches fifty (50) "
            "cases, the rate of $34.25 per case applies to every case on that line, and when the quantity "
            "billed on that line reaches two hundred (200) cases, the rate of $29.90 per case applies to "
            "every case on that line. Discounts that apply only to cases above a threshold are not "
            "offered under this Agreement, and the whole-line rate is determined by the quantity actually "
            "invoiced on the line."
        ),
        "included_prose": (
            "Standard delivery and inside placement (SKU PS-900) and the monthly spend and usage report "
            "(SKU PS-901) are included in the rates in Section 3.2 and in the case rates in Section 4.1. "
            "No delivery, handling, fuel, small-order or reporting fee may be added to an invoice."
        ),
        "mechanism_prose": (
            "Supplier may substitute an equivalent product for a discontinued item without changing the "
            "SKU or the rate, provided the substitute is of equal or better specification and the "
            "substitution is disclosed on the next monthly report."
        ),
        "adjustment_prose": (
            "The rates in Section 3.2 and the case rates in Section 4.1 are firm and fixed for the "
            "entire Term. Supplier shall not increase any price during the Term, and an invoice line "
            "that states a price above the applicable rate is incorrect, is not payable as billed and "
            "may be deducted by Customer from the amount payable. Delivery surcharges, small-order fees "
            "and index adjustments are not permitted."
        ),
    },
    {
        "vendor_id": "kestrel_staffing",
        "canonical_name": "Kestrel Staffing Partners",
        "aliases": ["Kestrel Staffing"],
        "address": "1301 Congress Avenue, Suite 1450, Austin, Texas 78701",
        "industry": "contract staffing",
        "industry_label": "Contract staffing services",
        "role": "Staffing Provider",
        "entity_kind": "a Texas limited liability company",
        "duty": (
            "contract staffing services for the analyst, engineering and administrative roles "
            "catalogued in Exhibit B, including recruiting, screening and assignment administration"
        ),
        "service_standard": (
            "Staffing Provider shall replace an assigned worker who does not meet the assignment "
            "requirements within three (3) business days at no additional charge, and shall reconcile "
            "approved timesheets weekly rather than at invoice time"
        ),
        "effective_date": "2023-08-01",
        "term_years": 3,
        "payment_days": 30,
        "dispute_days": 20,
        "audit_months": 24,
        "notice_days": 60,
        "governing_law": "the State of Texas",
        "po_prefix": "HL-KS-",
        "rate_verb": "is invoiced at",
        "escalator_max_pct": 0.04,
        "tier_type": "incremental",
        "rate_card": {
            "KS-100": 78.00,
            "KS-200": 145.00,
            "KS-300": 42.00,
            "KS-400": 2500.00,
        },
        "volume_tiers": {},
        "included_skus": ["KS-900", "KS-901"],
        "sku_meta": {
            "KS-100": {
                "description": "Contract analyst, per hour worked",
                "clause": "A contract analyst (SKU KS-100)",
                "unit": "hour",
                "unit_one": "per hour worked",
            },
            "KS-200": {
                "description": "Senior engineer, per hour worked",
                "clause": "A senior engineer (SKU KS-200)",
                "unit": "hour",
                "unit_one": "per hour worked",
            },
            "KS-300": {
                "description": "Data entry clerk, per hour worked",
                "clause": "A data entry clerk (SKU KS-300)",
                "unit": "hour",
                "unit_one": "per hour worked",
            },
            "KS-400": {
                "description": "Permanent placement fee, accepted placement",
                "clause": "A permanent placement fee (SKU KS-400)",
                "unit": "placement",
                "unit_one": "per accepted placement",
            },
            "KS-900": {
                "description": "Timesheet administration and approval",
                "clause": "timesheet administration and approval (SKU KS-900)",
                "unit": "month",
                "unit_one": "per month",
            },
            "KS-901": {
                "description": "Monthly utilization and compliance report",
                "clause": "the monthly utilization and compliance report (SKU KS-901)",
                "unit": "month",
                "unit_one": "per month",
            },
        },
        "bands_prose": (
            "This Agreement contains no volume rate bands or tiered discounts. Hours are billed at the "
            "hourly rates in Section 3.2 regardless of the number of hours invoiced in a month, and no "
            "blended rate, overtime multiplier or volume discount applies."
        ),
        "included_prose": (
            "Timesheet administration and approval (SKU KS-900) and the monthly utilization and "
            "compliance report (SKU KS-901) are included in the hourly rates in Section 3.2. Neither "
            "may be billed separately, and the placement fee covers all recruiting, screening, "
            "onboarding and background-check administration."
        ),
        "mechanism_prose": (
            "Rates are stated per hour worked. Staffing Provider shall not bill for orientation, "
            "training, equipment, benefits administration or travel time, and shall not invoice hours "
            "beyond the timesheets Customer approved for the period invoiced."
        ),
        "adjustment_prose": (
            "Staffing Provider may adjust the hourly rates in Section 3.2 on each anniversary of the "
            "Effective Date by no more than four percent (4.0%) of the rate in effect immediately "
            "before that anniversary, compounding annually over the Term. An adjustment may not be "
            "applied before the anniversary on which it takes effect and may not be applied to hours "
            "worked in an earlier period. The placement fee in Section 3.2 is fixed for the Term."
        ),
    },
]

VENDORS_BY_ID: dict[str, dict[str, Any]] = {v["vendor_id"]: v for v in VENDORS}


def sku_description(vendor_id: str, sku: str, fallback: str = "") -> str:
    meta = VENDORS_BY_ID[vendor_id]["sku_meta"].get(sku)
    return meta["description"] if meta else fallback


def contract_price(vendor_id: str, sku: str) -> float | None:
    vendor = VENDORS_BY_ID[vendor_id]
    if sku in vendor["rate_card"]:
        return float(vendor["rate_card"][sku])
    return None


# --------------------------------------------------------------------------- #
# clause rendering
# --------------------------------------------------------------------------- #
def _rate_sentence(vendor: dict[str, Any], sku: str, price: float) -> str:
    meta = vendor["sku_meta"][sku]
    return f"{meta['clause']} {vendor['rate_verb']} {unit_price_text(price)} {meta['unit_one']}"


def build_clauses(vendor: dict[str, Any]) -> list[dict[str, str]]:
    role = vendor["role"]
    eff = long_date(vendor["effective_date"])
    term_word = _YEAR_WORDS.get(vendor["term_years"], str(vendor["term_years"]))
    rate_sentences = " ".join(
        _rate_sentence(vendor, sku, price) + "." for sku, price in vendor["rate_card"].items()
    )
    tiered = bool(vendor["volume_tiers"])
    pricing_intro = (
        "The rates below are the complete schedule of charges for the services described in "
        "Section 2.1, stated per unit of measure."
    )
    clauses = [
        {
            "id": "1.1",
            "title": "Parties and Roles",
            "text": (
                f"This Master Services Agreement (this \"Agreement\") is made by and between "
                f"{vendor['canonical_name']}, {vendor['entity_kind']} (\"{role}\"), and {BUYER_NAME}, "
                f"{BUYER_BLURB} (\"Customer\"). {role} and Customer are each a \"Party\" and together "
                f"the \"Parties\". {role} shall perform the services described in Section 2.1 through "
                f"its own employees and subcontractors, and remains responsible for their performance."
            ),
        },
        {
            "id": "1.2",
            "title": "Effective Date and Term",
            "text": (
                f"This Agreement takes effect on {eff} (the \"Effective Date\") and continues for a "
                f"Term of {term_word} ({vendor['term_years']}) years from that date (the \"Term\") "
                f"unless terminated earlier under Section 9.1. On expiration of the initial Term the "
                f"Agreement renews for successive twelve (12) month periods unless a Party gives "
                f"written notice of non-renewal at least {vendor['notice_days']} days before the end of "
                f"the then-current period. All amounts are stated in United States dollars."
            ),
        },
        {
            "id": "2.1",
            "title": "Services Provided",
            "text": (
                f"{role} shall provide {vendor['duty']}. The only charges that may be invoiced under "
                f"this Agreement are the rates and bands expressly identified in Section 3.2 and "
                f"Section 4.1, and the pass-through amounts permitted by Section 3.3. No other charges, "
                f"surcharges, administrative fees, minimum commitments or accessorials may be billed "
                f"unless Customer authorizes them in writing before they are incurred."
            ),
        },
        {
            "id": "2.2",
            "title": "Service Standards and Remedies",
            "text": (
                f"{vendor['service_standard']}. A service failure gives rise to the credits stated in "
                f"this Section and does not create a right to increase any rate, to suspend service "
                f"without notice, or to add a recovery surcharge of any kind."
            ),
        },
        {
            "id": "3.1",
            "title": "Invoicing and Payment",
            "text": (
                f"{role} shall invoice monthly in arrears. Each invoice must state a unique invoice "
                f"number, the invoice date, the applicable purchase order number, and for every line "
                f"item the SKU code, the description, the quantity, the unit price and the line amount. "
                f"The quantity multiplied by the unit price must equal the line amount, and the invoice "
                f"total must equal the sum of the line amounts. Customer pays undisputed amounts within "
                f"{vendor['payment_days']} days of receipt of a correct invoice. An invoice that does "
                f"not comply with this Section is returned for correction without affecting the Term."
            ),
        },
        {
            "id": "3.2",
            "title": "Rates and Charges",
            "text": (
                f"{pricing_intro} {rate_sentences} Rates are exclusive of sales and use taxes, which "
                f"Customer pays as required by law. No fuel, minimum, platform, administrative or "
                f"convenience charge may be added to these rates."
            ),
        },
        {
            "id": "3.3",
            "title": "Pass-Through Charges",
            "text": (
                f"Customer-approved third-party costs are passed through at actual cost with no markup "
                f"and must be identified on the invoice by the SKU to which they relate. A pass-through "
                f"amount that is not pre-approved in writing is not payable. {role} bears all costs of "
                f"doing business under this Agreement, including its own insurance, licensing, "
                f"equipment and supervision."
            ),
        },
        {
            "id": "4.1",
            "title": "Volume Bands and Quantity Pricing",
            "text": vendor["bands_prose"],
        },
        {
            "id": "5.1",
            "title": "Included Services",
            "text": vendor["included_prose"],
        },
        {
            "id": "5.2",
            "title": "Charges Not Permitted",
            "text": (
                f"{role} shall not bill separately for travel time, training, supervision, "
                f"administrative overhead or any service described in Section 5.1. A charge for a "
                f"service identified in Section 5.1 may not appear on an invoice with a positive "
                f"amount, and a credit for such a charge may only be applied with Customer's written "
                f"agreement."
            ),
        },
        {
            "id": "6.1",
            "title": "Purchase Orders and Reporting",
            "text": (
                f"Each invoice must reference a Customer purchase order with the {vendor['po_prefix']} "
                f"prefix, and {role} shall not invoice against an expired or closed purchase order. "
                f"{role} shall also provide a quarterly business review covering volumes, service "
                f"performance and any substitute products, substitutions or rate changes applied during "
                f"the quarter."
            ),
        },
        {
            "id": "7.1",
            "title": "Adjustment Mechanism",
            "text": vendor["mechanism_prose"],
        },
        {
            "id": "7.2",
            "title": "Price Adjustments",
            "text": vendor["adjustment_prose"],
        },
        {
            "id": "8.1",
            "title": "Audit and Records",
            "text": (
                f"Customer or its designee may audit {role}'s records supporting any invoice for "
                f"{vendor['audit_months']} months after the invoice date. If an audit shows an "
                f"overcharge, {role} shall refund or credit the overcharged amount within thirty (30) "
                f"days of the audit findings, together with interest at one percent (1%) per month from "
                f"the invoice date. {role} shall keep supporting records for the full audit period."
            ),
        },
        {
            "id": "8.2",
            "title": "Disputed Amounts",
            "text": (
                f"Customer may withhold a disputed amount and shall give written notice within "
                f"{vendor['dispute_days']} days of receiving the invoice. The Parties shall resolve the "
                f"dispute in good faith within thirty (30) days of notice, and {role} shall not suspend "
                f"service or impose a late fee on a disputed amount while the dispute is pending. "
                f"Amounts found to be overcharges are credited on the next invoice."
            ),
        },
        {
            "id": "9.1",
            "title": "Termination",
            "text": (
                f"Either Party may terminate this Agreement for material breach on thirty (30) days' "
                f"written notice if the breach is not cured within that period, or for convenience on "
                f"{vendor['notice_days']} days' written notice. Termination does not affect Customer's "
                f"right to recover overcharges identified under Section 8.1, and the rates in Section "
                f"3.2 continue to govern all services performed before the effective date of "
                f"termination."
            ),
        },
        {
            "id": "10.1",
            "title": "Governing Law and Entire Agreement",
            "text": (
                f"This Agreement is governed by the laws of {vendor['governing_law']}, without regard "
                f"to its conflict of laws rules. This Agreement, together with its Exhibits, is the "
                f"entire agreement of the Parties on its subject matter and supersedes all prior "
                f"proposals, quotes and rate sheets. No purchase order, invoice, portal term or "
                f"click-through term modifies this Agreement, and any such term that conflicts with "
                f"this Agreement is void."
            ),
        },
        {
            "id": "10.2",
            "title": "Execution",
            "text": (
                f"The Parties execute this Agreement as of the Effective Date. {BUYER_NAME}, by its "
                f"authorized officer, and {vendor['canonical_name']}, by its authorized officer, have "
                f"each signed below and delivered this Agreement electronically.\n\n"
                f"| Customer | {role} |\n| --- | --- |\n"
                f"| {BUYER_NAME} | {vendor['canonical_name']} |\n"
                f"| Name: Dana Whitfield | Name: Priya Raghunathan |\n"
                f"| Title: Director, Procurement Operations | Title: Vice President, Commercial |\n"
            ),
        },
    ]
    if not tiered:
        # keep section 4.1 free of any band numbers for flat-rate vendors
        clauses[7]["title"] = "No Volume Bands"
    return clauses


def build_markdown(vendor: dict[str, Any], terms: dict[str, Any]) -> str:
    lines = [
        f"# Master Services Agreement — {vendor['canonical_name']}",
        "",
        f"*{vendor['industry_label']} for {BUYER_NAME}*",
        "",
        (
            f"This Agreement is entered into by {vendor['canonical_name']} (\"{vendor['role']}\") and "
            f"{BUYER_NAME} (\"Customer\") as of {long_date(vendor['effective_date'])}. It sets out the "
            f"services, the rates, the volume bands and the included services that apply to every "
            f"invoice {vendor['role']} issues during the Term."
        ),
        "",
    ]
    for clause in terms["clauses"]:
        lines.append(f"## {clause['id']} {clause['title']}")
        lines.append("")
        lines.append(clause["text"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_terms(vendor: dict[str, Any]) -> dict[str, Any]:
    """CONTRACT.md ``ContractTerms`` for one vendor."""
    return {
        "vendor_id": vendor["vendor_id"],
        "effective_date": vendor["effective_date"],
        "rate_card": copy.deepcopy(vendor["rate_card"]),
        "escalator_max_pct": vendor["escalator_max_pct"],
        "volume_tiers": copy.deepcopy(vendor["volume_tiers"]),
        "tier_type": vendor["tier_type"],
        "included_skus": list(vendor["included_skus"]),
        "clauses": build_clauses(vendor),
    }


def all_terms() -> dict[str, dict[str, Any]]:
    return {vendor["vendor_id"]: build_terms(vendor) for vendor in VENDORS}


def vendor_list_json() -> list[dict[str, Any]]:
    return [
        {
            "vendor_id": vendor["vendor_id"],
            "canonical_name": vendor["canonical_name"],
            "aliases": list(vendor["aliases"]),
        }
        for vendor in VENDORS
    ]
