"""Business logic for Codex CLI account management."""

import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

from claude_switcher import keychain
from claude_switcher.cli_paths import cli_env, find_cli
from claude_switcher.config import (
    AccountInfo,
    add_account,
    get_active_account,
    load_accounts,
    remove_account,
    save_accounts,
    set_active_account,
    DEFAULT_CONFIG_PATH,
)

CODEX_HOME = Path.home() / ".codex"
CODEX_AUTH_FILE = CODEX_HOME / "auth.json"
CODEX_CONFIG_FILE = CODEX_HOME / "config.toml"
CODEX_KEYCHAIN_PREFIX = "codex-switcher:"
CODEX_LOGIN_TIMEOUT_SECONDS = 300
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_KEYRING_UNSUPPORTED_MESSAGE = (
    "Codex keyring credential storage is not supported yet. "
    'Set cli_auth_credentials_store = "file" in ~/.codex/config.toml and run codex login.'
)
CODEX_SESSION_EXPIRED_MESSAGE = (
    "This saved Codex session has expired. Please add the Codex account again to sign in."
)


class CodexCredentialsExpiredError(RuntimeError):
    """Raised when Codex refresh tokens have already been consumed or revoked."""

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _find_codex() -> str | None:
    """Find the codex binary, checking common install locations beyond PATH."""
    found = shutil.which("codex")
    if found:
        return found
    return find_cli("codex")


def check_codex_cli() -> bool:
    """Check if the Codex CLI is available."""
    return _find_codex() is not None


def _codex_cmd() -> str:
    """Return the path to the Codex binary, or 'codex' as fallback."""
    return _find_codex() or "codex"


def get_codex_auth_status() -> dict | None:
    """Run `codex login status`. Returns a simple dict on success."""
    cmd = _codex_cmd()
    result = subprocess.run(
        [cmd, "login", "status"],
        capture_output=True,
        text=True,
        env=cli_env(cmd),
    )
    if result.returncode != 0:
        return None
    return {"loggedIn": True, "message": result.stdout.strip() or result.stderr.strip()}


def _validate_email(email: str) -> str:
    """Validate email before using it in Keychain service names."""
    if not _EMAIL_RE.match(email) or len(email) > 254:
        raise RuntimeError(f"Invalid email format: {email}")
    return email


