"""Async event bus used to broadcast sentinel state to subscribers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import TypeAlias


EventPayload: TypeAlias = dict[str, object]


@dataclass(slots=True)
class _Subscriber:
    """Internal subscription handle."""

    queue: "asyncio.Queue[EventPayload]"

    async def put(self, event: EventPayload) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
            self.queue.put_nowait(event)

    async def close(self) -> None:
        try:
            self.queue.put_nowait({"type": "__disconnect__"})
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
            self.queue.put_nowait({"type": "__disconnect__"})


class SentinelEventBus:
    """Fan-out event bus for container metrics, logs, and incidents."""

    def __init__(self) -> None:
        self._subscribers: set[_Subscriber] = set()
        self._lock = asyncio.Lock()

    async def publish(self, event: EventPayload) -> None:
        """Broadcast *event* to all active subscribers."""

        if not event:
            return

        # Snapshot the listeners to avoid holding the lock while awaiting puts
        async with self._lock:
            listeners = list(self._subscribers)

        for listener in listeners:
            try:
                await listener.put(event)
            except asyncio.CancelledError:  # pragma: no cover - defensive
                raise
            except Exception:
                # If a queue is closed or raises we silently drop it; the
                # websocket layer will prune dead connections on next ping.
                with suppress(KeyError):
                    async with self._lock:
                        self._subscribers.remove(listener)

    async def subscribe(self) -> "SentinelSubscription":
        """Register a new subscription and return its handle."""

        queue: "asyncio.Queue[EventPayload]" = asyncio.Queue(maxsize=256)
        subscriber = _Subscriber(queue)
        async with self._lock:
            self._subscribers.add(subscriber)
        return SentinelSubscription(self, subscriber)

    async def unsubscribe(self, subscriber: _Subscriber) -> None:
        async with self._lock:
            self._subscribers.discard(subscriber)


class SentinelSubscription:
    """Wrapper returned to callers so they can consume bus events."""

    def __init__(self, bus: SentinelEventBus, subscriber: _Subscriber) -> None:
        self._bus = bus
        self._subscriber = subscriber
        self._closed = False

    def __aiter__(self) -> AsyncIterator[EventPayload]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[EventPayload]:
        while not self._closed:
            event = await self._subscriber.queue.get()
            if event.get("type") == "__disconnect__":
                break
            yield event

    async def get(self) -> EventPayload:
        """Return the next event from the subscription queue."""

        event = await self._subscriber.queue.get()
        if event.get("type") == "__disconnect__":
            raise asyncio.CancelledError
        return event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._bus.unsubscribe(self._subscriber)
        await self._subscriber.close()
