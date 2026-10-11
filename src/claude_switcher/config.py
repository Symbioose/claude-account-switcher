"""Account list persistence in ~/.config/claude-switcher/accounts.json."""

import functools
import json
import os
import shutil
import threading
from dataclasses import dataclass, asdict, field
from pathlib import Path

from claude_switcher.fsutil import atomic_write_text

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "claude-switcher" / "accounts.json"
CONFIG_VERSION = 2
DEFAULT_PROVIDERS = ("claude", "codex")

# Serializes read-modify-write cycles on the config file. The menu bar app
# mutates it from the main thread and from background threads.
_CONFIG_LOCK = threading.RLock()


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _CONFIG_LOCK:
            return fn(*args, **kwargs)
    return wrapper


@dataclass
class AccountInfo:
    email: str
    subscription_type: str
    org_name: str
    active: bool
    keychain_account: str
    oauth_account: dict | None = None
    provider: str = "claude"


@dataclass
class AppSettings:
    auto_switch: dict[str, bool] = field(
        default_factory=lambda: {provider: False for provider in DEFAULT_PROVIDERS}
    )
    auto_switch_threshold: float = 100.0


def _default_settings_dict() -> dict:
    return asdict(AppSettings())


def _read_config_data(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """Read raw config JSON. Returns a valid empty config shape on failure."""
    if not path.exists():
        return {"version": CONFIG_VERSION, "settings": _default_settings_dict(), "accounts": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _backup_unreadable_config(path)
        return {"version": CONFIG_VERSION, "settings": _default_settings_dict(), "accounts": []}
    except OSError:
        return {"version": CONFIG_VERSION, "settings": _default_settings_dict(), "accounts": []}
    if not isinstance(data, dict):
        _backup_unreadable_config(path)
        return {"version": CONFIG_VERSION, "settings": _default_settings_dict(), "accounts": []}
    return data


def _backup_unreadable_config(path: Path) -> None:
    """Keep a copy of an unreadable config before the next save replaces it."""
    backup = path.with_name(path.name + ".corrupt")
    try:
        if backup.exists():
            return
        shutil.copy2(path, backup)
        os.chmod(backup, 0o600)
    except OSError:
        pass


def _write_config_data(data: dict, path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Write raw config JSON with private file permissions."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data.setdefault("version", CONFIG_VERSION)
    data.setdefault("settings", _default_settings_dict())
    data.setdefault("accounts", [])
    atomic_write_text(path, json.dumps(data, indent=2), mode=0o600)


def _settings_from_dict(data: dict | None) -> AppSettings:
    defaults = AppSettings()
    if not isinstance(data, dict):
        return defaults

    auto_switch = dict(defaults.auto_switch)
    raw_auto_switch = data.get("auto_switch")
    if isinstance(raw_auto_switch, dict):
        for provider, enabled in raw_auto_switch.items():
            if isinstance(provider, str):
                auto_switch[provider] = bool(enabled)

    threshold = defaults.auto_switch_threshold
    try:
        threshold = float(data.get("auto_switch_threshold", threshold))
    except (TypeError, ValueError):
        threshold = defaults.auto_switch_threshold

    return AppSettings(auto_switch=auto_switch, auto_switch_threshold=threshold)


def load_accounts(path: Path = DEFAULT_CONFIG_PATH) -> list[AccountInfo]:
    """Load accounts from JSON file. Returns empty list if file doesn't exist."""
    data = _read_config_data(path)
    accounts = data.get("accounts", [])
    if not isinstance(accounts, list):
        return []

    loaded = []
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        fields = {k: v for k, v in acc.items() if k in AccountInfo.__dataclass_fields__}
        try:
            loaded.append(AccountInfo(**fields))
        except TypeError:
            continue
    return loaded


@_locked
def save_accounts(accounts: list[AccountInfo], path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Save accounts to JSON file, preserving app settings."""
    data = _read_config_data(path)
    data["version"] = CONFIG_VERSION
    data["settings"] = asdict(_settings_from_dict(data.get("settings")))
    data["accounts"] = [asdict(acc) for acc in accounts]
    _write_config_data(data, path)


@_locked
def add_account(account: AccountInfo, path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Add or update an account, matched by email and provider."""
    accounts = load_accounts(path)
    accounts = [
        a for a in accounts
        if not (a.email == account.email and a.provider == account.provider)
    ]
    accounts.append(account)
    save_accounts(accounts, path)


@_locked
def remove_account(email: str, path: Path = DEFAULT_CONFIG_PATH, provider: str = "claude") -> None:
    """Remove an account by email and provider."""
    accounts = load_accounts(path)
    accounts = [a for a in accounts if not (a.email == email and a.provider == provider)]
    save_accounts(accounts, path)


def get_active_account(
    path: Path = DEFAULT_CONFIG_PATH, provider: str = "claude"
) -> AccountInfo | None:
    """Return the active account for a provider, or None."""
    for acc in load_accounts(path):
        if acc.active and acc.provider == provider:
            return acc
    return None


@_locked
def set_active_account(
    email: str, path: Path = DEFAULT_CONFIG_PATH, provider: str = "claude"
) -> None:
    """Set an account active within a provider, deactivating only that provider."""
    accounts = load_accounts(path)
    for acc in accounts:
        if acc.provider == provider:
            acc.active = (acc.email == email)
    save_accounts(accounts, path)


def load_settings(path: Path = DEFAULT_CONFIG_PATH) -> AppSettings:
    """Load persisted app settings with defaults for missing fields."""
    data = _read_config_data(path)
    return _settings_from_dict(data.get("settings"))


@_locked
def save_settings(settings: AppSettings, path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Persist app settings without modifying accounts."""
    data = _read_config_data(path)
    data["version"] = CONFIG_VERSION
    data["settings"] = asdict(settings)
    data["accounts"] = data.get("accounts", [])
    _write_config_data(data, path)


def is_auto_switch_enabled(provider: str, path: Path = DEFAULT_CONFIG_PATH) -> bool:
    """Return whether auto-switch is enabled for a provider."""
    settings = load_settings(path)
    return bool(settings.auto_switch.get(provider, False))


@_locked
def set_auto_switch_enabled(
    provider: str, enabled: bool, path: Path = DEFAULT_CONFIG_PATH
) -> None:
    """Enable or disable auto-switch for one provider."""
    settings = load_settings(path)
    settings.auto_switch[provider] = bool(enabled)
    save_settings(settings, path)
