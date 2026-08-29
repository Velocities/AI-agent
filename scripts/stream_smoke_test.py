"""Manual check that assistant text reaches the terminal incrementally.

Run against a live Ollama instance:
    python scripts/stream_smoke_test.py "explain python decorators"
"""

from __future__ import annotations

import sys
import time

from ai_agent.cli.app import build_agent, configure_logging


def main() -> int:
    prompt = " ".join(sys.argv[1:]) or "In three sentences, explain database migrations."
    agent = build_agent()
    configure_logging("WARNING")

    health = agent.llm.healthcheck()
    if not health.ok:
        print(f"Ollama not usable: {health.message}")
        return 1

    start = time.perf_counter()
    arrivals: list[float] = []

    def on_chunk(text: str) -> None:
        arrivals.append(time.perf_counter() - start)
        sys.stdout.write(text)
        sys.stdout.flush()

    result = agent.run(prompt, stream_callback=on_chunk)
    total = time.perf_counter() - start

    print("\n" + "-" * 60)
    print(f"chunks: {len(arrivals)}")
    if arrivals:
        print(f"first chunk after: {arrivals[0]:.2f}s")
        print(f"last chunk after:  {arrivals[-1]:.2f}s")
    print(f"total: {total:.2f}s | iterations: {result.iterations} | error: {result.error}")
    print(f"final message length: {len(result.final_message)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
