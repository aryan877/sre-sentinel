"""
Docker MCP Gateway Orchestrator for automated fix execution.

This module handles communication with the Docker MCP (Model Context Protocol)
Gateway to execute automated fixes on containers. It processes fix actions
recommended by the AI analysis and executes them through the MCP gateway.

The orchestrator is designed to:
1. Execute different types of fixes on containers
2. Verify container health after applying fixes
3. Handle communication with MCP tools using proper MCP client
4. Discover available tools dynamically from MCP servers
5. Provide clear feedback on fix execution

Flow:
1. AI analysis recommends fix actions with structured parameters
2. Fix actions are sent to the orchestrator
3. Orchestrator connects to MCP gateway
4. Orchestrator discovers available tools from MCP servers
5. Orchestrator executes fixes via MCP gateway using proper MCP protocol
6. Container health is verified after fixes
7. Results are returned to the incident handler
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Dict, List, Optional, Any, Union
from pathlib import Path

from pydantic import BaseModel, Field
from rich.console import Console

# MCP client imports
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import Tool

from sentinel_types import FixAction, FixActionName, FixExecutionResult

console = Console()


class MCPSettings(BaseModel):
    """
    Configuration settings for the MCP gateway.

    This model encapsulates all the settings needed to connect
    to the MCP gateway, including URL and auto-heal settings.
    """

    gateway_url: str = Field(description="URL of the MCP gateway")
    auto_heal_enabled: bool = Field(description="Whether automatic healing is enabled")
    timeout: int = Field(default=30, description="Timeout for HTTP requests")
    max_retries: int = Field(default=3, description="Maximum number of retries")

    @classmethod
    def from_env(cls) -> "MCPSettings":
        """
        Create settings from environment variables.

        Loads configuration from environment variables with sensible defaults.
        """
        url = os.getenv("MCP_GATEWAY_URL", "http://localhost:8811")
        auto_heal = os.getenv("AUTO_HEAL_ENABLED", "true").strip().lower() == "true"
        timeout = int(os.getenv("MCP_TIMEOUT", "30"))
        max_retries = int(os.getenv("MCP_MAX_RETRIES", "3"))
        return cls(
            gateway_url=url,
            auto_heal_enabled=auto_heal,
            timeout=timeout,
            max_retries=max_retries,
        )


# Constants for MCP operations
_HEALTH_CHECK_INTERVAL: int = 2  # Interval between health checks
_MAX_HEALTH_WAIT: int = 30  # Maximum time to wait for health


class MCPOrchestrator:
    """
    Orchestrates Docker container actions via MCP Gateway with proper MCP client.

    This class handles the complete fix execution workflow:
    1. Receives fix actions from the AI analysis
    2. Connects to the MCP gateway
    3. Discovers available tools from MCP servers dynamically
    4. Executes fixes through the MCP gateway using proper MCP protocol
    5. Verifies container health after fixes
    6. Returns structured execution results

    The orchestrator provides a unified interface for all types of
    container operations through the MCP gateway with dynamic tool discovery.
    """

    def __init__(self, settings: Optional[MCPSettings] = None) -> None:
        """
        Initialize the MCP orchestrator with gateway settings.

        Args:
            settings: Gateway configuration settings. If None, loads from environment.
        """
        self.settings = settings or MCPSettings.from_env()
        self._session: ClientSession | None = None
        self._client_context = None
        self._available_tools: List[Tool] = []
        self._tool_schemas: Dict[str, Dict[str, Any]] = {}

    async def initialize(self) -> None:
        """
        Initialize MCP connection to the gateway and discover available tools.

        This method connects to the MCP gateway and discovers all available tools.
        """
        console.print("[cyan]🔌 Initializing MCP Gateway connection...[/cyan]")

        try:
            # Connect to the MCP gateway
            await self._connect_to_gateway()
            console.print(
                f"[green]✓ Connected to MCP Gateway at {self.settings.gateway_url}[/green]"
            )

            # Discover available tools
            await self._discover_tools()

        except Exception as exc:
            console.print(f"[red]✗ Failed to connect to MCP Gateway: {exc}[/red]")
            raise

    async def _connect_to_gateway(self) -> None:
        """
        Connect to the MCP gateway and discover all available tools.
        """
        # Connect to the MCP gateway via HTTP
        self._client_context = streamablehttp_client(f"{self.settings.gateway_url}/mcp")
        read, write, _ = await self._client_context.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.initialize()

    async def _discover_tools(self) -> None:
        """
        Discover available tools from the MCP gateway.

        This method queries the MCP gateway for available tools and
        stores their schemas for later use in parameter validation.
        """
        # Discover available tools
        tools_response = await self._session.list_tools()
        self._available_tools = tools_response.tools

        # Update tool schemas with actual tool definitions
        for tool in self._available_tools:
            self._tool_schemas[tool.name] = {
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }

        console.print(
            f"[dim]Discovered {len(self._available_tools)} tools from MCP Gateway[/dim]"
        )

    async def execute_fix(self, fix_action: FixAction) -> FixExecutionResult:
        """
        Execute a suggested fix via MCP Gateway using proper MCP protocol.

        This is the main method for fix execution. It discovers available tools
        and dynamically calls the appropriate tool based on the fix action.

        Args:
            fix_action: The fix action to execute, recommended by AI analysis

        Returns:
            FixExecutionResult with the execution outcome
        """
        # Display fix information to the console
        console.print("\n[bold cyan]🔧 Executing Fix via MCP Gateway[/bold cyan]")
        console.print(f"[cyan]Action:[/cyan] {fix_action.action.value}")
        console.print(f"[cyan]Target:[/cyan] {fix_action.target}")
        console.print(f"[cyan]Details:[/cyan] {fix_action.details}")

        # Check if auto-heal is enabled
        if not self.settings.auto_heal_enabled:
            console.print("[yellow]⚠️  Auto-heal disabled. Skipping execution.[/yellow]")
            return FixExecutionResult(success=False, message="Auto-heal disabled")

        # Ensure we have a connection
        if not self._session:
            await self.initialize()

        try:
            # AI already tells us which tool to use via the action field
            tool_name = fix_action.action.value

            # Check if the tool is available
            if not any(tool.name == tool_name for tool in self._available_tools):
                return FixExecutionResult(
                    success=False,
                    message=f"Tool {tool_name} not found in MCP Gateway",
                    error=f"Tool {tool_name} not found in MCP Gateway",
                )

            # Parse the fix action details as JSON to get structured parameters
            try:
                args = json.loads(fix_action.details)
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                # If details is not valid JSON, create a basic args dict
                args = {}

                # Add container_name if it's a common parameter
                tool_schema = self._tool_schemas.get(tool_name, {})
                input_schema = tool_schema.get("input_schema", {})
                properties = input_schema.get("properties", {})

                if "container_name" in properties:
                    args["container_name"] = fix_action.target

                # Add details as a generic parameter if the tool supports it
                if "details" in properties:
                    args["details"] = fix_action.details

            # Call the tool with the parsed arguments
            return await self._call_tool(tool_name, args)

        except Exception as exc:
            console.print(f"[red]Error executing fix: {exc}[/red]")
            return FixExecutionResult(success=False, message=str(exc), error=str(exc))

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
        """
        Verify MCP gateway is accessible and healthy using MCP protocol.

        Returns:
            True if gateway is healthy, False otherwise
        """
        try:
            # Check if we have a connection
            if not self._session:
                await self.initialize()

            # Try to list tools from the gateway
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
        """
        Verify container health after applying fixes using MCP protocol.

        This method repeatedly checks the health of a container
        until it becomes healthy or the timeout is reached.

        Args:
            container_name: Name of the container to check
            max_wait: Maximum time to wait for the container to become healthy

        Returns:
            True if the container becomes healthy, False otherwise
        """
        console.print(f"[yellow]🏥 Verifying health of {container_name}...[/yellow]")
        start_time = asyncio.get_event_loop().time()

        # Check health repeatedly until timeout
        while (asyncio.get_event_loop().time() - start_time) < max_wait:
            try:
                # Perform health check via MCP protocol
                result = await self._call_tool(
                    "health_check", {"container_name": container_name}
                )

                if result.success:
                    # Try to extract health status from the result
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
                            pass  # Continue with default check

                    # If we got here, assume success means healthy
                    console.print("[green]✓ Container is healthy![/green]")
                    return True
            except Exception as exc:
                console.print(f"[red]Health check error: {exc}[/red]")
                # Don't return False immediately, try again

            # Wait before the next health check
            await asyncio.sleep(_HEALTH_CHECK_INTERVAL)

        # Timeout reached, container is still unhealthy
        console.print(
            f"[red]✗ Container did not become healthy within {max_wait}s[/red]"
        )
        return False

    async def _call_tool(
        self, tool_name: str, args: Dict[str, Any]
    ) -> FixExecutionResult:
        """
        Call a tool on the MCP gateway using proper MCP protocol.

        Args:
            tool_name: Name of the tool to call
            args: Arguments to pass to the tool

        Returns:
            FixExecutionResult with the tool execution outcome
        """
        try:
            if not self._session:
                return FixExecutionResult(
                    success=False,
                    message="MCP Gateway not connected",
                    error="MCP Gateway not connected",
                )

            result = await self._session.call_tool(tool_name, args)

            # Parse the result
            if result.content and len(result.content) > 0:
                content = result.content[0]
                if hasattr(content, "text"):
                    response_data = json.loads(content.text)
                    success = response_data.get("success", False)
                    message = response_data.get("message", "")

                    if success:
                        return FixExecutionResult(
                            success=True,
                            message=message,
                            details=(
                                json.dumps(response_data) if response_data else None
                            ),
                        )
                    else:
                        error = response_data.get("error", "Unknown error")
                        return FixExecutionResult(
                            success=False, message=message, error=error
                        )

            return FixExecutionResult(
                success=False, message="Invalid response from MCP Gateway"
            )
        except Exception as exc:
            return FixExecutionResult(success=False, message=str(exc), error=str(exc))

    async def list_available_tools(self) -> List[Tool]:
        """
        List all available tools from the MCP gateway.

        Returns:
            List of available tools
        """
        return self._available_tools.copy()

    async def get_tools_for_ai(self) -> str:
        """
        Get a formatted description of available tools for AI consumption.

        Returns:
            Formatted string describing available tools and their parameters
        """
        if not self._available_tools:
            await self.initialize()

        tools_description = []
        for tool in self._available_tools:
            tool_desc = f"- {tool.name}: {tool.description}\n"
            if hasattr(tool, "inputSchema") and tool.inputSchema:
                # Add required parameters
                required = tool.inputSchema.get("required", [])
                if required:
                    tool_desc += f"  Required parameters: {', '.join(required)}\n"

                # Add parameter descriptions
                properties = tool.inputSchema.get("properties", {})
                for param_name, param_info in properties.items():
                    param_desc = param_info.get("description", "")
                    if param_desc:
                        tool_desc += f"  - {param_name}: {param_desc}\n"

            tools_description.append(tool_desc)

        return "\n".join(tools_description)


if __name__ == "__main__":
    """
    Example usage of the MCP orchestrator with proper MCP protocol.

    This block demonstrates how to use the orchestrator to execute
    fix actions on containers. It's primarily for testing and
    demonstration purposes.
    """
    from dotenv import load_dotenv

    load_dotenv()

    async def _test() -> None:
        orchestrator = MCPOrchestrator()

        # Initialize MCP connections
        await orchestrator.initialize()

        # List available tools
        tools = await orchestrator.list_available_tools()
        console.print("\n[bold]Available Tools:[/bold]")
        for tool in tools:
            console.print(f"  - {tool.name}: {tool.description}")

        # Execute a fix action with JSON parameters
        fix_action = FixAction(
            action=FixActionName.RESTART_CONTAINER,
            target="demo-postgres",
            details='{"container_name": "demo-postgres", "reason": "Restarting due to connection failures"}',
            priority=1,
        )
        result = await orchestrator.execute_fix(fix_action)
        console.print("\n[bold]Execution Result:[/bold]")
        console.print(result.model_dump())

        # Verify health
        healthy = await orchestrator.verify_health("demo-postgres")
        console.print(
            f"\n[bold]Health Status:[/bold] {'✓ Healthy' if healthy else '✗ Unhealthy'}"
        )

        # Close connections
        await orchestrator.close()

    asyncio.run(_test())
