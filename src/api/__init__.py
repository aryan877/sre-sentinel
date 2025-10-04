"""
API and web server components.

This module contains the FastAPI application, WebSocket handlers,
and REST endpoints for the SRE Sentinel dashboard.
"""

from .websocket_server import build_application

__all__ = ["build_application"]
