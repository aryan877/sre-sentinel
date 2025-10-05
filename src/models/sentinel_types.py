"""
Shared Pydantic models and type definitions for SRE Sentinel.

VISUALIZATION & USAGE GUIDE:

This file contains all the data models that flow through the SRE Sentinel system.
Here's how they work together in practice:

1. ANOMALY DETECTION FLOW:
   Container logs → Cerebras AI → AnomalyDetectionResult → Incident creation

2. ROOT CAUSE ANALYSIS FLOW:
   Incident context → Llama AI → RootCauseAnalysis → FixAction[] → MCP execution

3. REAL-TIME EVENT FLOW:
   ContainerState/LogEvent → Redis EventBus → WebSocket → Dashboard

TYPE VISUALIZATIONS:

🔍 AnomalyDetectionResult (from Cerebras):
{
    "is_anomaly": true,
    "confidence": 0.85,
    "anomaly_type": "error",
    "severity": "high",
    "summary": "Database connection failures detected in API service"
}

🧠 RootCauseAnalysis (from Llama):
{
    "root_cause": "PostgreSQL container is not responding to connection attempts",
    "explanation": "The API service is unable to establish connections to PostgreSQL...",
    "affected_components": ["api", "postgres"],
    "suggested_fixes": [
        {
            "action": "restart_container",
            "target": "postgres",
            "details": "{\"container_name\": \"postgres\", \"reason\": \"Database not responding\"}",
            "priority": 4
        }
    ],
    "confidence": 0.92,
    "prevention": "Configure proper health checks and connection pooling"
}

🔧 FixAction (MCP Gateway Integration):
This is the key type that bridges AI analysis with actual container operations.
Each FixAction represents an MCP tool call:

{
    "action": "restart_container",        # MCP tool name from catalog.yaml
    "target": "postgres",                 # Container/service to operate on
    "details": "{\"container_name\": \"postgres\", \"reason\": \"Database not responding\"}",  # JSON parameters for MCP tool
    "priority": 4                         # 1-5 priority (5=highest)
}

MCP TOOL EXAMPLES:
- restart_container: {"container_name": "service-name", "reason": "description"}
- update_env_vars: {"container_name": "service-name", "env_updates": {"KEY": "value"}}
- exec_command: {"container_name": "service-name", "command": ["sh", "-c", "command"], "timeout": 30}
- update_resources: {"container_name": "service-name", "resources": {"memory": "512m", "cpu": "0.5"}}

📊 ContainerState (Real-time monitoring):
{
    "id": "abc123",
    "name": "demo-api",
    "service": "api",
    "status": "running",
    "restarts": 0,
    "cpu": 15.2,
    "memory": 45.8,
    "network_rx": 1024.5,
    "network_tx": 2048.1,
    "disk_read": 0.0,
    "disk_write": 512.3,
    "timestamp": "2025-01-01T12:00:00Z"
}

🚨 Incident (Complete incident lifecycle):
{
    "id": "INC-20250101-120000",
    "service": "api",
    "detected_at": "2025-01-01T12:00:00Z",
    "anomaly": { ... AnomalyDetectionResult ... },
    "status": "resolved",
    "analysis": { ... RootCauseAnalysis ... },
    "fixes": [ ... FixExecutionResult ... ],
    "resolved_at": "2025-01-01T12:05:00Z",
    "explanation": "The PostgreSQL container was restarted successfully...",
    "resolution_notes": "Service recovered within 5 minutes"
}

USAGE LOCATIONS:
- Core monitoring: monitor.py uses ContainerState, Incident, AnomalyDetectionResult
- AI analysis: llama_analyzer.py uses RootCauseAnalysis, FixAction
- MCP integration: orchestrator.py consumes FixAction and produces FixExecutionResult
- API layer: websocket_server.py serializes all types for dashboard
- Event bus: redis_event_bus.py transmits event types (ContainerUpdateEvent, LogEvent, etc.)

Each type is designed to be JSON-serializable for Redis pub/sub and WebSocket transmission.
"""

from __future__ import annotations

import os
from enum import Enum

from pydantic import BaseModel, Field, field_validator


__all__ = [
    # Base Classes
    "BaseModel",
    # Enums
    "AnomalyType",
    "AnomalySeverity",
    "FixActionName",
    "IncidentStatus",
    # Settings/Configuration
    "CerebrasSettings",
    "LlamaSettings",
    "MCPSettings",
    "RedisSettings",
    # Messages
    "CompletionMessage",
    "AnalysisMessage",
    "RedisMessage",
    # Internal Payloads
    "AnomalyPayload",
    "RootCausePayload",
    # Domain Models
    "AnomalyDetectionResult",
    "FixAction",
    "FixExecutionResult",
    "RootCauseAnalysis",
    "ContainerState",
    "Incident",
    # Events
    "ContainerUpdateEvent",
    "LogEvent",
    "IncidentEvent",
    "IncidentUpdateEvent",
    "BootstrapEvent",
    # Utility Models
    "LogEntry",
    "ContainerStats",
    "HealthResponse",
]


