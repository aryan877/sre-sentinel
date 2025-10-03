"""
Llama AI client for root cause analysis of incidents.

This module handles communication with the Llama AI service to perform
deep root cause analysis of detected anomalies. It processes incident
data, system context, and logs to identify the underlying cause of
issues and recommend appropriate fixes.

The analyzer is designed to:
1. Collect comprehensive system context
2. Send detailed incident data to Llama AI
3. Parse and validate AI analysis results
4. Generate human-friendly explanations

Flow:
1. An anomaly is detected by the monitoring system
2. System context (logs, configs, stats) is collected
3. Context is sent to Llama AI for analysis
4. AI response is parsed into validated models
5. Results are returned to the incident handler
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

from openai import OpenAI
from openai.types.chat import ChatCompletion
from pydantic import BaseModel, Field, field_validator
from rich.console import Console
from tenacity import retry, stop_after_attempt, wait_exponential

from sentinel_types import RootCauseAnalysis, FixAction

console = Console()


class LlamaAnalyzerError(RuntimeError):
    """
    Custom exception for Llama analyzer errors.

    Raised when the Llama API returns unusable data or when
    communication with the API fails.
    """


class LlamaSettings(BaseModel):
    """
    Configuration settings for Llama API access.

    This model encapsulates all the settings needed to connect
    to the Llama API, including authentication and model selection.
    """

    api_key: str = Field(description="API key for Llama authentication")
    base_url: str = Field(
        default="https://openrouter.ai/api/v1", description="Base URL for the API"
    )
    model: str = Field(
        default="meta-llama/llama-4-scout", description="Model name to use for analysis"
    )

    @classmethod
    def from_env(cls) -> "LlamaSettings":
        """
        Create settings from environment variables.

        Loads configuration from environment variables with sensible defaults.
        Raises ValueError if required settings are missing.
        """
        api_key = os.getenv("LLAMA_API_KEY")
        if not api_key:
            raise ValueError("LLAMA_API_KEY not found in environment")
        default_base = "https://openrouter.ai/api/v1"
        default_model = "meta-llama/llama-4-scout"
        base = os.getenv("LLAMA_API_BASE", default_base)
        model = os.getenv("LLAMA_MODEL", default_model)
        return cls(api_key=api_key, base_url=base, model=model)


class AnalysisMessage(BaseModel):
    """
    Chat message structure for Llama API.

    Represents a single message in the conversation with the AI model,
    including the role (system, user, assistant) and content.
    """

    role: str = Field(
        pattern="^(system|user|assistant)$",
        description="Message role in the conversation",
    )
    content: str = Field(description="Message content")


class FixActionPayload(BaseModel):
    """
    Expected fix action structure from Llama response.

    This model defines the structure of fix actions recommended by
    the AI model in its analysis response.
    """

    action: str = Field(
        description="Type of fix action to perform (must match available tool name)"
    )
    target: str = Field(description="Container name or other target for the fix")
    parameters: dict = Field(description="JSON parameters for the tool execution")
    priority: int = Field(
        ge=1, le=5, description="Priority from 1 (lowest) to 5 (highest)"
    )

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        """Normalize action to lowercase."""
        return v.lower()


class RootCausePayload(BaseModel):
    """
    Expected root cause analysis structure from Llama response.

    This model defines the structure of the complete analysis response
    from the AI model, including root cause, affected components,
    and recommended fixes.
    """

    root_cause: str = Field(description="Primary cause of the incident")
    explanation: str = Field(
        description="Detailed explanation of the root cause analysis"
    )
    affected_components: list[str] = Field(
        description="List of components affected by the incident"
    )
    suggested_fixes: list[FixActionPayload] = Field(
        description="Recommended fixes to resolve the incident"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0"
    )
    prevention: str = Field(
        description="Recommendations for preventing similar incidents"
    )


# System prompt for the AI model
_ANALYSIS_SYSTEM_PROMPT: str = """You are a world-class Site Reliability Engineer with deep expertise in:
- Container orchestration (Docker, Kubernetes)
- Database systems (PostgreSQL, MySQL, Redis)
- Application debugging (Node.js, Python, Java, Go)
- Network troubleshooting
- Performance optimization

Given comprehensive system context, perform root cause analysis and provide actionable fixes.

Available MCP Gateway tools will be provided in the user message. Use only the tools listed there.

