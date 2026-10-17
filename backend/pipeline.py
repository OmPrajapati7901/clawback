"""run_invoice per CONTRACT: yields StepEvents, persists results, traces the whole run to PRISM."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Generator, Iterator

from backend import db, pricing, steps, tracing
from backend.schemas import Finding, RunResult, StepEvent


class _Abort(Exception):
    def __init__(self, step: str, error: Exception):
        super().__init__(f"{step}: {type(error).__name__}: {error}")


def _do(
    run: tracing.Run, errors: list[str], name: str, fn: Callable, *args: Any, version: str
) -> Generator[StepEvent, None, steps.Outcome]:
    yield StepEvent(step=name, status="running", detail="", ms=0)
    t0 = time.perf_counter()
    try:
        o = fn(run, *args, version=version)
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        yield StepEvent(step=name, status="error", detail=f"{type(e).__name__}: {e}", ms=ms)
        raise _Abort(name, e) from e
    if o.error:
        errors.append(f"{name}: {o.error}")
    yield StepEvent(step=name, status="error" if o.error else "ok", detail=o.error or o.detail, ms=o.ms)
    return o


def run_invoice(invoice_path: str, version: str = "v1", expected: dict | None = None) -> Iterator[StepEvent]:
    invoice_no = Path(invoice_path).stem
    run = tracing.start_run("run_invoice", session_id=invoice_no, invoice_path=invoice_path, version=version)
    errors: list[str] = []
    findings: list[Finding] = []
    decision, email, aborted = "FLAG", None, False
    try:
        try:
            inv = (yield from _do(run, errors, "parse_invoice", steps.parse_invoice, invoice_path, version=version)).value
            invoice_no = inv.invoice_no
            db.upsert_invoice(inv, invoice_path)
            vendor = (yield from _do(run, errors, "resolve_vendor", steps.resolve_vendor,
                                     inv.vendor_name_raw, version=version)).value
            terms = (yield from _do(run, errors, "load_contract_terms", steps.load_contract_terms,
                                    vendor["vendor_id"], version=version)).value
            yield from _do(run, errors, "compute_expected", steps.compute_expected, inv, terms, version=version)
            findings = (yield from _do(run, errors, "compare_lines", steps.compare_lines,
                                       inv, terms, version=version)).value
            findings = (yield from _do(run, errors, "explain_findings", steps.explain_findings,
                                       findings, terms, version=version)).value
            findings = (yield from _do(run, errors, "verify_citations", steps.verify_citations,
                                       findings, vendor["vendor_id"], version=version)).value
            decision, email = (yield from _do(run, errors, "decide_and_draft", steps.decide_and_draft,
                                              inv, vendor, findings, version=version)).value
        except _Abort as a:
            aborted = True
            errors.append(str(a))

        result = RunResult(
            invoice_no=invoice_no, version=version, decision=decision, findings=findings,
            total_delta_usd=pricing.total_delta(findings), dispute_email=email,
            run_status="failed" if errors else "ok", trace_id=run.trace_id,
        )
        if expected is not None and not aborted:
            try:
                yield from _do(run, errors, "grade", steps.grade, result, expected, version=version)
            except _Abort as a:
                errors.append(str(a))
            if errors:
                result.run_status = "failed"

        if errors:
            tracing.mark_failed(run, "; ".join(errors))
        db.save_run(result)
    finally:
        tracing.end_run(run, locals().get("result"))
    yield StepEvent(step="result", status="error" if errors else "ok",
                    detail="; ".join(errors) or result.decision, ms=0, result=result)