class AnomalyType(str, Enum):
    """Types of anomalies that can be detected in container logs."""

    CRASH = "crash"
    ERROR = "error"
    WARNING = "warning"
    PERFORMANCE = "performance"
    NONE = "none"


class AnomalySeverity(str, Enum):
    """Severity levels for detected anomalies."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FixActionName(str):
    """Dynamic action name for automated fixes that can be applied to containers."""

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not isinstance(v, str):
            raise TypeError("FixActionName must be a string")
        return v


class IncidentStatus(str, Enum):
    """Status values for incident lifecycle tracking."""

    ANALYZING = "analyzing"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


# =============================================================================
# Configuration / Settings Models
# =============================================================================


class CerebrasSettings(BaseModel):
    """Configuration settings for Cerebras API access via OpenRouter."""

    api_key: str = Field(description="OpenRouter API key")
    base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description="Base URL for the API (OpenRouter)",
    )
    model: str = Field(
        default="meta-llama/llama-3.1-8b-instruct",
        description="Model name to use for analysis (small, fast model for anomaly detection)",
    )

    @classmethod
    def from_env(cls) -> "CerebrasSettings":
        """Create settings from environment variables."""
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment")
        return cls(
            api_key=api_key,
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            model=os.getenv("CEREBRAS_MODEL", "meta-llama/llama-3.1-8b-instruct"),
        )


class LlamaSettings(BaseModel):
    """Configuration settings for Llama API access via OpenRouter."""

    api_key: str = Field(description="OpenRouter API key")
    base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description="Base URL for the API (OpenRouter)",
    )
    model: str = Field(
        default="meta-llama/llama-4-scout",
        description="Model name to use for analysis (large context model - 10M tokens)",
    )

    @classmethod
    def from_env(cls) -> "LlamaSettings":
        """Create settings from environment variables."""
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment")
        return cls(
            api_key=api_key,
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            model=os.getenv("LLAMA_MODEL", "meta-llama/llama-4-scout"),
        )


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


class RedisSettings(BaseModel):
    """Configuration settings for Redis connection."""

    host: str = Field(default="localhost", description="Redis server host")
    port: int = Field(default=6379, ge=1, le=65535, description="Redis server port")
    db: int = Field(default=0, ge=0, description="Redis database number")
    password: str | None = Field(
        default=None, description="Password for Redis authentication"
    )
    max_connections: int = Field(
        default=10, ge=1, le=100, description="Maximum connections in pool"
    )

    @classmethod
    def from_env(cls) -> "RedisSettings":
        """Create settings from environment variables."""
        return cls(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD"),
            max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", "10")),
        )


# =============================================================================
# Message Models
# =============================================================================


class CompletionMessage(BaseModel):
    """Chat message structure for Cerebras API."""

    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class AnalysisMessage(BaseModel):
    """Chat message structure for Llama API."""

    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class RedisMessage(BaseModel):
    """Redis pub/sub message structure."""

    type: str = Field(description="Message type from Redis pub/sub")
    pattern: bytes | None = Field(
        default=None, description="Pattern for pmessage subscriptions"
    )
    channel: bytes = Field(description="Channel the message was received on")
    data: bytes = Field(description="Raw message data as bytes")


# =============================================================================
# Internal Payload Models (used for API parsing)
# =============================================================================


class AnomalyPayload(BaseModel):
    """Expected anomaly detection response from Cerebras."""

    is_anomaly: bool
    confidence: float = Field(ge=0.0, le=1.0)
    anomaly_type: str = Field(pattern="^(crash|error|warning|performance|none)$")
    severity: str = Field(pattern="^(low|medium|high|critical)$")
    summary: str

    @field_validator("anomaly_type", "severity")
    @classmethod
    def normalize_fields(cls, v: str) -> str:
        """Normalize fields to lowercase."""
        return v.lower()


class RootCausePayload(BaseModel):
    """Expected root cause analysis structure from Llama response."""

    root_cause: str
    explanation: str
    affected_components: list[str]
    suggested_fixes: list[FixAction]
    confidence: float = Field(ge=0.0, le=1.0)
    prevention: str


# =============================================================================
# Domain Models
# =============================================================================


class AnomalyDetectionResult(BaseModel):
    """
    Result of anomaly detection analysis from Cerebras AI model.

    This is the OUTPUT of Cerebras fast anomaly detection and the TRIGGER
    for incident creation when severity is HIGH or CRITICAL.

    EXAMPLE USAGE:
    {
        "is_anomaly": true,
        "confidence": 0.85,
        "anomaly_type": "error",
        "severity": "high",
        "summary": "Database connection failures detected in API service logs"
    }

    FLOW:
    1. monitor.py streams container logs to Cerebras
    2. Cerebras analyzes logs and returns AnomalyDetectionResult
    3. If is_anomaly=true and severity=HIGH/CRITICAL → create incident
    4. Incident triggers Llama root cause analysis
    5. Results flow to dashboard via WebSocket

    THRESHOLDS:
    - LOW/MEDIUM severity → logged only, no incident
    - HIGH/CRITICAL severity → incident created + root cause analysis
    """

    is_anomaly: bool = Field(description="Whether an anomaly was detected")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0"
    )
    anomaly_type: AnomalyType = Field(description="Type of anomaly detected")
    severity: AnomalySeverity = Field(description="Severity level of the anomaly")
    summary: str = Field(description="Human-readable summary of the detected anomaly")


class FixAction(BaseModel):
    """A specific fix action recommended by the AI analysis."""

    action: FixActionName
    target: str = Field(description="Container name or other target for the fix")
    details: str = Field(description="Specific details about how to apply the fix")
    priority: int = Field(
        ge=1, le=5, description="Priority from 1 (lowest) to 5 (highest)"
    )

    @field_validator("priority", mode="before")
    @classmethod
    def validate_priority_not_bool(cls, v) -> int:
        """Guard against JSON "true"/"false" being passed as priority."""
        if isinstance(v, bool):
            raise ValueError("priority cannot be boolean")
        return v


class FixExecutionResult(BaseModel):
    """Result of executing a fix action through the MCP orchestrator."""

    success: bool = Field(description="Whether the fix was successfully applied")
    message: str | None = Field(
        default=None, description="Success message from the fix execution"
    )
    error: str | None = Field(
        default=None, description="Error message if the fix failed"
    )
    status: str | None = Field(
        default=None, description="Status code from the fix execution"
    )
    details: str | None = Field(
        default=None, description="Additional details about the execution"
    )


class RootCauseAnalysis(BaseModel):
    """Comprehensive root cause analysis from Llama AI model."""

    root_cause: str = Field(description="Primary cause of the incident")
    explanation: str = Field(
        description="Detailed explanation of the root cause analysis"
    )
    affected_components: tuple[str, ...] = Field(
        description="List of components affected by the incident"
    )
    suggested_fixes: tuple[FixAction, ...] = Field(
        description="Recommended fixes to resolve the incident"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0"
    )
    prevention: str = Field(
        description="Recommendations for preventing similar incidents in the future"
    )


class ContainerState(BaseModel):
    """
    Current state snapshot of a monitored container.

    This is the REAL-TIME monitoring data that flows through the system.
    ContainerState objects are created every 5 seconds and broadcast via WebSocket.

    EXAMPLE USAGE:
    {
        "id": "abc123def456",
        "name": "demo-api",
        "service": "api",
        "status": "running",
        "restarts": 0,
        "cpu": 15.2,
        "memory": 45.8,
        "network_rx": 1024.5,
        "network_tx": 2048.1,
        "disk_read": 0.0,
        "disk_write": 512.3,
        "timestamp": "2025-01-01T12:00:00Z"
    }

    FLOW:
    1. monitor.py collects stats from Docker API every 5 seconds
    2. Creates ContainerState object with current metrics
    3. Publishes as ContainerUpdateEvent via Redis
    4. WebSocket server broadcasts to dashboard
    5. Dashboard displays real-time graphs and status

    METRICS:
    - CPU/Memory: Percentage usage (0-100)
    - Network: Bytes per second (calculated from Docker stats)
    - Disk: Bytes per second (calculated from Docker stats)
    - Status: Docker container status (running, stopped, etc.)
    """

    id: str | None = Field(default=None, description="Container ID from Docker")
    name: str | None = Field(default=None, description="Container name from Docker")
    service: str = Field(description="Service name from docker-compose label")
    status: str = Field(
        description="Current operational status (running, stopped, exited, etc.)"
    )
    restarts: int | None = Field(
        default=None, description="Number of times the container has restarted"
    )
    cpu: float = Field(ge=0.0, description="Current CPU usage percentage (0-100)")
    memory: float = Field(ge=0.0, description="Current memory usage percentage (0-100)")
    network_rx: float = Field(
        default=0.0, description="Network receive rate (bytes/sec, can be negative on counter reset)"
    )
    network_tx: float = Field(
        default=0.0, description="Network transmit rate (bytes/sec, can be negative on counter reset)"
    )
    disk_read: float = Field(
        default=0.0, description="Disk read rate (bytes/sec, can be negative on counter reset)"
    )
    disk_write: float = Field(
        default=0.0, description="Disk write rate (bytes/sec, can be negative on counter reset)"
    )
    timestamp: str = Field(description="ISO timestamp when this state was captured")


class Incident(BaseModel):
    """
    Complete incident record from detection to resolution.

    This is the CORE DATA STRUCTURE that tracks the entire lifecycle of an incident
    from initial anomaly detection through root cause analysis to fix execution.

    EXAMPLE USAGE:
    {
        "id": "INC-20250101-120000",
        "service": "api",
        "detected_at": "2025-01-01T12:00:00Z",
        "anomaly": {
            "is_anomaly": true,
            "confidence": 0.85,
            "anomaly_type": "error",
            "severity": "high",
            "summary": "Database connection failures detected"
        },
        "status": "resolved",
        "analysis": {
            "root_cause": "PostgreSQL container not responding",
            "explanation": "The API service cannot connect to database...",
            "affected_components": ["api", "postgres"],
            "suggested_fixes": [ ... FixAction objects ... ],
            "confidence": 0.92,
            "prevention": "Configure proper health checks"
        },
        "fixes": [
            {
                "success": true,
                "message": "Container restarted successfully",
                "details": "{\"restart_time\": \"2.3s\"}"
            }
        ],
        "resolved_at": "2025-01-01T12:05:00Z",
        "explanation": "The PostgreSQL container was restarted and service recovered",
        "resolution_notes": "Service recovered within 5 minutes"
    }

    LIFECYCLE:
    1. DETECTED: Created when AnomalyDetectionResult has HIGH/CRITICAL severity
    2. ANALYZING: Llama performs root cause analysis
    3. RESOLVED/UNRESOLVED: After fix execution attempts
    4. Archived for historical tracking and dashboard display
    """

    id: str = Field(
        description="Unique incident identifier (format: INC-YYYYMMDD-HHMMSS)"
    )
    service: str = Field(description="Service name where the incident occurred")
    detected_at: str = Field(
        description="ISO timestamp when the incident was first detected"
    )
    anomaly: AnomalyDetectionResult = Field(
        description="Anomaly that triggered this incident"
    )
    status: IncidentStatus = Field(description="Current status of the incident")
    analysis: RootCauseAnalysis | None = Field(
        default=None, description="Root cause analysis results"
    )
    fixes: tuple[FixExecutionResult, ...] = Field(
        default=(), description="Results of applied fixes"
    )
    resolved_at: str | None = Field(
        default=None, description="ISO timestamp when the incident was resolved"
    )
    explanation: str | None = Field(
        default=None, description="Human-friendly explanation of the incident"
    )
    resolution_notes: str | None = Field(
        default=None, description="Notes about the resolution or failure"
    )


# =============================================================================
# Event Models
# =============================================================================


class ContainerUpdateEvent(BaseModel):
    """Container state update event."""

    type: str = Field(default="container_update", description="Event type identifier")
    container: ContainerState = Field(description="Updated container state")


class LogEvent(BaseModel):
    """Log line event for real-time log streaming."""

    type: str = Field(default="log", description="Event type identifier")
    container: str = Field(description="Name of the container the log came from")
    timestamp: str = Field(description="Timestamp when the log was generated")
    message: str = Field(description="Content of the log line")


class IncidentEvent(BaseModel):
    """Incident creation event."""

    type: str = Field(default="incident", description="Event type identifier")
    incident: Incident = Field(description="Incident details")


class IncidentUpdateEvent(BaseModel):
    """Incident update event."""

    type: str = Field(default="incident_update", description="Event type identifier")
    incident: Incident = Field(description="Updated incident details")


class BootstrapEvent(BaseModel):
    """Bootstrap event for WebSocket clients."""

    type: str = Field(default="bootstrap", description="Event type identifier")
    containers: list[dict[str, object]] = Field(description="Current container states")
    incidents: list[dict[str, object]] = Field(description="Current incident states")


# =============================================================================
# Utility Models
# =============================================================================


class LogEntry(BaseModel):
    """Structured log entry with timestamp and content."""

    timestamp: str = Field(description="Timestamp when the log was generated")
    line: str = Field(description="Content of the log line")


class ContainerStats(BaseModel):
    """Container statistics and state information."""

    status: str | None = Field(default=None, description="Current container status")
    restarts: int | None = Field(
        default=None, description="Number of container restarts"
    )
    created: str | None = Field(
        default=None, description="Container creation timestamp"
    )
    exit_code: int | None = Field(default=None, description="Container exit code")


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(default="ok", description="Health status of the service")