For each fix, provide structured JSON parameters that match the tool's input schema. 
For example:
- For restart_container: {"container_name": "service-name", "reason": "description"}
- For update_env_vars: {"container_name": "service-name", "env_updates": {"KEY": "value"}}
- For update_resources: {"container_name": "service-name", "resources": {"memory": "512m", "cpu": "0.5"}}

Respond ONLY with a JSON object in this format:
{
    "root_cause": "detailed explanation of the underlying issue",
    "explanation": "step-by-step reasoning of how you arrived at this conclusion",
    "affected_components": ["component1", "component2"],
    "suggested_fixes": [
        {
            "action": "tool_name_from_available_tools",
            "target": "service_name or file_path",
            "parameters": {"structured": "json_parameters"},
            "priority": 1-5
        }
    ],
    "confidence": 0.0-1.0,
    "prevention": "how to prevent this issue in the future"
}"""

# Template for user prompt with full context
_ANALYSIS_USER_PROMPT: str = """Analyze this production incident and provide root cause + fixes:

{full_context}

Your analysis:"""

# Template for human-friendly explanation prompt
_HUMAN_SUMMARY_PROMPT: str = """Convert this technical root cause analysis into a simple, natural language explanation
that a non-technical stakeholder can understand.

Technical Analysis:
{analysis_json}

