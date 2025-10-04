"""
OpenRouter client factory for AI model access.

Provides a centralized way to create OpenAI-compatible clients
configured for OpenRouter API access.
"""

from __future__ import annotations

from openai import OpenAI


def create_openrouter_client(api_key: str, base_url: str = "https://openrouter.ai/api/v1") -> OpenAI:
    """
    Create an OpenAI client configured for OpenRouter.

    Args:
        api_key: OpenRouter API key
        base_url: Base URL for OpenRouter API (default: https://openrouter.ai/api/v1)

    Returns:
        Configured OpenAI client instance
    """
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        default_headers={
            "HTTP-Referer": "https://github.com/sre-sentinel",
            "X-Title": "SRE-Sentinel"
        }
    )
