"""
FastAPI application exposing WebSocket + REST telemetry.
"""

from __future__ import annotations

import asyncio
import json
from typing import Mapping, Protocol

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from src.infrastructure.redis_event_bus import RedisEventBus
from src.models.sentinel_types import HealthResponse, BootstrapEvent


class SentinelAPI(Protocol):
    """Protocol for Sentinel API operations."""

    def snapshot_containers(self) -> list[dict[str, object]]:
        """Get current container states."""
        ...

    def snapshot_incidents(self) -> list[dict[str, object]]:
        """Get incident history."""
        ...


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

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WebSocket endpoint for real-time event streaming."""
        try:
            await websocket.accept()

            # Send bootstrap data with increased timeout
            bootstrap_event = BootstrapEvent(
                containers=sentinel.snapshot_containers(),
                incidents=sentinel.snapshot_incidents(),
            )
            try:
                await asyncio.wait_for(
                    websocket.send_text(_json_dump(bootstrap_event.model_dump())),
                    timeout=10.0,
                )
            except asyncio.TimeoutError:
                print("Bootstrap data send timed out")
                await websocket.close(code=1013, reason="Server timeout")
                return

            # Subscribe to event bus with increased timeout
            try:
                subscription = await asyncio.wait_for(
                    event_bus.subscribe(), timeout=10.0
                )
            except asyncio.TimeoutError:
                print("Event bus subscription timed out")
                await websocket.close(code=1013, reason="Server timeout")
                return

            try:
                async for event in subscription:
                    try:
                        await asyncio.wait_for(
                            websocket.send_text(_json_dump(event)), timeout=10.0
                        )
                    except asyncio.TimeoutError:
                        print("Event send timed out, continuing...")
                        continue
                    except WebSocketDisconnect:
                        print("WebSocket disconnected during event send")
                        break
            except WebSocketDisconnect:
                print("WebSocket disconnected normally")
                pass
            except asyncio.TimeoutError:
                print("Event iteration timed out")
            except asyncio.CancelledError:
                print("WebSocket task cancelled")
                raise
            except Exception as e:
                print(f"Error in event loop: {e}")
            finally:
                try:
                    await subscription.close()
                except Exception as e:
                    print(f"Error closing subscription: {e}")
        except WebSocketDisconnect:
            print("WebSocket disconnected during handshake")
        except Exception as e:
            # Log the error but don't raise to avoid breaking the connection
            print(f"WebSocket error: {e}")
            try:
                await websocket.close(code=1011, reason="Internal server error")
            except:
                pass

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
