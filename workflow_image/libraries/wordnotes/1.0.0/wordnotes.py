"""Extra helper used only by count-words, so its closure is not count-lines'."""


def notable_words(text: str) -> int:
    return sum(1 for word in text.split() if len(word) > 3)
