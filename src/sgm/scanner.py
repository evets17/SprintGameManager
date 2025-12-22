from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import os

IS_WINDOWS = os.name == "nt"

from sgm.domain import GameAssets, ROM_EXTS, choose_rom


SUPPORTED_EXTS = {".bin", ".int", ".rom", ".cfg", ".json", ".png"}


@dataclass(frozen=True)
class ScanResult:
    folder: Path
    games: dict[str, GameAssets]
    folders: dict[str, GameAssets]


def scan_folder(folder: Path) -> ScanResult:
    games: dict[str, GameAssets] = {}
    folders: dict[str, GameAssets] = {}

    if not folder.exists() or not folder.is_dir():
        return ScanResult(folder=folder, games={}, folders={})

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
        # Keep this simple: dot-files are hidden; Windows hidden attribute is handled
        # via the directory pruning above.
        return p.name.startswith(".")

    # Custom walk so we can prune hidden dirs.
    stack = [folder]
    while stack:
        cur = stack.pop()
        try:
            entries = list(cur.iterdir())
        except Exception:
            continue

        # Pre-scan child directories so we can treat sibling files with the same
        # basename as folder-supporting assets (not games).
        dir_names: set[str] = set()
        for entry in entries:
            if not entry.is_dir():
                continue
            if is_hidden_dir(entry):
                continue
            dir_names.add(entry.name)
            stack.append(entry)

        for entry in entries:
            if entry.is_dir():
                continue
            if not entry.is_file():
                continue
            if is_hidden_file(entry):
                continue

            suffix = entry.suffix.lower()
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
    return ScanResult(folder=folder, games=games, folders=folders)


def _classify(path: Path) -> tuple[str | None, str | None]:
    suffix = path.suffix.lower()
    stem = path.stem

    if suffix in ROM_EXTS:
        return stem, "rom"
    if suffix == ".cfg":
        return stem, "config"
    if suffix == ".json":
        return stem, "metadata"
    if suffix != ".png":
        return None, None

    lower = stem.lower()

    if lower.endswith("_big_overlay"):
        return stem[: -len("_big_overlay")], "overlay_big"
    if lower.endswith("_overlay2"):
        return stem[: -len("_overlay2")], "overlay2"
    if lower.endswith("_overlay3"):
        return stem[: -len("_overlay3")], "overlay3"
    if lower.endswith("_overlay"):
        return stem[: -len("_overlay")], "overlay"
    if lower.endswith("_qrcode"):
        return stem[: -len("_qrcode")], "qrcode"
    if lower.endswith("_small"):
        return stem[: -len("_small")], "box_small"

    for i in (1, 2, 3):
        token = f"_snap{i}"
        if lower.endswith(token):
            return stem[: -len(token)], f"snap{i}"

    # Default .png with no recognized suffix is box art.
    return stem, "box"
