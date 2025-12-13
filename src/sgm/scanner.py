from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sgm.domain import GameAssets, ROM_EXTS, choose_rom


SUPPORTED_EXTS = {".bin", ".int", ".rom", ".cfg", ".json", ".png"}


@dataclass(frozen=True)
class ScanResult:
    folder: Path
    games: dict[str, GameAssets]


def scan_folder(folder: Path) -> ScanResult:
    games: dict[str, GameAssets] = {}

    if not folder.exists() or not folder.is_dir():
        return ScanResult(folder=folder, games={})

    for entry in folder.iterdir():
        if not entry.is_file():
            continue

        suffix = entry.suffix.lower()
        if suffix not in SUPPORTED_EXTS:
            continue

        base, kind = _classify(entry)
        if base is None or kind is None:
            continue

        game = games.get(base)
        if game is None:
            game = GameAssets(basename=base, folder=folder)
            games[base] = game

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
        elif kind == "overlay1":
            game.overlay1 = entry
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
    return ScanResult(folder=folder, games=games)


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
    if lower.endswith("_overlay1"):
        return stem[: -len("_overlay1")], "overlay1"
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
