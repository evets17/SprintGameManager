from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import os

IS_WINDOWS = os.name == "nt"

from sgm.domain import GameAssets, ROM_EXTS, choose_rom


SUPPORTED_EXTS = {".bin", ".int", ".rom", ".cfg", ".json", ".png"}


def _sanitize_basename(basename: str) -> str:
    """Remove apostrophes from basename as they are not supported by Sprint."""
    return basename.replace("'", "")


@dataclass(frozen=True)
class ScanResult:
    folder: Path
    games: dict[str, GameAssets]
    folders: dict[str, GameAssets]
    palette_files: list[Path]
    keyboard_files: list[Path]


def scan_folder(folder: Path, *, palette_exts: set[str] | None = None) -> ScanResult:
    games: dict[str, GameAssets] = {}
    folders: dict[str, GameAssets] = {}
    palette_files: list[Path] = []
    keyboard_files: list[Path] = []

    if not folder.exists() or not folder.is_dir():
        return ScanResult(folder=folder, games={}, folders={}, palette_files=[], keyboard_files=[])

    pal_exts = {".cfg", ".txt"} if not palette_exts else {e.lower() for e in palette_exts}

    def is_hidden_dir(p: Path) -> bool:
        name = p.name
        if name.startswith("."):
            return True
        if IS_WINDOWS:
            try:
                import ctypes

                # https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-getfileattributesw
                # INVALID_FILE_ATTRIBUTES == 0xFFFFFFFF
                attrs = ctypes.windll.kernel32.GetFileAttributesW(str(p))
                if attrs in (-1, 0xFFFFFFFF, 4294967295):
                    return False
                FILE_ATTRIBUTE_HIDDEN = 0x2
                return bool(attrs & FILE_ATTRIBUTE_HIDDEN)
            except Exception:
                return False
        return False

    def is_hidden_file(p: Path) -> bool:
        # Keep this simple: dot-files are hidden.
        # Note: we still traverse hidden directories for helper file discovery
        # (palette/.kbd), so we do not rely on Windows hidden attributes here.
        return p.name.startswith(".")

    # Custom walk so we can prune hidden dirs for game discovery,
    # but still traverse them to find helper files (palette/.kbd).
    #
    # allow_games=False means: do NOT discover games or folder-supporting assets
    # from this subtree; only collect helper files.
    stack: list[tuple[Path, bool]] = [(folder, True)]
    while stack:
        cur, allow_games = stack.pop()
        try:
            entries = list(cur.iterdir())
        except Exception:
            continue

        dir_names: set[str] = set()
        if allow_games:
            # Pre-scan child directories so we can treat sibling files with the same
            # basename as folder-supporting assets (not games).
            for entry in entries:
                if not entry.is_dir():
                    continue
                if is_hidden_dir(entry):
                    # Hidden directories should not contribute to game discovery,
                    # but we still walk them for helper files.
                    stack.append((entry, False))
                    continue
                dir_names.add(entry.name)
                stack.append((entry, True))
        else:
            # Helper-only mode: traverse the subtree, but never discover games/assets.
            for entry in entries:
                if entry.is_dir():
                    stack.append((entry, False))

        for entry in entries:
            if entry.is_dir():
                continue
            if not entry.is_file():
                continue
            if is_hidden_file(entry):
                continue

            suffix = entry.suffix.lower()

            # Track helper files used by Advanced JSON settings.
            # Palette files: extension matches PaletteExtensions and name contains "palette".
            if suffix in pal_exts and "palette" in entry.name.casefold():
                palette_files.append(entry)

            # Keyboard hack files.
            if suffix == ".kbd":
                keyboard_files.append(entry)

            if not allow_games:
                continue
            if suffix not in SUPPORTED_EXTS:
                continue

            base, kind = _classify(entry)
            if base is None or kind is None:
                continue

            # Folder-supporting assets live alongside a folder whose name is <basename>.
            # These should not appear as games.
            if base in dir_names:
                # ROM and CFG do not apply to folders.
                if kind in {"rom", "config"}:
                    continue

                folder_dir = cur / base
                fkey = str(folder_dir)
                asset = folders.get(fkey)
                if asset is None:
                    asset = GameAssets(basename=base, folder=cur)
                    folders[fkey] = asset

                if kind == "metadata":
                    asset.metadata = entry
                elif kind == "box":
                    asset.box = entry
                elif kind == "box_small":
                    asset.box_small = entry
                elif kind == "overlay":
                    asset.overlay = entry
                elif kind == "overlay2":
                    asset.overlay2 = entry
                elif kind == "overlay3":
                    asset.overlay3 = entry
                elif kind == "overlay_big":
                    asset.overlay_big = entry
                elif kind == "qrcode":
                    asset.qrcode = entry
                elif kind == "snap1":
                    asset.snap1 = entry
                elif kind == "snap2":
                    asset.snap2 = entry
                elif kind == "snap3":
                    asset.snap3 = entry
                else:
                    asset.other.append(entry)
                continue

            game_folder = entry.parent
            rel_folder = Path(".")
            try:
                rel_folder = game_folder.relative_to(folder)
            except Exception:
                rel_folder = Path(".")

            # Unique key: include folder path when game is in a subfolder.
            if str(rel_folder) in {".", ""}:
                key = base
            else:
                key = f"{rel_folder.as_posix()}/{base}"

            game = games.get(key)
            if game is None:
                game = GameAssets(basename=base, folder=game_folder)
                games[key] = game

            if kind == "rom":
                game.rom = choose_rom(game.rom, entry)
            elif kind == "config":
                game.config = entry
            elif kind == "metadata":
                game.metadata = entry
            elif kind == "box":
                game.box = entry
            elif kind == "box_small":
                game.box_small = entry
            elif kind == "overlay":
                game.overlay = entry
            elif kind == "overlay2":
                game.overlay2 = entry
            elif kind == "overlay3":
                game.overlay3 = entry
            elif kind == "overlay_big":
                game.overlay_big = entry
            elif kind == "qrcode":
                game.qrcode = entry
            elif kind == "snap1":
                game.snap1 = entry
            elif kind == "snap2":
                game.snap2 = entry
            elif kind == "snap3":
                game.snap3 = entry
            else:
                game.other.append(entry)

    # Stable ordering for UI
    games = dict(sorted(games.items(), key=lambda kv: kv[0].lower()))
    folders = dict(sorted(folders.items(), key=lambda kv: kv[0].lower()))
    palette_files = sorted(palette_files, key=lambda p: str(p).casefold())
    keyboard_files = sorted(keyboard_files, key=lambda p: str(p).casefold())
    return ScanResult(folder=folder, games=games, folders=folders, palette_files=palette_files, keyboard_files=keyboard_files)


