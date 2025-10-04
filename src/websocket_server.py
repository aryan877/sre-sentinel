"""
FastAPI application exposing WebSocket + REST telemetry.
"""

from __future__ import annotations

import asyncio
import json
from typing import Mapping

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from redis_event_bus import RedisEventBus


class SentinelAPI(BaseModel):
    """Protocol for Sentinel API operations."""

    def snapshot_containers(self) -> list[dict[str, object]]:
        """Get current container states."""
        ...

    def snapshot_incidents(self) -> list[dict[str, object]]:
        """Get incident history."""
        ...


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(default="ok", description="Health status of the service")


class BootstrapEvent(BaseModel):
    """Bootstrap event for WebSocket clients."""

    type: str = Field(default="bootstrap", description="Event type identifier")
    containers: list[dict[str, object]] = Field(description="Current container states")
    incidents: list[dict[str, object]] = Field(description="Current incident states")


def build_application(sentinel: SentinelAPI, event_bus: RedisEventBus) -> FastAPI:
    """Create the FastAPI application bound to a sentinel instance."""
    app = FastAPI(title="SRE Sentinel", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["Health"], response_model=HealthResponse)
    def healthcheck() -> HealthResponse:
        """Health check endpoint."""
        return HealthResponse(status="ok")

    @app.get("/containers", tags=["Monitoring"])
    def list_containers() -> list[dict[str, object]]:
        """Get current container states."""
        return sentinel.snapshot_containers()

    @app.get("/incidents", tags=["Monitoring"])
    def list_incidents() -> list[dict[str, object]]:
        """Get incident history."""
        return sentinel.snapshot_incidents()

    @app.websocket("/ws", tags=["Real-time"])
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WebSocket endpoint for real-time event streaming."""
        await websocket.accept()

        bootstrap_event = BootstrapEvent(
            containers=sentinel.snapshot_containers(),
            incidents=sentinel.snapshot_incidents(),
        )
        await websocket.send_text(_json_dump(bootstrap_event.model_dump()))

        subscription = await event_bus.subscribe()

        try:
            async for event in subscription:
                await websocket.send_text(_json_dump(event))
        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:
            raise
        finally:
            await subscription.close()

    return app


def _json_dump(payload: Mapping[str, object]) -> str:
    """Serialize a payload to JSON string."""
    return json.dumps(payload, default=_json_default)


def _json_default(obj: object) -> object:
    """Default JSON serializer for special types."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()

    if hasattr(obj, "model_dump"):
        return obj.model_dump()

    return str(obj)
