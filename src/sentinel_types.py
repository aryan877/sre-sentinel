"""
Shared Pydantic models and type definitions for SRE Sentinel.
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping

from pydantic import BaseModel, Field, field_validator


__all__ = [
    "AnomalyDetectionResult",
    "AnomalySeverity",
    "AnomalyType",
    "ContainerState",
    "FixAction",
    "FixActionName",
    "FixExecutionResult",
    "Incident",
    "IncidentStatus",
    "RootCauseAnalysis",
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


class AnomalyDetectionResult(BaseModel):
    """Result of anomaly detection analysis from Cerebras AI model."""

    is_anomaly: bool
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0"
    )
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    summary: str = Field(description="Human-readable summary of the detected anomaly")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "AnomalyDetectionResult":
        """Create an AnomalyDetectionResult from a raw mapping/dictionary."""
        return cls.model_validate(payload)


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

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "FixAction":
        """Create a FixAction from a raw mapping/dictionary."""
        return cls.model_validate(payload)


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

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "FixExecutionResult":
        """Create a FixExecutionResult from a raw mapping/dictionary."""
        return cls.model_validate(payload)


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

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "RootCauseAnalysis":
        """Create a RootCauseAnalysis from a raw mapping/dictionary."""
        return cls.model_validate(payload)


class ContainerState(BaseModel):
    """Current state snapshot of a monitored container."""

    id: str | None = Field(default=None, description="Container ID")
    name: str | None = Field(default=None, description="Container name")
    service: str = Field(description="Service name the container belongs to")
    status: str = Field(
        description="Current operational status (running, stopped, etc.)"
    )
    restarts: int | None = Field(
        default=None, description="Number of times the container has restarted"
    )
    cpu: float = Field(ge=0.0, description="Current CPU usage percentage")
    memory: float = Field(ge=0.0, description="Current memory usage percentage")
    network_rx: float = Field(
        default=0.0, ge=0.0, description="Network receive rate (bytes/sec)"
    )
    network_tx: float = Field(
        default=0.0, ge=0.0, description="Network transmit rate (bytes/sec)"
    )
    disk_read: float = Field(
        default=0.0, ge=0.0, description="Disk read rate (bytes/sec)"
    )
    disk_write: float = Field(
        default=0.0, ge=0.0, description="Disk write rate (bytes/sec)"
    )
    timestamp: str = Field(description="Timestamp when this state was captured")


class Incident(BaseModel):
    """Complete incident record from detection to resolution."""

    id: str = Field(description="Unique incident identifier")
    service: str = Field(description="Service name where the incident occurred")
    detected_at: str = Field(
        description="Timestamp when the incident was first detected"
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
        default=None, description="Timestamp when the incident was resolved"
    )
    explanation: str | None = Field(
        default=None, description="Human-friendly explanation of the incident"
    )
