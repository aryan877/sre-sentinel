#!/usr/bin/env python3
"""SRE Sentinel monitoring agent with real-time streaming."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping, MutableMapping
from typing import cast

import docker
import docker.errors
import docker.models.containers
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from cerebras_client import CerebrasAnomalyDetector
from event_bus import SentinelEventBus
from llama_analyzer import LlamaRootCauseAnalyzer
from mcp_orchestrator import MCPOrchestrator
from sentinel_types import (
    AnomalyDetectionResult,
    AnomalySeverity,
    ContainerState,
    FixExecutionResult,
    Incident,
    IncidentStatus,
    SerializableMixin,
)

console = Console()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _serialise_payload(value: object) -> object:
    if isinstance(value, SerializableMixin):
        return value.to_dict()
    if is_dataclass(value):
        return {
            field.name: _serialise_payload(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {key: _serialise_payload(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_serialise_payload(item) for item in value]
    return value


class SRESentinel:
    """Main monitoring and self-healing orchestrator."""

    def __init__(self, event_bus: SentinelEventBus) -> None:
        self.event_bus = event_bus
        self.docker_client = docker.from_env()
        self.cerebras = CerebrasAnomalyDetector()
        self.llama = LlamaRootCauseAnalyzer()
        self.mcp = MCPOrchestrator()

        self._loop: asyncio.AbstractEventLoop | None = None
        self.log_buffers: dict[str, deque[dict[str, str]]] = defaultdict(
            lambda: deque(maxlen=2000)
        )
        self.container_states: MutableMapping[str, ContainerState] = {}
        self.incidents: list[Incident] = []

        self._compose_cache: str | None = None
        self._compose_path = Path(__file__).resolve().parent.parent / "docker-compose.yml"

        # Log analysis tuning (override via environment if needed)
        self.log_lines_per_check = int(os.getenv("LOG_LINES_PER_CHECK", "20"))
        self.log_check_interval_seconds = float(os.getenv("LOG_CHECK_INTERVAL", "5"))

    # ------------------------------------------------------------------
    # Public state accessors (used by API layer)
    # ------------------------------------------------------------------
    def snapshot_containers(self) -> list[dict[str, object]]:
        return [state.to_dict() for state in self.container_states.values()]

    def snapshot_incidents(self) -> list[dict[str, object]]:
        return [incident.to_dict() for incident in self.incidents]

    # ------------------------------------------------------------------
    async def monitor_loop(self) -> None:
        """Main monitoring loop."""

        self._loop = asyncio.get_running_loop()

        console.print("\n[bold green]🛡️  SRE Sentinel Starting...[/bold green]\n")

        containers = self._get_monitored_containers()
        if not containers:
            console.print(
                "[red]No containers found with label sre-sentinel.monitor=true[/red]"
            )
            console.print(
                "[yellow]Add labels to docker-compose.yml and restart containers.[/yellow]"
            )
            return

        console.print(f"[green]Monitoring {len(containers)} containers:[/green]")
        for container in containers:
            service_name = self._service_name(container)
            console.print(f"  • {service_name} ({container.short_id})")
        console.print()

        tasks = [asyncio.create_task(self._monitor_container(container)) for container in containers]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            raise

    async def _publish_event(self, event: Mapping[str, object]) -> None:
        serialised = _serialise_payload(event)
        if isinstance(serialised, dict):
            await self.event_bus.publish(serialised)
        else:
            await self.event_bus.publish({"data": serialised})

    # ------------------------------------------------------------------
    def _get_monitored_containers(self) -> list[docker.models.containers.Container]:
        try:
            containers_raw = self.docker_client.containers.list(
                filters={"label": "sre-sentinel.monitor=true"}
            )
            return cast(list[docker.models.containers.Container], containers_raw)
        except docker.errors.DockerException as exc:
            console.print(f"[red]Docker error while listing containers: {exc}[/red]")
            return []

    def _service_name(self, container: docker.models.containers.Container) -> str:
        labels_raw = container.labels
        if labels_raw:
            labels = cast(Mapping[str, str], labels_raw)
            return labels.get("sre-sentinel.service", container.name or container.short_id)
        return container.name or container.short_id

    async def _monitor_container(self, container: docker.models.containers.Container) -> None:
        service_name = self._service_name(container)
        container_id = container.id

        await self._publish_container_state(container, service_name)

        log_task = asyncio.create_task(self._stream_container_logs(container, service_name))
        stats_task = asyncio.create_task(self._track_container_stats(container, service_name))

        try:
            await asyncio.gather(log_task, stats_task)
        finally:
            if not log_task.done():
                log_task.cancel()
            if not stats_task.done():
                stats_task.cancel()
            if container_id:
                self.container_states.pop(container_id, None)

    # ------------------------------------------------------------------
    async def _track_container_stats(
        self, container: docker.models.containers.Container, service_name: str
    ) -> None:
        """Periodically publish container health metrics."""

        container_id = container.id

        while True:
            try:
                stats_raw = await asyncio.to_thread(container.stats, stream=False)
                stats = cast(Mapping[str, object], stats_raw)
                metrics = self._parse_stats(stats)
                container.reload()
                status = container.status or "unknown"
                restart_count = _to_int(container.attrs.get("RestartCount", 0))
            except docker.errors.NotFound:
                console.print(f"[yellow]{service_name} container disappeared; stopping monitor.[/yellow]")
                offline_state = ContainerState(
                    id=container_id,
                    name=container.name,
                    service=service_name,
                    status="offline",
                    restarts=None,
                    cpu=0.0,
                    memory=0.0,
                    timestamp=_utcnow(),
                )
                if container_id:
                    self.container_states[container_id] = offline_state
                await self._publish_event(
                    {"type": "container_update", "container": offline_state}
                )
                break
            except docker.errors.DockerException as exc:
                console.print(f"[red]Error fetching stats for {service_name}: {exc}[/red]")
                status = "unknown"
                restart_count = None
                metrics = {"cpu_percent": 0.0, "memory_percent": 0.0}

            container_state = ContainerState(
                id=container_id,
                name=container.name,
                service=service_name,
                status=status,
                restarts=restart_count,
                cpu=round(metrics.get("cpu_percent", 0.0), 2),
                memory=round(metrics.get("memory_percent", 0.0), 2),
                timestamp=_utcnow(),
            )
            if container_id:
                self.container_states[container_id] = container_state
            await self._publish_event(
                {"type": "container_update", "container": container_state}
            )

            await asyncio.sleep(5)

    async def _publish_container_state(
        self, container: docker.models.containers.Container, service_name: str
    ) -> None:
        try:
            container.reload()
        except docker.errors.DockerException as exc:
            console.print(f"[red]Unable to refresh container {service_name}: {exc}[/red]")
        status = container.status or "unknown"
        restarts = (
            _to_int(container.attrs.get("RestartCount", 0))
            if hasattr(container, "attrs")
            else None
        )
        container_id = container.id
        container_state = ContainerState(
            id=container_id,
            name=container.name,
            service=service_name,
            status=status,
            restarts=restarts,
            cpu=0.0,
            memory=0.0,
            timestamp=_utcnow(),
        )
        if container_id:
            self.container_states[container_id] = container_state
        await self._publish_event({"type": "container_update", "container": container_state})

    def _parse_stats(self, stats: Mapping[str, object]) -> dict[str, float]:
        cpu_percent = 0.0
        memory_percent = 0.0

        cpu_stats = cast(Mapping[str, object], stats.get("cpu_stats") or {})
        precpu = cast(Mapping[str, object], stats.get("precpu_stats") or {})

        cpu_usage = cast(Mapping[str, object], cpu_stats.get("cpu_usage") or {})
        precpu_usage = cast(Mapping[str, object], precpu.get("cpu_usage") or {})

        total_usage_current = cpu_usage.get("total_usage", 0.0)
        total_usage_prev = precpu_usage.get("total_usage", 0.0)
        if not isinstance(total_usage_current, (int, float)):
            total_usage_current = 0.0
        if not isinstance(total_usage_prev, (int, float)):
            total_usage_prev = 0.0
        cpu_delta = float(total_usage_current) - float(total_usage_prev)
        
        system_cpu_current = cpu_stats.get("system_cpu_usage", 0.0)
        system_cpu_prev = precpu.get("system_cpu_usage", 0.0)
        if not isinstance(system_cpu_current, (int, float)):
            system_cpu_current = 0.0
        if not isinstance(system_cpu_prev, (int, float)):
            system_cpu_prev = 0.0
        system_delta = float(system_cpu_current) - float(system_cpu_prev)
        percpu_usage_raw = cpu_usage.get("percpu_usage")
        if isinstance(percpu_usage_raw, list):
            cores = len(cast(list[object], percpu_usage_raw))
        elif isinstance(percpu_usage_raw, tuple):
            cores = len(cast(tuple[object, ...], percpu_usage_raw))
        else:
            cores = 0

        if system_delta > 0 and cpu_delta >= 0:
            cpu_percent = (cpu_delta / system_delta) * cores * 100.0

        memory_stats = cast(Mapping[str, object], stats.get("memory_stats") or {})
        memory_usage_raw = memory_stats.get("usage", 0.0)
        stats_dict = cast(Mapping[str, object], memory_stats.get("stats") or {})
        cache_raw = stats_dict.get("cache", 0.0)
        if not isinstance(memory_usage_raw, (int, float)):
            memory_usage_raw = 0.0
        if not isinstance(cache_raw, (int, float)):
            cache_raw = 0.0
        memory_usage = float(memory_usage_raw) - float(cache_raw)
        memory_limit_raw = memory_stats.get("limit", 1.0)
        if not isinstance(memory_limit_raw, (int, float)):
            memory_limit_raw = 1.0
        memory_limit = float(memory_limit_raw)
        if memory_limit > 0:
            memory_percent = (memory_usage / memory_limit) * 100.0

        return {"cpu_percent": cpu_percent, "memory_percent": memory_percent}

    # ------------------------------------------------------------------
    async def _stream_container_logs(
        self, container: docker.models.containers.Container, service_name: str
    ) -> None:
        container_name = container.name or container.short_id
        queue: "asyncio.Queue[str | None]" = asyncio.Queue()

        if self._loop is None:
            raise RuntimeError("Event loop not initialised")

        loop = self._loop

        def _pump_logs() -> None:
            try:
                for raw in container.logs(stream=True, follow=True):
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    loop.call_soon_threadsafe(queue.put_nowait, line)
            except Exception as exc:  # pragma: no cover - best effort logging
                console.print(f"[red]Log stream for {service_name} ended: {exc}[/red]")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=_pump_logs, daemon=True).start()
        console.print(f"[cyan]📡 Streaming logs from {service_name}...[/cyan]")

        lines_since_check = 0
        last_check_time = time.monotonic()

        while True:
            line = await queue.get()
            if line is None:
                break

            timestamp = _utcnow()
            self.log_buffers[container_name].append({"timestamp": timestamp, "line": line})

            await self._publish_event(
                {
                    "type": "log",
                    "container": service_name,
                    "timestamp": timestamp,
                    "message": line,
                }
            )

            lines_since_check += 1
            elapsed = time.monotonic() - last_check_time
            if lines_since_check >= self.log_lines_per_check or elapsed >= self.log_check_interval_seconds:
                await self._check_for_anomalies(container, service_name)
                lines_since_check = 0
                last_check_time = time.monotonic()

    async def _check_for_anomalies(
        self, container: docker.models.containers.Container, service_name: str
    ) -> None:
        container_name = container.name or container.short_id
        recent_logs = list(self.log_buffers[container_name])[-200:]
        log_chunk = "\n".join(item["line"] for item in recent_logs)
        if not log_chunk.strip():
            return

        context: dict[str, str | int | None]
        try:
            container.reload()
            container_info = container.attrs
            state_info = cast(Mapping[str, object], container_info.get("State", {}))
            health_info = cast(Mapping[str, object], state_info.get("Health", {}))
            exit_code_raw = state_info.get("ExitCode")
            exit_code = _to_int(exit_code_raw)
            restarts_val = _to_int(container_info.get("RestartCount", 0))
            context = {
                "status": container.status or "unknown",
                "health": str(health_info.get("Status", "unknown")),
                "restarts": restarts_val,
                "exit_code": exit_code,
            }
        except docker.errors.DockerException:
            context = {}

        anomaly = self.cerebras.detect_anomaly(
            log_chunk=log_chunk, service_name=service_name, context=context
        )

        if anomaly.is_anomaly and anomaly.severity in {
            AnomalySeverity.HIGH,
            AnomalySeverity.CRITICAL,
        }:
            console.print(
                f"\n[red bold]🚨 CRITICAL ANOMALY DETECTED IN {service_name}[/red bold]"
            )
            await self._handle_incident(container, service_name, anomaly)

    # ------------------------------------------------------------------
    async def _handle_incident(
        self,
        container: docker.models.containers.Container,
        service_name: str,
        anomaly: AnomalyDetectionResult,
    ) -> None:
        incident_id = f"INC-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        console.print(f"\n[bold yellow]{'='*60}[/bold yellow]")
        console.print(f"[bold]🚨 INCIDENT: {incident_id}[/bold]")
        console.print(f"[bold yellow]{'='*60}[/bold yellow]\n")

        incident_record = Incident(
            id=incident_id,
            service=service_name,
            detected_at=_utcnow(),
            anomaly=anomaly,
            status=IncidentStatus.ANALYZING,
        )
        self.incidents.append(incident_record)
        await self._publish_event({"type": "incident", "incident": incident_record})

        console.print("[bold cyan]📊 Step 1: Gathering system context...[/bold cyan]")

        container_name = container.name or container.short_id
        all_logs = "\n".join(log["line"] for log in self.log_buffers[container_name])

        docker_compose = self._read_docker_compose()

        try:
            container_info = container.attrs
        except Exception:
            container_info = {}

        environment_vars: dict[str, str] = {}
        config_info = cast(Mapping[str, object], container_info.get("Config", {}))
        env_list_raw = config_info.get("Env", [])
        if isinstance(env_list_raw, list):
            env_list = cast(list[object], env_list_raw)
            for env_item in env_list:
                if isinstance(env_item, str):
                    key, _, value = env_item.partition("=")
                    environment_vars[key] = value

        state_data = cast(Mapping[str, object], container_info.get("State", {}))
        exit_code_val = state_data.get("ExitCode")
        container_stats: dict[str, str | int | None] = {
            "status": container.status or "unknown",
            "restarts": _to_int(container_info.get("RestartCount", 0)),
            "created": str(container_info.get("Created", "")),
            "exit_code": _to_int(exit_code_val),
        }

        console.print(
            f"[green]✓ Context gathered: {len(all_logs)} chars, {len(environment_vars)} env vars[/green]\n"
        )

        console.print(
            "[bold cyan]📊 Step 2: Performing root cause analysis with Llama 4 Scout...[/bold cyan]"
        )

        analysis = self.llama.analyze_root_cause(
            anomaly_summary=anomaly.summary,
            full_logs=all_logs,
            docker_compose=docker_compose,
            environment_vars=environment_vars,
            container_stats=container_stats,
        )
        incident_record.analysis = analysis
        await self._publish_event({"type": "incident_update", "incident": incident_record})

        console.print(
            f"\n[green]✓ Root cause identified with {analysis.confidence:.0%} confidence[/green]\n"
        )

        console.print(
            Panel(
                f"[bold]Root Cause:[/bold]\n{analysis.root_cause}\n\n"
                f"[bold]Affected Components:[/bold]\n"
                + "\n".join(f"  • {component}" for component in analysis.affected_components),
                title="🧠 AI Analysis",
                border_style="cyan",
            )
        )

        console.print(
            "\n[bold cyan]📊 Step 3: Executing fixes via Docker MCP Gateway...[/bold cyan]"
        )

        fix_results: list[FixExecutionResult] = []
        for fix in analysis.suggested_fixes:
            console.print(
                f"\n[yellow]→ Applying fix (priority {fix.priority})...[/yellow]"
            )
            result = await self.mcp.execute_fix(fix)
            fix_results.append(result)

            if result.success:
                console.print(f"[green]✓ {result.message or 'Fix applied successfully'}[/green]")
            else:
                failure_reason = result.error or result.message or "Unknown error"
                console.print(f"[red]✗ Fix failed: {failure_reason}[/red]")

        incident_record.fixes = tuple(fix_results)
        await self._publish_event({"type": "incident_update", "incident": incident_record})

        console.print(
            "\n[bold cyan]📊 Step 4: Verifying system health...[/bold cyan]"
        )

        is_healthy = await self.mcp.verify_health(container_name, max_wait=30)

        if is_healthy:
            console.print(f"\n[bold green]{'='*60}[/bold green]")
            console.print(f"[bold green]✅ INCIDENT RESOLVED: {incident_id}[/bold green]")
            console.print(f"[bold green]{'='*60}[/bold green]\n")
            incident_record.status = IncidentStatus.RESOLVED
            incident_record.resolved_at = _utcnow()
        else:
            console.print(f"\n[bold red]{'='*60}[/bold red]")
            console.print(f"[bold red]⚠️  INCIDENT UNRESOLVED: {incident_id}[/bold red]")
            console.print("[bold red]Manual intervention required[/bold red]")
            console.print(f"[bold red]{'='*60}[/bold red]\n")
            incident_record.status = IncidentStatus.UNRESOLVED

        await self._publish_event({"type": "incident_update", "incident": incident_record})

        console.print(
            "\n[bold cyan]📊 Generating explanation for stakeholders...[/bold cyan]"
        )
        explanation = self.llama.explain_for_humans(analysis)
        incident_record.explanation = explanation

        console.print(
            Panel(
                explanation,
                title="📢 Human-Friendly Explanation",
                border_style="green",
            )
        )

        await self._publish_event({"type": "incident_update", "incident": incident_record})

    # ------------------------------------------------------------------
    def _read_docker_compose(self) -> str | None:
        if self._compose_cache is not None:
            return self._compose_cache
        try:
            self._compose_cache = self._compose_path.read_text()
        except FileNotFoundError:
            self._compose_cache = None
        return self._compose_cache


async def main() -> None:
    """Entrypoint used by CLI and Docker container."""

    load_dotenv()

    banner = "=" * 60
    console.print()
    console.print(f"[bold cyan]{banner}[/bold cyan]")
    console.print("[bold cyan]        🛡️  SRE SENTINEL - AI DevOps Copilot        [/bold cyan]")
    console.print(f"[bold cyan]{banner}[/bold cyan]")
    console.print()
    console.print("[dim]Powered by Cerebras (⚡ fast), Llama 4 (🧠 smart), Docker MCP (🔧 secure)[/dim]")
    console.print()

    event_bus = SentinelEventBus()
    try:
        sentinel = SRESentinel(event_bus=event_bus)
    except ValueError as exc:
        console.print(f"[red]Failed to initialise SRE Sentinel: {exc}[/red]")
        console.print("[yellow]Ensure API keys are configured in the .env file.[/yellow]")
        return

    from websocket_server import build_application

    app = build_application(sentinel, event_bus)

    import uvicorn

    api_port = int(os.getenv("API_PORT", "8000"))
    api_host = os.getenv("API_HOST", "0.0.0.0")

    config = uvicorn.Config(app, host=api_host, port=api_port, log_level="info")
    server = uvicorn.Server(config)

    monitor_task = asyncio.create_task(sentinel.monitor_loop())
    api_task = asyncio.create_task(server.serve())

    try:
        await asyncio.wait({monitor_task, api_task}, return_when=asyncio.FIRST_EXCEPTION)
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down gracefully...[/yellow]")
    finally:
        if not monitor_task.done():
            monitor_task.cancel()
        server.should_exit = True
        await api_task


if __name__ == "__main__":
    asyncio.run(main())
