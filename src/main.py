#!/usr/bin/env python3
"""
Main entry point for SRE Sentinel.

This module provides the primary entry point for the SRE Sentinel monitoring
and self-healing system. It orchestrates all components and starts the
monitoring loop and API server.
"""

from __future__ import annotations

import asyncio
import os
from dotenv import load_dotenv
from rich.console import Console

from src.core.monitor import SRESentinel
from src.infrastructure.redis_event_bus import create_redis_event_bus
from src.api.websocket_server import build_application

console = Console()


async def main() -> None:
    """Main entry point for the SRE Sentinel monitoring agent."""
    load_dotenv()

    banner = "=" * 60
    console.print()
    console.print(f"[bold cyan]{banner}[/bold cyan]")
    console.print(
        "[bold cyan]        🛡️  SRE SENTINEL - AI DevOps Copilot        [/bold cyan]"
    )
    console.print(f"[bold cyan]{banner}[/bold cyan]")
    console.print()
    console.print(
        "[dim]Powered by Cerebras (⚡ fast), Llama 4 (🧠 smart), Docker MCP (🔧 secure)[/dim]"
    )
    console.print()

    try:
        event_bus = await create_redis_event_bus()
        sentinel = SRESentinel(event_bus=event_bus)
    except Exception as exc:
        console.print(f"[red]Failed to initialise Redis event bus: {exc}[/red]")
        console.print("[yellow]Ensure Redis is running and accessible.[/yellow]")
        console.print(
            "[yellow]You can start Redis with: docker run -d -p 6379:6379 redis:latest[/yellow]"
        )
        return

    app = build_application(sentinel, event_bus)

    import uvicorn

    api_port = int(os.getenv("API_PORT", "8000"))
    api_host = os.getenv("API_HOST", "0.0.0.0")

    config = uvicorn.Config(app, host=api_host, port=api_port, log_level="info")
    server = uvicorn.Server(config)

    monitor_task = asyncio.create_task(sentinel.monitor_loop())
    api_task = asyncio.create_task(server.serve())

    try:
        # Run both tasks concurrently
        await asyncio.gather(monitor_task, api_task)
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down gracefully...[/yellow]")
    finally:
        if not monitor_task.done():
            monitor_task.cancel()
        server.should_exit = True
        if not api_task.done():
            await api_task
        await event_bus.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
