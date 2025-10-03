"""
Docker MCP Gateway Orchestrator for automated fix execution.

This module handles communication with the Docker MCP (Model Context Protocol)
Gateway to execute automated fixes on containers. It processes fix actions
recommended by the AI analysis and executes them through the MCP gateway.

The orchestrator is designed to:
1. Execute different types of fixes on containers
2. Verify container health after applying fixes
3. Handle communication with MCP tools
4. Provide clear feedback on fix execution

Flow:
1. AI analysis recommends fix actions
2. Fix actions are sent to the orchestrator
3. Orchestrator executes fixes via MCP gateway
4. Container health is verified after fixes
5. Results are returned to the incident handler
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

import aiohttp
from pydantic import BaseModel, Field
from rich.console import Console
from tenacity import retry, stop_after_attempt, wait_exponential

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
            max_retries=max_retries
        )


class MCPToolResponse(BaseModel):
    """
    Response structure from MCP tools.
    
    This model defines the structure of responses from MCP tools,
    including success status, messages, and additional data.
    """
    message: str | None = Field(default=None, description="Response message from the tool")
    status: str | None = Field(default=None, description="Status code from the tool")
    error: str | None = Field(default=None, description="Error message if the tool failed")
    health: str | None = Field(default=None, description="Health status if this was a health check")
    restart_count: int | None = Field(default=None, description="Restart count if this was a restart")
    cpu_percent: float | None = Field(default=None, description="CPU usage if this was a stats query")
    memory_percent: float | None = Field(default=None, description="Memory usage if this was a stats query")


class RestartContainerArgs(BaseModel):
    """
    Arguments for restart container MCP tool.
    
    Defines the parameters needed to restart a container
    through the MCP gateway.
    """
    container_name: str = Field(description="Name of the container to restart")
    reason: str = Field(description="Reason for restarting the container")


class HealthCheckArgs(BaseModel):
    """
    Arguments for health check MCP tool.
    
    Defines the parameters needed to check the health of a container
    through the MCP gateway.
    """
    container_name: str = Field(description="Name of the container to check")


class UpdateEnvVarsArgs(BaseModel):
    """
    Arguments for update environment variables MCP tool.
    
    Defines the parameters needed to update environment variables
    in a container through the MCP gateway.
    """
    container_name: str = Field(description="Name of the container to update")
    env_updates: dict[str, str] = Field(description="Environment variables to update")


class UpdateResourcesArgs(BaseModel):
    """
    Arguments for update resources MCP tool.
    
    Defines the parameters needed to update resource limits
    for a container through the MCP gateway.
    """
    container_name: str = Field(description="Name of the container to update")
    resources: dict[str, str] = Field(description="Resource limits to update")


# Constants for MCP operations
_MCP_TIMEOUT_SECONDS: int = 30  # Timeout for MCP tool calls
_HEALTH_CHECK_INTERVAL: int = 2  # Interval between health checks
_MAX_HEALTH_WAIT: int = 30  # Maximum time to wait for health


class MCPOrchestrator:
    """
    Orchestrates Docker container actions via MCP Gateway with Pydantic models.
    
    This class handles the complete fix execution workflow:
    1. Receives fix actions from the AI analysis
    2. Formats fix actions for MCP tools
    3. Executes fixes through the MCP gateway
    4. Verifies container health after fixes
    5. Returns structured execution results
    
    The orchestrator provides a unified interface for all types of
    container operations through the MCP gateway.
    """

    def __init__(self, settings: MCPSettings | None = None) -> None:
        """
        Initialize the MCP orchestrator with gateway settings.
        
        Args:
            settings: Gateway configuration settings. If None, loads from environment.
        """
        self.settings = settings or MCPSettings.from_env()
        self._session: aiohttp.ClientSession | None = None

    async def execute_fix(self, fix_action: FixAction) -> FixExecutionResult:
        """
        Execute a suggested fix via MCP Gateway.
        
        This is the main method for fix execution. It determines the type
        of fix to apply and delegates to the appropriate handler method.
        
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

        try:
            # Execute the appropriate fix based on the action type
            if fix_action.action is FixActionName.RESTART_CONTAINER:
                return await self._restart_container(fix_action)
            elif fix_action.action is FixActionName.UPDATE_CONFIG:
                return await self._update_config(fix_action)
            elif fix_action.action is FixActionName.SCALE_RESOURCES:
                return await self._scale_resources(fix_action)
            else:  # FixActionName.PATCH_CODE
                return await self._patch_code(fix_action)
        except Exception as exc:
            console.print(f"[red]Error executing fix: {exc}[/red]")
            return FixExecutionResult(success=False, message=str(exc), error=str(exc))
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session for API calls."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.settings.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def verify_gateway_health(self) -> bool:
        """
        Verify MCP gateway is accessible and healthy using HTTP API.
        
        Returns:
            True if gateway is healthy, False otherwise
        """
        try:
            # Try HTTP API health check
            session = await self._get_session()
            async with session.get(f"{self.settings.gateway_url}/") as response:
                if response.status == 200:
                    console.print("[green]✓ MCP Gateway is healthy (HTTP API)[/green]")
                    return True
                else:
                    console.print(f"[red]MCP Gateway returned status {response.status}[/red]")
                    return False
        except Exception as exc:
            console.print(f"[red]MCP Gateway health check error: {exc}[/red]")
            return False

    async def verify_health(self, container_name: str, max_wait: int = _MAX_HEALTH_WAIT) -> bool:
        """
        Verify container health after applying fixes.
        
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
                # Perform health check via MCP gateway
                args = HealthCheckArgs(container_name=container_name)
                result = await self._call_mcp_tool(
                    server="docker-control",
                    tool="health_check",
                    args=args.model_dump(),
                )
            except Exception as exc:
                console.print(f"[red]Health check error: {exc}[/red]")
                return False

            # Check if the container is healthy
            if result.success:
                normalized_status = (result.status or "").lower()
                if normalized_status in {"healthy", "running"}:
                    console.print("[green]✓ Container is healthy![/green]")
                    return True

                # Check health status in the response details
                health = _extract_health(result.details)
                if health in {"healthy", "running"}:
                    console.print("[green]✓ Container is healthy![/green]")
                    return True

            # Wait before the next health check
            await asyncio.sleep(_HEALTH_CHECK_INTERVAL)

        # Timeout reached, container is still unhealthy
        console.print(f"[red]✗ Container did not become healthy within {max_wait}s[/red]")
        return False

    async def _restart_container(self, fix_action: FixAction) -> FixExecutionResult:
        """
        Restart a container via MCP gateway.
        
        Args:
            fix_action: Fix action with container name and restart reason
            
        Returns:
            FixExecutionResult with the restart outcome
        """
        console.print(f"[yellow]↻ Restarting container: {fix_action.target}...[/yellow]")
        args = RestartContainerArgs(
            container_name=fix_action.target,
            reason=fix_action.details
        )
        result = await self._call_mcp_tool(
            server="docker-control",
            tool="restart_container",
            args=args.model_dump(),
        )
        _log_result(result, success_msg=f"Restarted {fix_action.target}")
        return result

    async def _update_config(self, fix_action: FixAction) -> FixExecutionResult:
        """
        Update container configuration via MCP gateway.
        
        Args:
            fix_action: Fix action with container name and config updates
            
        Returns:
            FixExecutionResult with the config update outcome
        """
        console.print(f"[yellow]⚙️  Updating config for: {fix_action.target}...[/yellow]")
        updates = _parse_key_value_lines(fix_action.details)
        args = UpdateEnvVarsArgs(
            container_name=fix_action.target,
            env_updates=updates
        )
        result = await self._call_mcp_tool(
            server="config-patcher",
            tool="update_env_vars",
            args=args.model_dump(),
        )
        _log_result(result, success_msg=f"Updated config for {fix_action.target}")
        return result

    async def _scale_resources(self, fix_action: FixAction) -> FixExecutionResult:
        """
        Scale container resources via MCP gateway.
        
        Args:
            fix_action: Fix action with container name and resource updates
            
        Returns:
            FixExecutionResult with the resource scaling outcome
        """
        console.print(f"[yellow]📊 Scaling resources for: {fix_action.target}...[/yellow]")
        resources = _parse_inline_assignments(fix_action.details)
        args = UpdateResourcesArgs(
            container_name=fix_action.target,
            resources=resources
        )
        result = await self._call_mcp_tool(
            server="docker-control",
            tool="update_resources",
            args=args.model_dump(),
        )
        _log_result(result, success_msg=f"Scaled resources for {fix_action.target}")
        return result

    async def _patch_code(self, fix_action: FixAction) -> FixExecutionResult:
        """
        Patch container code via MCP gateway (future feature).
        
        Args:
            fix_action: Fix action with container name and patch details
            
        Returns:
            FixExecutionResult indicating the feature is not yet implemented
        """
        console.print(f"[yellow]🔨 Patching code at: {fix_action.target}...[/yellow]")
        console.print("[red]⚠️  Code patching not yet implemented (coming soon!)[/red]")
        return FixExecutionResult(
            success=False,
            message="Code patching not implemented",
            error="Code patching not implemented",
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _call_mcp_tool(
        self,
        *,
        server: str,
        tool: str,
        args: Mapping[str, object],
    ) -> FixExecutionResult:
        """
        Call an MCP tool using HTTP API.
        
        This method handles the low-level communication with the MCP gateway,
        including HTTP request construction, execution, and response parsing.
        
        Args:
            server: MCP server name (e.g., "docker-control")
            tool: Tool name to call (e.g., "restart_container")
            args: Arguments to pass to the tool
            
        Returns:
            FixExecutionResult with the tool execution outcome
        """
        return await self._call_mcp_tool_http(server, tool, args)
    
    async def _call_mcp_tool_cli(
        self,
        server: str,
        tool: str,
        args: Mapping[str, object],
    ) -> FixExecutionResult:
        """
        Call MCP tool using Docker CLI.
        
        Args:
            server: MCP server name (e.g., "docker-control")
            tool: Tool name to call (e.g., "restart_container")
            args: Arguments to pass to the tool
            
        Returns:
            FixExecutionResult with the tool execution outcome
        """
        # Construct the Docker MCP command
        cmd: Sequence[str] = (
            "docker",
            "mcp",
            "tools",
            "call",
            f"{server}/{tool}",
            "--args",
            json.dumps(args),
        )

        console.print(f"[dim]Running CLI: {' '.join(cmd)}[/dim]")

        try:
            # Execute the MCP command
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return FixExecutionResult(
                success=False,
                message="docker MCP CLI not installed",
                error="docker MCP CLI not installed",
            )

        try:
            # Wait for the command to complete with timeout
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=_MCP_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            # Handle timeout by killing the process
            process.kill()
            await process.communicate()
            return FixExecutionResult(
                success=False,
                message="Tool call timed out",
                error="Tool call timed out",
            )

        # Parse the command output
        stdout_text = stdout.decode().strip()
        stderr_text = stderr.decode().strip()

        # Check if the command failed
        if process.returncode != 0:
            error_message = stderr_text or stdout_text or "Unknown error"
            return FixExecutionResult(success=False, message=error_message, error=error_message)

        # Parse the JSON response if available
        if stdout_text:
            raw_payload = _safe_parse_json(stdout_text)
        else:
            raw_payload = {}

        # Validate with Pydantic model
        try:
            payload = MCPToolResponse.model_validate(raw_payload)
        except Exception as e:
            console.print(f"[yellow]Warning: Could not validate MCP response: {e}[/yellow]")
            # Fall back to raw response if validation fails
            payload = MCPToolResponse()

        # Extract response information
        message = payload.message or "Tool call completed successfully"
        status = payload.status
        details = payload.model_dump(exclude={"message", "status"})

        return FixExecutionResult(
            success=True,
            message=message,
            status=status,
            details=json.dumps(details) if details else None,
        )
    
    async def _call_mcp_tool_http(
        self,
        server: str,
        tool: str,
        args: Mapping[str, object],
    ) -> FixExecutionResult:
        """
        Call MCP tool using HTTP API as recommended by Docker.
        
        Args:
            server: MCP server name (e.g., "docker-control")
            tool: Tool name to call (e.g., "restart_container")
            args: Arguments to pass to the tool
            
        Returns:
            FixExecutionResult with the tool execution outcome
        """
        session = await self._get_session()
        
        # Construct the HTTP request
        url = f"{self.settings.gateway_url}/docker/mcp/tools"
        payload = {
            "name": f"{server}/{tool}",
            "arguments": dict(args)
        }
        
        console.print(f"[dim]Calling HTTP API: POST {url}[/dim]")
        console.print(f"[dim]Payload: {json.dumps(payload, indent=2)}[/dim]")
        
        try:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    response_text = await response.text()
                    console.print(f"[dim]Response: {response_text[:200]}...[/dim]")
                    
                    # Parse the JSON response
                    raw_payload = _safe_parse_json(response_text)
                    
                    # Try to extract content from MCP response format
                    if isinstance(raw_payload, dict) and "content" in raw_payload:
                        content = raw_payload.get("content", [])
                        if content and isinstance(content, list) and len(content) > 0:
                            text_content = content[0].get("text", "{}")
                            parsed_content = _safe_parse_json(text_content)
                        else:
                            parsed_content = {}
                    else:
                        parsed_content = raw_payload
                    
                    # Validate with Pydantic model
                    try:
                        mcp_response = MCPToolResponse.model_validate(parsed_content)
                    except Exception as e:
                        console.print(f"[yellow]Warning: Could not validate MCP response: {e}[/yellow]")
                        mcp_response = MCPToolResponse()
                    
                    # Extract response information
                    message = mcp_response.message or "Tool call completed successfully"
                    status = mcp_response.status
                    details = mcp_response.model_dump(exclude={"message", "status"})
                    
                    return FixExecutionResult(
                        success=True,
                        message=message,
                        status=status,
                        details=json.dumps(details) if details else None,
                    )
                else:
                    error_text = await response.text()
                    return FixExecutionResult(
                        success=False,
                        message=f"HTTP {response.status}: {error_text}",
                        error=f"HTTP {response.status}: {error_text}",
                    )
        except asyncio.TimeoutError:
            return FixExecutionResult(
                success=False,
                message="HTTP request timed out",
                error="HTTP request timed out",
            )
        except Exception as exc:
            return FixExecutionResult(
                success=False,
                message=f"HTTP request failed: {exc}",
                error=f"HTTP request failed: {exc}",
            )


def _parse_key_value_lines(details: str) -> dict[str, str]:
    """
    Parse key-value pairs from multi-line text.
    
    Extracts key=value pairs from a multi-line string, ignoring
    lines that don't contain the equals sign.
    
    Args:
        details: Multi-line string with key=value pairs
        
    Returns:
        Dictionary of parsed key-value pairs
    """
    updates: dict[str, str] = {}
    for line in details.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        updates[key.strip()] = value.strip()
    return updates


def _parse_inline_assignments(details: str) -> dict[str, str]:
    """
    Parse key-value assignments from space-separated text.
    
    Extracts key=value pairs from a space-separated string, ignoring
    parts that don't contain the equals sign.
    
    Args:
        details: Space-separated string with key=value pairs
        
    Returns:
        Dictionary of parsed key-value pairs
    """
    assignments: dict[str, str] = {}
    for part in details.split():
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        assignments[key.strip()] = value.strip()
    return assignments


def _safe_parse_json(text: str) -> dict[str, object]:
    """
    Safely parse JSON from text that might contain extra content.
    
    Attempts to parse JSON from text that might contain additional
    content before or after the JSON data.
    
    Args:
        text: Text containing JSON data
        
    Returns:
        Parsed JSON as a dictionary
    """
    text = text.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Try to find the start of JSON data
        brace_index = min(
            [index for index in (text.find("{"), text.find("[")) if index != -1],
            default=-1,
        )
        if brace_index == -1:
            raise
        parsed = json.loads(text[brace_index:])
    if isinstance(parsed, dict):
        return parsed
    return {"data": parsed}


def _extract_health(details: str | None) -> str:
    """
    Extract health status from MCP tool response.
    
    Parses the health status from a JSON response string,
    returning a normalized health status value.
    
    Args:
        details: JSON response string from MCP tool
        
    Returns:
        Normalized health status value
    """
    if not details:
        return "unknown"
    try:
        parsed = json.loads(details)
    except json.JSONDecodeError:
        return "unknown"
    if isinstance(parsed, dict):
        health = parsed.get("health")
        if isinstance(health, str):
            health_lower = health.lower()
            # Validate against our known health statuses
            if health_lower in ("healthy", "running", "unhealthy"):
                return health_lower
    return "unknown"


def _log_result(result: FixExecutionResult, success_msg: str) -> None:
    """
    Log the result of a fix execution to the console.
    
    Args:
        result: Result of the fix execution
        success_msg: Message to display on success
    """
    if result.success:
        console.print(f"[green]✓ {result.message or success_msg}[/green]")
    else:
        failure_reason = result.error or result.message or "Unknown error"
        console.print(f"[red]✗ {failure_reason}[/red]")


if __name__ == "__main__":
    """
    Example usage of the MCP orchestrator.
    
    This block demonstrates how to use the orchestrator to execute
    fix actions on containers. It's primarily for testing and
    demonstration purposes.
    """
    from dotenv import load_dotenv

    load_dotenv()

    async def _test() -> None:
        orchestrator = MCPOrchestrator()
        fix_action = FixAction(
            action=FixActionName.RESTART_CONTAINER,
            target="demo-postgres",
            details="Restarting due to connection failures",
            priority=1,
        )
        result = await orchestrator.execute_fix(fix_action)
        console.print("\n[bold]Execution Result:[/bold]")
        console.print(result.model_dump())

        healthy = await orchestrator.verify_health("demo-postgres")
        console.print(f"\n[bold]Health Status:[/bold] {'✓ Healthy' if healthy else '✗ Unhealthy'}")

    asyncio.run(_test())
