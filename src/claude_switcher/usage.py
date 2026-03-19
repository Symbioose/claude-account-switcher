"""Fetch Claude API usage stats via the OAuth usage endpoint."""

import json
import urllib.request
import urllib.error

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


def format_usage(usage: dict | None) -> str:
    """Format usage data into a readable string."""
    if not usage:
        return "Usage indisponible"

    parts = []
    five_h = usage.get("five_hour", {})
    seven_d = usage.get("seven_day", {})

    if "utilization" in five_h:
        parts.append(f"5h: {five_h['utilization']:.0f}%")
    if "utilization" in seven_d:
        parts.append(f"7j: {seven_d['utilization']:.0f}%")

    return " | ".join(parts) if parts else "Usage indisponible"
