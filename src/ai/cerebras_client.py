"""
Cerebras AI client for anomaly detection in container logs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from openai.types.chat import ChatCompletion
from rich.console import Console
from tenacity import retry, stop_after_attempt, wait_exponential

from src.utils.api_key_detector import fallback_secret_detection
from src.ai.openrouter_client import create_openrouter_client
from src.models.sentinel_types import (
    AnomalyDetectionResult,
    AnomalySeverity,
    AnomalyType,
    CerebrasSettings,
    CompletionMessage,
    AnomalyPayload,
)

console = Console()


class CerebrasClientError(RuntimeError):
    """Custom exception for Cerebras client errors."""


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
- Crashes: "FATAL", "segmentation fault", "killed", "OOM", "heap out of memory", "JavaScript heap out of memory"
- Errors: "ERROR", "Exception", "failed to", "connection refused"
- Performance: "timeout", "slow query", "high latency", "memory leak"
- Warnings: "deprecated", "retry", "fallback"

Severity guidelines:
- CRITICAL: "FATAL", "OOM", "heap out of memory", "segmentation fault", container crashes
- HIGH: Multiple repeated errors, connection failures, service unavailable, "memory leak"
- MEDIUM: Single errors, timeouts, performance degradation
- LOW: Warnings, deprecation notices, single failed requests
"""

_USER_PROMPT_TEMPLATE = """Service: {service}

Recent logs (last 100 lines):
```
{logs}
```{context}

Analyze for anomalies. Respond with JSON only."""

_ENV_CLASSIFICATION_SYSTEM_PROMPT = """You are a security expert analyzing environment variable names.
Classify which environment variable names likely contain sensitive information (passwords, API keys, tokens, secrets, credentials, etc.).

Respond ONLY with a JSON object in this format:
{
    "sensitive_keys": ["KEY_NAME_1", "KEY_NAME_2"]
}

Include a key in "sensitive_keys" if it likely contains:
- Passwords or credentials
- API keys or tokens
- Database connection strings with embedded passwords
- Private keys or certificates
- OAuth secrets
- Encryption keys

Common patterns to flag as sensitive:
- Contains: "key", "secret", "password", "token", "auth", "credential", "private", "cert"
- Database URLs that may embed passwords: "DATABASE_URL", "DB_URL", "MONGO_URL", "REDIS_URL"
- Cloud provider credentials: "AWS_", "GCP_", "AZURE_"
- Third-party API keys: "*_API_KEY", "*_TOKEN", "*_SECRET"

DO NOT flag safe configuration like:
- "NODE_ENV", "PORT", "LOG_LEVEL", "TIMEOUT", "MAX_CONNECTIONS", "DEBUG"
- "HOSTNAME", "PATH", "HOME", "USER", "LANG"
"""

_ENV_CLASSIFICATION_USER_PROMPT = """Classify these environment variable names as sensitive or safe:

{env_var_names}

Respond with JSON only."""


