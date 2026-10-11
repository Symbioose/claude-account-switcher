"""Locate CLI binaries when the app is launched from Finder with a minimal PATH."""

import os
import re
from collections.abc import Iterator
from pathlib import Path


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", path.name))


def _candidate_dirs() -> Iterator[Path]:
    """Yield install directories a Finder-launched app does not see, in order.

    The first three are the historical locations and are always checked first;
    the others are only looked at when none of those has the binary.
    """
    home = Path.home()
    yield home / ".local" / "bin"
    yield Path("/usr/local/bin")
    yield Path("/opt/homebrew/bin")
    yield home / ".claude" / "local"
    yield home / ".npm-global" / "bin"
    yield home / ".bun" / "bin"
    yield home / ".volta" / "bin"
    # nvm installs one bin directory per Node version; prefer the newest.
    try:
        versions = sorted(
            (home / ".nvm" / "versions" / "node").glob("*"), key=_version_key, reverse=True
        )
    except OSError:
        versions = []
    for version in versions:
        yield version / "bin"


def find_cli(name: str) -> str | None:
    """Find a binary in common install directories. Returns its path or None."""
    for directory in _candidate_dirs():
        candidate = directory / name
        if candidate.is_file():
            return str(candidate)
    return None


def cli_env(binary: str) -> dict[str, str] | None:
    """Return an environment whose PATH also includes the binary's directory.

    npm-installed CLIs start with `#!/usr/bin/env node`; with nvm, node lives
    next to the CLI binary and is not on a Finder-launched app's PATH. The
    directory is appended, so anything already found on PATH still wins.
    Returns None (inherit the environment unchanged) when there is nothing to add.
    """
    directory = os.path.dirname(binary)
    current = os.environ.get("PATH")
    if not directory or not current or directory in current.split(os.pathsep):
        return None
    env = dict(os.environ)
    env["PATH"] = f"{current}{os.pathsep}{directory}"
    return env
