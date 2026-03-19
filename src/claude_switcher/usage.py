"""Fetch Claude API usage stats via the OAuth usage endpoint."""

import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

from claude_switcher import keychain

USAGE_URL = "https://api.anthropic.com/oauth/usage"


def _extract_token(creds_json: str) -> str | None:
    """Extract the OAuth access token from a credentials JSON blob."""
    try:
        data = json.loads(creds_json)
        return data.get("claudeAiOauth", {}).get("accessToken")
    except (json.JSONDecodeError, AttributeError):
        return None


def fetch_usage(service: str) -> dict | None:
    """Fetch usage for a Keychain service. Returns parsed JSON or None on failure.

    Response format:
        {
            "five_hour": {"utilization": 42.5, "resets_at": "..."},
            "seven_day": {"utilization": 18.3, "resets_at": "..."}
        }
    """
    creds = keychain.read_credentials(service)
    if not creds:
        return None

    token = _extract_token(creds)
    if not token:
        return None

    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Accept": "application/json",
            "anthropic-beta": "oauth-2025-04-20",
            "Authorization": f"Bearer {token}",
            "User-Agent": "claude-code/2.1.11",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None


def fetch_usage_for_account(email: str) -> dict | None:
    """Fetch usage for a saved account by email."""
    return fetch_usage(f"claude-switcher:{email}")


def fetch_active_usage() -> dict | None:
    """Fetch usage for the currently active Claude Code session."""
    return fetch_usage(keychain.CLAUDE_SERVICE)


def _format_reset_delta(resets_at: str) -> str:
    """Convert an ISO 8601 resets_at timestamp to a human-readable relative time."""
    try:
        # Strip fractional seconds for simpler parsing
        cleaned = resets_at.replace("Z", "+00:00")
        reset_dt = datetime.fromisoformat(cleaned)
        now = datetime.now(timezone.utc)
        diff = int((reset_dt - now).total_seconds())

        if diff <= 0:
            return "now"

        days = diff // 86400
        hours = (diff % 86400) // 3600
        minutes = (diff % 3600) // 60

        if days > 0:
            return f"{days}d {hours}h"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    except (ValueError, TypeError):
        return "?"


def format_usage(usage: dict | None) -> str:
    """Format usage data into a readable string."""
    if not usage:
        return "Usage indisponible"

    parts = []
    five_h = usage.get("five_hour", {})
    seven_d = usage.get("seven_day", {})

    if "utilization" in five_h:
        pct = f"{five_h['utilization']:.0f}%"
        reset = f" ({_format_reset_delta(five_h['resets_at'])})" if "resets_at" in five_h else ""
        parts.append(f"5h {pct}{reset}")
    if "utilization" in seven_d:
        pct = f"{seven_d['utilization']:.0f}%"
        reset = f" ({_format_reset_delta(seven_d['resets_at'])})" if "resets_at" in seven_d else ""
        parts.append(f"7j {pct}{reset}")

    return " | ".join(parts) if parts else "Usage indisponible"