Write two short paragraphs that cover:
1. What broke
2. Why it broke
3. What is being done to fix it
4. How long remediation is expected to take
"""


class LlamaRootCauseAnalyzer:
    """
    Deep root cause analysis using Llama 4 Scout's long context with Pydantic models.

    This class handles the complete root cause analysis workflow:
    1. Collects comprehensive system context
    2. Formats data for AI analysis
    3. Communicates with the Llama API
    4. Parses and validates responses
    5. Returns structured analysis results

    The analyzer is designed to provide detailed insights into
    why incidents occurred and how to resolve them.
    """

    def __init__(self, settings: LlamaSettings | None = None) -> None:
        """
        Initialize the root cause analyzer with API settings.

        Args:
            settings: API configuration settings. If None, loads from environment.
        """
        self.settings = settings or LlamaSettings.from_env()
        self.client = OpenAI(
            api_key=self.settings.api_key, base_url=self.settings.base_url
        )

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def analyze_root_cause(
        self,
        anomaly_summary: str,
        full_logs: str,
        docker_compose: str | None = None,
        environment_vars: Mapping[str, str] | None = None,
        service_code: str | None = None,
        container_stats: Mapping[str, object] | None = None,
        available_tools: str | None = None,
    ) -> RootCauseAnalysis:
        """
        Perform deep root cause analysis with full system context.

        This is the main method for root cause analysis. It collects all available
        context about the incident, sends it to the AI model, and returns a
        structured analysis with recommended fixes.

        Args:
            anomaly_summary: Summary of the detected anomaly
            full_logs: Complete log history for analysis
            docker_compose: Docker compose configuration
            environment_vars: Environment variables from the container
            service_code: Source code of the service (if available)
            container_stats: Container statistics and state information
            available_tools: Description of available MCP tools

        Returns:
            RootCauseAnalysis with detailed analysis and recommended fixes
        """
        # Build comprehensive context for the AI model
        context = self._build_context(
            anomaly_summary=anomaly_summary,
            full_logs=full_logs,
            docker_compose=docker_compose,
            environment_vars=environment_vars,
            service_code=service_code,
            container_stats=container_stats,
            available_tools=available_tools,
        )

        console.print(
            "[yellow]🧠 Analyzing with Llama 4 Scout "
            f"({len(context)} chars / ~{len(context)//4} tokens)...[/yellow]"
        )

        # Format the context for the AI model
        messages = self._build_analysis_messages(context)

        try:
            # Send the formatted context to the AI model
            completion: ChatCompletion = self.client.chat.completions.create(
                model=self.settings.model,
                messages=[msg.model_dump() for msg in messages],
                temperature=0.2,  # Low temperature for consistent results
                max_tokens=2000,
                response_format={"type": "json_object"},  # Force JSON response
                stream=False,
            )
        except Exception as exc:
            console.print(f"[red]Error contacting Llama API: {exc}[/red]")
            raise LlamaAnalyzerError(f"Failed to contact Llama API: {exc}")

        try:
            # Parse and validate the AI response
            analysis = self._parse_completion(completion)
        except Exception as exc:
            console.print(f"[red]Unable to parse Llama response: {exc}[/red]")
            raise LlamaAnalyzerError(f"Failed to parse Llama response: {exc}")

        # Display results to the console
        console.print("\n[bold green]✓ Root Cause Analysis Complete[/bold green]")
        console.print(f"[cyan]Root Cause:[/cyan] {analysis.root_cause[:200]}...")
        console.print(f"[cyan]Confidence:[/cyan] {analysis.confidence:.0%}")
        console.print(
            f"[cyan]Suggested Fixes:[/cyan] {len(analysis.suggested_fixes)} actions"
        )

        return analysis

    def explain_for_humans(self, analysis: RootCauseAnalysis) -> str:
        """
        Translate technical analysis into a stakeholder-friendly narrative.

        This method takes the technical analysis from the AI model and
        generates a simple, natural language explanation that non-technical
        stakeholders can understand.

        Args:
            analysis: Root cause analysis results from the AI model

        Returns:
            Human-friendly explanation of the incident
        """
        # Format the analysis for the explanation prompt
        messages = self._build_explanation_messages(analysis)

        try:
            # Generate the human-friendly explanation
            completion: ChatCompletion = self.client.chat.completions.create(
                model=self.settings.model,
                messages=[msg.model_dump() for msg in messages],
                temperature=0.7,  # Higher temperature for more natural language
                max_tokens=500,
                stream=False,
            )
        except Exception as exc:
            return f"Error generating explanation: {exc}"

        if not completion.choices:
            return "Unable to generate human-friendly explanation"

        message = completion.choices[0].message
        return message.content or "Unable to generate human-friendly explanation"

    def _build_analysis_messages(self, context: str) -> list[AnalysisMessage]:
        """
        Build validated messages for root cause analysis.

        Formats the system context into a structured conversation
        that the AI model can understand and analyze.

        Args:
            context: Formatted system context for analysis

        Returns:
            List of formatted messages for the AI model
        """
        # Create the user prompt with full context
        user_prompt = _ANALYSIS_USER_PROMPT.format(full_context=context)

        # Return the complete conversation
        messages = [
            AnalysisMessage(role="system", content=_ANALYSIS_SYSTEM_PROMPT),
            AnalysisMessage(role="user", content=user_prompt),
        ]
        return messages

    def _build_explanation_messages(
        self, analysis: RootCauseAnalysis
    ) -> list[AnalysisMessage]:
        """
        Build validated messages for human-friendly explanation.

        Formats the technical analysis for the explanation prompt
        to generate a stakeholder-friendly narrative.

        Args:
            analysis: Root cause analysis results from the AI model

        Returns:
            List of formatted messages for the AI model
        """
        # Format the analysis as JSON for the prompt
        prompt = _HUMAN_SUMMARY_PROMPT.format(
            analysis_json=json.dumps(analysis.model_dump(), indent=2)
        )

        # Return the explanation request
        messages = [
            AnalysisMessage(role="user", content=prompt),
        ]
        return messages

    def _parse_completion(self, completion: ChatCompletion) -> RootCauseAnalysis:
        """
        Parse AI model output into a validated domain object.

        Takes the raw response from the AI model, validates it against
        our expected schema, and converts it to our domain model.

        Args:
            completion: Raw completion response from the AI model

        Returns:
            Validated RootCauseAnalysis

        Raises:
            LlamaAnalyzerError: If the response is invalid or missing
        """
        # Check that we have a valid response
        if not completion.choices:
            raise LlamaAnalyzerError("Empty response from Llama API")

        # Extract the message content from the completion
        message = completion.choices[0].message
        if message.content is None:
            raise LlamaAnalyzerError("Missing content in Llama API response")

        # Parse the JSON response
        payload_raw = json.loads(message.content)

        if not isinstance(payload_raw, Mapping):
            raise LlamaAnalyzerError("Llama response was not a JSON object")

        # Validate with Pydantic model
        try:
            payload = RootCausePayload.model_validate(payload_raw)
        except Exception as e:
            raise LlamaAnalyzerError(f"Invalid response format: {e}")

        # Convert FixActionPayload to FixAction
        suggested_fixes = tuple(
            FixAction(
                action=fix.action,
                target=fix.target,
                details=json.dumps(fix.parameters),  # Convert parameters to JSON string
                priority=fix.priority,
            )
            for fix in payload.suggested_fixes
        )

        # Convert to our domain model
        return RootCauseAnalysis(
            root_cause=payload.root_cause,
            explanation=payload.explanation,
            affected_components=tuple(payload.affected_components),
            suggested_fixes=suggested_fixes,
            confidence=payload.confidence,
            prevention=payload.prevention,
        )

    def _build_context(
        self,
        *,
        anomaly_summary: str,
        full_logs: str,
        docker_compose: str | None,
        environment_vars: Mapping[str, str] | None,
        service_code: str | None,
        container_stats: Mapping[str, object] | None,
        available_tools: str | None,
    ) -> str:
        """
        Build comprehensive context for the AI model.

        Combines all available information about the incident into a
        structured format that the AI model can analyze effectively.

        Args:
            anomaly_summary: Summary of the detected anomaly
            full_logs: Complete log history for analysis
            docker_compose: Docker compose configuration
            environment_vars: Environment variables from the container
            service_code: Source code of the service (if available)
            container_stats: Container statistics and state information
            available_tools: Description of available MCP tools

        Returns:
            Formatted context string for the AI model
        """
        sections: list[str] = [f"# Anomaly Detected\n{anomaly_summary}\n"]

        # Add available tools if provided
        if available_tools:
            sections.append(f"\n# Available MCP Gateway Tools\n{available_tools}")

        # Add container statistics if available
        if container_stats:
            sections.append(
                "\n# Container Stats\n" + json.dumps(dict(container_stats), indent=2)
            )

        # Add environment variables if available
        if environment_vars:
            sections.append(
                "\n# Environment Variables\n"
                + json.dumps(_redact_sensitive(environment_vars), indent=2)
            )

        # Add Docker compose configuration if available
        if docker_compose:
            sections.append(
                f"\n# Docker Compose Configuration\n```yaml\n{docker_compose}\n```"
            )

        # Add service code if available
        if service_code:
            sections.append(f"\n# Service Code\n```\n{service_code}\n```")

        # Add complete log history
        sections.append(
            (
                f"\n# Complete Log History ({len(full_logs)} characters)\n"
                f"```\n{full_logs}\n```"
            )
        )

        return "\n".join(sections)


def _redact_sensitive(env_vars: Mapping[str, str]) -> Mapping[str, str]:
    """
    Redact sensitive information from environment variables.

    Replaces values of sensitive environment variables (keys, secrets,
    passwords, tokens) with placeholder text to prevent exposing
    sensitive information in logs or AI prompts.

    Args:
        env_vars: Dictionary of environment variables

    Returns:
        Dictionary with sensitive values redacted
    """
    redacted: dict[str, str] = {}
    for key, value in env_vars.items():
        lowered = key.lower()
        if any(token in lowered for token in ("key", "secret", "password", "token")):
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted


if __name__ == "__main__":
    """
    Example usage of the Llama root cause analyzer.

    This block demonstrates how to use the analyzer with sample incident data.
    It's primarily for testing and demonstration purposes.
    """
    from dotenv import load_dotenv

    load_dotenv()
    analyzer = LlamaRootCauseAnalyzer()

    sample_logs = (
        """
