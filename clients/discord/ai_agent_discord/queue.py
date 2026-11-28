"""One in-flight turn per deployment URL.

The agent API only refuses a second turn in the same conversation. Two people
in two conversations would otherwise share one model with no warning. This
queue is the Discord bot's line for a deployment.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


class DeploymentQueue:
    def __init__(self) -> None:
        self._meta = asyncio.Lock()
        self._locks: dict[str, asyncio.Lock] = {}
        self._depth: dict[str, int] = {}

    async def join(self, deployment: str) -> Ticket:
        async with self._meta:
            lock = self._locks.setdefault(deployment, asyncio.Lock())
            ahead = self._depth.get(deployment, 0)
            self._depth[deployment] = ahead + 1
        return Ticket(deployment=deployment, ahead=ahead, lock=lock, queue=self)

    async def release(self, deployment: str) -> None:
        async with self._meta:
            lock = self._locks[deployment]
            # Unlock before the depth drops so a new joiner cannot observe an
            # empty line while this turn still holds the lock.
            lock.release()
            self._decrement(deployment)

    async def abandon(self, deployment: str) -> None:
        """Drop a ticket that never took the lock."""
        async with self._meta:
            self._decrement(deployment)

    def _decrement(self, deployment: str) -> None:
        depth = self._depth.get(deployment, 1) - 1
        if depth <= 0:
            self._depth.pop(deployment, None)
        else:
            self._depth[deployment] = depth


@dataclass
class Ticket:
    deployment: str
    ahead: int
    lock: asyncio.Lock
    queue: DeploymentQueue
    _state: str = "joined"

    async def wait(self) -> None:
        if self._state != "joined":
            raise RuntimeError("This ticket is already waiting or finished.")
        try:
            await self.lock.acquire()
        except BaseException:
            await self.queue.abandon(self.deployment)
            self._state = "closed"
            raise
        self._state = "holding"

    async def close(self) -> None:
        if self._state == "closed":
            return
        if self._state == "holding":
            await self.queue.release(self.deployment)
        else:
            await self.queue.abandon(self.deployment)
        self._state = "closed"
