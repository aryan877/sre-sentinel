"""
Shared Pydantic models and type definitions for SRE Sentinel.

This module contains all the core data structures used throughout the SRE Sentinel system.
Each model is carefully designed with Pydantic to provide:
- Runtime validation of incoming data
- Automatic serialization/deserialization
- Clear error messages for invalid data
- Type hints for better IDE support

The models represent:
1. Anomaly detection results from Cerebras
2. Root cause analysis from Llama
3. Fix actions and their execution results
4. Container state information
5. Incident lifecycle data
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping, Sequence, TypeVar, cast

from pydantic import BaseModel, Field


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
    """
    Types of anomalies that can be detected in container logs.
    
    These values correspond to the categories the AI model uses to classify
    different types of issues it finds in log data.
    """
    CRASH = "crash"          # Application crashes or fatal errors
    ERROR = "error"          # General errors that don't crash the app
    WARNING = "warning"      # Warning messages that might indicate issues
    PERFORMANCE = "performance"  # Performance-related issues
    NONE = "none"            # No anomaly detected


class AnomalySeverity(str, Enum):
    """
    Severity levels for detected anomalies.
    
    These help prioritize which incidents need immediate attention.
    Higher severity incidents are automatically processed first.
    """
    LOW = "low"              # Minor issues that can be addressed later
    MEDIUM = "medium"        # Issues that should be addressed soon
    HIGH = "high"            # Serious issues requiring prompt attention
    CRITICAL = "critical"    # Critical issues requiring immediate action


class FixActionName(str, Enum):
    """
    Types of automated fixes that can be applied to containers.
    
    These represent the different remediation actions the system can take
    when it detects problems with monitored containers.
    """
    RESTART_CONTAINER = "restart_container"  # Restart a problematic container
    UPDATE_ENV_VARS = "update_env_vars"      # Update environment variables for a container
    UPDATE_RESOURCES = "update_resources"    # Update CPU and memory limits for a container
    HEALTH_CHECK = "health_check"            # Check the health status of a container
    GET_LOGS = "get_logs"                    # Get recent logs from a container


class IncidentStatus(str, Enum):
    """
    Status values for incident lifecycle tracking.
    
    These represent the different states an incident goes through
    from detection to resolution.
    """
    ANALYZING = "analyzing"    # Incident detected, analysis in progress
    RESOLVED = "resolved"      # Incident successfully resolved
    UNRESOLVED = "unresolved"  # Incident could not be resolved automatically


class AnomalyDetectionResult(BaseModel):
    """
    Result of anomaly detection analysis from Cerebras AI model.
    
    This model captures the output from the anomaly detection service,
    including whether an anomaly was found, how confident the model is,
    and details about what type of anomaly was detected.
    """
    is_anomaly: bool
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    summary: str = Field(description="Human-readable summary of the detected anomaly")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "AnomalyDetectionResult":
        """
        Create an AnomalyDetectionResult from a raw mapping/dictionary.
        
        This method safely converts raw API responses into our validated model,
        handling type coercion and validation.
        """
        return cls(
            is_anomaly=_coerce_bool(payload.get("is_anomaly")),
            confidence=_coerce_float(payload.get("confidence")),
            anomaly_type=_coerce_enum(payload.get("anomaly_type"), AnomalyType),
            severity=_coerce_enum(payload.get("severity"), AnomalySeverity),
            summary=_coerce_str(payload.get("summary")),
        )


class FixAction(BaseModel):
    """
    A specific fix action recommended by the AI analysis.
    
    This model represents a single remediation step that should be taken
    to address an issue. It includes what action to take, what target
    to apply it to, and details about how to perform the action.
    """
    action: FixActionName
    target: str = Field(description="Container name or other target for the fix")
    details: str = Field(description="Specific details about how to apply the fix")
    priority: int = Field(ge=1, le=5, description="Priority from 1 (lowest) to 5 (highest)")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "FixAction":
        """
        Create a FixAction from a raw mapping/dictionary.
        
        Safely converts raw API responses into our validated model.
        """
        priority_raw = payload.get("priority")
        if isinstance(priority_raw, bool):  # Guard against JSON "true"/"false"
            raise ValueError("priority cannot be boolean")
        return cls(
            action=_coerce_enum(payload.get("action"), FixActionName),
            target=_coerce_str(payload.get("target")),
            details=_coerce_str(payload.get("details")),
            priority=int(_coerce_float(priority_raw)),
        )


class FixExecutionResult(BaseModel):
    """
    Result of executing a fix action through the MCP orchestrator.
    
    This model captures the outcome of attempting to apply a fix,
    including whether it succeeded and any relevant messages or errors.
    """
    success: bool = Field(description="Whether the fix was successfully applied")
    message: str | None = Field(default=None, description="Success message from the fix execution")
    error: str | None = Field(default=None, description="Error message if the fix failed")
    status: str | None = Field(default=None, description="Status code from the fix execution")
    details: str | None = Field(default=None, description="Additional details about the execution")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "FixExecutionResult":
        """
        Create a FixExecutionResult from a raw mapping/dictionary.
        
        Safely converts raw API responses into our validated model.
        """
        return cls(
            success=_coerce_bool(payload.get("success")),
            message=_coerce_optional_str(payload.get("message")),
            error=_coerce_optional_str(payload.get("error")),
            status=_coerce_optional_str(payload.get("status")),
            details=_coerce_optional_str(payload.get("details")),
        )


class RootCauseAnalysis(BaseModel):
    """
    Comprehensive root cause analysis from Llama AI model.
    
    This model captures the detailed analysis of why an incident occurred,
    what components were affected, and what fixes should be applied.
    It represents the "deep thinking" output from the AI analyzer.
    """
    root_cause: str = Field(description="Primary cause of the incident")
    explanation: str = Field(description="Detailed explanation of the root cause analysis")
    affected_components: tuple[str, ...] = Field(description="List of components affected by the incident")
    suggested_fixes: tuple[FixAction, ...] = Field(description="Recommended fixes to resolve the incident")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    prevention: str = Field(description="Recommendations for preventing similar incidents in the future")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "RootCauseAnalysis":
        """
        Create a RootCauseAnalysis from a raw mapping/dictionary.
        
        Safely converts raw API responses into our validated model,
        including nested FixAction objects.
        """
        actions_raw = payload.get("suggested_fixes")
        if not isinstance(actions_raw, Sequence) or isinstance(actions_raw, (str, bytes)):
            raise ValueError("suggested_fixes must be a sequence")
        actions = tuple(
            FixAction.from_mapping(_ensure_mapping(item, "suggested_fixes"))
            for item in actions_raw
        )
        affected_raw = payload.get("affected_components")
        if not isinstance(affected_raw, Sequence) or isinstance(affected_raw, (str, bytes)):
            raise ValueError("affected_components must be a sequence")
        affected = tuple(_coerce_str(item) for item in affected_raw)

        return cls(
            root_cause=_coerce_str(payload.get("root_cause")),
            explanation=_coerce_str(payload.get("explanation")),
            affected_components=affected,
            suggested_fixes=actions,
            confidence=_coerce_float(payload.get("confidence")),
            prevention=_coerce_str(payload.get("prevention")),
        )


class ContainerState(BaseModel):
    """
    Current state snapshot of a monitored container.
    
    This model captures the real-time status of a container, including
    its resource usage and operational status. It's updated regularly
    as the monitoring system tracks container health.
    """
    id: str | None = Field(default=None, description="Container ID")
    name: str | None = Field(default=None, description="Container name")
    service: str = Field(description="Service name the container belongs to")
    status: str = Field(description="Current operational status (running, stopped, etc.)")
    restarts: int | None = Field(default=None, description="Number of times the container has restarted")
    cpu: float = Field(ge=0.0, description="Current CPU usage percentage")
    memory: float = Field(ge=0.0, description="Current memory usage percentage")
    timestamp: str = Field(description="Timestamp when this state was captured")


class Incident(BaseModel):
    """
    Complete incident record from detection to resolution.
    
    This model tracks the entire lifecycle of an incident, from when it was
    first detected through analysis, fix attempts, and final resolution.
    It serves as the central record for all incident-related data.
    """
    id: str = Field(description="Unique incident identifier")
    service: str = Field(description="Service name where the incident occurred")
    detected_at: str = Field(description="Timestamp when the incident was first detected")
    anomaly: AnomalyDetectionResult = Field(description="Anomaly that triggered this incident")
    status: IncidentStatus = Field(description="Current status of the incident")
    analysis: RootCauseAnalysis | None = Field(default=None, description="Root cause analysis results")
    fixes: tuple[FixExecutionResult, ...] = Field(default=(), description="Results of applied fixes")
    resolved_at: str | None = Field(default=None, description="Timestamp when the incident was resolved")
    explanation: str | None = Field(default=None, description="Human-friendly explanation of the incident")


# Helper functions for type coercion and validation
def _coerce_bool(value: object) -> bool:
    """Safely convert a value to boolean, handling various input types."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    raise ValueError(f"Cannot interpret {value!r} as boolean")


def _coerce_float(value: object) -> float:
    """Safely convert a value to float, handling various input types."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value.strip())
    raise ValueError(f"Cannot interpret {value!r} as float")


def _coerce_str(value: object) -> str:
    """Safely convert a value to string, handling various input types."""
    if isinstance(value, str):
        return value
    if value is None:
        raise ValueError("Expected string, received None")
    return str(value)


def _coerce_optional_str(value: object) -> str | None:
    """Safely convert a value to optional string, handling None values."""
    if value is None:
        return None
    return _coerce_str(value)


EnumT = TypeVar("EnumT", bound=Enum)


def _coerce_enum(value: object, enum_cls: type[EnumT]) -> EnumT:
    """Safely convert a value to an enum member, handling string inputs."""
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        for member in enum_cls:
            if member.value == value.strip().lower():
                return member
    raise ValueError(f"Value {value!r} not valid for {enum_cls.__name__}")


def _ensure_mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Ensure a value is a mapping, raising a clear error if not."""
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    raise ValueError(f"Expected {field_name} items to be mappings, received {type(value).__name__}")
