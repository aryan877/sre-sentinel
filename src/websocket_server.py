"""
FastAPI application exposing WebSocket + REST telemetry with Pydantic models.

This module provides the web API for the SRE Sentinel system, exposing
both REST endpoints for historical data and WebSocket endpoints for
real-time event streaming. It serves as the primary interface for
the web dashboard and external monitoring tools.

The API server provides:
1. REST endpoints for container and incident data
2. WebSocket endpoint for real-time event streaming
3. Health check endpoint for monitoring systems
4. CORS support for web dashboard integration

Architecture:
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Web Clients   │───▶│   FastAPI       │───▶│   Event Bus     │
│                 │    │                 │    │                 │
│ - Dashboard     │    │ - REST API      │    │ - Subscribe     │
│ - Monitoring    │    │ - WebSocket     │    │ - Publish       │
│ - Alerts        │    │ - CORS          │    │ - History       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │   SRE Sentinel  │
                       │                 │
                       │ - State         │
                       │ - Events        │
                       └─────────────────┘
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
    """
    Protocol for Sentinel API operations.
    
    Defines the interface that the SRE Sentinel monitoring system
    must implement to provide data to the API server.
    """
    
    def snapshot_containers(self) -> list[dict[str, object]]: 
        """
        Get current container states.
        
        Returns:
            List of container state dictionaries
        """
        ...
    
    def snapshot_incidents(self) -> list[dict[str, object]]: 
        """
        Get incident history.
        
        Returns:
            List of incident dictionaries
        """
        ...


class HealthResponse(BaseModel):
    """
    Health check response model.
    
    Simple response model for the health check endpoint,
    indicating the service is operational.
    """
    status: str = Field(default="ok", description="Health status of the service")


class BootstrapEvent(BaseModel):
    """
    Bootstrap event for WebSocket clients.
    
    Sent when a new WebSocket client connects, providing the
    current state of containers and incidents to bootstrap
    the client with the latest data.
    """
    type: str = Field(default="bootstrap", description="Event type identifier")
    containers: list[dict[str, object]] = Field(description="Current container states")
    incidents: list[dict[str, object]] = Field(description="Current incident states")


def build_application(sentinel: SentinelAPI, event_bus: RedisEventBus) -> FastAPI:
    """
    Create the FastAPI application bound to a sentinel instance.
    
    This function builds and configures the FastAPI application with
    all the necessary routes, middleware, and error handlers. It
    connects the API to the SRE Sentinel monitoring system and
    Redis event bus for real-time data streaming.
    
    Args:
        sentinel: SRE Sentinel monitoring system instance
        event_bus: Redis event bus for real-time events
        
    Returns:
        Configured FastAPI application
    """
    # Create FastAPI app with metadata
    app = FastAPI(title="SRE Sentinel", version="1.0.0")

    # Add CORS middleware for web dashboard support
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, restrict to specific origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["Health"], response_model=HealthResponse)
    def healthcheck() -> HealthResponse:
        """
        Health check endpoint.
        
        Used by monitoring systems and load balancers to verify
        that the API service is operational. Returns a simple
        status indicating the service is healthy.
        
        Returns:
            Health response with status "ok"
        """
        return HealthResponse(status="ok")

    @app.get("/containers", tags=["Monitoring"])
    def list_containers() -> list[dict[str, object]]:
        """
        Get current container states.
        
        Returns the current state of all monitored containers,
        including resource usage, status, and other metrics.
        Used by the dashboard and external monitoring tools.
        
        Returns:
            List of container state dictionaries
        """
        return sentinel.snapshot_containers()

    @app.get("/incidents", tags=["Monitoring"])
    def list_incidents() -> list[dict[str, object]]:
        """
        Get incident history.
        
        Returns the complete history of incidents detected
        by the monitoring system, including status, analysis,
        and resolution information. Used by the dashboard
        and incident management systems.
        
        Returns:
            List of incident dictionaries
        """
        return sentinel.snapshot_incidents()

    @app.websocket("/ws", tags=["Real-time"])
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """
        WebSocket endpoint for real-time event streaming.
        
        Provides a real-time stream of events from the monitoring
        system, including container state updates, log events,
        and incident lifecycle changes. Used by the web dashboard
        for live monitoring and alerting.
        
        Args:
            websocket: WebSocket connection instance
        """
        # Accept the WebSocket connection
        await websocket.accept()

        # Send bootstrap event with current state
        bootstrap_event = BootstrapEvent(
            containers=sentinel.snapshot_containers(),
            incidents=sentinel.snapshot_incidents()
        )
        await websocket.send_text(
            _json_dump(bootstrap_event.model_dump())
        )

        # Subscribe to real-time events
        subscription = await event_bus.subscribe()

        try:
            # Stream events to the WebSocket client
            async for event in subscription:
                await websocket.send_text(_json_dump(event))
        except WebSocketDisconnect:
            # Client disconnected gracefully
            pass
        except asyncio.CancelledError:
            # Server shutting down
            raise
        finally:
            # Clean up subscription
            await subscription.close()

    return app


def _json_dump(payload: Mapping[str, object]) -> str:
    """
    Serialize a payload to JSON string.
    
    Converts a payload dictionary to a JSON string with proper
    serialization for special types like datetime.
    
    Args:
        payload: Payload to serialize
        
    Returns:
        JSON string representation of the payload
    """
    return json.dumps(payload, default=_json_default)


def _json_default(obj: object) -> object:
    """
    Default JSON serializer for special types.
    
    Handles serialization of special types that aren't natively
    supported by JSON, such as datetime objects and Pydantic models.
    
    Args:
        obj: Object to serialize
        
    Returns:
        JSON-serializable representation of the object
    """
    # Handle datetime objects
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    
    # Handle Pydantic models
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    
    # Fallback to string representation
    return str(obj)
