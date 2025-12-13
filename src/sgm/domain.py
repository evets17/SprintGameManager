from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


ROM_EXTS = {".int", ".bin", ".rom"}


@dataclass
class GameAssets:
    basename: str
    folder: Path

    rom: Path | None = None
    config: Path | None = None
    metadata: Path | None = None

    box: Path | None = None
    box_small: Path | None = None
    overlay: Path | None = None
    overlay1: Path | None = None
    overlay2: Path | None = None
    overlay3: Path | None = None
    overlay_big: Path | None = None
    qrcode: Path | None = None

    snap1: Path | None = None
    snap2: Path | None = None
    snap3: Path | None = None

    other: list[Path] = field(default_factory=list)

    def all_paths(self) -> list[Path]:
        paths: list[Path] = []
        for p in [
            self.rom,
            self.config,
            self.metadata,
            self.box,
            self.box_small,
            self.overlay,
            self.overlay1,
            self.overlay2,
            self.overlay3,
            self.overlay_big,
            self.qrcode,
            self.snap1,
            self.snap2,
            self.snap3,
        ]:
            if p is not None:
                paths.append(p)
        paths.extend(self.other)
        return paths


def choose_rom(current: Path | None, candidate: Path) -> Path:
    if current is None:
        return candidate

    # Prefer .int over .bin over .rom (arbitrary but stable)
    priority = {".int": 0, ".bin": 1, ".rom": 2}
    cur_p = priority.get(current.suffix.lower(), 99)
    cand_p = priority.get(candidate.suffix.lower(), 99)
    return candidate if cand_p < cur_p else current