2025-09-30 12:00:01 INFO Starting API server on port 3001
2025-09-30 12:00:02 INFO Connecting to database at postgresql://postgres@postgres:5432/demo_db
2025-09-30 12:00:03 ERROR Connection failed: getaddrinfo ENOTFOUND postgres
2025-09-30 12:00:04 INFO Retrying connection (1/5)...
2025-09-30 12:00:05 ERROR Connection failed: getaddrinfo ENOTFOUND postgres
2025-09-30 12:00:10 ERROR Connection failed: getaddrinfo ENOTFOUND postgres
2025-09-30 12:00:15 FATAL Unable to connect to database after 5 retries. Exiting.
2025-09-30 12:00:16 INFO Process exited with code 1
"""
        * 10
    )

    sample_compose = """
version: '3.8'
services:
  api:
    image: node:20-alpine
    environment:
      - DATABASE_URL=postgresql://postgres:wrongpassword@postgres:5432/demo_db
    depends_on:
      - postgres
  postgres:
    image: postgres:15-alpine
    environment:
      - POSTGRES_PASSWORD=demo_password
"""

    result = analyzer.analyze_root_cause(
        anomaly_summary="Database connection failures, service crashed",
        full_logs=sample_logs,
        docker_compose=sample_compose,
        container_stats={"restarts": 3, "status": "exited", "exit_code": 1},
    )

    console.print("\n[bold]Analysis Result:[/bold]")
    console.print(json.dumps(result.model_dump(), indent=2))

    console.print("\n[bold]Human-Friendly Explanation:[/bold]")
    explanation = analyzer.explain_for_humans(result)
    console.print(explanation)
