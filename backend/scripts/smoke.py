"""One traced run containing one LLM call. Run: backend/.venv/bin/python -m backend.scripts.smoke"""
from pydantic import BaseModel

from backend import tracing
from backend.llm import complete_json, model_name


class Hello(BaseModel):
    greeting: str
    vendor_count: int


def main() -> None:
    run = tracing.start_run("smoke", session_id="smoke")
    try:
        with tracing.step(run, "hello", {"model": model_name()}) as s:
            out = complete_json(
                "You are a test endpoint.",
                "Say hello to the Clawback team and report vendor_count=5.",
                Hello,
            )
            s.output(out)
        print("LLM output:", out.model_dump())
    except Exception as e:
        tracing.mark_failed(run, str(e))
        raise
    finally:
        tracing.end_run(run)
        tracing.shutdown()
        print("trace_id:", run.trace_id or "(tracing disabled: PRISMTRACE_API_KEY unset)")


if __name__ == "__main__":
    main()
