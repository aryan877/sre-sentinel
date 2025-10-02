"""Cerebras anomaly detection client with defensive parsing."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Generator, cast

from cerebras.cloud.sdk import Cerebras
from openai.types.chat import ChatCompletion
from typing import Any
from rich.console import Console
from tenacity import retry, stop_after_attempt, wait_exponential

from sentinel_types import AnomalyDetectionResult, AnomalySeverity, AnomalyType

console = Console()


class CerebrasClientError(RuntimeError):
    """Base error for Cerebras client issues."""


@dataclass(slots=True, frozen=True)
class CerebrasSettings:
    """Configuration required for Cerebras API access."""

    api_key: str
    model: str = "llama-4-scout-17b-16e-instruct"

    @classmethod
    def from_env(cls) -> "CerebrasSettings":
        api_key = os.getenv("CEREBRAS_API_KEY")
        if not api_key:
            raise ValueError("CEREBRAS_API_KEY not found in environment")
        default_model = "llama-4-scout-17b-16e-instruct"
        model = os.getenv("CEREBRAS_MODEL", default_model)
        return cls(api_key=api_key, model=model)


class CerebrasAnomalyDetector:
    """Fast anomaly detection using Cerebras inference."""

    def __init__(self, settings: CerebrasSettings | None = None) -> None:
        self.settings = settings or CerebrasSettings.from_env()
        self.client = Cerebras(api_key=self.settings.api_key)

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def detect_anomaly(
        self,
        log_chunk: str,
        service_name: str,
        context: Mapping[str, object] | None = None,
    ) -> AnomalyDetectionResult:
        """Detect anomalies in *log_chunk* for *service_name*."""

        messages = self._build_messages(log_chunk, service_name, context)
        console.print(
            f"[cyan]⚡ Analyzing logs with Cerebras ({len(log_chunk)} chars)...[/cyan]"
        )

        try:
            completion = cast(
                ChatCompletion,
                self.client.chat.completions.create(
                    model=self.settings.model,
                    messages=messages,
                    temperature=0.1,
                    max_completion_tokens=300,
                    response_format={"type": "json_object"},
                ),
            )
            anomaly = self._parse_completion(completion)
        except Exception as exc:
            console.print(f"[red]Error in Cerebras API call: {exc}[/red]")
            return AnomalyDetectionResult(
                is_anomaly=False,
                confidence=0.0,
                anomaly_type=AnomalyType.NONE,
                severity=AnomalySeverity.LOW,
                summary=f"Error analyzing logs: {exc}",
            )

        if anomaly.is_anomaly:
            console.print(
                "[red]🚨 Anomaly detected![/red] "
                f"Type: {anomaly.anomaly_type.value}, "
                f"Severity: {anomaly.severity.value}, "
                f"Confidence: {anomaly.confidence:.0%}"
            )
        else:
            console.print("[green]✓ No anomalies detected[/green]")

        return anomaly

    def detect_anomaly_streaming(
        self,
        log_chunk: str,
        service_name: str,
        context: Mapping[str, object] | None = None,
    ) -> Generator[str, None, None]:
        """Stream partial Cerebras responses for dashboards and TTYs."""

        messages = self._build_messages(log_chunk, service_name, context)

        try:
            stream = cast(
                Iterable[object],
                self.client.chat.completions.create(
                    model=self.settings.model,
                    messages=messages,
                    temperature=0.1,
                    max_completion_tokens=300,
                    stream=True,
                ),
            )
            for chunk in stream:
                chunk_dict = self._as_dict(chunk)
                if not chunk_dict:
                    continue

                for choice in self._normalise_choices(chunk_dict):
                    delta = self._as_dict(choice.get("delta"))
                    if delta:
                        delta_content = delta.get("content")
                        if isinstance(delta_content, str):
                            yield delta_content

                    message = self._as_dict(choice.get("message"))
                    if message:
                        message_content = message.get("content")
                        if isinstance(message_content, str):
                            yield message_content
        except Exception as exc:  # pragma: no cover - best effort logging
            console.print(f"[red]Streaming error: {exc}[/red]")
            yield json.dumps({"error": str(exc)})

    # ------------------------------------------------------------------
    def _build_messages(
        self,
        log_chunk: str,
        service_name: str,
        context: Mapping[str, object] | None,
    ) -> list[dict[str, Any]]:
        system_prompt = _SYSTEM_PROMPT
        context_block = ""
        if context:
            context_block = f"\n\nAdditional context:\n{json.dumps(dict(context), indent=2)}"

        user_prompt = _USER_PROMPT_TEMPLATE.format(
            service=service_name,
            logs=log_chunk,
            context=context_block,
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return messages

    def _parse_completion(self, completion: ChatCompletion) -> AnomalyDetectionResult:
        message = completion.choices[0].message
        if message.content is None:
            raise CerebrasClientError("Missing content in Cerebras response")

        payload = json.loads(message.content)
        if not isinstance(payload, Mapping):
            raise CerebrasClientError("Cerebras response was not a JSON object")
        payload_mapping = cast(Mapping[str, object], payload)
        return AnomalyDetectionResult.from_mapping(payload_mapping)

    @staticmethod
    def _as_dict(value: object) -> dict[str, object] | None:
        if isinstance(value, Mapping):
            return cast(dict[str, object], value)
        return None

    def _normalise_choices(
        self, chunk_dict: Mapping[str, object]
    ) -> list[Mapping[str, object]]:
        choices = chunk_dict.get("choices")
        if isinstance(choices, list):
            return [cast(Mapping[str, object], choice) for choice in choices if isinstance(choice, Mapping)]
        return []


_SYSTEM_PROMPT = """You are an expert SRE analyzing container logs for anomalies.
Respond ONLY with a JSON object in this format:
{
    "is_anomaly": true/false,
    "confidence": 0.0-1.0,
    "anomaly_type": "crash|error|warning|performance|none",
    "severity": "low|medium|high|critical",
    "summary": "one-sentence description"
}

Common anomaly patterns:
- Crashes: "FATAL", "segmentation fault", "killed", "OOM"
- Errors: "ERROR", "Exception", "failed to", "connection refused"
- Performance: "timeout", "slow query", "high latency", "memory leak"
- Warnings: "deprecated", "retry", "fallback"
"""


_USER_PROMPT_TEMPLATE = """Service: {service}

Recent logs (last 100 lines):
```
{logs}
```{context}

Analyze for anomalies. Respond with JSON only."""


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    detector = CerebrasAnomalyDetector()
    sample_logs = """
2025-09-30 12:00:01 INFO Starting application...
2025-09-30 12:00:02 INFO Connected to database
2025-09-30 12:05:15 ERROR Connection to postgres failed: Connection refused
2025-09-30 12:05:16 ERROR Retrying connection...
2025-09-30 12:05:17 ERROR Connection to postgres failed: Connection refused
2025-09-30 12:05:18 FATAL Unable to connect to database after 3 retries
2025-09-30 12:05:19 INFO Shutting down...
"""

    result = detector.detect_anomaly(
        log_chunk=sample_logs,
        service_name="demo-api",
        context={"health": "unhealthy", "restarts": "2"},
    )

    console.print("\n[bold]Detection Result:[/bold]")
    console.print(result.to_dict())