class CerebrasAnomalyDetector:
    """Fast anomaly detection using Cerebras inference via OpenRouter."""

    def __init__(self, settings: CerebrasSettings | None = None) -> None:
        """Initialize the anomaly detector with API settings."""
        self.settings = settings or CerebrasSettings.from_env()
        self.client = create_openrouter_client(
            api_key=self.settings.api_key, base_url=self.settings.base_url
        )

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def detect_anomaly(
        self,
        log_chunk: str,
        service_name: str,
        context: Mapping[str, object] | None = None,
    ) -> AnomalyDetectionResult:
        """Detect anomalies in a log chunk for a specific service."""
        messages = self._build_messages(log_chunk, service_name, context)
        console.print(
            f"[cyan]⚡ Analyzing logs with Cerebras ({len(log_chunk)} chars)...[/cyan]"
        )

        try:
            completion = self.client.chat.completions.create(
                model=self.settings.model,
                messages=[msg.model_dump() for msg in messages],
                temperature=0.1,
                max_completion_tokens=300,
                response_format={"type": "json_object"},
                extra_body={"provider": {"order": ["Cerebras"]}},
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

    def _build_messages(
        self,
        log_chunk: str,
        service_name: str,
        context: Mapping[str, object] | None,
    ) -> list[CompletionMessage]:
        """Build validated messages for the AI model."""
        context_block = ""
        if context:
            context_block = (
                f"\n\nAdditional context:\n{json.dumps(dict(context), indent=2)}"
            )

        user_prompt = _USER_PROMPT_TEMPLATE.format(
            service=service_name,
            logs=log_chunk,
            context=context_block,
        )

        return [
            CompletionMessage.model_validate(
                {"role": "system", "content": _SYSTEM_PROMPT}
            ),
            CompletionMessage.model_validate({"role": "user", "content": user_prompt}),
        ]

    def _parse_completion(self, completion: ChatCompletion) -> AnomalyDetectionResult:
        """Parse AI model output into a validated domain object."""
        message = completion.choices[0].message
        if message.content is None:
            raise CerebrasClientError("Missing content in Cerebras response")

        payload_raw = json.loads(message.content)

        if not isinstance(payload_raw, Mapping):
            raise CerebrasClientError("Cerebras response was not a JSON object")

        try:
            payload = AnomalyPayload.model_validate(payload_raw)
        except Exception as e:
            raise CerebrasClientError(f"Invalid response format: {e}")

        return AnomalyDetectionResult(
            is_anomaly=payload.is_anomaly,
            confidence=payload.confidence,
            anomaly_type=AnomalyType(payload.anomaly_type),
            severity=AnomalySeverity(payload.severity),
            summary=payload.summary,
        )

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def classify_sensitive_env_vars(
        self, env_var_names: list[str], env_var_values: Mapping[str, str] | None = None
    ) -> set[str]:
        """
        Classify which environment variable names are likely sensitive.

        Uses Cerebras for fast, intelligent classification based on naming patterns.
        Returns a set of env var names that should be redacted.

        Args:
            env_var_names: List of environment variable names to classify
            env_var_values: Optional mapping of names to values for pattern-based fallback
        """
        if not env_var_names:
            return set()

        console.print(
            f"[cyan]🔐 Classifying {len(env_var_names)} env vars with Cerebras...[/cyan]"
        )

        # Format env var names as a list
        env_names_str = "\n".join(f"- {name}" for name in env_var_names)
        user_prompt = _ENV_CLASSIFICATION_USER_PROMPT.format(
            env_var_names=env_names_str
        )

        messages = [
            CompletionMessage.model_validate(
                {"role": "system", "content": _ENV_CLASSIFICATION_SYSTEM_PROMPT}
            ),
            CompletionMessage.model_validate({"role": "user", "content": user_prompt}),
        ]

        try:
            completion = self.client.chat.completions.create(
                model=self.settings.model,
                messages=[msg.model_dump() for msg in messages],
                temperature=0.0,  # Deterministic classification
                max_completion_tokens=500,
                response_format={"type": "json_object"},
                extra_body={"provider": {"order": ["Cerebras"]}},
            )

            message = completion.choices[0].message
            if message.content is None:
                console.print("[yellow]⚠️  Empty response from Cerebras[/yellow]")
                return fallback_secret_detection(env_var_names, env_var_values)

            response_data = json.loads(message.content)
            sensitive_keys = response_data.get("sensitive_keys", [])

            if not isinstance(sensitive_keys, list):
                console.print(
                    "[yellow]⚠️  Invalid response format from Cerebras[/yellow]"
                )
                return fallback_secret_detection(env_var_names, env_var_values)

            sensitive_set = {key for key in sensitive_keys if isinstance(key, str)}
            console.print(
                f"[green]✓ Classified {len(sensitive_set)}/{len(env_var_names)} as sensitive[/green]"
            )

            return sensitive_set

        except Exception as exc:
            console.print(
                f"[yellow]⚠️  Error classifying env vars with Cerebras: {exc}[/yellow]"
            )
            return fallback_secret_detection(env_var_names, env_var_values)


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
    console.print(result.model_dump())
