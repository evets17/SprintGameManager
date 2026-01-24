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
    language: str = "en"
    desired_max_base_file_length: int = 35
    desired_number_of_snaps: int = 2

    box_resolution: Resolution = Resolution(186, 256)
    box_small_resolution: Resolution = Resolution(148, 204)
    overlay_resolution: Resolution = Resolution(228, 478)
    overlay_big_resolution: Resolution = Resolution(300, 478)
    overlay_build_resolution: Resolution = Resolution(180, 286)
    overlay_build_position: tuple[int, int] = (25, 5)
    overlay_template_override: str = ""
    overlay_cutter_template: str = ""
    qrcode_resolution: Resolution = Resolution(123, 123)
    snap_resolution: Resolution = Resolution(640, 400)

    use_box_image_for_box_small: bool = True

    # If True: when adding a Big Overlay image, automatically build Overlay 1
    # from it (only if Overlay 1 is currently missing).
    auto_build_overlay: bool = False

    # If True: show confirmation dialogs before overwriting images.
    confirm_image_overwrite: bool = True

    # Used when building jzintv flags that reference files on the target device.
    # Example output: --kbdhackfile="<prefix>/<relative_path>"
    jzintv_media_prefix: str = "/media/usb0"

    # Extensions used when detecting palette helper files.
    # Example: ".txt|.cfg|.pal"
    palette_extensions: list[str] = None  # populated in defaults()

    metadata_editors: list[str] = None  # populated in defaults()

    # Used by Bulk JSON Update dialog to offer common JSON keys.
    # Supports nested paths like description/en.
    json_keys: list[str] = None  # populated in defaults()

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

        cfg.json_keys = [
            "name",
            "nb_players",
            "editor",
            "year",
            "description/en",
            "jzintv_extra",
            "save_highscores",
        ]
        cfg.palette_extensions = _normalize_extensions([".txt", ".cfg"])
        return cfg

    @staticmethod
    def _to_ini_kv(cfg: "AppConfig") -> dict[str, str]:
        editors = cfg.metadata_editors or []
        editors_clean = [str(e).strip() for e in editors if str(e).strip()]
        editors_clean_sorted = sorted(editors_clean, key=lambda s: s.casefold())

        json_keys = cfg.json_keys or []
        json_keys_clean: list[str] = []
        for k in json_keys:
            s = str(k).strip()
            if not s:
                continue
            if s not in json_keys_clean:
                json_keys_clean.append(s)
        return {
            "LastGameFolder": (cfg.last_game_folder or "none"),
            "Language": (cfg.language or "en").strip().lower() or "en",
            "DesiredMaxBaseFileLength": str(int(cfg.desired_max_base_file_length)),
            "DesiredNumberOfSnaps": str(int(cfg.desired_number_of_snaps)),
            "BoxResolution": cfg.box_resolution.to_string(),
            "BoxSmallResolution": cfg.box_small_resolution.to_string(),
            "OverlayResolution": cfg.overlay_resolution.to_string(),
            "OverlayBigResolution": cfg.overlay_big_resolution.to_string(),
            "OverlayBuildResolution": cfg.overlay_build_resolution.to_string(),
            "OverlayBuildPosition": f"{cfg.overlay_build_position[0]},{cfg.overlay_build_position[1]}",
            "OverlayTemplateOverride": (cfg.overlay_template_override or ""),
            "OverlayCutterTemplate": (cfg.overlay_cutter_template or ""),
            "QrCodeResolution": cfg.qrcode_resolution.to_string(),
            "SnapResolution": cfg.snap_resolution.to_string(),
            "UseBoxImageForBoxSmall": "True" if cfg.use_box_image_for_box_small else "False",
            "AutoBuildOverlay": "True" if cfg.auto_build_overlay else "False",
            "ConfirmImageOverwrite": "True" if cfg.confirm_image_overwrite else "False",
            "JzIntvMediaPrefix": (cfg.jzintv_media_prefix or "/media/usb0").strip() or "/media/usb0",
            "PaletteExtensions": "|".join(_normalize_extensions(cfg.palette_extensions or [])),
            "MetadataEditors": "|".join(editors_clean_sorted),
            "JsonKeys": "|".join(json_keys_clean),
        }

    @staticmethod
    def _upgrade_ini_if_missing_keys(path: Path, *, defaults: "AppConfig") -> None:
        """Ensure an existing ini contains all known keys.

        Preserves existing file contents and values; only appends missing keys
        with default values.
        """

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        present: set[str] = set()
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#") or line.startswith(";"):
                continue
            if "=" not in line:
                continue
            k, _ = line.split("=", 1)
            key = k.strip()
            if key:
                present.add(key)

        expected = AppConfig._to_ini_kv(defaults)
        missing = [k for k in expected.keys() if k not in present]
        if not missing:
            return

        # Append missing keys at the end to avoid rewriting/normalizing the file.
        out = text
        if out and not out.endswith("\n"):
            out += "\n"
        for k in missing:
            out += f"{k}={expected[k]}\n"

        try:
            path.write_text(out, encoding="utf-8")
        except Exception:
            return

    @staticmethod
    def load_or_create(path: Path) -> "AppConfig":
        if not path.exists():
            cfg = AppConfig.defaults()
            cfg.save(path)
            return cfg
        # Upgrade existing ini files by appending any newly-added settings.
        defaults = AppConfig.defaults()
        AppConfig._upgrade_ini_if_missing_keys(path, defaults=defaults)
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

        lang = (data.get("Language", cfg.language) or "").strip().lower()
        # Supported description languages.
        cfg.language = lang if lang in {"en", "fr", "es", "de", "it"} else "en"

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
        cfg.overlay_cutter_template = data.get("OverlayCutterTemplate", "").strip()
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

        cfg.auto_build_overlay = _parse_bool(
            data.get("AutoBuildOverlay"), default=cfg.auto_build_overlay
        )

        cfg.confirm_image_overwrite = _parse_bool(
            data.get("ConfirmImageOverwrite"), default=cfg.confirm_image_overwrite
        )

        cfg.jzintv_media_prefix = (data.get("JzIntvMediaPrefix", cfg.jzintv_media_prefix) or "").strip() or "/media/usb0"

        cfg.palette_extensions = _normalize_extensions(
            _parse_string_list(data.get("PaletteExtensions"), default=cfg.palette_extensions)
        )

        cfg.metadata_editors = _parse_string_list(
            data.get("MetadataEditors"),
            default=cfg.metadata_editors,
        )

        cfg.json_keys = _parse_string_list(
            data.get("JsonKeys"),
            default=cfg.json_keys,
        )
        return cfg

    def save(self, path: Path) -> None:
        kv = AppConfig._to_ini_kv(self)
        lines = [f"{k}={v}" for k, v in kv.items()]
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


def _normalize_extensions(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        s = (v or "").strip().lower()
        if not s:
            continue
        if not s.startswith("."):
            s = "." + s
        if s not in out:
            out.append(s)
    return out
