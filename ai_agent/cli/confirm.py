from __future__ import annotations


def confirm(console, question: str) -> bool:
    """Ask a yes/no question using a Linux-style (y/n) prompt."""
    answer = console.input(f"{question} (y/n) ").strip().lower()
    return answer in {"y", "yes"}
