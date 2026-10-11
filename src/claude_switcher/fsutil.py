"""Filesystem helpers for the switcher's own config file."""

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str, mode: int) -> None:
    """Write text so readers see either the old file or the new one, never a partial one.

    The content goes to a temporary file in the same directory, which then
    replaces the destination. Symlinks are followed so the link target is
    replaced, not the link. If any step fails, fall back to a plain in-place
    write so the result is never worse than writing the file directly.
    """
    target = Path(os.path.realpath(path))
    tmp_name = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, target)
        return
    except OSError:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    path.write_text(text, encoding="utf-8")
    os.chmod(path, mode)