def _codex_credentials_store() -> str:
    """Read the configured Codex credential store."""
    try:
        data = tomllib.loads(CODEX_CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return "auto"
    store = data.get("cli_auth_credentials_store", "auto")
    return store if store in {"file", "keyring", "auto"} else "auto"


def _read_codex_credentials_from_file() -> str | None:
    try:
        content = CODEX_AUTH_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return content or None


def normalize_codex_credentials_blob(creds: str | None) -> str | None:
    """Return a JSON auth blob, decoding hex-encoded Keychain output when needed."""
    if not creds:
        return creds

    raw = creds.strip()
    try:
        if isinstance(json.loads(raw), dict):
            return raw
    except json.JSONDecodeError:
        pass

    compact = "".join(raw.split())
    if len(compact) % 2 != 0 or not re.fullmatch(r"[0-9a-fA-F]+", compact):
        return raw

    try:
        decoded = bytes.fromhex(compact).decode("utf-8").strip()
        if isinstance(json.loads(decoded), dict):
            return decoded
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return raw

    return raw


def read_codex_credentials() -> str | None:
    """Read Codex credentials from ~/.codex/auth.json."""
    store = _codex_credentials_store()
    if store == "keyring":
        raise RuntimeError(CODEX_KEYRING_UNSUPPORTED_MESSAGE)

    creds = _read_codex_credentials_from_file()
    if not creds and store == "auto":
        raise RuntimeError(CODEX_KEYRING_UNSUPPORTED_MESSAGE)
    return normalize_codex_credentials_blob(creds)


def _read_codex_credentials_for_import() -> str | None:
    """Read file-mode credentials without treating a missing file as a hard failure."""
    store = _codex_credentials_store()
    if store == "keyring":
        raise RuntimeError(CODEX_KEYRING_UNSUPPORTED_MESSAGE)
    return normalize_codex_credentials_blob(_read_codex_credentials_from_file())


def _decode_jwt_payload(token: str) -> dict | None:
    """Decode a JWT payload without verification."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return None


def _credentials_data(creds_json: str | None = None) -> dict | None:
    try:
        raw = creds_json if creds_json is not None else read_codex_credentials()
        raw = normalize_codex_credentials_blob(raw)
        data = json.loads(raw) if raw else None
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, RuntimeError):
        return None


def refresh_codex_credentials(creds_json: str) -> str | None:
    """Refresh Codex OAuth credentials, returning an updated auth.json blob."""
    data = _credentials_data(creds_json)
    if not data:
        return None

    tokens = data.get("tokens", {})
    if not isinstance(tokens, dict) or not tokens.get("refresh_token"):
        return None

    body = urlencode({
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": CODEX_OAUTH_CLIENT_ID,
    }).encode("utf-8")
    req = Request(CODEX_OAUTH_TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")

    try:
        with urlopen(req, timeout=15) as resp:
            refreshed = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        if exc.code in {400, 401} and (
            "already been used" in body_text
            or "invalid_grant" in body_text
            or "token_invalidated" in body_text
        ):
            raise CodexCredentialsExpiredError(CODEX_SESSION_EXPIRED_MESSAGE) from exc
        return None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None

    for key in ("access_token", "refresh_token", "id_token"):
        if refreshed.get(key):
            tokens[key] = refreshed[key]
    for key in ("token_type", "expires_in", "account_id"):
        if refreshed.get(key):
            tokens[key] = refreshed[key]
    data["tokens"] = tokens
    data["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return json.dumps(data, separators=(",", ":"))


def backup_codex_credentials(creds: str) -> str | None:
    """Store a valid Codex auth blob in the switcher Keychain backup."""
    creds = normalize_codex_credentials_blob(creds) or ""
    email = _codex_email_from_credentials(creds)
    if not email:
        return None
    _validate_email(email)
    keychain.write_credentials(f"{CODEX_KEYCHAIN_PREFIX}{email}", email, creds)
    return email


def _codex_email_from_credentials(creds_json: str | None = None) -> str | None:
    """Extract email from Codex credentials."""
    data = _credentials_data(creds_json)
    if not data:
        return None

    tokens = data.get("tokens", {})
    if isinstance(tokens, dict):
        id_token = tokens.get("id_token")
        if id_token:
            payload = _decode_jwt_payload(id_token)
            if payload and isinstance(payload.get("email"), str):
                return payload["email"]

    for key in ("email", "user", "account"):
        value = data.get(key)
        if isinstance(value, str) and _EMAIL_RE.match(value):
            return value
    return None


def _codex_plan_from_credentials(creds_json: str | None = None) -> str:
    """Extract ChatGPT plan type from Codex credentials."""
    data = _credentials_data(creds_json)
    if not data:
        return "chatgpt"

    tokens = data.get("tokens", {})
    id_token = tokens.get("id_token") if isinstance(tokens, dict) else None
    if id_token:
        payload = _decode_jwt_payload(id_token)
        if payload:
            auth_info = payload.get("https://api.openai.com/auth", {})
            if isinstance(auth_info, dict) and auth_info.get("chatgpt_plan_type"):
                return str(auth_info["chatgpt_plan_type"])
    return str(data.get("auth_mode") or "chatgpt")


def _saved_codex_account(email: str, config_path: Path) -> AccountInfo | None:
    return next(
        (a for a in load_accounts(config_path) if a.provider == "codex" and a.email == email),
        None,
    )


def import_current_codex_account(config_path: Path = DEFAULT_CONFIG_PATH) -> AccountInfo | None:
    """Import the currently logged-in Codex account."""
    creds = _read_codex_credentials_for_import()
    if not creds or get_codex_auth_status() is None:
        return None

    email = _codex_email_from_credentials(creds)
    if not email:
        return None
    _validate_email(email)

    keychain.write_credentials(f"{CODEX_KEYCHAIN_PREFIX}{email}", email, creds)

    account = AccountInfo(
        email=email,
        subscription_type=_codex_plan_from_credentials(creds),
        org_name="",
        active=True,
        keychain_account=email,
        provider="codex",
    )
    add_account(account, config_path)
    set_active_account(email, config_path, provider="codex")
    return account


def _write_codex_credentials(creds: str) -> None:
    """Write credentials back to ~/.codex/auth.json."""
    creds = normalize_codex_credentials_blob(creds) or ""
    if _credentials_data(creds) is None:
        raise RuntimeError("Invalid Codex credentials; refusing to write ~/.codex/auth.json.")
    CODEX_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    CODEX_AUTH_FILE.write_text(creds, encoding="utf-8")
    CODEX_AUTH_FILE.chmod(0o600)


def write_active_codex_credentials(creds: str) -> None:
    """Write the active Codex auth.json with validation."""
    _write_codex_credentials(creds)


def run_codex_logout() -> None:
    """Run `codex logout`."""
    cmd = _codex_cmd()
    subprocess.run([cmd, "logout"], capture_output=True, text=True, env=cli_env(cmd))


def _clear_codex_credentials_file() -> None:
    """Remove the active file-mode Codex credentials before a fresh login."""
    try:
        CODEX_AUTH_FILE.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _launch_codex_login_terminal() -> None:
    """Open Terminal.app and run an interactive Codex login command."""
    script_path = Path(tempfile.gettempdir()) / f"claude-switcher-codex-login-{os.getpid()}.command"
    cmd = _codex_cmd()
    codex_cmd = shlex.quote(cmd)
    codex_dir = shlex.quote(os.path.dirname(cmd) or "/usr/bin")
    script = f"""#!/bin/zsh
export PATH="$PATH":{codex_dir}
echo "Claude Switcher - Codex login"
echo ""
echo "Complete the Codex login flow in this Terminal window."
echo "When login succeeds, return to Claude Switcher."
echo ""
{codex_cmd} login -c 'cli_auth_credentials_store="file"'
status=$?
echo ""
if [ $status -eq 0 ]; then
  echo "Codex login completed. You can close this window."
else
  echo "Codex login failed or was cancelled. You can close this window."
fi
echo ""
read -k 1 "?Press any key to close..."
exit $status
"""
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o700)

    result = subprocess.run(
        ["open", str(script_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError("Could not open Terminal for Codex login.")


def run_codex_login(timeout: int = CODEX_LOGIN_TIMEOUT_SECONDS) -> bool:
    """Open a visible Codex login flow and wait for file credentials."""
    _launch_codex_login_terminal()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        creds = _read_codex_credentials_from_file()
        if creds and _codex_email_from_credentials(creds):
            return True
        time.sleep(2)
    return False


def switch_codex_account(target_email: str, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Switch to a different Codex account, saving current credentials first."""
    active = get_active_account(config_path, provider="codex")

    if active:
        current_creds = _read_codex_credentials_for_import()
        if current_creds:
            keychain.write_credentials(
                f"{CODEX_KEYCHAIN_PREFIX}{active.email}",
                active.keychain_account,
                current_creds,
            )

    _validate_email(target_email)
    target_creds = keychain.read_credentials(f"{CODEX_KEYCHAIN_PREFIX}{target_email}")
    if not target_creds:
        raise RuntimeError(f"Credentials not found for Codex account {target_email}")
    target_creds = normalize_codex_credentials_blob(target_creds) or target_creds

    accounts = load_accounts(config_path)
    target_account = next(
        (a for a in accounts if a.email == target_email and a.provider == "codex"),
        None,
    )
    if not target_account:
        raise RuntimeError(f"Codex account {target_email} not found in config")

    try:
        refreshed = refresh_codex_credentials(target_creds)
    except CodexCredentialsExpiredError as exc:
        raise RuntimeError(
            f"Saved Codex session for {target_email} expired. "
            "Use Add Codex account to sign in again."
        ) from exc
    if refreshed:
        target_creds = refreshed
        keychain.write_credentials(
            f"{CODEX_KEYCHAIN_PREFIX}{target_email}",
            target_account.keychain_account,
            target_creds,
        )

    _write_codex_credentials(target_creds)
    for account in accounts:
        if account.provider == "codex":
            account.active = account.email == target_email
    save_accounts(accounts, config_path)


def add_new_codex_account(config_path: Path = DEFAULT_CONFIG_PATH) -> AccountInfo | None:
    """Add a Codex account via `codex login`."""
    active = get_active_account(config_path, provider="codex")
    current_creds = _read_codex_credentials_for_import()
    current_email = _codex_email_from_credentials(current_creds)

    if current_creds and current_email:
        if not _saved_codex_account(current_email, config_path):
            return import_current_codex_account(config_path)
        keychain.write_credentials(
            f"{CODEX_KEYCHAIN_PREFIX}{current_email}",
            current_email,
            current_creds,
        )
    elif active:
        current_creds = keychain.read_credentials(f"{CODEX_KEYCHAIN_PREFIX}{active.email}")

    run_codex_logout()
    _clear_codex_credentials_file()

    if not run_codex_login():
        if current_creds:
            _write_codex_credentials(current_creds)
        return None

    try:
        return import_current_codex_account(config_path)
    except Exception:
        if current_creds:
            _write_codex_credentials(current_creds)
        return None


def remove_codex_account(email: str, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Remove a saved Codex account from config and Keychain."""
    keychain.delete_credentials(f"{CODEX_KEYCHAIN_PREFIX}{email}")
    remove_account(email, config_path, provider="codex")