def _classify(path: Path) -> tuple[str | None, str | None]:
    suffix = path.suffix.lower()
    stem = path.stem

    if suffix in ROM_EXTS:
        return _sanitize_basename(stem), "rom"
    if suffix == ".cfg":
        # Some games folders include palette/config helper files that are not game configs.
        # If the filename contains "palette" anywhere, ignore it for game discovery.
        if "palette" in path.name.casefold():
            return None, None
        return _sanitize_basename(stem), "config"
    if suffix == ".json":
        return _sanitize_basename(stem), "metadata"
    if suffix != ".png":
        return None, None

    lower = stem.lower()

    if lower.endswith("_big_overlay"):
        return _sanitize_basename(stem[: -len("_big_overlay")]), "overlay_big"
    if lower.endswith("_overlay2"):
        return _sanitize_basename(stem[: -len("_overlay2")]), "overlay2"
    if lower.endswith("_overlay3"):
        return _sanitize_basename(stem[: -len("_overlay3")]), "overlay3"
    if lower.endswith("_overlay"):
        return _sanitize_basename(stem[: -len("_overlay")]), "overlay"
    if lower.endswith("_qrcode"):
        return _sanitize_basename(stem[: -len("_qrcode")]), "qrcode"
    if lower.endswith("_small"):
        return _sanitize_basename(stem[: -len("_small")]), "box_small"

    for i in (1, 2, 3):
        token = f"_snap{i}"
        if lower.endswith(token):
            return _sanitize_basename(stem[: -len(token)]), f"snap{i}"

    # Default .png with no recognized suffix is box art.
    return _sanitize_basename(stem), "box"
