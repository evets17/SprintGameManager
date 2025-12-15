from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from sgm.scanner import _classify


class RenameCollisionError(RuntimeError):
    pass


def copy_file(src: Path, dest: Path, *, overwrite: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if not overwrite:
            raise FileExistsError(str(dest))
        if dest.is_dir():
            raise IsADirectoryError(str(dest))
    shutil.copy2(src, dest)


def plan_rename_for_game_files(folder: Path, old_basename: str, new_basename: str) -> list[tuple[Path, Path]]:
    moves: list[tuple[Path, Path]] = []

    for entry in folder.iterdir():
        if not entry.is_file():
            continue
        base, kind = _classify(entry)
        if base != old_basename or kind is None:
            continue

        new_name = _build_name(new_basename, entry, kind)
        moves.append((entry, folder / new_name))

    return moves


def rename_many(moves: list[tuple[Path, Path]]) -> None:
    if not moves:
        return

    srcs = {s.resolve() for s, _ in moves}

    # Detect collisions with existing files not part of the rename set.
    for _, dst in moves:
        if dst.exists() and dst.resolve() not in srcs:
            raise RenameCollisionError(f"Destination already exists: {dst}")

    # Use temporary unique names to handle swaps.
    tmp_moves: list[tuple[Path, Path]] = []
    for src, _ in moves:
        tmp = src.with_name(src.name + f".tmp.{uuid.uuid4().hex}")
        tmp_moves.append((src, tmp))

    for src, tmp in tmp_moves:
        src.rename(tmp)

    tmp_to_final = []
    for (_, dst), (_, tmp) in zip(moves, tmp_moves, strict=True):
        tmp_to_final.append((tmp, dst))

    for tmp, dst in tmp_to_final:
        tmp.rename(dst)


def swap_files(a: Path, b: Path) -> None:
    if not a.exists() or not b.exists():
        return
    tmp = a.with_name(a.name + f".tmp.{uuid.uuid4().hex}")
    a.rename(tmp)
    b.rename(a)
    tmp.rename(b)


def _build_name(new_basename: str, old_path: Path, kind: str) -> str:
    suffix = old_path.suffix

    if kind == "rom":
        return new_basename + suffix
    if kind == "config":
        return new_basename + ".cfg"
    if kind == "metadata":
        return new_basename + ".json"
    if kind == "box":
        return new_basename + ".png"
    if kind == "box_small":
        return new_basename + "_small.png"
    if kind == "overlay":
        return new_basename + "_overlay.png"
    if kind == "overlay2":
        return new_basename + "_overlay2.png"
    if kind == "overlay3":
        return new_basename + "_overlay3.png"
    if kind == "overlay_big":
        return new_basename + "_big_overlay.png"
    if kind == "qrcode":
        return new_basename + "_qrcode.png"
    if kind in {"snap1", "snap2", "snap3"}:
        n = kind[-1]
        return new_basename + f"_snap{n}.png"

    return new_basename + suffix
