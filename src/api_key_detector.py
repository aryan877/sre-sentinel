"""
API key and secret detection utilities.

Provides intelligent pattern-based detection of sensitive information
in environment variables and configuration values.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping

from rich.console import Console

console = Console()


def fallback_secret_detection(
    env_var_names: list[str], env_var_values: Mapping[str, str] | None = None
) -> set[str]:
    """
    Smart fallback for detecting secrets when AI classification is unavailable.

    Uses multiple heuristics:
    1. Keyword matching in names
    2. URL pattern detection (e.g., postgresql://user:password@host)
    3. API key format detection (e.g., sk-, pk-, UUID patterns)
    4. High entropy strings (likely random secrets)
    5. Base64 encoded patterns
    """
    console.print(
        "[yellow]🔍 Using intelligent pattern-based secret detection (fallback)[/yellow]"
    )

    sensitive_keys = set()

    # Heuristic 1: Keyword matching in names
    sensitive_keywords = {
        "key", "secret", "password", "token", "auth", "credential",
        "private", "cert", "api", "jwt", "oauth", "session"
    }

    for name in env_var_names:
        lowered_name = name.lower()

        # Check for keywords
        if any(keyword in lowered_name for keyword in sensitive_keywords):
            sensitive_keys.add(name)
            continue

        # Check for database/service URLs (likely contain passwords)
        if any(pattern in lowered_name for pattern in ["_url", "_uri", "_dsn", "_connection"]):
            sensitive_keys.add(name)
            continue

        # Check for cloud provider patterns
        if any(lowered_name.startswith(prefix) for prefix in ["aws_", "gcp_", "azure_", "cloudflare_"]):
            if not lowered_name.endswith(("_region", "_zone", "_endpoint", "_bucket")):
                sensitive_keys.add(name)
                continue

    # Heuristic 2: Analyze values if provided
    if env_var_values:
        for name, value in env_var_values.items():
            if not value or name in sensitive_keys:
                continue

            # Pattern: URL with embedded credentials (user:password@host)
            if has_embedded_credentials(value):
                sensitive_keys.add(name)
                continue

            # Pattern: API key formats (sk-, pk-, hex strings, etc.)
            if looks_like_api_key(value):
                sensitive_keys.add(name)
                continue

            # Pattern: High entropy (likely random secret)
            if has_high_entropy(value):
                sensitive_keys.add(name)
                continue

    console.print(
        f"[green]✓ Detected {len(sensitive_keys)}/{len(env_var_names)} as potentially sensitive[/green]"
    )

    return sensitive_keys


def has_embedded_credentials(value: str) -> bool:
    """Check if value contains URL with embedded credentials (user:password@host)."""
    # Matches: scheme://user:password@host or scheme://user:password@host:port
    url_with_password = re.compile(r"://[^:/@\s]+:[^@\s]+@")
    return bool(url_with_password.search(value))


def looks_like_api_key(value: str) -> bool:
    """Check if value looks like an API key or token."""
    value_stripped = value.strip()

    # Common API key prefixes
    if any(value_stripped.startswith(prefix) for prefix in [
        "sk-", "pk-", "tok_", "key_", "api_", "Bearer ", "ghp_", "gho_", "ghs_"
    ]):
        return True

    # Long hex strings (e.g., 32+ chars)
    if re.match(r"^[a-fA-F0-9]{32,}$", value_stripped):
        return True

    # UUID format
    if re.match(
        r"^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$",
        value_stripped
    ):
        return True

    # JWT format (3 base64 segments separated by dots)
    if re.match(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$", value_stripped):
        parts = value_stripped.split(".")
        if all(len(part) > 10 for part in parts):
            return True

    # Long base64 strings (64+ chars)
    if re.match(r"^[A-Za-z0-9+/]{64,}={0,2}$", value_stripped):
        return True

    return False


def has_high_entropy(value: str) -> bool:
    """
    Check if value has high entropy (randomness), indicating it's likely a secret.

    Uses Shannon entropy calculation. Secrets typically have entropy > 4.5.
    """
    if len(value) < 16:
        return False  # Too short to be meaningful

    # Calculate Shannon entropy
    counter = Counter(value)
    length = len(value)
    entropy = -sum(
        (count / length) * math.log2(count / length)
        for count in counter.values()
    )

    # High entropy threshold (adjusted for base64/hex)
    # Typical thresholds:
    # - Random base64: ~6.0
    # - Random hex: ~4.0
    # - English text: ~4.0
    # - Passwords: ~4.5-5.5
    return entropy > 4.5 and len(value) >= 20


def redact_url_passwords(value: str) -> str:
    """
    Redact passwords from URLs while preserving the rest of the URL.

    Examples:
        postgresql://user:password@host/db → postgresql://user:***REDACTED***@host/db
        redis://:password@host:6379 → redis://:***REDACTED***@host:6379
        mongodb://user:pass@host:27017/db → mongodb://user:***REDACTED***@host:27017/db
    """
    # Pattern: scheme://[user]:password@host
    # Captures: scheme, optional user, password, rest of URL
    url_password_pattern = re.compile(r"(://(?:[^:/@\s]+:)?)([^@\s]+)(@)")

    def replace_password(match):
        return f"{match.group(1)}***REDACTED***{match.group(3)}"

    return url_password_pattern.sub(replace_password, value)
