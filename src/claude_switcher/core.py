"""Business logic for account management."""

import json
import re
import shutil
import subprocess
from pathlib import Path

from claude_switcher import keychain
from claude_switcher.config import (
    AccountInfo,
    add_account,
    get_active_account,
    load_accounts,
    remove_account,
    set_active_account,
    DEFAULT_CONFIG_PATH,
)

CLAUDE_SERVICE = keychain.CLAUDE_SERVICE
CLAUDE_STATE_FILE = Path.home() / ".claude.json"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(email: str) -> str:
    """Validate email before using it in Keychain service names."""
    if not _EMAIL_RE.match(email) or len(email) > 254:
        raise RuntimeError(f"Invalid email format: {email}")
    return email


def _read_oauth_account() -> dict | None:
    """Read the oauthAccount object from ~/.claude.json."""
    try:
        data = json.loads(CLAUDE_STATE_FILE.read_text())
        return data.get("oauthAccount")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _write_oauth_account(oauth_account: dict) -> None:
    """Write the oauthAccount object into ~/.claude.json (merge, not overwrite)."""
    try:
        data = json.loads(CLAUDE_STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    data["oauthAccount"] = oauth_account
    CLAUDE_STATE_FILE.write_text(json.dumps(data))


_EXTRA_PATHS = [
    Path.home() / ".local" / "bin",
    Path("/usr/local/bin"),
    Path("/opt/homebrew/bin"),
]


def _find_claude() -> str | None:
    """Find the claude binary, checking common install locations beyond PATH."""
    found = shutil.which("claude")
    if found:
        return found
    for d in _EXTRA_PATHS:
        candidate = d / "claude"
        if candidate.is_file():
            return str(candidate)
    return None


def check_claude_cli() -> bool:
    """Check if the claude CLI is available."""
    return _find_claude() is not None


def _claude_cmd() -> str:
    """Return the path to the claude binary, or 'claude' as fallback."""
    return _find_claude() or "claude"


def get_auth_status() -> dict | None:
    """Run `claude auth status --json` and return parsed JSON, or None on failure."""
    result = subprocess.run(
        [_claude_cmd(), "auth", "status", "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def run_auth_logout() -> None:
    """Run `claude auth logout`."""
    subprocess.run([_claude_cmd(), "auth", "logout"], capture_output=True, text=True)


def run_auth_login() -> bool:
    """Run `claude auth login`. Returns True if successful (exit code 0)."""
    result = subprocess.run([_claude_cmd(), "auth", "login"])
    return result.returncode == 0


def import_current_account(config_path: Path = DEFAULT_CONFIG_PATH) -> AccountInfo | None:
    """Import the currently logged-in Claude Code account. Returns AccountInfo or None."""
    creds = keychain.read_credentials(CLAUDE_SERVICE)
    if not creds:
        return None

    acct_attr = keychain.read_account_attribute(CLAUDE_SERVICE) or "unknown"

    status = get_auth_status()
    if status and status.get("email"):
        email = status["email"]
        sub_type = status.get("subscriptionType", "unknown")
        org_name = status.get("orgName", "")
    else:
        try:
            email = json.loads(creds).get("email", "unknown@unknown")
        except (json.JSONDecodeError, AttributeError):
            return None
        sub_type = "unknown"
        org_name = ""

    _validate_email(email)
    keychain.write_credentials(f"claude-switcher:{email}", acct_attr, creds)

    oauth_account = _read_oauth_account()

    account = AccountInfo(
        email=email,
        subscription_type=sub_type,
        org_name=org_name,
        active=True,
        keychain_account=acct_attr,
        oauth_account=oauth_account,
    )
    add_account(account, config_path)
    set_active_account(email, config_path)
    return account


def switch_account(target_email: str, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Switch to a different account. Saves current credentials first."""
    active = get_active_account(config_path)

    if active:
        current_creds = keychain.read_credentials(CLAUDE_SERVICE)
        if current_creds:
            keychain.write_credentials(
                f"claude-switcher:{active.email}", active.keychain_account, current_creds
            )
        # Save current oauthAccount state from ~/.claude.json
        current_oauth = _read_oauth_account()
        if current_oauth:
            active.oauth_account = current_oauth
            add_account(active, config_path)

    _validate_email(target_email)
    target_creds = keychain.read_credentials(f"claude-switcher:{target_email}")
    if not target_creds:
        raise RuntimeError(f"Credentials not found in Keychain for {target_email}")

    accounts = load_accounts(config_path)
    target_account = next((a for a in accounts if a.email == target_email), None)
    if not target_account:
        raise RuntimeError(f"Account {target_email} not found in config")

    keychain.write_credentials(CLAUDE_SERVICE, target_account.keychain_account, target_creds)

    # Restore target's oauthAccount into ~/.claude.json
    if target_account.oauth_account:
        _write_oauth_account(target_account.oauth_account)

    set_active_account(target_email, config_path)


def add_new_account(config_path: Path = DEFAULT_CONFIG_PATH) -> AccountInfo | None:
    """Add a new account via claude auth login. Returns AccountInfo or None if cancelled."""
    active = get_active_account(config_path)
    if active:
        current_creds = keychain.read_credentials(CLAUDE_SERVICE)
        if current_creds:
            keychain.write_credentials(
                f"claude-switcher:{active.email}", active.keychain_account, current_creds
            )

    run_auth_logout()

    # Ensure all "Claude Code-credentials" entries are gone before login.
    # claude auth logout may not clean up the Keychain properly, and leftover
    # entries cause security find-generic-password -w to return the OLD token
    # instead of the freshly-issued one after login.
    while keychain.delete_credentials(CLAUDE_SERVICE):
        pass

    if not run_auth_login():
        if active:
            prev_creds = keychain.read_credentials(f"claude-switcher:{active.email}")
            if prev_creds:
                keychain.write_credentials(CLAUDE_SERVICE, active.keychain_account, prev_creds)
        return None

    try:
        return import_current_account(config_path)
    except Exception:
        # Login succeeded but import failed — restore previous account
        if active:
            prev_creds = keychain.read_credentials(f"claude-switcher:{active.email}")
            if prev_creds:
                keychain.write_credentials(CLAUDE_SERVICE, active.keychain_account, prev_creds)
        return None


def remove_saved_account(email: str, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Remove a saved account from config and Keychain."""
    keychain.delete_credentials(f"claude-switcher:{email}")
    remove_account(email, config_path)
