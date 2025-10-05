"""
Docker MCP Gateway Orchestrator for automated fix execution.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from rich.console import Console

from mcp.client.session import ClientSession
from mcp.types import Tool
import asyncio

from src.models.sentinel_types import (
    FixAction,
    FixActionName,
    FixExecutionResult,
    MCPSettings,
)

console = Console()

_HEALTH_CHECK_INTERVAL = 2
_MAX_HEALTH_WAIT = 30


class ToolAdapter:
    """Adapter to provide consistent interface for tool data from different sources."""

    def __init__(self, tool_data: dict[str, Any] | Tool) -> None:
        """Initialize with either dict or Tool object."""
        if isinstance(tool_data, dict):
            self._data = tool_data
        else:
            # Convert Tool object to dict
            self._data = {
                "name": tool_data.name,
                "description": tool_data.description,
                "inputSchema": tool_data.inputSchema,
            }

    @property
    def name(self) -> str:
        """Get tool name."""
        return self._data.get("name", "unknown")

    @property
    def description(self) -> str:
        """Get tool description."""
        return self._data.get("description", "")

    @property
    def input_schema(self) -> dict[str, Any]:
        """Get input schema."""
        return self._data.get("inputSchema", {})

    @property
    def data(self) -> dict[str, Any]:
        """Get raw data."""
        return self._data


class MCPOrchestrator:
    """Orchestrates Docker container actions via MCP Gateway."""

    def __init__(self, settings: MCPSettings | None = None) -> None:
        """Initialize the MCP orchestrator with gateway settings."""
        self.settings = settings or MCPSettings.from_env()
        self._session: ClientSession | None = None
        self._client_context = None
        self._available_tools: list[ToolAdapter] = []
        self._tool_schemas: dict[str, dict[str, Any]] = {}
        self._session_id: str | None = None

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
        """Connect to the MCP gateway using SSE protocol."""
        # The Docker MCP Gateway uses SSE protocol with session management
        base_url = self.settings.gateway_url.rstrip("/")
        mcp_url = f"{base_url}/mcp"
        console.print(f"[dim]Connecting to MCP Gateway at {mcp_url}[/dim]")

        try:
            # Use a timeout to prevent hanging
            await asyncio.wait_for(
                self._initialize_session(mcp_url), timeout=self.settings.timeout
            )
            console.print(f"[green]✓ Connected to MCP Gateway at {base_url}[/green]")
            # Set connected flag
            self._connected = True
        except asyncio.TimeoutError:
            console.print(f"[yellow]⚠️  Timeout connecting to {mcp_url}[/yellow]")
            raise Exception(f"Timeout connecting to MCP Gateway at {mcp_url}")
        except Exception as e:
            console.print(f"[red]✗ Failed to connect to {mcp_url}: {e}[/red]")
            raise Exception(f"Failed to connect to MCP Gateway: {e}")

    async def _initialize_session(self, url: str) -> None:
        """Initialize a session with the MCP Gateway."""
        import aiohttp

        async with aiohttp.ClientSession() as session:
            try:
                # Initialize session
                init_payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "sre-sentinel", "version": "1.0.0"},
                    },
                }

                async with session.post(
                    url, headers={"Content-Type": "application/json"}, json=init_payload
                ) as response:
                    if response.status == 200:
                        # Extract session ID from headers
                        session_id = response.headers.get("Mcp-Session-Id")
                        if not session_id:
                            raise Exception("No session ID received from MCP Gateway")

                        self._session_id = session_id
                        console.print(
                            f"[green]✓ Initialized session: {session_id}[/green]"
                        )
                        return
                    else:
                        error_text = await response.text()
                        raise Exception(f"HTTP {response.status}: {error_text}")
            except Exception as e:
                console.print(f"[red]Session initialization failed: {e}[/red]")
                raise

    async def _discover_tools(self) -> None:
        """Discover available tools from the MCP gateway."""
        base_url = self.settings.gateway_url.rstrip("/")
        mcp_url = f"{base_url}/mcp"

        import aiohttp

        if not self._session_id:
            raise Exception("No session ID available for tool discovery")

        async with aiohttp.ClientSession() as session:
            try:
                # List tools using the session
                list_payload = {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                }

                async with session.post(
                    mcp_url,
                    headers={
                        "Content-Type": "application/json",
                        "Mcp-Session-Id": self._session_id,
                    },
                    json=list_payload,
                ) as response:
                    if response.status == 200:
                        # Parse SSE response
                        response_text = await response.text()
                        # Extract JSON data from SSE format
                        lines = response_text.split("\n")
                        for line in lines:
                            if line.startswith("data: "):
                                data = line[6:]  # Remove 'data: ' prefix
                                if data:
                                    tools_data = json.loads(data)
                                    if (
                                        "result" in tools_data
                                        and "tools" in tools_data["result"]
                                    ):
                                        # Convert tools to adapters
                                        self._available_tools = [
                                            ToolAdapter(tool)
                                            for tool in tools_data["result"]["tools"]
                                        ]

                                        # Create tool schemas
                                        for tool in self._available_tools:
                                            self._tool_schemas[tool.name] = {
                                                "description": tool.description,
                                                "input_schema": tool.input_schema,
                                            }

                                        console.print(
                                            f"[dim]Discovered {len(self._available_tools)} tools from MCP Gateway[/dim]"
                                        )
                                        return
                        raise Exception("No tools data found in response")
                    else:
                        error_text = await response.text()
                        raise Exception(f"HTTP {response.status}: {error_text}")
            except Exception as e:
                console.print(f"[red]Failed to discover tools: {e}[/red]")
                raise

    async def execute_fix(self, fix_action: FixAction) -> FixExecutionResult:
        """Execute a suggested fix via MCP Gateway."""
        console.print("\n[bold cyan]🔧 Executing Fix via MCP Gateway[/bold cyan]")
        console.print(f"[cyan]Action:[/cyan] {fix_action.action}")
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
            tool_name = str(fix_action.action)

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
            if not getattr(self, "_connected", False):
                await self.initialize()

            # If we have tools and a session ID, we're healthy
            if self._available_tools and self._session_id:
                console.print("[green]✓ MCP Gateway is healthy (SSE)[/green]")
                return True
            else:
                console.print(
                    "[red]MCP Gateway: No tools available or no session[/red]"
                )
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
        self, tool_name: str, args: dict[str, Any]
    ) -> FixExecutionResult:
        """Call a tool on the MCP gateway."""
        try:
            if not getattr(self, "_connected", False) or not self._session_id:
                return FixExecutionResult.model_validate(
                    {
                        "success": False,
                        "message": "MCP Gateway not connected",
                        "error": "MCP Gateway not connected",
                    }
                )

            base_url = self.settings.gateway_url.rstrip("/")
            mcp_url = f"{base_url}/mcp"

            import aiohttp

            async with aiohttp.ClientSession() as session:
                # Prepare the request payload
                call_payload = {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": args},
                }

                async with session.post(
                    mcp_url,
                    headers={
                        "Content-Type": "application/json",
                        "Mcp-Session-Id": self._session_id,
                    },
                    json=call_payload,
                ) as response:
                    if response.status == 200:
                        # Parse SSE response
                        response_text = await response.text()
                        # Extract JSON data from SSE format
                        lines = response_text.split("\n")
                        for line in lines:
                            if line.startswith("data: "):
                                data = line[6:]  # Remove 'data: ' prefix
                                if data:
                                    result_data = json.loads(data)
                                    if (
                                        "result" in result_data
                                        and "content" in result_data["result"]
                                    ):
                                        content = result_data["result"]["content"][0]
                                        if (
                                            isinstance(content, dict)
                                            and "text" in content
                                        ):
                                            tool_result = json.loads(content["text"])
                                            success = tool_result.get("success", False)
                                            message = tool_result.get("message", "")

                                            if success:
                                                return (
                                                    FixExecutionResult.model_validate(
                                                        {
                                                            "success": True,
                                                            "message": message,
                                                            "details": (
                                                                json.dumps(tool_result)
                                                                if tool_result
                                                                else None
                                                            ),
                                                        }
                                                    )
                                                )
                                            else:
                                                error = tool_result.get(
                                                    "error", "Unknown error"
                                                )
                                                return (
                                                    FixExecutionResult.model_validate(
                                                        {
                                                            "success": False,
                                                            "message": message,
                                                            "error": error,
                                                        }
                                                    )
                                                )

                        return FixExecutionResult.model_validate(
                            {
                                "success": False,
                                "message": "Invalid response from MCP Gateway",
                            }
                        )
                    else:
                        error_text = await response.text()
                        return FixExecutionResult.model_validate(
                            {
                                "success": False,
                                "message": f"HTTP {response.status}",
                                "error": error_text,
                            }
                        )
        except Exception as exc:
            return FixExecutionResult.model_validate(
                {"success": False, "message": str(exc), "error": str(exc)}
            )

    async def list_available_tools(self) -> list[ToolAdapter]:
        """List all available tools from the MCP gateway."""
        return self._available_tools.copy()

    async def get_tools_for_ai(self) -> str:
        """Get a formatted description of available tools for AI consumption."""
        if not self._available_tools:
            await self.initialize()

        tools_description = []
        for tool in self._available_tools:
            tool_desc_str = f"- {tool.name}: {tool.description}\n"
            if tool.input_schema:
                required = tool.input_schema.get("required", [])
                if required:
                    tool_desc_str += f"  Required parameters: {', '.join(required)}\n"

                properties = tool.input_schema.get("properties", {})
                for param_name, param_info in properties.items():
                    param_desc = param_info.get("description", "")
                    if param_desc:
                        tool_desc_str += f"  - {param_name}: {param_desc}\n"

            tools_description.append(tool_desc_str)

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
