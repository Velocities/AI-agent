"""Manual check that a long answer completes without visible resume artifacts.

Run against a live Ollama instance:
    python scripts/resume_smoke_test.py ["custom prompt"]
"""

from __future__ import annotations

import logging
import sys
import time

from ai_agent.cli.app import build_agent, configure_logging, run_error_notice

PROMPT = (
    "Write a detailed reference on Python error handling. Cover the exception "
    "hierarchy, try/except/else/finally, custom exceptions, context managers, "
    "retries, logging, and testing failure paths. Include code examples and a "
    "common-mistakes section for each topic."
)


class ResumeCounter(logging.Handler):
    """Count how many times the loop resumed a cut-off answer."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage().startswith("Resuming answer"):
            self.count += 1


def main() -> int:
    prompt = " ".join(sys.argv[1:]) or PROMPT
    agent = build_agent()
    configure_logging("DEBUG")

    health = agent.llm.healthcheck()
    if not health.ok:
        print(f"Ollama not usable: {health.message}")
        return 1

    counter = ResumeCounter()
    loop_logger = logging.getLogger("ai_agent.agent.loop")
    loop_logger.setLevel(logging.DEBUG)
    loop_logger.addHandler(counter)

    parts: list[str] = []
    start = time.perf_counter()
    result = agent.run(prompt, stream_callback=parts.append)
    total = time.perf_counter() - start
    answer = "".join(parts)

    print("\n" + "-" * 60)
    print(f"chunks: {len(parts)} | resumes: {counter.count} | total: {total:.1f}s")
    print(f"streamed chars: {len(answer)} | final chars: {len(result.final_message)}")
    print(f"error: {result.error} | notice: {run_error_notice(result.error)}")
    print("-" * 60)
    print("tail of streamed answer:")
    print(answer[-500:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
