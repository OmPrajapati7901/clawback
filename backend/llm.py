"""All LLM calls: Nicrron (OpenAI-compatible) → validated Pydantic objects."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import TypeVar

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from backend import tracing

load_dotenv()

BASE_URL = "https://api.nicrron.ai/v1"
CACHE_PATH = Path(__file__).parent / ".cache" / "llm.sqlite"
T = TypeVar("T", bound=BaseModel)

_client: OpenAI | None = None


def model_name() -> str:
    m = os.getenv("MODEL") or "anthropic/claude-sonnet-5"
    if m == "nicrron/auto":
        raise ValueError("MODEL=nicrron/auto is not allowed")
    return m


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=BASE_URL, api_key=os.environ["NICRRON_API_KEY"])
    return _client


def _cache_db() -> sqlite3.Connection | None:
    if os.getenv("LLM_CACHE") != "1":
        return None
    CACHE_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(CACHE_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, text TEXT)")
    return con


def _chat(messages: list[dict], name: str) -> str:
    model = model_name()
    key = hashlib.sha256((model + json.dumps(messages, sort_keys=True)).encode()).hexdigest()
    with tracing.llm_span(name, model, messages) as rec:
        con = _cache_db()
        if con is not None:
            row = con.execute("SELECT text FROM cache WHERE key=?", (key,)).fetchone()
            if row:
                rec.text, rec.cache_hit = row[0], True
                return row[0]
        resp = _get_client().chat.completions.create(model=model, messages=messages, temperature=0)
        text = resp.choices[0].message.content or ""
        rec.text = text
        if resp.usage:
            rec.input_tokens, rec.output_tokens = resp.usage.prompt_tokens, resp.usage.completion_tokens
        if con is not None:
            con.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (key, text))
            con.commit()
        return text


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


def complete_json(system: str, user: str, model_cls: type[T]) -> T:
    schema = json.dumps(model_cls.model_json_schema())
    messages = [
        {"role": "system", "content": f"{system}\n\nRespond with JSON only, no prose, matching this JSON schema:\n{schema}"},
        {"role": "user", "content": user},
    ]
    text = _chat(messages, f"llm:{model_cls.__name__}")
    try:
        return model_cls.model_validate_json(_strip_fences(text))
    except ValidationError as e:
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": f"That JSON failed validation:\n{e}\nReturn corrected JSON only."},
        ]
        text = _chat(messages, f"llm:{model_cls.__name__}:retry")
        return model_cls.model_validate_json(_strip_fences(text))
