"""FastAPI per CONTRACT HTTP API. Run: backend/.venv/bin/uvicorn backend.app:app --reload"""
from __future__ import annotations

import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend import db, steps, tracing
from backend.pipeline import run_invoice
from backend.schemas import Invoice

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = Path(__file__).parent / "uploads"
FRONTEND = ROOT / "frontend"


def _load_data() -> None:
    if (steps.DATA / "vendors.json").exists():
        for v in steps.load_vendors():
            db.upsert_vendor(v)
    for p in sorted((steps.DATA / "invoices").glob("*.json")):
        db.upsert_invoice(Invoice.model_validate_json(p.read_text()), str(p))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_data()
    yield
    tracing.shutdown()


app = FastAPI(title="Clawback", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _labels() -> dict:
    p = steps.DATA / "labels.json"
    return json.loads(p.read_text()) if p.exists() else {}


@app.post("/api/invoices")
def upload_invoice(file: UploadFile) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".json"):
        raise HTTPException(400, "upload a .pdf or .json invoice")
    UPLOADS.mkdir(exist_ok=True)
    tmp = UPLOADS / f"upload-{Path(file.filename).name}"
    with tmp.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    run = tracing.start_run("upload_invoice", session_id=tmp.stem, filename=file.filename)
    try:
        out = steps.parse_invoice(run, str(tmp))
    except Exception as e:
        tracing.mark_failed(run, str(e))
        raise HTTPException(422, f"could not parse invoice: {e}")
    finally:
        tracing.end_run(run, locals().get("out") and out.value)
    inv: Invoice = out.value
    dest = UPLOADS / f"{inv.invoice_no}{suffix}"
    tmp.replace(dest)
    db.upsert_invoice(inv, str(dest))
    return {"invoice_no": inv.invoice_no}


@app.get("/api/invoices")
def list_invoices() -> list[dict]:
    out = []
    for r in db.list_invoices():
        res = db.latest_run(r["invoice_no"])
        vendor = steps.match_vendor(r["vendor_name_raw"])
        out.append({
            "invoice_no": r["invoice_no"],
            "vendor": vendor["canonical_name"] if vendor else r["vendor_name_raw"],
            "invoice_date": r["invoice_date"],
            "total": r["total"],
            "decision": res.decision if res else None,
            "total_delta_usd": res.total_delta_usd if res else None,
            "status": res.run_status if res else "pending",
        })
    return out


@app.get("/api/invoices/{invoice_no}")
def get_invoice(invoice_no: str) -> dict:
    found = db.get_invoice(invoice_no)
    if not found:
        raise HTTPException(404, "invoice not found")
    res = db.latest_run(invoice_no)
    return {"invoice": found[0].model_dump(), "result": res.model_dump() if res else None}


@app.get("/api/invoices/{invoice_no}/process")
def process_invoice(invoice_no: str, version: str = "v1") -> StreamingResponse:
    found = db.get_invoice(invoice_no)
    if not found:
        raise HTTPException(404, "invoice not found")
    expected = _labels().get(invoice_no)

    def events() -> Iterator[str]:
        for ev in run_invoice(found[1], version=version, expected=expected):
            yield f"data: {ev.model_dump_json()}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/contracts/{vendor_id}")
def get_contract(vendor_id: str) -> dict:
    try:
        text = steps.contract_text(vendor_id)
    except FileNotFoundError:
        raise HTTPException(404, "contract not found")
    run = tracing.start_run("load_contract", session_id=vendor_id, vendor_id=vendor_id)
    try:
        terms = steps.load_contract_terms(run, vendor_id).value
    except Exception as e:
        tracing.mark_failed(run, str(e))
        raise HTTPException(500, f"could not extract terms: {e}")
    finally:
        tracing.end_run(run)
    return {"text": text, "terms": terms.model_dump()}


@app.get("/api/stats")
def stats() -> dict:
    return db.stats()


if FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
