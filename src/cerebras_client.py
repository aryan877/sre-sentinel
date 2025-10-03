"""
Cerebras AI client for anomaly detection in container logs.

This module handles communication with the Cerebras AI service to detect
anomalies in container logs. It processes log chunks, sends them to the
AI model, and returns structured anomaly detection results.

The client is designed to:
1. Format log data for optimal AI analysis
2. Handle API communication with retries
3. Parse and validate AI responses
4. Provide both synchronous and streaming interfaces

Flow:
1. Log data is collected from containers
2. Log chunks are formatted with context
3. Formatted data is sent to Cerebras API
4. AI response is parsed into validated models
5. Results are returned to the monitoring system
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from typing import Generator

from cerebras.cloud.sdk import Cerebras
from openai.types.chat import ChatCompletion
from pydantic import BaseModel, Field, field_validator
from rich.console import Console
from tenacity import retry, stop_after_attempt, wait_exponential

from sentinel_types import AnomalyDetectionResult, AnomalySeverity, AnomalyType

console = Console()


class CerebrasClientError(RuntimeError):
    """
    Custom exception for Cerebras client errors.
    
    Raised when the Cerebras API returns unusable data or when
    communication with the API fails.
    """


class CerebrasSettings(BaseModel):
    """
    Configuration settings for Cerebras API access.
    
    This model encapsulates all the settings needed to connect
    to the Cerebras API, including authentication and model selection.
    """
    api_key: str = Field(description="API key for Cerebras authentication")
    model: str = Field(default="llama-4-scout-17b-16e-instruct", description="Model name to use for analysis")

    @classmethod
    def from_env(cls) -> "CerebrasSettings":
        """
        Create settings from environment variables.
        
        Loads configuration from environment variables with sensible defaults.
        Raises ValueError if required settings are missing.
        """
        api_key = os.getenv("CEREBRAS_API_KEY")
        if not api_key:
            raise ValueError("CEREBRAS_API_KEY not found in environment")
        default_model = "llama-4-scout-17b-16e-instruct"
        model = os.getenv("CEREBRAS_MODEL", default_model)
        return cls(api_key=api_key, model=model)


class CompletionMessage(BaseModel):
    """
    Chat message structure for Cerebras API.
    
    Represents a single message in the conversation with the AI model,
    including the role (system, user, assistant) and content.
    """
    role: str = Field(pattern="^(system|user|assistant)$", description="Message role in the conversation")
    content: str = Field(description="Message content")


class AnomalyPayload(BaseModel):
    """
    Expected anomaly detection response from Cerebras.
    
    This model defines the structure of the JSON response we expect
    from the Cerebras API when performing anomaly detection.
    """
    is_anomaly: bool = Field(description="Whether an anomaly was detected")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    anomaly_type: str = Field(pattern="^(crash|error|warning|performance|none)$", description="Type of anomaly detected")
    severity: str = Field(pattern="^(low|medium|high|critical)$", description="Severity level of the anomaly")
    summary: str = Field(description="Human-readable summary of the detected anomaly")

    @field_validator('anomaly_type')
    @classmethod
    def validate_anomaly_type(cls, v: str) -> str:
        """Normalize anomaly type to lowercase."""
        return v.lower()

    @field_validator('severity')
    @classmethod
    def validate_severity(cls, v: str) -> str:
        """Normalize severity to lowercase."""
        return v.lower()


# System prompt for the AI model
_SYSTEM_PROMPT: str = """You are an expert SRE analyzing container logs for anomalies.
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

# Template for user prompt with service name and logs
_USER_PROMPT_TEMPLATE: str = """Service: {service}

Recent logs (last 100 lines):
```
{logs}
```{context}

Analyze for anomalies. Respond with JSON only."""


