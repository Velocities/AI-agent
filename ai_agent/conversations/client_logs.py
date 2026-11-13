"""Client debug logs, appended to one file per user in the order the client logged them.

A client process is one stream. It numbers every line from zero and sends batches
one at a time, so a batch always starts where the previous acknowledged one ended.
The server keeps the next expected number per stream. A retried batch whose lines
are already written is skipped, and a gap (lines the client dropped) is marked in
the file instead of being silently closed up.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

LOG_NAME = "client.log"
STATE_NAME = "client-log-state.json"
MAX_FILE_BYTES = 10 * 1024 * 1024
BACKUPS = 3
MAX_STREAMS_KEPT = 50

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class ClientLogError(ValueError):
    """The batch cannot be stored."""


@dataclass(frozen=True)
class ClientLogBatch:
    stream: str
    device: str
    first_seq: int
    lines: tuple[str, ...]


class ClientLogWriter:
    def __init__(self, root: Path):
        self.root = root
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def append(self, user_id: str, batch: ClientLogBatch) -> int:
        """Write the lines this stream has not written yet. Return the next expected number."""
        owner = _safe(user_id, "user id")
        stream = _safe(batch.stream, "stream")
        if batch.first_seq < 0:
            raise ClientLogError("first_seq must not be negative.")
        with self._lock_for(owner):
            folder = self.root / owner
            folder.mkdir(parents=True, exist_ok=True)
            state = _read_state(folder / STATE_NAME)
            streams: dict[str, int] = state.setdefault("streams", {})
            expected = int(streams.get(stream, 0))
            end = batch.first_seq + len(batch.lines)
            if end <= expected:
                return expected
            skip = max(0, expected - batch.first_seq)
            start = batch.first_seq + skip
            out: list[str] = []
            if state.get("last_stream") != stream:
                device = _one_line(batch.device)[:120] or "unknown device"
                out.append(f"----- client {stream} ({device}) -----")
            if start > expected:
                out.append(f"[{start - expected} client log lines were dropped before they were sent]")
            out.extend(_one_line(line) for line in batch.lines[skip:])
            log = folder / LOG_NAME
            _rotate_if_full(log)
            with log.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(out) + "\n")
            streams.pop(stream, None)
            streams[stream] = end
            while len(streams) > MAX_STREAMS_KEPT:
                streams.pop(next(iter(streams)))
            state["last_stream"] = stream
            _write_state(folder / STATE_NAME, state)
            return end

    def _lock_for(self, owner: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(owner, threading.Lock())


def _safe(value: str, label: str) -> str:
    text = value.strip()
    if not _SAFE_ID.match(text) or text in {".", ".."}:
        raise ClientLogError(f"The {label} is not a valid log id.")
    return text


def _one_line(text: str) -> str:
    return text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _read_state(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_state(path: Path, state: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state), encoding="utf-8")
    temp.replace(path)


def _rotate_if_full(log: Path) -> None:
    try:
        if log.stat().st_size < MAX_FILE_BYTES:
            return
    except FileNotFoundError:
        return
    for index in range(BACKUPS, 0, -1):
        older = log.with_name(f"{log.name}.{index}")
        newer = log.with_name(f"{log.name}.{index - 1}") if index > 1 else log
        if newer.exists():
            newer.replace(older)
