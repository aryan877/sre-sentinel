"""
Redis-based event bus for SRE Sentinel with Pydantic models.

This module provides a distributed event bus using Redis for pub/sub
messaging and event persistence. It enables real-time communication
between components of the SRE Sentinel system and provides persistence
for event history.

The event bus is responsible for:
1. Publishing events to all subscribers
2. Maintaining a history of recent events
3. Providing real-time event streaming
4. Handling connection management with Redis

Architecture:
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Publishers    │───▶│   Redis Pub/Sub │───▶│   Subscribers   │
│                 │    │                 │    │                 │
│ - Monitor       │    │ - Events        │    │ - WebSocket     │
│ - MCP Gateway   │    │ - History       │    │ - API Clients   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │   Redis List    │
                       │                 │
                       │ - Event History │
                       │ - Persistence   │
                       └─────────────────┘
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator

import redis.asyncio as redis
from pydantic import BaseModel, Field
from rich.console import Console

console = Console()


class RedisMessage(BaseModel):
    """
    Redis pub/sub message structure.
    
    Represents a message received from Redis pub/sub, including
    the message type, channel, and data payload.
    """
    type: str = Field(description="Message type from Redis pub/sub")
    pattern: bytes | None = Field(default=None, description="Pattern for pmessage subscriptions")
    channel: bytes = Field(description="Channel the message was received on")
    data: bytes = Field(description="Raw message data as bytes")


class BootstrapEvent(BaseModel):
    """
    Bootstrap event for initial state synchronization.
    
    Published when a new WebSocket client connects, providing
    the current state of containers and incidents to bootstrap
    the client with the latest data.
    """
    type: str = Field(default="bootstrap", description="Event type identifier")
    containers: list[dict[str, object]] = Field(description="Current container states")
    incidents: list[dict[str, object]] = Field(description="Current incident states")


class RedisSettings(BaseModel):
    """
    Configuration settings for Redis connection.
    
    This model encapsulates all the settings needed to connect
    to Redis, including host, port, authentication, and connection
    pool configuration.
    """
    host: str = Field(default="localhost", description="Redis server host")
    port: int = Field(default=6379, ge=1, le=65535, description="Redis server port")
    db: int = Field(default=0, ge=0, description="Redis database number")
    password: str | None = Field(default=None, description="Password for Redis authentication")
    max_connections: int = Field(default=10, ge=1, le=100, description="Maximum connections in pool")
    
    @classmethod
    def from_env(cls) -> "RedisSettings":
        """
        Create settings from environment variables.
        
        Loads configuration from environment variables with sensible defaults.
        """
        return cls(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD"),
            max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", "10")),
        )


# Constants for Redis configuration
_DEFAULT_HOST: str = "localhost"
_DEFAULT_PORT: int = 6379
_DEFAULT_DB: int = 0
_DEFAULT_MAX_CONNECTIONS: int = 10
_EVENT_CHANNEL: str = "sre-sentinel-events"  # Channel for event pub/sub
_EVENT_HISTORY_KEY: str = "sre-sentinel-events-history"  # Key for event history list
_MAX_HISTORY_SIZE: int = 1000  # Maximum number of events to keep in history
_SUBSCRIBE_TIMEOUT: float = 1.0  # Timeout for pub/sub subscription (seconds)
_ERROR_RETRY_DELAY: float = 0.1  # Delay between subscription retries (seconds)


class RedisEventBus:
    """
    Redis-backed event bus with pub/sub and persistence using Pydantic models.
    
    This class provides a distributed event bus using Redis for pub/sub
    messaging and event persistence. It enables real-time communication
    between components of the SRE Sentinel system.
    
    Features:
    1. Real-time event publishing and subscription
    2. Event history persistence
    3. Connection management and error handling
    4. Type-safe event handling with Pydantic models
    """
    
    def __init__(self, settings: RedisSettings | None = None) -> None:
        """
        Initialize the Redis event bus with connection settings.
        
        Args:
            settings: Redis connection settings. If None, loads from environment.
        """
        self.settings = settings or RedisSettings.from_env()
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._channel_name = _EVENT_CHANNEL
        
    async def connect(self) -> None:
        """
        Initialize Redis connection.
        
        Establishes a connection to Redis and tests it with a ping.
        Raises an exception if the connection fails.
        """
        try:
            # Create Redis client with connection pooling
            self._redis = redis.Redis(
                host=self.settings.host,
                port=self.settings.port,
                db=self.settings.db,
                password=self.settings.password,
                max_connections=self.settings.max_connections,
                decode_responses=True,
            )
            # Test the connection
            await self._redis.ping()
            console.print(f"[green]✓ Connected to Redis at {self.settings.host}:{self.settings.port}[/green]")
        except Exception as exc:
            console.print(f"[red]Failed to connect to Redis: {exc}[/red]")
            raise
            
    async def disconnect(self) -> None:
        """
        Close Redis connections.
        
        Gracefully closes the pub/sub connection and Redis client,
        releasing all resources.
        """
        if self._pubsub:
            await self._pubsub.close()
            self._pubsub = None
        if self._redis:
            await self._redis.close()
            self._redis = None
            
    async def publish(self, event: dict[str, object]) -> None:
        """
        Publish event to Redis channel.
        
        Publishes an event to the Redis pub/sub channel and also
        stores it in a Redis list for persistence and history.
        
        Args:
            event: Event data to publish as a dictionary
        """
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")
            
        if not event:
            return
            
        try:
            # Serialize event to JSON
            message = json.dumps(event, default=str)
            
            # Publish to pub/sub channel
            await self._redis.publish(self._channel_name, message)
            
            # Store in list for persistence (keep last N events)
            await self._redis.lpush(_EVENT_HISTORY_KEY, message)
            await self._redis.ltrim(_EVENT_HISTORY_KEY, 0, _MAX_HISTORY_SIZE - 1)
        except Exception as exc:
            console.print(f"[red]Failed to publish event: {exc}[/red]")
            
    async def subscribe(self) -> "RedisSubscription":
        """
        Subscribe to events and return subscription handle.
        
        Creates a pub/sub subscription to the event channel and returns
        a subscription handle that can be used to iterate over events.
        
        Returns:
            RedisSubscription handle for iterating over events
        """
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")
            
        # Create pub/sub subscription
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(self._channel_name)
        return RedisSubscription(self._pubsub, self._redis)
        
    async def get_event_history(self, limit: int = 100) -> list[dict[str, object]]:
        """
        Get historical events from Redis list.
        
        Retrieves the most recent events from the Redis list that
        stores event history. This is useful for bootstrapping new
        subscribers with recent events.
        
        Args:
            limit: Maximum number of events to retrieve
            
        Returns:
            List of event dictionaries
        """
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")
            
        try:
            # Get events from Redis list
            events = await self._redis.lrange(_EVENT_HISTORY_KEY, 0, limit - 1)
            # Parse JSON events
            return [json.loads(event) for event in events]
        except Exception as exc:
            console.print(f"[red]Failed to get event history: {exc}[/red]")
            return []


class RedisSubscription:
    """
    Wrapper for Redis pub/sub subscription with Pydantic models.
    
    This class provides a clean interface for iterating over events
    from a Redis pub/sub subscription, with proper error handling
    and type validation.
    """
    
    def __init__(self, pubsub: redis.client.PubSub, redis_client: redis.Redis) -> None:
        """
        Initialize the subscription wrapper.
        
        Args:
            pubsub: Redis pub/sub subscription object
            redis_client: Redis client for the subscription
        """
        self._pubsub = pubsub
        self._redis = redis_client
        self._closed = False
        
    def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        """
        Make subscription async iterable.
        
        Returns:
            Async iterator that yields event dictionaries
        """
        return self._iterate()
        
    async def _iterate(self) -> AsyncIterator[dict[str, object]]:
        """
        Iterate over published events.
        
        Continuously receives messages from the Redis pub/sub
        subscription and yields parsed event dictionaries.
        Handles connection errors and retries automatically.
        
        Yields:
            Event dictionaries from the pub/sub subscription
        """
        while not self._closed and self._pubsub:
            try:
                # Get message from pub/sub with timeout
                message = await self._pubsub.get_message(timeout=_SUBSCRIBE_TIMEOUT)
                if message and message["type"] == "message":
                    # Validate message structure with our Pydantic model
                    try:
                        redis_msg = RedisMessage.model_validate(message)
                        event = json.loads(redis_msg.data)
                        yield event
                    except Exception as e:
                        console.print(f"[yellow]Warning: Could not validate Redis message: {e}[/yellow]")
                        # Fall back to raw parsing if validation fails
                        if isinstance(message.get("data"), (str, bytes)):
                            try:
                                event = json.loads(message["data"])
                                yield event
                            except json.JSONDecodeError:
                                # If we can't parse JSON, yield the raw data
                                yield {"data": message["data"], "type": "raw"}
            except Exception as exc:
                console.print(f"[red]Error in subscription: {exc}[/red]")
                # Wait before retrying to prevent tight loop on error
                await asyncio.sleep(_ERROR_RETRY_DELAY)
                
    async def get(self) -> dict[str, object]:
        """
        Get the next event from subscription.
        
        Convenience method that returns the next event from the
        subscription, raising an exception if the subscription is closed.
        
        Returns:
            Next event dictionary from the subscription
            
        Raises:
            asyncio.CancelledError: If the subscription is closed
        """
        async for event in self:
            return event
        raise asyncio.CancelledError("Subscription closed")
        
    async def close(self) -> None:
        """
        Close the subscription.
        
        Unsubscribes from the channel and closes the pub/sub
        connection, releasing all resources.
        """
        if self._closed:
            return
        self._closed = True
        if self._pubsub:
            await self._pubsub.unsubscribe(_EVENT_CHANNEL)
            await self._pubsub.close()


async def create_redis_event_bus(settings: RedisSettings | None = None) -> RedisEventBus:
    """
    Create and connect to Redis event bus.
    
    Convenience function that creates a RedisEventBus instance
    and establishes the connection to Redis.
    
    Args:
        settings: Redis connection settings. If None, loads from environment.
        
    Returns:
        Connected RedisEventBus instance
    """
    bus = RedisEventBus(settings)
    await bus.connect()
    return bus