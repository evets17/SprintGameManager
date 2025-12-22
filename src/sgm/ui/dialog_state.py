from __future__ import annotations

from pathlib import Path


_LAST_DIR: Path | None = None


def get_start_dir(fallback: str | Path | None = None) -> str:
    """Return the directory a file dialog should open in.

    Remembers the last directory used during this app session.
    """
    global _LAST_DIR

    if _LAST_DIR is not None:
        return str(_LAST_DIR)

    if fallback is None:
        return ""

    try:
        p = Path(str(fallback)).expanduser()
        if p.exists() and p.is_file():
            p = p.parent
        if p.exists() and p.is_dir():
            return str(p)
    except Exception:
        return str(fallback)

    return str(fallback)


def remember_path(chosen: str | Path | None) -> None:
    """Remember a chosen file or directory path for subsequent dialogs."""
    global _LAST_DIR

    if not chosen:
        return

    try:
        p = Path(str(chosen)).expanduser()
        if p.exists() and p.is_file():
            p = p.parent
        if p.exists() and p.is_dir():
            _LAST_DIR = p
    except Exception:
        return
