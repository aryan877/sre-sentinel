"""
Llama AI client for root cause analysis of incidents.
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

from sentinel_types import RootCauseAnalysis, FixAction, FixActionName

console = Console()


class LlamaAnalyzerError(RuntimeError):
    """Custom exception for Llama analyzer errors."""


class LlamaSettings(BaseModel):
    """Configuration settings for Llama API access."""

    api_key: str = Field(description="API key for Llama authentication")
    base_url: str = Field(
        default="https://openrouter.ai/api/v1", description="Base URL for the API"
    )
    model: str = Field(
        default="meta-llama/llama-4-scout", description="Model name to use for analysis"
    )

    @classmethod
    def from_env(cls) -> "LlamaSettings":
        """Create settings from environment variables."""
        api_key = os.getenv("LLAMA_API_KEY")
        if not api_key:
            raise ValueError("LLAMA_API_KEY not found in environment")
        return cls(
            api_key=api_key,
            base_url=os.getenv("LLAMA_API_BASE", "https://openrouter.ai/api/v1"),
            model=os.getenv("LLAMA_MODEL", "meta-llama/llama-4-scout"),
        )


class AnalysisMessage(BaseModel):
    """Chat message structure for Llama API."""

    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class FixActionPayload(BaseModel):
    """Expected fix action structure from Llama response."""

    action: str = Field(description="Type of fix action to perform")
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
    """Expected root cause analysis structure from Llama response."""

    root_cause: str
    explanation: str
    affected_components: list[str]
    suggested_fixes: list[FixActionPayload]
    confidence: float = Field(ge=0.0, le=1.0)
    prevention: str


_ANALYSIS_SYSTEM_PROMPT = """You are a world-class Site Reliability Engineer with deep expertise in:
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

_ANALYSIS_USER_PROMPT = """Analyze this production incident and provide root cause + fixes:

{full_context}

Your analysis:"""

_HUMAN_SUMMARY_PROMPT = """Convert this technical root cause analysis into a simple, natural language explanation
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
    """Deep root cause analysis using Llama 4 Scout's long context."""

    def __init__(self, settings: LlamaSettings | None = None) -> None:
        """Initialize the root cause analyzer with API settings."""
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
        """Perform deep root cause analysis with full system context."""
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

        messages = self._build_analysis_messages(context)

        try:
            completion: ChatCompletion = self.client.chat.completions.create(
                model=self.settings.model,
                messages=[msg.model_dump() for msg in messages],
                temperature=0.2,
                max_tokens=2000,
                response_format={"type": "json_object"},
                stream=False,
            )
        except Exception as exc:
            console.print(f"[red]Error contacting Llama API: {exc}[/red]")
            raise LlamaAnalyzerError(f"Failed to contact Llama API: {exc}")

        try:
            analysis = self._parse_completion(completion)
        except Exception as exc:
            console.print(f"[red]Unable to parse Llama response: {exc}[/red]")
            raise LlamaAnalyzerError(f"Failed to parse Llama response: {exc}")

        console.print("\n[bold green]✓ Root Cause Analysis Complete[/bold green]")
        console.print(f"[cyan]Root Cause:[/cyan] {analysis.root_cause[:200]}...")
        console.print(f"[cyan]Confidence:[/cyan] {analysis.confidence:.0%}")
        console.print(
            f"[cyan]Suggested Fixes:[/cyan] {len(analysis.suggested_fixes)} actions"
        )

        return analysis

    def explain_for_humans(self, analysis: RootCauseAnalysis) -> str:
        """Translate technical analysis into a stakeholder-friendly narrative."""
        messages = self._build_explanation_messages(analysis)

        try:
            completion: ChatCompletion = self.client.chat.completions.create(
                model=self.settings.model,
                messages=[msg.model_dump() for msg in messages],
                temperature=0.7,
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
        """Build validated messages for root cause analysis."""
        user_prompt = _ANALYSIS_USER_PROMPT.format(full_context=context)

        return [
            AnalysisMessage.model_validate(
                {"role": "system", "content": _ANALYSIS_SYSTEM_PROMPT}
            ),
            AnalysisMessage.model_validate({"role": "user", "content": user_prompt}),
        ]

    def _build_explanation_messages(
        self, analysis: RootCauseAnalysis
    ) -> list[AnalysisMessage]:
        """Build validated messages for human-friendly explanation."""
        prompt = _HUMAN_SUMMARY_PROMPT.format(
            analysis_json=json.dumps(analysis.model_dump(), indent=2)
        )

        return [
            AnalysisMessage.model_validate({"role": "user", "content": prompt}),
        ]

    def _parse_completion(self, completion: ChatCompletion) -> RootCauseAnalysis:
        """Parse AI model output into a validated domain object."""
        if not completion.choices:
            raise LlamaAnalyzerError("Empty response from Llama API")

        message = completion.choices[0].message
        if message.content is None:
            raise LlamaAnalyzerError("Missing content in Llama API response")

        payload_raw = json.loads(message.content)

        if not isinstance(payload_raw, Mapping):
            raise LlamaAnalyzerError("Llama response was not a JSON object")

        try:
            payload = RootCausePayload.model_validate(payload_raw)
        except Exception as e:
            raise LlamaAnalyzerError(f"Invalid response format: {e}")

        suggested_fixes = tuple(
            FixAction(
                action=FixActionName(fix.action),
                target=fix.target,
                details=json.dumps(fix.parameters),
                priority=fix.priority,
            )
            for fix in payload.suggested_fixes
        )

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
        """Build comprehensive context for the AI model."""
        sections: list[str] = [f"# Anomaly Detected\n{anomaly_summary}\n"]

        if available_tools:
            sections.append(f"\n# Available MCP Gateway Tools\n{available_tools}")

        if container_stats:
            sections.append(
                "\n# Container Stats\n" + json.dumps(dict(container_stats), indent=2)
            )

        if environment_vars:
            sections.append(
                "\n# Environment Variables\n"
                + json.dumps(_redact_sensitive(environment_vars), indent=2)
            )

        if docker_compose:
            sections.append(
                f"\n# Docker Compose Configuration\n```yaml\n{docker_compose}\n```"
            )

        if service_code:
            sections.append(f"\n# Service Code\n```\n{service_code}\n```")

        sections.append(
            f"\n# Complete Log History ({len(full_logs)} characters)\n"
            f"```\n{full_logs}\n```"
        )

        return "\n".join(sections)


def _redact_sensitive(env_vars: Mapping[str, str]) -> Mapping[str, str]:
    """Redact sensitive information from environment variables."""
    redacted: dict[str, str] = {}
    for key, value in env_vars.items():
        lowered = key.lower()
        if any(token in lowered for token in ("key", "secret", "password", "token")):
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted


if __name__ == "__main__":
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
