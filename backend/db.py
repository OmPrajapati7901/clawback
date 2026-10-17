"""SQLite persistence. Rows hold JSON blobs of the CONTRACT types."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.schemas import ContractTerms, Invoice, RunResult

DB_PATH = Path(__file__).parent / "clawback.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS vendors (vendor_id TEXT PRIMARY KEY, canonical_name TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS contracts (
  vendor_id TEXT, version TEXT, text_sha TEXT, text TEXT, terms_json TEXT,
  PRIMARY KEY (vendor_id, version, text_sha));
CREATE TABLE IF NOT EXISTS invoices (
  invoice_no TEXT PRIMARY KEY, vendor_name_raw TEXT, invoice_date TEXT, total REAL, path TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, invoice_no TEXT, version TEXT, decision TEXT, total_delta_usd REAL,
  run_status TEXT, trace_id TEXT, result_json TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS findings (
  run_id TEXT, type TEXT, sku TEXT, billed_amount REAL, expected_amount REAL, delta_usd REAL,
  clause_id TEXT, clause_quote TEXT, citation_verified INTEGER, explanation TEXT);
CREATE TABLE IF NOT EXISTS disputes (run_id TEXT PRIMARY KEY, invoice_no TEXT, subject TEXT, body TEXT);
"""


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert_vendor(v: dict) -> None:
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO vendors VALUES (?,?,?)", (v["vendor_id"], v["canonical_name"], json.dumps(v)))


def list_vendors() -> list[dict]:
    with connect() as con:
        return [json.loads(r["json"]) for r in con.execute("SELECT json FROM vendors")]


def get_terms(vendor_id: str, version: str, text_sha: str) -> ContractTerms | None:
    with connect() as con:
        r = con.execute(
            "SELECT terms_json FROM contracts WHERE vendor_id=? AND version=? AND text_sha=?",
            (vendor_id, version, text_sha),
        ).fetchone()
    return ContractTerms.model_validate_json(r["terms_json"]) if r else None


def save_terms(terms: ContractTerms, version: str, text_sha: str, text: str) -> None:
    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO contracts VALUES (?,?,?,?,?)",
            (terms.vendor_id, version, text_sha, text, terms.model_dump_json()),
        )


def upsert_invoice(inv: Invoice, path: str) -> None:
    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO invoices VALUES (?,?,?,?,?,?)",
            (inv.invoice_no, inv.vendor_name_raw, inv.invoice_date, inv.total, path, inv.model_dump_json()),
        )


def get_invoice(invoice_no: str) -> tuple[Invoice, str] | None:
    with connect() as con:
        r = con.execute("SELECT json, path FROM invoices WHERE invoice_no=?", (invoice_no,)).fetchone()
    return (Invoice.model_validate_json(r["json"]), r["path"]) if r else None


def list_invoices() -> list[sqlite3.Row]:
    with connect() as con:
        return con.execute("SELECT * FROM invoices ORDER BY invoice_no").fetchall()


def save_run(result: RunResult) -> str:
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        con.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, result.invoice_no, result.version, result.decision, result.total_delta_usd,
             result.run_status, result.trace_id, result.model_dump_json(), now),
        )
        con.executemany(
            "INSERT INTO findings VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(run_id, f.type, f.sku, f.billed_amount, f.expected_amount, f.delta_usd,
              f.clause_id, f.clause_quote, int(f.citation_verified), f.explanation) for f in result.findings],
        )
        if result.dispute_email:
            con.execute(
                "INSERT INTO disputes VALUES (?,?,?,?)",
                (run_id, result.invoice_no, result.dispute_email.subject, result.dispute_email.body),
            )
    return run_id


def latest_run(invoice_no: str) -> RunResult | None:
    with connect() as con:
        r = con.execute(
            "SELECT result_json FROM runs WHERE invoice_no=? ORDER BY created_at DESC LIMIT 1", (invoice_no,)
        ).fetchone()
    return RunResult.model_validate_json(r["result_json"]) if r else None


def stats() -> dict:
    with connect() as con:
        rows = con.execute(
            """SELECT r.decision, r.total_delta_usd FROM runs r
               JOIN (SELECT invoice_no, MAX(created_at) m FROM runs GROUP BY invoice_no) l
               ON r.invoice_no = l.invoice_no AND r.created_at = l.m"""
        ).fetchall()
        n_invoices = con.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
    return {
        "recovered_usd": round(sum(r["total_delta_usd"] for r in rows if r["decision"] == "DISPUTE"), 2),
        "invoices": n_invoices,
        "disputes": sum(r["decision"] == "DISPUTE" for r in rows),
        "flags": sum(r["decision"] == "FLAG" for r in rows),
        "approvals": sum(r["decision"] == "APPROVE" for r in rows),
    }