class CerebrasAnomalyDetector:
    """
    Fast anomaly detection using Cerebras inference with Pydantic models.
    
    This class handles the complete anomaly detection workflow:
    1. Formats log data for AI analysis
    2. Communicates with the Cerebras API
    3. Parses and validates responses
    4. Returns structured detection results
    
    The detector is designed to be resilient to API failures and
    provides clear error messages for debugging.
    """

    def __init__(self, settings: CerebrasSettings | None = None) -> None:
        """
        Initialize the anomaly detector with API settings.
        
        Args:
            settings: API configuration settings. If None, loads from environment.
        """
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
        """
        Detect anomalies in a log chunk for a specific service.
        
        This is the main method for anomaly detection. It formats the log data,
        sends it to the AI model, and returns a structured detection result.
        
        Args:
            log_chunk: Text content of logs to analyze
            service_name: Name of the service the logs belong to
            context: Additional context information about the container/service
            
        Returns:
            AnomalyDetectionResult with the analysis results
        """
        # Format the log data for the AI model
        messages = self._build_messages(log_chunk, service_name, context)
        console.print(
            f"[cyan]⚡ Analyzing logs with Cerebras ({len(log_chunk)} chars)...[/cyan]"
        )

        try:
            # Send the formatted logs to the AI model
            completion = self.client.chat.completions.create(
                model=self.settings.model,
                messages=[msg.model_dump() for msg in messages],
                temperature=0.1,  # Low temperature for consistent results
                max_completion_tokens=300,
                response_format={"type": "json_object"},  # Force JSON response
            )
            # Parse and validate the AI response
            anomaly = self._parse_completion(completion)
        except Exception as exc:
            console.print(f"[red]Error in Cerebras API call: {exc}[/red]")
            # Return a default "no anomaly" result on error
            return AnomalyDetectionResult(
                is_anomaly=False,
                confidence=0.0,
                anomaly_type=AnomalyType.NONE,
                severity=AnomalySeverity.LOW,
                summary=f"Error analyzing logs: {exc}",
            )

        # Display results to the console
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
        """
        Stream partial Cerebras responses for real-time dashboards.
        
        This method provides a streaming interface for the AI response,
        allowing dashboards to display results as they're generated.
        
        Args:
            log_chunk: Text content of logs to analyze
            service_name: Name of the service the logs belong to
            context: Additional context information about the container/service
            
        Yields:
            Partial response content as strings
        """
        messages = self._build_messages(log_chunk, service_name, context)

        try:
            # Create a streaming request to the AI model
            stream = self.client.chat.completions.create(
                model=self.settings.model,
                messages=[msg.model_dump() for msg in messages],
                temperature=0.1,
                max_completion_tokens=300,
                stream=True,  # Enable streaming
            )
            # Process and yield each chunk of the response
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
        except Exception as exc:
            console.print(f"[red]Streaming error: {exc}[/red]")
            yield json.dumps({"error": str(exc)})

    def _build_messages(
        self,
        log_chunk: str,
        service_name: str,
        context: Mapping[str, object] | None,
    ) -> list[CompletionMessage]:
        """
        Build validated messages for the AI model.
        
        Formats the log data and context into a structured conversation
        that the AI model can understand and analyze.
        
        Args:
            log_chunk: Text content of logs to analyze
            service_name: Name of the service the logs belong to
            context: Additional context information about the container/service
            
        Returns:
            List of formatted messages for the AI model
        """
        # Format any additional context as JSON
        context_block = ""
        if context:
            context_block = f"\n\nAdditional context:\n{json.dumps(dict(context), indent=2)}"

        # Create the user prompt with service name and logs
        user_prompt = _USER_PROMPT_TEMPLATE.format(
            service=service_name,
            logs=log_chunk,
            context=context_block,
        )

        # Return the complete conversation
        messages = [
            CompletionMessage(role="system", content=_SYSTEM_PROMPT),
            CompletionMessage(role="user", content=user_prompt),
        ]
        return messages

    def _parse_completion(self, completion: ChatCompletion) -> AnomalyDetectionResult:
        """
        Parse AI model output into a validated domain object.
        
        Takes the raw response from the AI model, validates it against
        our expected schema, and converts it to our domain model.
        
        Args:
            completion: Raw completion response from the AI model
            
        Returns:
            Validated AnomalyDetectionResult
            
        Raises:
            CerebrasClientError: If the response is invalid or missing
        """
        # Extract the message content from the completion
        message = completion.choices[0].message
        if message.content is None:
            raise CerebrasClientError("Missing content in Cerebras response")

        # Parse the JSON response
        payload_raw = json.loads(message.content)

        if not isinstance(payload_raw, Mapping):
            raise CerebrasClientError("Cerebras response was not a JSON object")

        # Validate with Pydantic model
        try:
            payload = AnomalyPayload.model_validate(payload_raw)
        except Exception as e:
            raise CerebrasClientError(f"Invalid response format: {e}")

        # Convert to our domain model with proper enum types
        return AnomalyDetectionResult(
            is_anomaly=payload.is_anomaly,
            confidence=payload.confidence,
            anomaly_type=AnomalyType(payload.anomaly_type),
            severity=AnomalySeverity(payload.severity),
            summary=payload.summary,
        )

    @staticmethod
    def _as_dict(value: object) -> dict[str, object] | None:
        """Safely convert a value to a dictionary if possible."""
        if isinstance(value, Mapping):
            return dict(value)
        return None

    def _normalise_choices(
        self, chunk_dict: Mapping[str, object]
    ) -> list[Mapping[str, object]]:
        """Extract and normalize choices from a streaming response chunk."""
        choices = chunk_dict.get("choices")
        if isinstance(choices, list):
            return [choice for choice in choices if isinstance(choice, Mapping)]
        return []


if __name__ == "__main__":
    """
    Example usage of the Cerebras anomaly detector.
    
    This block demonstrates how to use the detector with sample log data.
    It's primarily for testing and demonstration purposes.
    """
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
