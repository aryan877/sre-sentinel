"""Shared typed structures and helpers for SRE Sentinel."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Mapping, Sequence, TypeVar, cast


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
    "SerializableMixin",
]


class SerializableMixin:
    """Provide ``to_dict`` for dataclasses with sensible defaults."""

    def to_dict(self, *, include_none: bool = True) -> dict[str, object]:
        result: dict[str, object] = {}
        for field in fields(self):  # type: ignore[arg-type]
            value = getattr(self, field.name)
            if value is None and not include_none:
                continue
            result[field.name] = _serialise(value)
        return result


class AnomalyType(str, Enum):
    CRASH = "crash"
    ERROR = "error"
    WARNING = "warning"
    PERFORMANCE = "performance"
    NONE = "none"


class AnomalySeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FixActionName(str, Enum):
    RESTART_CONTAINER = "restart_container"
    UPDATE_CONFIG = "update_config"
    PATCH_CODE = "patch_code"
    SCALE_RESOURCES = "scale_resources"


class IncidentStatus(str, Enum):
    ANALYZING = "analyzing"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


@dataclass(slots=True, frozen=True)
class AnomalyDetectionResult(SerializableMixin):
    """Structured result returned by the Cerebras anomaly detector."""

    is_anomaly: bool
    confidence: float
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    summary: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "AnomalyDetectionResult":
        return cls(
            is_anomaly=_coerce_bool(payload.get("is_anomaly")),
            confidence=_coerce_float(payload.get("confidence")),
            anomaly_type=_coerce_enum(payload.get("anomaly_type"), AnomalyType),
            severity=_coerce_enum(payload.get("severity"), AnomalySeverity),
            summary=_coerce_str(payload.get("summary")),
        )


@dataclass(slots=True, frozen=True)
class FixAction(SerializableMixin):
    """Action suggested by the root cause analyzer."""

    action: FixActionName
    target: str
    details: str
    priority: int

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "FixAction":
        priority_raw = payload.get("priority")
        if isinstance(priority_raw, bool):  # Guard against JSON "true"/"false"
            raise ValueError("priority cannot be boolean")
        return cls(
            action=_coerce_enum(payload.get("action"), FixActionName),
            target=_coerce_str(payload.get("target")),
            details=_coerce_str(payload.get("details")),
            priority=int(_coerce_float(priority_raw)),
        )


@dataclass(slots=True)
class FixExecutionResult(SerializableMixin):
    """Structured response after executing a fix through the MCP orchestrator."""

    success: bool
    message: str | None = None
    error: str | None = None
    status: str | None = None
    details: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "FixExecutionResult":
        return cls(
            success=_coerce_bool(payload.get("success")),
            message=_coerce_optional_str(payload.get("message")),
            error=_coerce_optional_str(payload.get("error")),
            status=_coerce_optional_str(payload.get("status")),
            details=_coerce_optional_str(payload.get("details")),
        )


@dataclass(slots=True, frozen=True)
class RootCauseAnalysis(SerializableMixin):
    """High-level analysis returned by the Llama analyzer."""

    root_cause: str
    explanation: str
    affected_components: tuple[str, ...]
    suggested_fixes: tuple[FixAction, ...]
    confidence: float
    prevention: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "RootCauseAnalysis":
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


@dataclass(slots=True)
class ContainerState(SerializableMixin):
    """Lightweight snapshot of a monitored container."""

    id: str | None
    name: str | None
    service: str
    status: str
    restarts: int | None
    cpu: float
    memory: float
    timestamp: str


@dataclass(slots=True)
class Incident(SerializableMixin):
    """Captured incident life-cycle data."""

    id: str
    service: str
    detected_at: str
    anomaly: AnomalyDetectionResult
    status: IncidentStatus
    analysis: RootCauseAnalysis | None = None
    fixes: tuple[FixExecutionResult, ...] = ()
    resolved_at: str | None = None
    explanation: str | None = None


def _serialise(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: _serialise(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_serialise(item) for item in value]
    if not is_dataclass(value):
        return value
    
    # At this point, value is a dataclass
    # Check if it has to_dict method (SerializableMixin)
    to_dict_method = getattr(value, "to_dict", None)
    if callable(to_dict_method):
        return to_dict_method()
    
    # Fallback: serialize dataclass fields manually
    serialised: dict[str, object] = {}
    for field in fields(value):
        serialised[field.name] = _serialise(getattr(value, field.name))
    return serialised


def _coerce_bool(value: object) -> bool:
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
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value.strip())
    raise ValueError(f"Cannot interpret {value!r} as float")


def _coerce_str(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        raise ValueError("Expected string, received None")
    return str(value)


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    return _coerce_str(value)


EnumT = TypeVar("EnumT", bound=Enum)


def _coerce_enum(value: object, enum_cls: type[EnumT]) -> EnumT:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        for member in enum_cls:
            if member.value == value.strip().lower():
                return member
    raise ValueError(f"Value {value!r} not valid for {enum_cls.__name__}")


def _ensure_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    raise ValueError(f"Expected {field_name} items to be mappings, received {type(value).__name__}")
