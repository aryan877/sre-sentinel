"""FastAPI application exposing WebSocket + REST telemetry."""

from __future__ import annotations

import asyncio
import json
from typing import Mapping, Protocol

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from event_bus import SentinelEventBus


class SentinelAPI(Protocol):
    def snapshot_containers(self) -> list[dict[str, object]]: ...

    def snapshot_incidents(self) -> list[dict[str, object]]: ...


def build_application(sentinel: SentinelAPI, event_bus: SentinelEventBus) -> FastAPI:
    """Create the FastAPI app bound to a sentinel instance."""

    app = FastAPI(title="SRE Sentinel", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthcheck() -> Mapping[str, str]:
        return {"status": "ok"}

    @app.get("/containers")
    def list_containers() -> list[dict[str, object]]:
        return sentinel.snapshot_containers()

    @app.get("/incidents")
    def list_incidents() -> list[dict[str, object]]:
        return sentinel.snapshot_incidents()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()

        await websocket.send_text(
            _json_dump(
                {
                    "type": "bootstrap",
                    "containers": sentinel.snapshot_containers(),
                    "incidents": sentinel.snapshot_incidents(),
                }
            )
        )

        subscription = await event_bus.subscribe()

        try:
            async for event in subscription:
                await websocket.send_text(_json_dump(event))
        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:  # pragma: no cover - server shutdown
            raise
        finally:
            await subscription.close()

    return app


def _json_dump(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, default=_json_default)


def _json_default(obj: object) -> object:
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)
