"""Process-local LRU for attachment bytes. Not part of the store protocol."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

from ai_agent.attachments.store import AttachmentNotFound, AttachmentStore

DEFAULT_CACHE_KEY = tuple[str, str, str]


class AttachmentCache:
    def __init__(self, store: AttachmentStore, *, max_bytes: int):
        self._store = store
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._entries: OrderedDict[DEFAULT_CACHE_KEY, bytes] = OrderedDict()
        self._size = 0

    def get(self, user_id: str, attachment_id: str, checksum: str | None = None) -> bytes:
        """Return bytes for this user. The cache key includes the checksum."""
        if checksum is not None:
            key = (user_id, attachment_id, checksum)
            with self._lock:
                cached = self._entries.get(key)
                if cached is not None:
                    self._entries.move_to_end(key)
                    return cached
        try:
            data = self._store.get(user_id, attachment_id)
        except AttachmentNotFound:
            raise
        digest = hashlib.sha256(data).hexdigest()
        if checksum is not None and digest != checksum:
            return data
        key = (user_id, attachment_id, checksum or digest)
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                self._entries.move_to_end(key)
                return existing
            self._entries[key] = data
            self._size += len(data)
            self._evict()
        return data

    def invalidate(self, user_id: str, attachment_id: str) -> None:
        with self._lock:
            self._drop(lambda key: key[0] == user_id and key[1] == attachment_id)

    def invalidate_conversation(self, user_id: str, conversation_id: str) -> None:
        """Drop this user's cached bytes. The cache does not index conversation ids."""
        del conversation_id
        with self._lock:
            self._drop(lambda key: key[0] == user_id)

    def size(self) -> int:
        with self._lock:
            return self._size

    def _evict(self) -> None:
        while self._size > self._max_bytes and self._entries:
            _key, blob = self._entries.popitem(last=False)
            self._size -= len(blob)

    def _drop(self, predicate) -> None:
        for key in [key for key in self._entries if predicate(key)]:
            blob = self._entries.pop(key)
            self._size -= len(blob)
