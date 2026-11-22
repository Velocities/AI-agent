"""Shared text helpers. Both example tools import this package."""


def count_lines(text: str) -> int:
    if text == "":
        return 0
    return len(text.splitlines())


def count_words(text: str) -> int:
    return len(text.split())
