"""Switch the Claude Desktop app's signed-in account alongside Claude Code."""

import base64
import json
import os
import subprocess
import time
from pathlib import Path

from claude_switcher import keychain
from claude_switcher.config import AccountInfo

DESKTOP_BUNDLE_ID = "com.anthropic.claudefordesktop"
DESKTOP_DATA_DIR = Path.home() / "Library" / "Application Support" / "Claude"
COOKIES_NAME = "Cookies"
CONFIG_NAME = "config.json"
# Desktop's sign-in lives in its session cookies plus these config.json entries.
LOGIN_KEYS = ("oauth:tokenCache", "oauth:tokenCacheV2", "lastKnownAccountUuid")
QUIT_TIMEOUT_SECONDS = 20


def _service(email: str) -> str:
    return f"claude-switcher-desktop:{email}"


def _app_exists() -> bool:
    result = subprocess.run(
        ["mdfind", f"kMDItemCFBundleIdentifier == '{DESKTOP_BUNDLE_ID}'"],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip()) or any(
        (d / "Claude.app").exists() for d in (Path("/Applications"), Path.home() / "Applications")
    )


def is_installed(data_dir: Path = DESKTOP_DATA_DIR) -> bool:
    return (data_dir / CONFIG_NAME).exists() and _app_exists()


def is_running() -> bool:
    result = subprocess.run(
        ["osascript", "-e", f'application id "{DESKTOP_BUNDLE_ID}" is running'],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "true"


def quit_app() -> None:
    subprocess.run(
        ["osascript", "-e", f'tell application id "{DESKTOP_BUNDLE_ID}" to quit'],
        capture_output=True,
        text=True,
    )
    deadline = time.time() + QUIT_TIMEOUT_SECONDS
    while is_running():
        if time.time() > deadline:
            raise RuntimeError("Claude Desktop did not quit; its account was not switched.")
        time.sleep(0.5)


def launch_app() -> None:
    subprocess.run(["open", "-b", DESKTOP_BUNDLE_ID], capture_output=True, text=True)


def _read_config(data_dir: Path) -> dict:
    try:
        return json.loads((data_dir / CONFIG_NAME).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_config(data: dict, data_dir: Path) -> None:
    path = data_dir / CONFIG_NAME
    tmp = path.with_suffix(".switcher-tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def current_account_uuid(data_dir: Path = DESKTOP_DATA_DIR) -> str | None:
    return _read_config(data_dir).get("lastKnownAccountUuid")


def _account_uuid(account: AccountInfo) -> str | None:
    return (account.oauth_account or {}).get("accountUuid")


def needs_switch(target: AccountInfo, data_dir: Path = DESKTOP_DATA_DIR) -> bool:
    """Whether Desktop is installed and signed in to another account than target."""
    return is_installed(data_dir) and current_account_uuid(data_dir) != _account_uuid(target)


def save_login(email: str, data_dir: Path = DESKTOP_DATA_DIR) -> None:
    """Back up Desktop's current sign-in to Keychain under email."""
    config = _read_config(data_dir)
    cookies = data_dir / COOKIES_NAME
    backup = {
        "login": {k: config[k] for k in LOGIN_KEYS if k in config},
        "cookies": base64.b64encode(cookies.read_bytes()).decode() if cookies.exists() else None,
    }
    keychain.write_credentials(_service(email), email, json.dumps(backup))


def has_login(email: str) -> bool:
    return keychain.read_credentials(_service(email)) is not None


def restore_login(email: str, data_dir: Path = DESKTOP_DATA_DIR) -> bool:
    """Put email's saved sign-in back; without one, sign Desktop out. Returns True if restored."""
    raw = keychain.read_credentials(_service(email))
    backup = json.loads(raw) if raw else None

    config = _read_config(data_dir)
    for key in LOGIN_KEYS:
        config.pop(key, None)
    # A leftover journal would replay the previous account's cookie writes.
    (data_dir / f"{COOKIES_NAME}-journal").unlink(missing_ok=True)

    cookies = data_dir / COOKIES_NAME
    if backup:
        config.update(backup["login"])
        if backup["cookies"]:
            cookies.write_bytes(base64.b64decode(backup["cookies"]))
            os.chmod(cookies, 0o600)
        else:
            cookies.unlink(missing_ok=True)
    else:
        cookies.unlink(missing_ok=True)

    _write_config(config, data_dir)
    return backup is not None


def switch_desktop(target: AccountInfo, accounts: list[AccountInfo],
                   data_dir: Path = DESKTOP_DATA_DIR) -> str:
    """Move Claude Desktop to target's account.

    Returns 'skipped', 'switched', 'signed_out' or 'unknown_account'."""
    if not is_installed(data_dir):
        return "skipped"

    desktop_uuid = current_account_uuid(data_dir)
    if desktop_uuid and desktop_uuid == _account_uuid(target):
        return "skipped"

    # Desktop may be on a different account than Claude Code, so file its sign-in by its own uuid.
    current = next(
        (a for a in accounts if a.provider == "claude" and desktop_uuid
         and _account_uuid(a) == desktop_uuid),
        None,
    )
    if desktop_uuid and not current:
        # Signed in to an account the switcher doesn't know: leave it rather than lose it.
        return "unknown_account"

    was_running = is_running()
    if was_running:
        quit_app()

    if current:
        save_login(current.email, data_dir)

    restored = restore_login(target.email, data_dir)

    if was_running:
        launch_app()
    return "switched" if restored else "signed_out"


def remove_login(email: str) -> None:
    keychain.delete_credentials(_service(email))
