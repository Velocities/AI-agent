import json
import sys

from textkit import count_words
from wordnotes import notable_words


def main() -> None:
    data = json.load(sys.stdin)
    text = data["text"]
    if not isinstance(text, str):
        raise SystemExit("text must be a string")
    json.dump(
        {"words": count_words(text), "notable": notable_words(text)},
        sys.stdout,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
