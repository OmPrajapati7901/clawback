"""PRISM tracing behind a tiny interface. The only module that knows about prismtrace.

We don't use LangChain chains, so we drive PRISMtraceCallbackHandler's callback
methods directly: a run is a root chain span, each step a child chain span, and
each LLM call a chat-model span under the active step. The handler buffers a
run's spans and POSTs them once when the root span ends.

Everything is a no-op when PRISMTRACE_API_KEY is unset.
"""
from __future__ import annotations

import contextvars
import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Iterator

from dotenv import load_dotenv

load_dotenv()

_handler: Any = None
_initialized = False
_current_step: contextvars.ContextVar["Step | None"] = contextvars.ContextVar("step", default=None)


class RunFailed(Exception):
    pass


class StepFailed(Exception):
    pass


def _get_handler() -> Any:
    global _handler, _initialized
    if not _initialized:
        _initialized = True
        if os.getenv("PRISMTRACE_API_KEY", "").strip():
            from prismtrace import PRISMtraceCallbackHandler

            _handler = PRISMtraceCallbackHandler(agent_name="clawback", source="clawback")
    return _handler


def _text(obj: Any) -> Any:
    """Pydantic models and plain objects → JSON-able."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, (list, tuple)):
        return [_text(o) for o in obj]
    if isinstance(obj, dict):
        return {k: _text(v) for k, v in obj.items()}
    return obj


@dataclass
class Run:
    name: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str | None = None
    failed: bool = False
    failure_reason: str | None = None
    ended: bool = False


@dataclass
class Step:
    run: Run
    name: str
    span_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    out: Any = None
    detail: str = ""
    error_msg: str | None = None
    t0: float = field(default_factory=time.perf_counter)

    def output(self, obj: Any) -> None:
        self.out = obj

    def error(self, msg: str) -> None:
        """Mark this step as errored without raising."""
        self.error_msg = msg

    @property
    def ms(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)


def current_step() -> Step | None:
    return _current_step.get()


def start_run(name: str, session_id: str | None = None, **attrs: Any) -> Run:
    run = Run(name=name)
    h = _get_handler()
    if h is None:
        return run
    meta = {k: str(v) for k, v in attrs.items()}
    if session_id:
        meta["session_id"] = session_id
    h.on_chain_start({"name": name}, _text(attrs), run_id=run.run_id, metadata=meta)
    try:
        run.trace_id = h._runs[run.run_id].trace_id
    except Exception:
        run.trace_id = run.run_id
    return run


@contextmanager
def step(run: Run, name: str, inputs: Any = None) -> Iterator[Step]:
    """A traced step. Never yield from a generator inside this block."""
    s = Step(run=run, name=name)
    h = _get_handler()
    if h is not None:
        h.on_chain_start({"name": name}, _text(inputs), run_id=s.span_id, parent_run_id=run.run_id)
    token = _current_step.set(s)
    try:
        yield s
    except BaseException as e:
        s.error_msg = s.error_msg or f"{type(e).__name__}: {e}"
        if h is not None:
            h.on_chain_error(e, run_id=s.span_id)
        raise
    finally:
        _current_step.reset(token)
    if h is not None:
        if s.error_msg:
            h.on_chain_error(StepFailed(s.error_msg), run_id=s.span_id)
        else:
            h.on_chain_end({"output": _text(s.out), "ms": s.ms}, run_id=s.span_id)


@contextmanager
def llm_span(name: str, model: str, messages: list[dict]) -> Iterator[SimpleNamespace]:
    """Trace one model call under the active step. Set .text, .input_tokens, .output_tokens, .cache_hit."""
    rec = SimpleNamespace(text="", input_tokens=None, output_tokens=None, cache_hit=False)
    h = _get_handler()
    parent = _current_step.get()
    if h is None or parent is None:
        yield rec
        return
    span_id = str(uuid.uuid4())
    h.on_chat_model_start(
        {"name": name}, [messages], run_id=span_id, parent_run_id=parent.span_id,
        invocation_params={"model": model},
    )
    try:
        yield rec
    except BaseException as e:
        h.on_chat_model_error(e, run_id=span_id)
        raise
    response = SimpleNamespace(
        generations=[[SimpleNamespace(text=rec.text)]],
        llm_output={"token_usage": {"prompt_tokens": rec.input_tokens, "completion_tokens": rec.output_tokens}},
    )
    h.on_chat_model_end(response, run_id=span_id)


def mark_failed(run: Run, reason: str) -> None:
    run.failed = True
    run.failure_reason = reason


def end_run(run: Run, output: Any = None) -> None:
    """Close the root span; this sends the whole run to PRISM."""
    if run.ended:
        return
    run.ended = True
    h = _get_handler()
    if h is None:
        return
    if run.failed:
        h.on_chain_error(RunFailed(run.failure_reason or "run failed"), run_id=run.run_id)
    else:
        h.on_chain_end({"output": _text(output)}, run_id=run.run_id)


def shutdown() -> None:
    if _handler is not None:
        _handler.close()


def dumps(obj: Any) -> str:
    return json.dumps(_text(obj), default=str)
