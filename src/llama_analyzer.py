"""Meta Llama root-cause analyzer with consistent typing."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from openai import OpenAI
from openai.types.chat import ChatCompletion
from rich.console import Console
from tenacity import retry, stop_after_attempt, wait_exponential

from sentinel_types import RootCauseAnalysis

console = Console()


class LlamaAnalyzerError(RuntimeError):
    """Raised when the Llama API returns unusable data."""


@dataclass(slots=True, frozen=True)
class LlamaSettings:
    """Configuration for connecting to OpenRouter / OpenAI compatible APIs."""

    api_key: str
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "meta-llama/llama-4-scout"

    @classmethod
    def from_env(cls) -> "LlamaSettings":
        api_key = os.getenv("LLAMA_API_KEY")
        if not api_key:
            raise ValueError("LLAMA_API_KEY not found in environment")
        default_base = "https://openrouter.ai/api/v1"
        default_model = "meta-llama/llama-4-scout"
        base = os.getenv("LLAMA_API_BASE", default_base)
        model = os.getenv("LLAMA_MODEL", default_model)
        return cls(api_key=api_key, base_url=base, model=model)


class LlamaRootCauseAnalyzer:
    """Deep root cause analysis using Llama 4 Scout's long context."""

    def __init__(self, settings: LlamaSettings | None = None) -> None:
        self.settings = settings or LlamaSettings.from_env()
        self.client = OpenAI(api_key=self.settings.api_key, base_url=self.settings.base_url)

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
    ) -> RootCauseAnalysis:
        """Perform deep root cause analysis with full system context."""

        context = self._build_context(
            anomaly_summary=anomaly_summary,
            full_logs=full_logs,
            docker_compose=docker_compose,
            environment_vars=environment_vars,
            service_code=service_code,
            container_stats=container_stats,
        )

        console.print(
            "[yellow]🧠 Analyzing with Llama 4 Scout "
            f"({len(context)} chars / ~{len(context)//4} tokens)...[/yellow]"
        )

        prompt = _ANALYSIS_SYSTEM_PROMPT
        user_prompt = _ANALYSIS_USER_PROMPT.format(full_context=context)

        try:
            completion: ChatCompletion = self.client.chat.completions.create(
                model=self.settings.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=2000,
                response_format={"type": "json_object"},
                stream=False,
            )
        except Exception as exc:
            console.print(f"[red]Error contacting Llama API: {exc}[/red]")
            return _fallback_analysis(str(exc))

        try:
            analysis = self._parse_completion(completion)
        except Exception as exc:
            console.print(f"[red]Unable to parse Llama response: {exc}[/red]")
            return _fallback_analysis(str(exc))

        console.print("\n[bold green]✓ Root Cause Analysis Complete[/bold green]")
        console.print(f"[cyan]Root Cause:[/cyan] {analysis.root_cause[:200]}...")
        console.print(f"[cyan]Confidence:[/cyan] {analysis.confidence:.0%}")
        console.print(
            f"[cyan]Suggested Fixes:[/cyan] {len(analysis.suggested_fixes)} actions"
        )

        return analysis

    def explain_for_humans(self, analysis: RootCauseAnalysis) -> str:
        """Translate technical analysis into a stakeholder-friendly narrative."""

        prompt = _HUMAN_SUMMARY_PROMPT.format(
            analysis_json=json.dumps(analysis.to_dict(), indent=2)
        )

        try:
            completion: ChatCompletion = self.client.chat.completions.create(
                model=self.settings.model,
                messages=[{"role": "user", "content": prompt}],
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

    # ------------------------------------------------------------------
    def _parse_completion(self, completion: ChatCompletion) -> RootCauseAnalysis:
        if not completion.choices:
            raise LlamaAnalyzerError("Empty response from Llama API")

        message = completion.choices[0].message
        if message.content is None:
            raise LlamaAnalyzerError("Missing content in Llama API response")

        payload = json.loads(message.content)
        if not isinstance(payload, Mapping):
            raise LlamaAnalyzerError("Llama response was not a JSON object")

        payload_mapping = cast(Mapping[str, object], payload)
        return RootCauseAnalysis.from_mapping(payload_mapping)

    def _build_context(
        self,
        *,
        anomaly_summary: str,
        full_logs: str,
        docker_compose: str | None,
        environment_vars: Mapping[str, str] | None,
        service_code: str | None,
        container_stats: Mapping[str, object] | None,
    ) -> str:
        sections: list[str] = [f"# Anomaly Detected\n{anomaly_summary}\n"]

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
            sections.append(f"\n# Docker Compose Configuration\n```yaml\n{docker_compose}\n```")

        if service_code:
            sections.append(f"\n# Service Code\n```\n{service_code}\n```")

        sections.append(
            (
                f"\n# Complete Log History ({len(full_logs)} characters)\n"
                f"```\n{full_logs}\n```"
            )
        )

        return "\n".join(sections)


def _redact_sensitive(env_vars: Mapping[str, str]) -> Mapping[str, str]:
    redacted: dict[str, str] = {}
    for key, value in env_vars.items():
        lowered = key.lower()
        if any(token in lowered for token in ("key", "secret", "password", "token")):
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted


def _fallback_analysis(error: str) -> RootCauseAnalysis:
    return RootCauseAnalysis(
        root_cause=f"Error analyzing: {error}",
        explanation="Unable to complete analysis",
        affected_components=(),
        suggested_fixes=(),
        confidence=0.0,
        prevention="",
    )


_ANALYSIS_SYSTEM_PROMPT = """You are a world-class Site Reliability Engineer with deep expertise in:
- Container orchestration (Docker, Kubernetes)
- Database systems (PostgreSQL, MySQL, Redis)
- Application debugging (Node.js, Python, Java, Go)
- Network troubleshooting
- Performance optimization

Given comprehensive system context, perform root cause analysis and provide actionable fixes.

Respond ONLY with a JSON object in this format:
{
    "root_cause": "detailed explanation of the underlying issue",
    "explanation": "step-by-step reasoning of how you arrived at this conclusion",
    "affected_components": ["component1", "component2"],
    "suggested_fixes": [
        {
            "action": "restart_container|update_config|patch_code|scale_resources",
            "target": "service_name or file_path",
            "details": "specific change to make",
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


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    analyzer = LlamaRootCauseAnalyzer()

    sample_logs = """
2025-09-30 12:00:01 INFO Starting API server on port 3001
2025-09-30 12:00:02 INFO Connecting to database at postgresql://postgres@postgres:5432/demo_db
2025-09-30 12:00:03 ERROR Connection failed: getaddrinfo ENOTFOUND postgres
2025-09-30 12:00:04 INFO Retrying connection (1/5)...
2025-09-30 12:00:05 ERROR Connection failed: getaddrinfo ENOTFOUND postgres
2025-09-30 12:00:10 ERROR Connection failed: getaddrinfo ENOTFOUND postgres
2025-09-30 12:00:15 FATAL Unable to connect to database after 5 retries. Exiting.
2025-09-30 12:00:16 INFO Process exited with code 1
""" * 10

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
    console.print(json.dumps(result.to_dict(), indent=2))

    console.print("\n[bold]Human-Friendly Explanation:[/bold]")
    explanation = analyzer.explain_for_humans(result)
    console.print(explanation)
