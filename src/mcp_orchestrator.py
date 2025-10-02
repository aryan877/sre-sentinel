"""Docker MCP Gateway Orchestrator with strong typing."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from rich.console import Console

from sentinel_types import FixAction, FixActionName, FixExecutionResult

console = Console()


@dataclass(slots=True, frozen=True)
class MCPSettings:
    """Runtime configuration for the MCP gateway."""

    gateway_url: str
    auto_heal_enabled: bool

    @classmethod
    def from_env(cls) -> "MCPSettings":
        url = os.getenv("MCP_GATEWAY_URL", "http://localhost:8811")
        auto_heal = os.getenv("AUTO_HEAL_ENABLED", "true").strip().lower() == "true"
        return cls(gateway_url=url, auto_heal_enabled=auto_heal)


class MCPOrchestrator:
    """Orchestrates Docker container actions via MCP Gateway."""

    def __init__(self, settings: MCPSettings | None = None) -> None:
        self.settings = settings or MCPSettings.from_env()

    async def execute_fix(self, fix_action: FixAction) -> FixExecutionResult:
        """Execute a suggested fix via MCP Gateway."""

        console.print("\n[bold cyan]🔧 Executing Fix via MCP Gateway[/bold cyan]")
        console.print(f"[cyan]Action:[/cyan] {fix_action.action.value}")
        console.print(f"[cyan]Target:[/cyan] {fix_action.target}")
        console.print(f"[cyan]Details:[/cyan] {fix_action.details}")

        if not self.settings.auto_heal_enabled:
            console.print("[yellow]⚠️  Auto-heal disabled. Skipping execution.[/yellow]")
            return FixExecutionResult(success=False, message="Auto-heal disabled")

        try:
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

    async def verify_health(self, container_name: str, max_wait: int = 30) -> bool:
        """Verify container health after applying fixes."""

        console.print(f"[yellow]🏥 Verifying health of {container_name}...[/yellow]")
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < max_wait:
            try:
                result = await self._call_mcp_tool(
                    server="docker-control",
                    tool="health_check",
                    args={"container_name": container_name},
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                console.print(f"[red]Health check error: {exc}[/red]")
                return False

            if result.success:
                normalized_status = (result.status or "").lower()
                if normalized_status in {"healthy", "running"}:
                    console.print("[green]✓ Container is healthy![/green]")
                    return True

                health = _extract_health(result.details)
                if health in {"healthy", "running"}:
                    console.print("[green]✓ Container is healthy![/green]")
                    return True

            await asyncio.sleep(2)

        console.print(f"[red]✗ Container did not become healthy within {max_wait}s[/red]")
        return False

    # ------------------------------------------------------------------
    async def _restart_container(self, fix_action: FixAction) -> FixExecutionResult:
        console.print(f"[yellow]↻ Restarting container: {fix_action.target}...[/yellow]")
        result = await self._call_mcp_tool(
            server="docker-control",
            tool="restart_container",
            args={"container_name": fix_action.target, "reason": fix_action.details},
        )
        _log_result(result, success_msg=f"Restarted {fix_action.target}")
        return result

    async def _update_config(self, fix_action: FixAction) -> FixExecutionResult:
        console.print(f"[yellow]⚙️  Updating config for: {fix_action.target}...[/yellow]")
        updates = _parse_key_value_lines(fix_action.details)
        result = await self._call_mcp_tool(
            server="config-patcher",
            tool="update_env_vars",
            args={"container_name": fix_action.target, "env_updates": updates},
        )
        _log_result(result, success_msg=f"Updated config for {fix_action.target}")
        return result

    async def _scale_resources(self, fix_action: FixAction) -> FixExecutionResult:
        console.print(f"[yellow]📊 Scaling resources for: {fix_action.target}...[/yellow]")
        resources = _parse_inline_assignments(fix_action.details)
        result = await self._call_mcp_tool(
            server="docker-control",
            tool="update_resources",
            args={"container_name": fix_action.target, "resources": resources},
        )
        _log_result(result, success_msg=f"Scaled resources for {fix_action.target}")
        return result

    async def _patch_code(self, fix_action: FixAction) -> FixExecutionResult:
        console.print(f"[yellow]🔨 Patching code at: {fix_action.target}...[/yellow]")
        console.print("[red]⚠️  Code patching not yet implemented (coming soon!)[/red]")
        return FixExecutionResult(
            success=False,
            message="Code patching not implemented",
            error="Code patching not implemented",
        )

    async def _call_mcp_tool(
        self,
        *,
        server: str,
        tool: str,
        args: Mapping[str, object],
    ) -> FixExecutionResult:
        cmd: Sequence[str] = (
            "docker",
            "mcp",
            "tools",
            "call",
            f"{server}/{tool}",
            "--args",
            json.dumps(args),
        )

        console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")

        try:
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
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return FixExecutionResult(
                success=False,
                message="Tool call timed out",
                error="Tool call timed out",
            )

        stdout_text = stdout.decode().strip()
        stderr_text = stderr.decode().strip()

        if process.returncode != 0:
            error_message = stderr_text or stdout_text or "Unknown error"
            return FixExecutionResult(success=False, message=error_message, error=error_message)

        if stdout_text:
            raw_payload = _safe_parse_json(stdout_text)
        else:
            raw_payload = {}

        payload: Mapping[str, object] = raw_payload
        message = _pluck_str(payload, "message") or "Tool call completed successfully"
        status = _pluck_str(payload, "status")
        details = _payload_remainder(payload)

        return FixExecutionResult(
            success=True,
            message=message,
            status=status,
            details=json.dumps(details) if details else None,
        )


def _parse_key_value_lines(details: str) -> Mapping[str, str]:
    updates: dict[str, str] = {}
    for line in details.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        updates[key.strip()] = value.strip()
    return updates


def _parse_inline_assignments(details: str) -> Mapping[str, str]:
    assignments: dict[str, str] = {}
    for part in details.split():
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        assignments[key.strip()] = value.strip()
    return assignments


def _safe_parse_json(text: str) -> Mapping[str, object]:
    text = text.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        brace_index = min(
            [index for index in (text.find("{"), text.find("[")) if index != -1],
            default=-1,
        )
        if brace_index == -1:
            raise
        parsed = json.loads(text[brace_index:])
    if isinstance(parsed, Mapping):
        return parsed
    return {"data": parsed}


def _pluck_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    return None


def _payload_remainder(payload: Mapping[str, object]) -> Mapping[str, object]:
    keys_to_remove = {"message", "status"}
    return {k: v for k, v in payload.items() if k not in keys_to_remove}


def _extract_health(details: str | None) -> str:
    if not details:
        return ""
    try:
        parsed = json.loads(details)
    except json.JSONDecodeError:
        return ""
    if isinstance(parsed, Mapping):
        health = parsed.get("health")
        if isinstance(health, str):
            return health.lower()
    return ""


def _log_result(result: FixExecutionResult, success_msg: str) -> None:
    if result.success:
        console.print(f"[green]✓ {result.message or success_msg}[/green]")
    else:
        failure_reason = result.error or result.message or "Unknown error"
        console.print(f"[red]✗ {failure_reason}[/red]")


if __name__ == "__main__":
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
        console.print(result.to_dict())

        healthy = await orchestrator.verify_health("demo-postgres")
        console.print(f"\n[bold]Health Status:[/bold] {'✓ Healthy' if healthy else '✗ Unhealthy'}")

    asyncio.run(_test())
