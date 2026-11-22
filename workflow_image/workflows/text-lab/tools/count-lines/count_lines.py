import json
import sys

from textkit import count_lines


def main() -> None:
    data = json.load(sys.stdin)
    text = data["text"]
    if not isinstance(text, str):
        raise SystemExit("text must be a string")
    json.dump({"lines": count_lines(text)}, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
