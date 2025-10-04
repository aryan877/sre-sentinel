"""
Redis-based event bus for SRE Sentinel.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator

import redis.asyncio as redis
from rich.console import Console

from ..models.sentinel_types import RedisMessage, RedisSettings

console = Console()


_EVENT_CHANNEL = "sre-sentinel-events"
_EVENT_HISTORY_KEY = "sre-sentinel-events-history"
_MAX_HISTORY_SIZE = 1000
_SUBSCRIBE_TIMEOUT = 1.0
_ERROR_RETRY_DELAY = 0.1


class RedisEventBus:
    """Redis-backed event bus with pub/sub and persistence."""

    def __init__(self, settings: RedisSettings | None = None) -> None:
        """Initialize the Redis event bus with connection settings."""
        self.settings = settings or RedisSettings.from_env()
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._channel_name = _EVENT_CHANNEL

    async def connect(self) -> None:
        """Initialize Redis connection."""
        try:
            self._redis = redis.Redis(
                host=self.settings.host,
                port=self.settings.port,
                db=self.settings.db,
                password=self.settings.password,
                max_connections=self.settings.max_connections,
                decode_responses=True,
            )
            await self._redis.ping()
            console.print(
                f"[green]✓ Connected to Redis at {self.settings.host}:{self.settings.port}[/green]"
            )
        except Exception as exc:
            console.print(f"[red]Failed to connect to Redis: {exc}[/red]")
            raise

    async def disconnect(self) -> None:
        """Close Redis connections."""
        if self._pubsub:
            await self._pubsub.close()
            self._pubsub = None
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def publish(self, event: dict[str, object]) -> None:
        """Publish event to Redis channel."""
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")

        if not event:
            return

        try:
            message = json.dumps(event, default=str)
            await self._redis.publish(self._channel_name, message)
            await self._redis.lpush(_EVENT_HISTORY_KEY, message)
            await self._redis.ltrim(_EVENT_HISTORY_KEY, 0, _MAX_HISTORY_SIZE - 1)
        except Exception as exc:
            console.print(f"[red]Failed to publish event: {exc}[/red]")

    async def subscribe(self) -> "RedisSubscription":
        """Subscribe to events and return subscription handle."""
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")

        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(self._channel_name)
        return RedisSubscription(self._pubsub, self._redis)

    async def get_event_history(self, limit: int = 100) -> list[dict[str, object]]:
        """Get historical events from Redis list."""
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")

        try:
            events = await self._redis.lrange(_EVENT_HISTORY_KEY, 0, limit - 1)
            return [json.loads(event) for event in events]
        except Exception as exc:
            console.print(f"[red]Failed to get event history: {exc}[/red]")
            return []


class RedisSubscription:
    """Wrapper for Redis pub/sub subscription."""

    def __init__(self, pubsub: redis.client.PubSub, redis_client: redis.Redis) -> None:
        """Initialize the subscription wrapper."""
        self._pubsub = pubsub
        self._redis = redis_client
        self._closed = False

    def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        """Make subscription async iterable."""
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[dict[str, object]]:
        """Iterate over published events."""
        while not self._closed and self._pubsub:
            try:
                message = await self._pubsub.get_message(timeout=_SUBSCRIBE_TIMEOUT)
                if message and message["type"] == "message":
                    try:
                        redis_msg = RedisMessage.model_validate(message)
                        event = json.loads(redis_msg.data)
                        yield event
                    except Exception as e:
                        console.print(
                            f"[yellow]Warning: Could not validate Redis message: {e}[/yellow]"
                        )
                        if isinstance(message.get("data"), (str, bytes)):
                            try:
                                event = json.loads(message["data"])
                                yield event
                            except json.JSONDecodeError:
                                yield {"data": message["data"], "type": "raw"}
            except Exception as exc:
                console.print(f"[red]Error in subscription: {exc}[/red]")
                await asyncio.sleep(_ERROR_RETRY_DELAY)

    async def get(self) -> dict[str, object]:
        """Get the next event from subscription."""
        async for event in self:
            return event
        raise asyncio.CancelledError("Subscription closed")

    async def close(self) -> None:
        """Close the subscription."""
        if self._closed:
            return
        self._closed = True
        if self._pubsub:
            await self._pubsub.unsubscribe(_EVENT_CHANNEL)
            await self._pubsub.close()


async def create_redis_event_bus(
    settings: RedisSettings | None = None,
) -> RedisEventBus:
    """Create and connect to Redis event bus."""
    bus = RedisEventBus(settings)
    await bus.connect()
    return bus
