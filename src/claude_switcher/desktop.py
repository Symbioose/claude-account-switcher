"""Claude Desktop app profile switching.

The desktop app keeps its own session, independent of the Claude Code CLI
credentials in the Keychain. Switching the CLI account therefore leaves the
desktop app logged in as the previous account. Electron accepts a
--user-data-dir flag, so each account gets its own profile directory and the
app is relaunched against the matching one.
"""

import re
import subprocess
import time
from pathlib import Path

CLAUDE_APP = Path("/Applications/Claude.app")
CLAUDE_BINARY = CLAUDE_APP / "Contents" / "MacOS" / "Claude"
PROFILES_ROOT = Path.home() / "Library" / "Application Support" / "Claude-Profiles"

QUIT_TIMEOUT_SECONDS = 15
_POLL_INTERVAL_SECONDS = 0.25
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def profile_dir(email: str) -> Path:
    """Return the profile directory for an account."""
    return PROFILES_ROOT / _UNSAFE_CHARS.sub("_", email)


def is_installed() -> bool:
    """Check whether the Claude desktop app is present."""
    return CLAUDE_BINARY.is_file()


def is_running() -> bool:
    """Check whether the Claude desktop app is currently running."""
    result = subprocess.run(
        ["pgrep", "-f", f"^{CLAUDE_BINARY}"], capture_output=True, text=True
    )
    return result.returncode == 0


def _quit_and_wait(timeout: float = QUIT_TIMEOUT_SECONDS) -> bool:
    """Ask the app to quit and wait for the process to actually exit."""
    subprocess.run(
        ["osascript", "-e", 'tell application "Claude" to quit'],
        capture_output=True,
        text=True,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_running():
            return True
        time.sleep(_POLL_INTERVAL_SECONDS)
    return False


def _launch(profile: Path) -> None:
    subprocess.Popen(
        ["open", "-a", str(CLAUDE_APP), "--args", f"--user-data-dir={profile}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def switch_desktop_profile(email: str) -> bool:
    """Point the desktop app at the profile for email. Returns True if relaunched.

    No-op when the app is not installed or not running: the flag is only
    applied at launch, so there is nothing to do until the user opens it.
    """
    if not is_installed() or not is_running():
        return False

    profile = profile_dir(email)
    profile.mkdir(parents=True, exist_ok=True)

    if not _quit_and_wait():
        return False

    _launch(profile)
    return True
