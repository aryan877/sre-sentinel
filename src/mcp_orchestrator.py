"""
Docker MCP Gateway Orchestrator for automated fix execution.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field, field_validator
from rich.console import Console

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import Tool

from sentinel_types import FixAction, FixActionName, FixExecutionResult

console = Console()


class MCPSettings(BaseModel):
    """Configuration settings for the MCP gateway."""

    gateway_url: str = Field(description="URL of the MCP gateway")
    auto_heal_enabled: bool = Field(description="Whether automatic healing is enabled")
    timeout: int = Field(default=30, description="Timeout for HTTP requests")
    max_retries: int = Field(default=3, description="Maximum number of retries")

    @field_validator("auto_heal_enabled", mode="before")
    @classmethod
    def validate_auto_heal_enabled(cls, v):
        """Convert string values to boolean for auto_heal_enabled."""
        if isinstance(v, str):
            return v.strip().lower() in {"true", "1", "yes"}
        return v

    @classmethod
    def from_env(cls) -> "MCPSettings":
        """Create settings from environment variables."""
        return cls(
            gateway_url=os.getenv("MCP_GATEWAY_URL", "http://localhost:8811"),
            auto_heal_enabled=os.getenv("AUTO_HEAL_ENABLED", "true").strip().lower()
            == "true",
            timeout=int(os.getenv("MCP_TIMEOUT", "30")),
            max_retries=int(os.getenv("MCP_MAX_RETRIES", "3")),
        )


_HEALTH_CHECK_INTERVAL = 2
_MAX_HEALTH_WAIT = 30


class MCPOrchestrator:
    """Orchestrates Docker container actions via MCP Gateway."""

    def __init__(self, settings: Optional[MCPSettings] = None) -> None:
        """Initialize the MCP orchestrator with gateway settings."""
        self.settings = settings or MCPSettings.from_env()
        self._session: ClientSession | None = None
        self._client_context = None
        self._available_tools: List[Tool] = []
        self._tool_schemas: Dict[str, Dict[str, Any]] = {}

    async def initialize(self) -> None:
        """Initialize MCP connection to the gateway and discover available tools."""
        console.print("[cyan]🔌 Initializing MCP Gateway connection...[/cyan]")

        try:
            await self._connect_to_gateway()
            console.print(
                f"[green]✓ Connected to MCP Gateway at {self.settings.gateway_url}[/green]"
            )
            await self._discover_tools()
        except Exception as exc:
            console.print(f"[red]✗ Failed to connect to MCP Gateway: {exc}[/red]")
            raise

    async def _connect_to_gateway(self) -> None:
        """Connect to the MCP gateway."""
        # Try different endpoint paths based on transport mode
        endpoints = ["/mcp", "/sse", ""]

        for endpoint in endpoints:
            try:
                url = f"{self.settings.gateway_url}{endpoint}"
                console.print(f"[dim]Trying to connect to MCP Gateway at {url}[/dim]")
                self._client_context = streamablehttp_client(url)
                read, write, _ = await self._client_context.__aenter__()
                self._session = ClientSession(read, write)
                await self._session.initialize()
                console.print(f"[green]✓ Connected to MCP Gateway at {url}[/green]")
                return
            except Exception as e:
                console.print(f"[yellow]⚠️  Failed to connect to {url}: {e}[/yellow]")
                if self._client_context:
                    try:
                        await self._client_context.__aexit__(None, None, None)
                    except:
                        pass
                    self._client_context = None
                continue

        # If all endpoints failed, raise the last exception
        raise Exception("Failed to connect to MCP Gateway on any endpoint")

    async def _discover_tools(self) -> None:
        """Discover available tools from the MCP gateway."""
        tools_response = await self._session.list_tools()
        self._available_tools = tools_response.tools

        for tool in self._available_tools:
            self._tool_schemas[tool.name] = {
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }

        console.print(
            f"[dim]Discovered {len(self._available_tools)} tools from MCP Gateway[/dim]"
        )

    async def execute_fix(self, fix_action: FixAction) -> FixExecutionResult:
        """Execute a suggested fix via MCP Gateway."""
        console.print("\n[bold cyan]🔧 Executing Fix via MCP Gateway[/bold cyan]")
        console.print(f"[cyan]Action:[/cyan] {fix_action.action.value}")
        console.print(f"[cyan]Target:[/cyan] {fix_action.target}")
        console.print(f"[cyan]Details:[/cyan] {fix_action.details}")

        if not self.settings.auto_heal_enabled:
            console.print("[yellow]⚠️  Auto-heal disabled. Skipping execution.[/yellow]")
            return FixExecutionResult.model_validate(
                {"success": False, "message": "Auto-heal disabled"}
            )

        if not self._session:
            await self.initialize()

        try:
            tool_name = fix_action.action.value

            if not any(tool.name == tool_name for tool in self._available_tools):
                return FixExecutionResult.model_validate(
                    {
                        "success": False,
                        "message": f"Tool {tool_name} not found in MCP Gateway",
                        "error": f"Tool {tool_name} not found in MCP Gateway",
                    }
                )

            try:
                args = json.loads(fix_action.details)
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}
                tool_schema = self._tool_schemas.get(tool_name, {})
                input_schema = tool_schema.get("input_schema", {})
                properties = input_schema.get("properties", {})

                if "container_name" in properties:
                    args["container_name"] = fix_action.target

                if "details" in properties:
                    args["details"] = fix_action.details

            return await self._call_tool(tool_name, args)

        except Exception as exc:
            console.print(f"[red]Error executing fix: {exc}[/red]")
            return FixExecutionResult.model_validate(
                {"success": False, "message": str(exc), "error": str(exc)}
            )

    async def close(self) -> None:
        """Close the MCP gateway session."""
        if self._session:
            try:
                await self._session.close()
                console.print("[dim]Closed connection to MCP Gateway[/dim]")
            except Exception as exc:
                console.print(
                    f"[yellow]Warning: Error closing connection to MCP Gateway: {exc}[/yellow]"
                )

        if self._client_context:
            try:
                await self._client_context.__aexit__(None, None, None)
            except Exception as exc:
                console.print(
                    f"[yellow]Warning: Error closing HTTP client: {exc}[/yellow]"
                )

        self._session = None
        self._client_context = None
        self._available_tools.clear()
        self._tool_schemas.clear()

    async def verify_gateway_health(self) -> bool:
        """Verify MCP gateway is accessible and healthy."""
        try:
            if not self._session:
                await self.initialize()

            tools = await self._session.list_tools()
            if tools.tools:
                console.print("[green]✓ MCP Gateway is healthy (MCP Protocol)[/green]")
                return True
            else:
                console.print("[red]MCP Gateway: No tools available[/red]")
                return False
        except Exception as exc:
            console.print(f"[red]MCP Gateway health check error: {exc}[/red]")
            return False

    async def verify_health(
        self, container_name: str, max_wait: int = _MAX_HEALTH_WAIT
    ) -> bool:
        """Verify container health after applying fixes."""
        console.print(f"[yellow]🏥 Verifying health of {container_name}...[/yellow]")
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < max_wait:
            try:
                result = await self._call_tool(
                    "health_check", {"container_name": container_name}
                )

                if result.success:
                    if result.details:
                        try:
                            details = json.loads(result.details)
                            status = details.get("status", "").lower()
                            health = details.get("health", "").lower()

                            if status in {"healthy", "running"} or health in {
                                "healthy",
                                "running",
                            }:
                                console.print("[green]✓ Container is healthy![/green]")
                                return True
                        except json.JSONDecodeError:
                            pass

                    console.print("[green]✓ Container is healthy![/green]")
                    return True
            except Exception as exc:
                console.print(f"[red]Health check error: {exc}[/red]")

            await asyncio.sleep(_HEALTH_CHECK_INTERVAL)

        console.print(
            f"[red]✗ Container did not become healthy within {max_wait}s[/red]"
        )
        return False

    async def _call_tool(
        self, tool_name: str, args: Dict[str, Any]
    ) -> FixExecutionResult:
        """Call a tool on the MCP gateway."""
        try:
            if not self._session:
                return FixExecutionResult.model_validate(
                    {
                        "success": False,
                        "message": "MCP Gateway not connected",
                        "error": "MCP Gateway not connected",
                    }
                )

            result = await self._session.call_tool(tool_name, args)

            if result.content and len(result.content) > 0:
                content = result.content[0]
                if hasattr(content, "text"):
                    response_data = json.loads(content.text)
                    success = response_data.get("success", False)
                    message = response_data.get("message", "")

                    if success:
                        return FixExecutionResult.model_validate(
                            {
                                "success": True,
                                "message": message,
                                "details": (
                                    json.dumps(response_data) if response_data else None
                                ),
                            }
                        )
                    else:
                        error = response_data.get("error", "Unknown error")
                        return FixExecutionResult.model_validate(
                            {"success": False, "message": message, "error": error}
                        )

            return FixExecutionResult.model_validate(
                {"success": False, "message": "Invalid response from MCP Gateway"}
            )
        except Exception as exc:
            return FixExecutionResult.model_validate(
                {"success": False, "message": str(exc), "error": str(exc)}
            )

    async def list_available_tools(self) -> List[Tool]:
        """List all available tools from the MCP gateway."""
        return self._available_tools.copy()

    async def get_tools_for_ai(self) -> str:
        """Get a formatted description of available tools for AI consumption."""
        if not self._available_tools:
            await self.initialize()

        tools_description = []
        for tool in self._available_tools:
            tool_desc = f"- {tool.name}: {tool.description}\n"
            if hasattr(tool, "inputSchema") and tool.inputSchema:
                required = tool.inputSchema.get("required", [])
                if required:
                    tool_desc += f"  Required parameters: {', '.join(required)}\n"

                properties = tool.inputSchema.get("properties", {})
                for param_name, param_info in properties.items():
                    param_desc = param_info.get("description", "")
                    if param_desc:
                        tool_desc += f"  - {param_name}: {param_desc}\n"

            tools_description.append(tool_desc)

        return "\n".join(tools_description)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    async def _test() -> None:
        orchestrator = MCPOrchestrator()
        await orchestrator.initialize()

        tools = await orchestrator.list_available_tools()
        console.print("\n[bold]Available Tools:[/bold]")
        for tool in tools:
            console.print(f"  - {tool.name}: {tool.description}")

        fix_action = FixAction(
            action=FixActionName("restart_container"),
            target="demo-postgres",
            details='{"container_name": "demo-postgres", "reason": "Restarting due to connection failures"}',
            priority=1,
        )
        result = await orchestrator.execute_fix(fix_action)
        console.print("\n[bold]Execution Result:[/bold]")
        console.print(result.model_dump())

        healthy = await orchestrator.verify_health("demo-postgres")
        console.print(
            f"\n[bold]Health Status:[/bold] {'✓ Healthy' if healthy else '✗ Unhealthy'}"
        )

        await orchestrator.close()

    asyncio.run(_test())
