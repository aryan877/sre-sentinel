#!/usr/bin/env python3
"""
SRE Sentinel monitoring agent with real-time streaming and Pydantic models.

This module is the core of the SRE Sentinel system, responsible for:
1. Monitoring Docker containers for anomalies
2. Detecting issues using AI-powered analysis
3. Performing root cause analysis
4. Executing automated fixes
5. Providing real-time telemetry

The monitoring agent runs continuously, collecting logs, metrics,
and events from monitored containers, analyzing them for issues,
and taking automated remediation actions when problems are detected.

Architecture:
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Containers    │───▶│   Monitor       │───▶│   Event Bus     │
│                 │    │                 │    │                 │
│ - Logs          │    │ - Collect       │    │ - Publish       │
│ - Metrics       │    │ - Analyze       │    │ - Persist       │
│ - Events        │    │ - Remediate     │    │ - Distribute    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │   AI Services   │
                        │                 │
                        │ - Cerebras      │
                        │ - Llama         │
└─────────────────┘    └─────────────────┘
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
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel

from cerebras_client import CerebrasAnomalyDetector
from redis_event_bus import RedisEventBus, create_redis_event_bus
from llama_analyzer import LlamaRootCauseAnalyzer
from mcp_orchestrator import MCPOrchestrator
from sentinel_types import (
    AnomalyDetectionResult,
    AnomalySeverity,
    ContainerState,
    FixExecutionResult,
    Incident,
    IncidentStatus,
)

console = Console()


# Pydantic models for structured data
class LogEntry(BaseModel):
    """
    Structured log entry with timestamp and content.

    Represents a single log line with its timestamp for
    time-series analysis and anomaly detection.
    """

    timestamp: str = Field(description="Timestamp when the log was generated")
    line: str = Field(description="Content of the log line")


class ContainerContext(BaseModel):
    """
    Container context information for anomaly detection.

    Captures the state and context of a container at the time
    of anomaly detection, providing additional information
    for the AI analysis.
    """

    status: str | None = Field(default=None, description="Current container status")
    health: str | None = Field(default=None, description="Container health status")
    restarts: int | None = Field(
        default=None, description="Number of container restarts"
    )
    exit_code: int | None = Field(default=None, description="Container exit code")


class ContainerStats(BaseModel):
    """
    Container statistics and state information.

    Captures detailed statistics about a container's state,
    including resource usage and operational status.
    """

    status: str | None = Field(default=None, description="Current container status")
    restarts: int | None = Field(
        default=None, description="Number of container restarts"
    )
    created: str | None = Field(
        default=None, description="Container creation timestamp"
    )
    exit_code: int | None = Field(default=None, description="Container exit code")


class Event(BaseModel):
    """
    Base event structure for all system events.

    Serves as the base class for all event types published
    through the event bus, providing a common structure.
    """

    type: str = Field(description="Type of the event")


class ContainerUpdateEvent(BaseModel):
    """
    Container state update event.

    Published when a container's state changes, including
    resource usage, status, and other metrics.
    """

    type: str = Field(default="container_update", description="Event type identifier")
    container: ContainerState = Field(description="Updated container state")


class LogEvent(BaseModel):
    """
    Log line event for real-time log streaming.

    Published for each log line from monitored containers,
    enabling real-time log streaming and analysis.
    """

    type: str = Field(default="log", description="Event type identifier")
    container: str = Field(description="Name of the container the log came from")
    timestamp: str = Field(description="Timestamp when the log was generated")
    message: str = Field(description="Content of the log line")


class IncidentEvent(BaseModel):
    """
    Incident creation event.

    Published when a new incident is created, providing
    initial incident information to subscribers.
    """

    type: str = Field(default="incident", description="Event type identifier")
    incident: Incident = Field(description="Incident details")


class IncidentUpdateEvent(BaseModel):
    """
    Incident update event.

    Published when an incident is updated, including
    status changes, analysis results, and fix outcomes.
    """

    type: str = Field(default="incident_update", description="Event type identifier")
    incident: Incident = Field(description="Updated incident details")


# Constants for monitoring configuration
_MAX_LOG_BUFFER_SIZE: int = 2000  # Maximum number of log lines to keep in memory
_LOG_LINES_PER_CHECK_DEFAULT: int = 20  # Default number of lines to analyze at once
_LOG_CHECK_INTERVAL_DEFAULT: float = (
    5.0  # Default interval between log checks (seconds)
)
_STATS_INTERVAL_SECONDS: int = 5  # Interval between stats collection (seconds)
_MAX_HEALTH_WAIT_SECONDS: int = (
    30  # Maximum time to wait for health verification (seconds)
)
_RECENT_LOGS_COUNT: int = 200  # Number of recent logs to include in analysis


# Utility functions
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
    """
    Serialize a value to JSON-compatible format.

    Recursively converts Pydantic models and other objects
    to JSON-compatible dictionaries for serialization.

    Args:
        value: Value to serialize

    Returns:
        JSON-compatible representation of the value
    """
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, Mapping):
        return {key: _serialise_payload(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_serialise_payload(item) for item in value]
    return value


class SRESentinel:
    """
    Main monitoring and self-healing orchestrator with Pydantic models.

    This class is the core of the SRE Sentinel system, responsible for:
    1. Monitoring containers for logs and metrics
    2. Detecting anomalies using AI analysis
    3. Performing root cause analysis
    4. Executing automated fixes
    5. Managing the incident lifecycle

    The sentinel runs continuously, collecting data from monitored
    containers and taking automated actions when issues are detected.
    """

    def __init__(self, event_bus: RedisEventBus) -> None:
        """
        Initialize the SRE Sentinel with an event bus.

        Args:
            event_bus: Event bus for publishing and subscribing to events
        """
        # Core components
        self.event_bus = event_bus
        self.docker_client = docker.from_env()
        self.cerebras = CerebrasAnomalyDetector()
        self.llama = LlamaRootCauseAnalyzer()
        self.mcp = MCPOrchestrator()

        # Runtime state
        self._loop: asyncio.AbstractEventLoop | None = None
        self.log_buffers: dict[str, deque[LogEntry]] = defaultdict(
            lambda: deque(maxlen=_MAX_LOG_BUFFER_SIZE)
        )
        self.container_states: MutableMapping[str, ContainerState] = {}
        self.incidents: list[Incident] = []

        # Configuration
        self._compose_cache: str | None = None
        self._compose_path = (
            Path(__file__).resolve().parent.parent / "docker-compose.yml"
        )

        # Log analysis tuning (override via environment if needed)
        self.log_lines_per_check = int(
            os.getenv("LOG_LINES_PER_CHECK", str(_LOG_LINES_PER_CHECK_DEFAULT))
        )
        self.log_check_interval_seconds = float(
            os.getenv("LOG_CHECK_INTERVAL", str(_LOG_CHECK_INTERVAL_DEFAULT))
        )

    # ------------------------------------------------------------------
    # Public state accessors (used by API layer)
    # ------------------------------------------------------------------
    def snapshot_containers(self) -> list[dict[str, object]]:
        """
        Get current snapshot of all container states.

        Returns:
            List of container state dictionaries for API consumption
        """
        return [state.model_dump() for state in self.container_states.values()]

    def snapshot_incidents(self) -> list[dict[str, object]]:
        """
        Get current snapshot of all incidents.

        Returns:
            List of incident dictionaries for API consumption
        """
        return [incident.model_dump() for incident in self.incidents]

    # ------------------------------------------------------------------
    # Main monitoring loop
    # ------------------------------------------------------------------
    async def monitor_loop(self) -> None:
        """
        Main monitoring loop that runs continuously.

        This is the entry point for the monitoring system. It discovers
        monitored containers and starts monitoring tasks for each one.
        The loop runs until cancelled.
        """
        # Store the event loop for later use
        self._loop = asyncio.get_running_loop()

        console.print("\n[bold green]🛡️  SRE Sentinel Starting...[/bold green]\n")

        # Find containers to monitor
        containers = self._get_monitored_containers()
        if not containers:
            console.print(
                "[red]No containers found with label sre-sentinel.monitor=true[/red]"
            )
            console.print(
                "[yellow]Add labels to docker-compose.yml and restart containers.[/yellow]"
            )
            return

        # Display containers being monitored
        console.print(f"[green]Monitoring {len(containers)} containers:[/green]")
        for container in containers:
            service_name = self._service_name(container)
            console.print(f"  • {service_name} ({container.short_id})")
        console.print()

        # Start monitoring tasks for each container
        tasks = [
            asyncio.create_task(self._monitor_container(container))
            for container in containers
        ]

        try:
            # Run all monitoring tasks concurrently
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            # Handle cancellation gracefully
            for task in tasks:
                task.cancel()
            raise

    async def _publish_event(self, event: BaseModel) -> None:
        """
        Publish an event to the message bus with proper serialization.

        Args:
            event: Event to publish (must be a Pydantic model)
        """
        serialised = _serialise_payload(event)
        if isinstance(serialised, dict):
            await self.event_bus.publish(serialised)
        else:
            await self.event_bus.publish({"data": serialised})

    # ------------------------------------------------------------------
    # Container discovery and management
    # ------------------------------------------------------------------
    def _get_monitored_containers(self) -> list[docker.models.containers.Container]:
        """
        Get all containers that should be monitored.

        Returns:
            List of Docker containers with the monitoring label
        """
        try:
            containers_raw = self.docker_client.containers.list(
                filters={"label": "sre-sentinel.monitor=true"}
            )
            return list(containers_raw)
        except docker.errors.DockerException as exc:
            console.print(f"[red]Docker error while listing containers: {exc}[/red]")
            return []

    def _service_name(self, container: docker.models.containers.Container) -> str:
        """
        Get the service name for a container.

        Extracts the service name from container labels or falls back
        to the container name/ID.

        Args:
            container: Docker container to get the service name for

        Returns:
            Service name for the container
        """
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
        """
        Monitor a single container for logs and metrics.

        This method monitors a container by:
        1. Publishing initial container state
        2. Streaming logs in real-time
        3. Collecting container metrics

        Args:
            container: Docker container to monitor
        """
        service_name = self._service_name(container)
        container_id = container.id

        # Publish initial container state
        await self._publish_container_state(container, service_name)

        # Start log streaming and metrics collection
        log_task = asyncio.create_task(
            self._stream_container_logs(container, service_name)
        )
        stats_task = asyncio.create_task(
            self._track_container_stats(container, service_name)
        )

        try:
            # Run both monitoring tasks concurrently
            await asyncio.gather(log_task, stats_task)
        finally:
            # Clean up tasks when monitoring ends
            if not log_task.done():
                log_task.cancel()
            if not stats_task.done():
                stats_task.cancel()
            if container_id:
                self.container_states.pop(container_id, None)

    # ------------------------------------------------------------------
    # Container metrics collection
    # ------------------------------------------------------------------
    async def _track_container_stats(
        self, container: docker.models.containers.Container, service_name: str
    ) -> None:
        """
        Periodically collect and publish container metrics.

        This method runs continuously, collecting container statistics
        at regular intervals and publishing them as events.

        Args:
            container: Docker container to collect stats for
            service_name: Service name for the container
        """
        container_id = container.id

        while True:
            try:
                # Get container statistics
                stats_raw = await asyncio.to_thread(container.stats, stream=False)
                stats = dict(stats_raw)
                metrics = self._parse_stats(stats)

                # Refresh container information
                container.reload()
                status = container.status or "unknown"
                restart_count = _to_int(container.attrs.get("RestartCount", 0))
            except docker.errors.NotFound:
                # Handle container disappearance
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
                    timestamp=_utcnow(),
                )
                if container_id:
                    self.container_states[container_id] = offline_state
                await self._publish_event(ContainerUpdateEvent(container=offline_state))
                break
            except docker.errors.DockerException as exc:
                # Handle Docker errors
                console.print(
                    f"[red]Error fetching stats for {service_name}: {exc}[/red]"
                )
                status = "unknown"
                restart_count = None
                metrics = {"cpu_percent": 0.0, "memory_percent": 0.0}

            # Create and publish container state
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
            await self._publish_event(ContainerUpdateEvent(container=container_state))

            # Wait before the next stats collection
            await asyncio.sleep(5)

    async def _publish_container_state(
        self, container: docker.models.containers.Container, service_name: str
    ) -> None:
        """
        Publish the current state of a container.

        Args:
            container: Docker container to publish state for
            service_name: Service name for the container
        """
        try:
            container.reload()
        except docker.errors.DockerException as exc:
            console.print(
                f"[red]Unable to refresh container {service_name}: {exc}[/red]"
            )

        # Extract container information
        status = container.status or "unknown"
        restarts = (
            _to_int(container.attrs.get("RestartCount", 0))
            if hasattr(container, "attrs")
            else None
        )
        container_id = container.id

        # Create and publish container state
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
        await self._publish_event(ContainerUpdateEvent(container=container_state))

    def _parse_stats(self, stats: dict[str, object]) -> dict[str, float]:
        """
        Parse container statistics from Docker API response.

        Extracts CPU and memory usage percentages from the raw
        Docker statistics API response.

        Args:
            stats: Raw statistics response from Docker API

        Returns:
            Dictionary with CPU and memory usage percentages
        """
        cpu_percent = 0.0
        memory_percent = 0.0

        # Parse CPU statistics
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

        # Parse memory statistics
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

        return {"cpu_percent": cpu_percent, "memory_percent": memory_percent}

    # ------------------------------------------------------------------
    # Container log streaming
    # ------------------------------------------------------------------
    async def _stream_container_logs(
        self, container: docker.models.containers.Container, service_name: str
    ) -> None:
        """
        Stream logs from a container in real-time.

        This method streams logs from a container, storing them in
        memory buffers and publishing them as events. It also
        periodically analyzes logs for anomalies.

        Args:
            container: Docker container to stream logs from
            service_name: Service name for the container
        """
        container_name = container.name or container.short_id
        queue: "asyncio.Queue[str | None]" = asyncio.Queue()

        if self._loop is None:
            raise RuntimeError("Event loop not initialised")

        loop = self._loop

        def _pump_logs() -> None:
            """
            Thread function to pump logs from Docker to the queue.

            Runs in a separate thread to avoid blocking the event loop
            while waiting for log data from Docker.
            """
            try:
                for raw in container.logs(stream=True, follow=True):
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    loop.call_soon_threadsafe(queue.put_nowait, line)
            except Exception as exc:  # pragma: no cover - best effort logging
                console.print(f"[red]Log stream for {service_name} ended: {exc}[/red]")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        # Start the log pumping thread
        threading.Thread(target=_pump_logs, daemon=True).start()
        console.print(f"[cyan]📡 Streaming logs from {service_name}...[/cyan]")

        # Process log lines from the queue
        lines_since_check = 0
        last_check_time = time.monotonic()

        while True:
            line = await queue.get()
            if line is None:
                break

            # Create and store log entry
            timestamp = _utcnow()
            log_entry = LogEntry(timestamp=timestamp, line=line)
            self.log_buffers[container_name].append(log_entry)

            # Publish log event
            log_event = LogEvent(
                container=service_name,
                timestamp=timestamp,
                message=line,
            )
            await self._publish_event(log_event)

            # Check for anomalies periodically
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
        """
        Check container logs for anomalies using AI analysis.

        This method collects recent logs and container context,
        sends them to the AI anomaly detection service, and
        processes any detected anomalies.

        Args:
            container: Docker container to check for anomalies
            service_name: Service name for the container
        """
        container_name = container.name or container.short_id
        recent_logs = list(self.log_buffers[container_name])[-200:]
        log_chunk = "\n".join(item.line for item in recent_logs)
        if not log_chunk.strip():
            return

        # Collect container context for analysis
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

        # Perform anomaly detection
        anomaly = self.cerebras.detect_anomaly(
            log_chunk=log_chunk, service_name=service_name, context=context
        )

        # Handle detected anomalies
        if anomaly.is_anomaly and anomaly.severity in {
            AnomalySeverity.HIGH,
            AnomalySeverity.CRITICAL,
        }:
            console.print(
                f"\n[red bold]🚨 CRITICAL ANOMALY DETECTED IN {service_name}[/red bold]"
            )
            await self._handle_incident(container, service_name, anomaly)

    # ------------------------------------------------------------------
    # Incident handling
    # ------------------------------------------------------------------
    async def _handle_incident(
        self,
        container: docker.models.containers.Container,
        service_name: str,
        anomaly: AnomalyDetectionResult,
    ) -> None:
        """
        Handle a detected anomaly by creating and managing an incident.

        This method manages the complete incident lifecycle:
        1. Creates an incident record
        2. Collects system context
        3. Performs root cause analysis
        4. Executes recommended fixes
        5. Verifies system health
        6. Generates human-friendly explanations

        Args:
            container: Docker container where the anomaly was detected
            service_name: Service name for the container
            anomaly: Anomaly detection results
        """
        # Generate unique incident ID
        incident_id = f"INC-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        # Display incident information
        console.print(f"\n[bold yellow]{'='*60}[/bold yellow]")
        console.print(f"[bold]🚨 INCIDENT: {incident_id}[/bold]")
        console.print(f"[bold yellow]{'='*60}[/bold yellow]\n")

        # Create incident record
        incident_record = Incident(
            id=incident_id,
            service=service_name,
            detected_at=_utcnow(),
            anomaly=anomaly,
            status=IncidentStatus.ANALYZING,
        )
        self.incidents.append(incident_record)

        # Publish incident creation event
        incident_event = IncidentEvent(incident=incident_record)
        await self._publish_event(incident_event)

        # Step 1: Gather system context
        console.print("[bold cyan]📊 Step 1: Gathering system context...[/bold cyan]")

        container_name = container.name or container.short_id
        all_logs = "\n".join(log.line for log in self.log_buffers[container_name])

        # Get Docker compose configuration
        docker_compose = self._read_docker_compose()

        # Collect container information
        try:
            container_info = container.attrs
        except Exception:
            container_info = {}

        # Collect environment variables
        environment_vars: dict[str, str] = {}
        config_info = dict(container_info.get("Config", {}))
        env_list_raw = config_info.get("Env", [])
        if isinstance(env_list_raw, list):
            for env_item in env_list_raw:
                if isinstance(env_item, str):
                    key, _, value = env_item.partition("=")
                    environment_vars[key] = value

        # Collect container statistics
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

        # Step 2: Perform root cause analysis
        console.print(
            "[bold cyan]📊 Step 2: Performing root cause analysis with Llama 4 Scout...[/bold cyan]"
        )

        # Get available tools from MCP Gateway
        available_tools = await self.mcp.get_tools_for_ai()

        try:
            analysis = self.llama.analyze_root_cause(
                anomaly_summary=anomaly.summary,
                full_logs=all_logs,
                docker_compose=docker_compose,
                environment_vars=environment_vars,
                container_stats=container_stats.model_dump(),
                available_tools=available_tools,
            )
        except Exception as exc:
            console.print(f"[red]Error in root cause analysis: {exc}[/red]")
            # Create a basic incident record with the error
            incident_record.analysis = None
            incident_record.status = IncidentStatus.UNRESOLVED
            incident_record.resolution_notes = f"Root cause analysis failed: {exc}"
            self.incidents.append(incident_record)

            # Publish incident creation event
            incident_event = IncidentEvent(incident=incident_record)
            await self._publish_event(incident_event)

            return  # Exit early if analysis failed
        incident_record.analysis = analysis

        # Publish analysis completion event
        update_event = IncidentUpdateEvent(incident=incident_record)
        await self._publish_event(update_event)

        console.print(
            f"\n[green]✓ Root cause identified with {analysis.confidence:.0%} confidence[/green]\n"
        )

        # Display analysis results
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

        # Step 3: Execute recommended fixes
        console.print(
            "\n[bold cyan]📊 Step 3: Executing fixes via Docker MCP Gateway...[/bold cyan]"
        )

        # Initialize MCP connections if not already done
        if not self.mcp._session:
            await self.mcp.initialize()

        # Verify MCP Gateway health before executing fixes
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

        # Publish fix execution event
        update_event = IncidentUpdateEvent(incident=incident_record)
        await self._publish_event(update_event)

        # Step 4: Verify system health
        console.print("\n[bold cyan]📊 Step 4: Verifying system health...[/bold cyan]")

        is_healthy = await self.mcp.verify_health(
            container_name, max_wait=_MAX_HEALTH_WAIT_SECONDS
        )

        if is_healthy:
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
            console.print("[bold red]Manual intervention required[/bold red]")
            console.print(f"[bold red]{'='*60}[/bold red]\n")
            incident_record.status = IncidentStatus.UNRESOLVED

        # Publish resolution status event
        update_event = IncidentUpdateEvent(incident=incident_record)
        await self._publish_event(update_event)

        # Step 5: Generate human-friendly explanation
        console.print(
            "\n[bold cyan]📊 Step 5: Generating explanation for stakeholders...[/bold cyan]"
        )
        explanation = self.llama.explain_for_humans(analysis)
        incident_record.explanation = explanation

        # Display explanation
        console.print(
            Panel(
                explanation,
                title="📢 Human-Friendly Explanation",
                border_style="green",
            )
        )

        # Publish explanation event
        update_event = IncidentUpdateEvent(incident=incident_record)
        await self._publish_event(update_event)

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------
    def _read_docker_compose(self) -> str | None:
        """
        Read Docker compose configuration from file.

        Returns:
            Docker compose configuration as string, or None if not found
        """
        if self._compose_cache is not None:
            return self._compose_cache
        try:
            self._compose_cache = self._compose_path.read_text()
        except FileNotFoundError:
            self._compose_cache = None
        return self._compose_cache


async def main() -> None:
    """
    Main entry point for the SRE Sentinel monitoring agent.

    This function initializes all components and starts the monitoring
    system. It also sets up the API server for external access.
    """
    # Load environment variables
    load_dotenv()

    # Display startup banner
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

    # Initialize Redis event bus
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

    # Initialize API server
    from websocket_server import build_application

    app = build_application(sentinel, event_bus)

    import uvicorn

    api_port = int(os.getenv("API_PORT", "8000"))
    api_host = os.getenv("API_HOST", "0.0.0.0")

    config = uvicorn.Config(app, host=api_host, port=api_port, log_level="info")
    server = uvicorn.Server(config)

    # Start monitoring and API tasks
    monitor_task = asyncio.create_task(sentinel.monitor_loop())
    api_task = asyncio.create_task(server.serve())

    try:
        # Run until either task fails
        await asyncio.wait(
            {monitor_task, api_task}, return_when=asyncio.FIRST_EXCEPTION
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down gracefully...[/yellow]")
    finally:
        # Clean up tasks
        if not monitor_task.done():
            monitor_task.cancel()
        server.should_exit = True
        await api_task
        # Disconnect Redis
        await event_bus.disconnect()


if __name__ == "__main__":
    # Run the main monitoring loop
    asyncio.run(main())
