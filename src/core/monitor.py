#!/usr/bin/env python3
"""
SRE Sentinel monitoring agent with real-time streaming.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping, MutableMapping

import docker
import docker.errors
import docker.models.containers
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from src.ai.cerebras_client import CerebrasAnomalyDetector
from src.infrastructure.redis_event_bus import RedisEventBus, create_redis_event_bus
from src.ai.llama_analyzer import LlamaRootCauseAnalyzer
from src.core.orchestrator import MCPOrchestrator
from src.models.sentinel_types import (
    AnomalyDetectionResult,
    AnomalySeverity,
    BaseModel,
    ContainerState,
    ContainerStats,
    ContainerUpdateEvent,
    FixExecutionResult,
    Incident,
    IncidentEvent,
    IncidentStatus,
    IncidentUpdateEvent,
    LogEntry,
    LogEvent,
)

console = Console()

_MAX_LOG_BUFFER_SIZE = 2000
_LOG_LINES_PER_CHECK_DEFAULT = 20
_LOG_CHECK_INTERVAL_DEFAULT = 5.0
_STATS_INTERVAL_SECONDS = 5
_MAX_HEALTH_WAIT_SECONDS = 30
_RECENT_LOGS_COUNT = 200
# Removed - no longer needed with Docker events


def _utcnow() -> str:
    """Get current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _to_int(value: object) -> int | None:
    """Safely convert a value to int, returning None if conversion fails."""
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
    """Serialize a value to JSON-compatible format."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, Mapping):
        return {key: _serialise_payload(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_serialise_payload(item) for item in value]
    return value


class SRESentinel:
    """Main monitoring and self-healing orchestrator."""

    def __init__(self, event_bus: RedisEventBus) -> None:
        """Initialize the SRE Sentinel with an event bus."""
        self.event_bus = event_bus
        self.docker_client = docker.from_env()
        self.cerebras = CerebrasAnomalyDetector()
        self.llama = LlamaRootCauseAnalyzer(cerebras_detector=self.cerebras)
        self.mcp = MCPOrchestrator()

        self._loop: asyncio.AbstractEventLoop | None = None
        self.log_buffers: dict[str, deque[LogEntry]] = defaultdict(
            lambda: deque(maxlen=_MAX_LOG_BUFFER_SIZE)
        )
        self.container_states: MutableMapping[str, ContainerState] = {}
        self.incidents: list[Incident] = []
        self.previous_stats: dict[str, dict[str, object]] = {}
        self._monitoring_tasks: dict[str, asyncio.Task] = {}

        self._compose_cache: str | None = None
        self._compose_path = (
            Path(__file__).resolve().parent.parent / "docker-compose.yml"
        )

        self.log_lines_per_check = int(
            os.getenv("LOG_LINES_PER_CHECK", str(_LOG_LINES_PER_CHECK_DEFAULT))
        )
        self.log_check_interval_seconds = float(
            os.getenv("LOG_CHECK_INTERVAL", str(_LOG_CHECK_INTERVAL_DEFAULT))
        )

    def snapshot_containers(self) -> list[dict[str, object]]:
        """Get current snapshot of all container states."""
        return [state.model_dump() for state in self.container_states.values()]

    def snapshot_incidents(self) -> list[dict[str, object]]:
        """Get current snapshot of all incidents."""
        return [incident.model_dump() for incident in self.incidents]

    async def monitor_loop(self) -> None:
        """Main monitoring loop using Docker events for real-time container discovery."""
        self._loop = asyncio.get_running_loop()

        console.print("\n[bold green]🛡️  SRE Sentinel Starting...[/bold green]\n")

        # Initial discovery of existing containers
        containers = self._get_monitored_containers()
        if containers:
            console.print(
                f"[cyan]🔍 Found {len(containers)} existing containers to monitor[/cyan]"
            )
            for container in containers:
                await self._start_monitoring_container(container)
        else:
            console.print(
                "[yellow]No containers found with label sre-sentinel.monitor=true[/yellow]"
            )
            console.print(
                "[yellow]Waiting for containers via Docker events...[/yellow]"
            )

        # Start Docker events listener for real-time container discovery
        console.print("[cyan]📡 Listening for Docker container events...[/cyan]")

        try:
            await self._listen_docker_events()
        except asyncio.CancelledError:
            console.print("[yellow]Monitoring loop cancelled, cleaning up...[/yellow]")
            for task in self._monitoring_tasks.values():
                task.cancel()
            raise

    async def _start_monitoring_container(
        self, container: docker.models.containers.Container
    ) -> None:
        """Start monitoring a container if not already monitored."""
        if container.id not in self._monitoring_tasks:
            service_name = self._service_name(container)
            console.print(
                f"[green]▶ Starting monitoring: {service_name} ({container.short_id})[/green]"
            )
            task = asyncio.create_task(self._monitor_container(container))
            self._monitoring_tasks[container.id] = task

    async def _listen_docker_events(self) -> None:
        """Listen to Docker events for real-time container lifecycle changes."""
        while True:
            try:
                console.print("[cyan]📡 Connecting to Docker events stream...[/cyan]")

                # Create a separate thread for the Docker events stream
                event_queue = asyncio.Queue()

                def _event_stream_thread():
                    try:
                        event_stream = self.docker_client.events(
                            decode=True,
                            filters={
                                "type": "container",
                                "label": "sre-sentinel.monitor=true",
                            },
                        )
                        for event in event_stream:
                            # Use thread-safe method to put events in queue
                            asyncio.run_coroutine_threadsafe(
                                event_queue.put(event), self._loop
                            )
                    except Exception as exc:
                        asyncio.run_coroutine_threadsafe(
                            event_queue.put({"error": str(exc)}), self._loop
                        )

                # Start the event stream thread
                thread = threading.Thread(target=_event_stream_thread, daemon=True)
                thread.start()

                console.print("[green]✅ Connected to Docker events stream[/green]")

                # Process events from the queue
                while True:
                    try:
                        # Wait for events with timeout to check thread health
                        event = await asyncio.wait_for(event_queue.get(), timeout=5.0)

                        if "error" in event:
                            raise Exception(
                                f"Docker events stream error: {event['error']}"
                            )

                        await self._handle_docker_event(event)

                    except asyncio.TimeoutError:
                        # Check if thread is still alive
                        if not thread.is_alive():
                            console.print(
                                "[red]Docker events thread died, restarting...[/red]"
                            )
                            break
                        continue

            except asyncio.TimeoutError:
                console.print("[red]Timeout connecting to Docker events stream[/red]")
                console.print("[yellow]Reconnecting in 5 seconds...[/yellow]")
                await asyncio.sleep(5)
            except docker.errors.DockerException as exc:
                console.print(f"[red]Docker connection error: {exc}[/red]")
                console.print("[yellow]Reconnecting in 5 seconds...[/yellow]")
                await asyncio.sleep(5)
            except Exception as exc:
                console.print(
                    f"[red]Unexpected error in Docker events listener: {exc}[/red]"
                )
                console.print("[yellow]Reconnecting in 10 seconds...[/yellow]")
                await asyncio.sleep(10)

    async def _handle_docker_event(self, event: dict[str, object]) -> None:
        """Handle a single Docker event."""
        action = event.get("Action", "")
        container_id = event.get("Actor", {}).get("ID", "")

        if not container_id:
            return

        # Only process events for containers with our monitoring label
        if not self._has_monitor_label(container_id):
            return

        if action == "start":
            # New container started - begin monitoring
            try:
                container = self.docker_client.containers.get(container_id)
                await self._start_monitoring_container(container)
            except docker.errors.NotFound:
                console.print(
                    f"[yellow]Container {container_id[:12]} already removed[/yellow]"
                )

        elif action in {"die", "kill", "stop", "pause"}:
            # Container stopped/paused - cleanup will happen in monitoring task
            self._cleanup_completed_tasks()

            # For stopped containers, we might want to restart monitoring if they come back
            if action == "stop":
                console.print(f"[yellow]Container {container_id[:12]} stopped[/yellow]")

        elif action == "destroy":
            # Container removed - cleanup monitoring task
            if container_id in self._monitoring_tasks:
                task = self._monitoring_tasks.pop(container_id)
                task.cancel()
                console.print(
                    f"[yellow]Container {container_id[:12]} destroyed, stopped monitoring[/yellow]"
                )

            # Also clean up container state
            self.container_states.pop(container_id, None)

        elif action == "restart":
            # Container restarted - continue monitoring the same container
            console.print(f"[cyan]Container {container_id[:12]} restarted[/cyan]")
            try:
                container = self.docker_client.containers.get(container_id)
                if container_id not in self._monitoring_tasks:
                    await self._start_monitoring_container(container)
            except docker.errors.NotFound:
                console.print(
                    f"[yellow]Container {container_id[:12]} disappeared during restart[/yellow]"
                )

    def _has_monitor_label(self, container_id: str) -> bool:
        """Check if a container has the monitoring label."""
        try:
            container = self.docker_client.containers.get(container_id)
            labels = container.labels or {}
            return labels.get("sre-sentinel.monitor") == "true"
        except docker.errors.NotFound:
            return False
        except Exception:
            return False

    def _cleanup_completed_tasks(self) -> None:
        """Remove completed monitoring tasks from the tracking dict."""
        completed_ids = [
            container_id
            for container_id, task in self._monitoring_tasks.items()
            if task.done()
        ]

        for container_id in completed_ids:
            task = self._monitoring_tasks.pop(container_id)

            # Log if the task ended with an exception
            if task.done() and not task.cancelled():
                try:
                    exc = task.exception()
                    if exc:
                        console.print(
                            f"[red]Monitoring task for container {container_id[:12]} ended with error: {exc}[/red]"
                        )
                except asyncio.CancelledError:
                    pass

    async def _publish_event(self, event: BaseModel) -> None:
        """Publish an event to the message bus with proper serialization."""
        serialised = _serialise_payload(event)
        if isinstance(serialised, dict):
            await self.event_bus.publish(serialised)
        else:
            await self.event_bus.publish({"data": serialised})

    def _get_monitored_containers(self) -> list[docker.models.containers.Container]:
        """Get all containers that should be monitored."""
        try:
            containers_raw = self.docker_client.containers.list(
                filters={"label": "sre-sentinel.monitor=true"}
            )
            return list(containers_raw)
        except docker.errors.DockerException as exc:
            console.print(f"[red]Docker error while listing containers: {exc}[/red]")
            return []

    def _service_name(self, container: docker.models.containers.Container) -> str:
        """Get the service name for a container."""
        labels_raw = container.labels
        if labels_raw:
            labels = dict(labels_raw)
            return labels.get(
                "sre-sentinel.service", container.name or container.short_id
            )
        return container.name or container.short_id

    async def _monitor_container(
        self, container: docker.models.containers.Container
    ) -> None:
        """Monitor a single container for logs and metrics."""
        service_name = self._service_name(container)
        container_id = container.id

        try:
            await self._publish_container_state(container, service_name)

            log_task = asyncio.create_task(
                self._stream_container_logs(container, service_name)
            )
            stats_task = asyncio.create_task(
                self._track_container_stats(container, service_name)
            )

            try:
                await asyncio.gather(log_task, stats_task)
            finally:
                if not log_task.done():
                    log_task.cancel()
                if not stats_task.done():
                    stats_task.cancel()
                if container_id:
                    self.container_states.pop(container_id, None)
        except asyncio.CancelledError:
            console.print(f"[yellow]Monitoring cancelled for {service_name}[/yellow]")
            raise
        except Exception as exc:
            console.print(
                f"[red]Unexpected error monitoring {service_name}: {exc}[/red]"
            )
            console.print(
                f"[yellow]Attempting to restart monitoring for {service_name} in 10 seconds...[/yellow]"
            )
            # Remove the current task from the monitoring tasks
            self._monitoring_tasks.pop(container_id, None)

            # Wait before restarting
            await asyncio.sleep(10)

            # Try to restart monitoring for this container
            try:
                # Check if container still exists
                container = self.docker_client.containers.get(container_id)
                await self._start_monitoring_container(container)
            except docker.errors.NotFound:
                console.print(
                    f"[yellow]Container {service_name} no longer exists[/yellow]"
                )
            except Exception as restart_exc:
                console.print(
                    f"[red]Failed to restart monitoring for {service_name}: {restart_exc}[/red]"
                )

    async def _track_container_stats(
        self, container: docker.models.containers.Container, service_name: str
    ) -> None:
        """Periodically collect and publish container metrics."""
        container_id = container.id

        while True:
            try:
                stats_raw = await asyncio.to_thread(container.stats, stream=False)
                stats = dict(stats_raw)
                metrics = self._parse_stats(stats)

                container.reload()
                status = container.status or "unknown"
                restart_count = _to_int(container.attrs.get("RestartCount", 0))
            except docker.errors.NotFound:
                console.print(
                    f"[yellow]{service_name} container disappeared; stopping monitor.[/yellow]"
                )
                offline_state = ContainerState(
                    id=container_id,
                    name=container.name,
                    service=service_name,
                    status="offline",
                    restarts=None,
                    cpu=0.0,
                    memory=0.0,
                    network_rx=0.0,
                    network_tx=0.0,
                    disk_read=0.0,
                    disk_write=0.0,
                    timestamp=_utcnow(),
                )
                if container_id:
                    self.container_states[container_id] = offline_state
                await self._publish_event(ContainerUpdateEvent(container=offline_state))
                break
            except docker.errors.DockerException as exc:
                console.print(
                    f"[red]Error fetching stats for {service_name}: {exc}[/red]"
                )
                status = "unknown"
                restart_count = None
                metrics = {
                    "cpu_percent": 0.0,
                    "memory_percent": 0.0,
                    "network_rx": 0.0,
                    "network_tx": 0.0,
                    "disk_read": 0.0,
                    "disk_write": 0.0,
                }

            network_rx_rate = 0.0
            network_tx_rate = 0.0
            disk_read_rate = 0.0
            disk_write_rate = 0.0

            current_rx = metrics.get("network_rx", 0.0)
            current_tx = metrics.get("network_tx", 0.0)
            current_read = metrics.get("disk_read", 0.0)
            current_write = metrics.get("disk_write", 0.0)

            if container_id in self.previous_stats:
                prev_stats = self.previous_stats[container_id]
                prev_time = prev_stats.get("timestamp", 0.0)
                current_time = time.time()
                time_delta = current_time - prev_time

                if time_delta > 0:
                    prev_rx = prev_stats.get("network_rx", 0.0)
                    prev_tx = prev_stats.get("network_tx", 0.0)
                    prev_read = prev_stats.get("disk_read", 0.0)
                    prev_write = prev_stats.get("disk_write", 0.0)

                    if isinstance(current_rx, (int, float)) and isinstance(
                        prev_rx, (int, float)
                    ):
                        network_rx_rate = (
                            float(current_rx) - float(prev_rx)
                        ) / time_delta
                    if isinstance(current_tx, (int, float)) and isinstance(
                        prev_tx, (int, float)
                    ):
                        network_tx_rate = (
                            float(current_tx) - float(prev_tx)
                        ) / time_delta
                    if isinstance(current_read, (int, float)) and isinstance(
                        prev_read, (int, float)
                    ):
                        disk_read_rate = (
                            float(current_read) - float(prev_read)
                        ) / time_delta
                    if isinstance(current_write, (int, float)) and isinstance(
                        prev_write, (int, float)
                    ):
                        disk_write_rate = (
                            float(current_write) - float(prev_write)
                        ) / time_delta

            self.previous_stats[container_id] = {
                "network_rx": current_rx,
                "network_tx": current_tx,
                "disk_read": current_read,
                "disk_write": current_write,
                "timestamp": time.time(),
            }

            try:
                container_state = ContainerState(
                    id=container_id,
                    name=container.name,
                    service=service_name,
                    status=status,
                    restarts=restart_count,
                    cpu=round(metrics.get("cpu_percent", 0.0), 2),
                    memory=round(metrics.get("memory_percent", 0.0), 2),
                    network_rx=round(network_rx_rate, 2),
                    network_tx=round(network_tx_rate, 2),
                    disk_read=round(disk_read_rate, 2),
                    disk_write=round(disk_write_rate, 2),
                    timestamp=_utcnow(),
                )
                if container_id:
                    self.container_states[container_id] = container_state
                await self._publish_event(
                    ContainerUpdateEvent(container=container_state)
                )
            except Exception as exc:
                console.print(
                    f"[red]Error creating container state for {service_name}: {exc}[/red]"
                )
                console.print(
                    f"[yellow]Metrics: cpu={metrics.get('cpu_percent')}, mem={metrics.get('memory_percent')}, "
                    f"net_rx={network_rx_rate}, net_tx={network_tx_rate}, "
                    f"disk_r={disk_read_rate}, disk_w={disk_write_rate}[/yellow]"
                )

            await asyncio.sleep(_STATS_INTERVAL_SECONDS)

    async def _publish_container_state(
        self, container: docker.models.containers.Container, service_name: str
    ) -> None:
        """Publish the current state of a container."""
        try:
            container.reload()
        except docker.errors.DockerException as exc:
            console.print(
                f"[red]Unable to refresh container {service_name}: {exc}[/red]"
            )

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
            network_rx=0.0,
            network_tx=0.0,
            disk_read=0.0,
            disk_write=0.0,
            timestamp=_utcnow(),
        )
        if container_id:
            self.container_states[container_id] = container_state
        await self._publish_event(ContainerUpdateEvent(container=container_state))

    def _parse_stats(self, stats: dict[str, object]) -> dict[str, float]:
        """Parse container statistics from Docker API response."""
        cpu_percent = 0.0
        memory_percent = 0.0
        network_rx = 0.0
        network_tx = 0.0
        disk_read = 0.0
        disk_write = 0.0

        cpu_stats = dict(stats.get("cpu_stats") or {})
        precpu = dict(stats.get("precpu_stats") or {})

        cpu_usage = dict(cpu_stats.get("cpu_usage") or {})
        precpu_usage = dict(precpu.get("cpu_usage") or {})

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
            cores = len(percpu_usage_raw)
        elif isinstance(percpu_usage_raw, tuple):
            cores = len(percpu_usage_raw)
        else:
            cores = 0

        if system_delta > 0 and cpu_delta >= 0:
            cpu_percent = (cpu_delta / system_delta) * cores * 100.0

        memory_stats = dict(stats.get("memory_stats") or {})
        memory_usage_raw = memory_stats.get("usage", 0.0)
        stats_dict = dict(memory_stats.get("stats") or {})
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

        networks = dict(stats.get("networks") or {})
        for _, interface_stats in networks.items():
            if isinstance(interface_stats, dict):
                rx_bytes = interface_stats.get("rx_bytes", 0.0)
                tx_bytes = interface_stats.get("tx_bytes", 0.0)
                if isinstance(rx_bytes, (int, float)):
                    network_rx += float(rx_bytes)
                if isinstance(tx_bytes, (int, float)):
                    network_tx += float(tx_bytes)

        blkio_stats = dict(stats.get("blkio_stats") or {})
        io_service_bytes = blkio_stats.get("io_service_bytes_recursive") or []
        for entry in io_service_bytes:
            if isinstance(entry, dict):
                op = entry.get("op", "")
                value = entry.get("value", 0.0)
                if isinstance(value, (int, float)):
                    if op.lower() == "read":
                        disk_read += float(value)
                    elif op.lower() == "write":
                        disk_write += float(value)

        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "network_rx": network_rx,
            "network_tx": network_tx,
            "disk_read": disk_read,
            "disk_write": disk_write,
        }

    async def _stream_container_logs(
        self, container: docker.models.containers.Container, service_name: str
    ) -> None:
        """Stream logs from a container in real-time."""
        container_name = container.name or container.short_id
        queue: "asyncio.Queue[str | None]" = asyncio.Queue()

        if self._loop is None:
            raise RuntimeError("Event loop not initialised")

        loop = self._loop

        def _pump_logs() -> None:
            """Thread function to pump logs from Docker to the queue."""
            try:
                for raw in container.logs(stream=True, follow=True):
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    loop.call_soon_threadsafe(queue.put_nowait, line)
            except Exception as exc:
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
            log_entry = LogEntry(timestamp=timestamp, line=line)
            self.log_buffers[container_name].append(log_entry)

            log_event = LogEvent(
                container=service_name,
                timestamp=timestamp,
                message=line,
            )
            await self._publish_event(log_event)

            lines_since_check += 1
            elapsed = time.monotonic() - last_check_time
            if (
                lines_since_check >= self.log_lines_per_check
                or elapsed >= self.log_check_interval_seconds
            ):
                await self._check_for_anomalies(container, service_name)
                lines_since_check = 0
                last_check_time = time.monotonic()

    async def _check_for_anomalies(
        self, container: docker.models.containers.Container, service_name: str
    ) -> None:
        """Check container logs for anomalies using AI analysis."""
        container_name = container.name or container.short_id
        recent_logs = list(self.log_buffers[container_name])[-_RECENT_LOGS_COUNT:]
        log_chunk = "\n".join(item.line for item in recent_logs)
        if not log_chunk.strip():
            return

        context: dict[str, object] = {}
        try:
            container.reload()
            container_info = container.attrs
            state_info = dict(container_info.get("State", {}))
            health_info = dict(state_info.get("Health", {}))
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

    async def _handle_incident(
        self,
        container: docker.models.containers.Container,
        service_name: str,
        anomaly: AnomalyDetectionResult,
    ) -> None:
        """Handle a detected anomaly by creating and managing an incident."""
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

        incident_event = IncidentEvent(incident=incident_record)
        await self._publish_event(incident_event)

        console.print("[bold cyan]📊 Step 1: Gathering system context...[/bold cyan]")

        container_name = container.name or container.short_id
        all_logs = "\n".join(log.line for log in self.log_buffers[container_name])

        docker_compose = self._read_docker_compose()

        try:
            container_info = container.attrs
        except Exception:
            container_info = {}

        environment_vars: dict[str, str] = {}
        config_info = dict(container_info.get("Config", {}))
        env_list_raw = config_info.get("Env", [])
        if isinstance(env_list_raw, list):
            for env_item in env_list_raw:
                if isinstance(env_item, str):
                    key, _, value = env_item.partition("=")
                    environment_vars[key] = value

        state_data = dict(container_info.get("State", {}))
        exit_code_val = state_data.get("ExitCode")
        container_stats = ContainerStats(
            status=container.status or "unknown",
            restarts=_to_int(container_info.get("RestartCount", 0)),
            created=str(container_info.get("Created", "")),
            exit_code=_to_int(exit_code_val),
        )

        console.print(
            f"[green]✓ Context gathered: {len(all_logs)} chars, {len(environment_vars)} env vars[/green]\n"
        )

        console.print(
            "[bold cyan]📊 Step 2: Performing root cause analysis with Llama 4 Scout...[/bold cyan]"
        )

        available_tools = await self.mcp.get_tools_for_ai()

        try:
            analysis = self.llama.analyze_root_cause(
                anomaly_summary=anomaly.summary,
                full_logs=all_logs,
                docker_compose=docker_compose,
                environment_vars=environment_vars,
                container_stats=container_stats.model_dump(),
                available_tools=available_tools,
                container_name=container.name,  # Pass actual container name
            )
        except Exception as exc:
            console.print(f"[red]Error in root cause analysis: {exc}[/red]")
            incident_record.analysis = None
            incident_record.status = IncidentStatus.UNRESOLVED
            incident_record.resolution_notes = f"Root cause analysis failed: {exc}"
            self.incidents.append(incident_record)

            incident_event = IncidentEvent(incident=incident_record)
            await self._publish_event(incident_event)

            return
        incident_record.analysis = analysis

        update_event = IncidentUpdateEvent(incident=incident_record)
        await self._publish_event(update_event)

        console.print(
            f"\n[green]✓ Root cause identified with {analysis.confidence:.0%} confidence[/green]\n"
        )

        console.print(
            Panel(
                f"[bold]Root Cause:[/bold]\n{analysis.root_cause}\n\n"
                f"[bold]Affected Components:[/bold]\n"
                + "\n".join(
                    f"  • {component}" for component in analysis.affected_components
                ),
                title="🧠 AI Analysis",
                border_style="cyan",
            )
        )

        console.print(
            "\n[bold cyan]📊 Step 3: Executing fixes via Docker MCP Gateway...[/bold cyan]"
        )

        if not self.mcp._session:
            await self.mcp.initialize()

        gateway_healthy = await self.mcp.verify_gateway_health()
        if not gateway_healthy:
            console.print(
                "[red]✗ MCP Gateway is not healthy. Skipping fix execution.[/red]"
            )
            incident_record.status = IncidentStatus.UNRESOLVED
            incident_record.resolution_notes = "MCP Gateway health check failed"
            return

        fix_results: list[FixExecutionResult] = []
        for fix in analysis.suggested_fixes:
            console.print(
                f"\n[yellow]→ Applying fix (priority {fix.priority})...[/yellow]"
            )
            result = await self.mcp.execute_fix(fix)
            fix_results.append(result)

            if result.success:
                console.print(
                    f"[green]✓ {result.message or 'Fix applied successfully'}[/green]"
                )
            else:
                failure_reason = result.error or result.message or "Unknown error"
                console.print(f"[red]✗ Fix failed: {failure_reason}[/red]")

        incident_record.fixes = tuple(fix_results)

        update_event = IncidentUpdateEvent(incident=incident_record)
        await self._publish_event(update_event)

        console.print("\n[bold cyan]📊 Step 4: Verifying system health...[/bold cyan]")

        is_healthy = await self.mcp.verify_health(
            container.name, max_wait=_MAX_HEALTH_WAIT_SECONDS
        )

        # Additional check: verify that all critical fixes succeeded
        all_critical_fixes_succeeded = True
        for fix in fix_results:
            if fix.priority <= 2 and not fix.success:  # Priority 1 and 2 are critical
                all_critical_fixes_succeeded = False
                console.print(
                    f"[red]✗ Critical fix failed: {fix.action} - {fix.error or fix.message}[/red]"
                )

        # Check if container is actually running (not just restarting)
        container.reload()
        is_actually_running = container.status == "running"

        if is_healthy and all_critical_fixes_succeeded and is_actually_running:
            console.print(f"\n[bold green]{'='*60}[/bold green]")
            console.print(
                f"[bold green]✅ INCIDENT RESOLVED: {incident_id}[/bold green]"
            )
            console.print(f"[bold green]{'='*60}[/bold green]\n")
            incident_record.status = IncidentStatus.RESOLVED
            incident_record.resolved_at = _utcnow()
        else:
            console.print(f"\n[bold red]{'='*60}[/bold red]")
            console.print(f"[bold red]⚠️  INCIDENT UNRESOLVED: {incident_id}[/bold red]")
            if not all_critical_fixes_succeeded:
                console.print("[bold red]Some critical fixes failed[/bold red]")
            if not is_actually_running:
                console.print(
                    f"[bold red]Container status: {container.status}[/bold red]"
                )
            if not is_healthy:
                console.print("[bold red]Health check failed[/bold red]")
            console.print("[bold red]Manual intervention required[/bold red]")
            console.print(f"[bold red]{'='*60}[/bold red]\n")
            incident_record.status = IncidentStatus.UNRESOLVED

        update_event = IncidentUpdateEvent(incident=incident_record)
        await self._publish_event(update_event)

        console.print(
            "\n[bold cyan]📊 Step 5: Generating explanation for stakeholders...[/bold cyan]"
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

        update_event = IncidentUpdateEvent(incident=incident_record)
        await self._publish_event(update_event)

    def _read_docker_compose(self) -> str | None:
        """Read Docker compose configuration from file."""
        if self._compose_cache is not None:
            return self._compose_cache
        try:
            self._compose_cache = self._compose_path.read_text()
        except FileNotFoundError:
            self._compose_cache = None
        return self._compose_cache


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

    from api.websocket_server import build_application

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
