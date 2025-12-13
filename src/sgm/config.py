from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Resolution:
    width: int
    height: int

    @staticmethod
    def parse(value: str, *, default: "Resolution") -> "Resolution":
        try:
            parts = value.lower().strip().split("x")
            if len(parts) != 2:
                return default
            w = int(parts[0].strip())
            h = int(parts[1].strip())
            if w <= 0 or h <= 0:
                return default
            return Resolution(w, h)
        except Exception:
            return default

    def to_string(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass
class AppConfig:
    last_game_folder: str = "none"
    desired_max_base_file_length: int = 30
    desired_number_of_snaps: int = 2

    box_resolution: Resolution = Resolution(186, 256)
    box_small_resolution: Resolution = Resolution(148, 204)
    overlay_resolution: Resolution = Resolution(228, 478)
    overlay_big_resolution: Resolution = Resolution(300, 478)
    overlay_build_resolution: Resolution = Resolution(180, 286)
    overlay_build_position: tuple[int, int] = (25, 5)
    overlay_template_override: str = ""
    qrcode_resolution: Resolution = Resolution(123, 123)
    snap_resolution: Resolution = Resolution(640, 400)

    use_box_image_for_box_small: bool = True

    metadata_editors: list[str] = None  # populated in defaults()

    @staticmethod
    def defaults() -> "AppConfig":
        cfg = AppConfig()
        cfg.metadata_editors = [
            "Parker Brothers",
            "Mattel",
            "Imagic",
            "Coleco",
            "Sega Enterprises",
            "INTV",
            "Activision",
            "Atarisoft",
        ]
        return cfg

    @staticmethod
    def load_or_create(path: Path) -> "AppConfig":
        if not path.exists():
            cfg = AppConfig.defaults()
            cfg.save(path)
            return cfg
        return AppConfig.load(path)

    @staticmethod
    def load(path: Path) -> "AppConfig":
        cfg = AppConfig.defaults()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return cfg

        data: dict[str, str] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#") or line.startswith(";"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()

        cfg.last_game_folder = data.get("LastGameFolder", cfg.last_game_folder)

        cfg.desired_max_base_file_length = _parse_int(
            data.get("DesiredMaxBaseFileLength"), default=cfg.desired_max_base_file_length
        )
        cfg.desired_number_of_snaps = _parse_int(
            data.get("DesiredNumberOfSnaps"), default=cfg.desired_number_of_snaps
        )
        cfg.desired_number_of_snaps = max(0, min(3, cfg.desired_number_of_snaps))

        cfg.box_resolution = Resolution.parse(
            data.get("BoxResolution", cfg.box_resolution.to_string()),
            default=cfg.box_resolution,
        )
        cfg.box_small_resolution = Resolution.parse(
            data.get("BoxSmallResolution", cfg.box_small_resolution.to_string()),
            default=cfg.box_small_resolution,
        )
        cfg.overlay_resolution = Resolution.parse(
            data.get("OverlayResolution", cfg.overlay_resolution.to_string()),
            default=cfg.overlay_resolution,
        )
        cfg.overlay_big_resolution = Resolution.parse(
            data.get("OverlayBigResolution", cfg.overlay_big_resolution.to_string()),
            default=cfg.overlay_big_resolution,
        )
        cfg.overlay_build_resolution = Resolution.parse(
            data.get("OverlayBuildResolution", cfg.overlay_build_resolution.to_string()),
            default=cfg.overlay_build_resolution,
        )
        cfg.overlay_build_position = _parse_position(
            data.get("OverlayBuildPosition"),
            default=cfg.overlay_build_position,
        )
        cfg.overlay_template_override = data.get("OverlayTemplateOverride", "").strip()
        cfg.qrcode_resolution = Resolution.parse(
            data.get("QrCodeResolution", cfg.qrcode_resolution.to_string()),
            default=cfg.qrcode_resolution,
        )
        cfg.snap_resolution = Resolution.parse(
            data.get("SnapResolution", cfg.snap_resolution.to_string()),
            default=cfg.snap_resolution,
        )

        cfg.use_box_image_for_box_small = _parse_bool(
            data.get("UseBoxImageForBoxSmall"), default=cfg.use_box_image_for_box_small
        )

        cfg.metadata_editors = _parse_string_list(
            data.get("MetadataEditors"),
            default=cfg.metadata_editors,
        )
        return cfg

    def save(self, path: Path) -> None:
        editors = self.metadata_editors or []
        editors_clean = [str(e).strip() for e in editors if str(e).strip()]
        editors_clean_sorted = sorted(editors_clean, key=lambda s: s.casefold())
        lines = [
            "LastGameFolder=" + (self.last_game_folder or "none"),
            f"DesiredMaxBaseFileLength={int(self.desired_max_base_file_length)}",
            f"DesiredNumberOfSnaps={int(self.desired_number_of_snaps)}",
            f"BoxResolution={self.box_resolution.to_string()}",
            f"BoxSmallResolution={self.box_small_resolution.to_string()}",
            f"OverlayResolution={self.overlay_resolution.to_string()}",
            f"OverlayBigResolution={self.overlay_big_resolution.to_string()}",
            f"OverlayBuildResolution={self.overlay_build_resolution.to_string()}",
            f"OverlayBuildPosition={self.overlay_build_position[0]},{self.overlay_build_position[1]}",
            f"OverlayTemplateOverride={self.overlay_template_override or ''}",
            f"QrCodeResolution={self.qrcode_resolution.to_string()}",
            f"SnapResolution={self.snap_resolution.to_string()}",
            f"UseBoxImageForBoxSmall={'True' if self.use_box_image_for_box_small else 'False'}",
            "MetadataEditors=" + "|".join(editors_clean_sorted),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value.strip())
    except Exception:
        return default


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    v = value.strip().lower()
    if v in {"true", "1", "yes", "y", "on"}:
        return True
    if v in {"false", "0", "no", "n", "off"}:
        return False
    return default


def _parse_position(value: str | None, *, default: tuple[int, int]) -> tuple[int, int]:
    if value is None:
        return default

    try:
        raw = value.strip().lower().replace(" ", "")
        if "," not in raw:
            return default
        a, b = raw.split(",", 1)
        x = int(a)
        y = int(b)
        if x < 0 or y < 0:
            return default
        return (x, y)
    except Exception:
        return default


def _parse_string_list(value: str | None, *, default: list[str]) -> list[str]:
    if value is None:
        return list(default)

    raw = value.strip()
    if not raw:
        return []

    # Prefer '|' as a delimiter; fall back to comma.
    parts = raw.split("|") if "|" in raw else raw.split(",")
    out: list[str] = []
    for p in parts:
        s = p.strip()
        if not s:
            continue
        if s not in out:
            out.append(s)
    return out
