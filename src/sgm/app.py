from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from sgm.config import AppConfig
from sgm.resources import resource_path
from sgm.ui.main_window import MainWindow
from sgm.version import APP_NAME


def _pick_icon_path() -> Path:
    # Prefer the native icon format per-platform, with fallbacks.
    if sys.platform == "darwin":
        names = ["icon.icns", "icon.png", "icon.ico"]
    elif sys.platform.startswith("linux"):
        names = ["icon.png", "icon.ico", "icon.icns"]
    else:
        names = ["icon.ico", "icon.png", "icon.icns"]

    for name in names:
        p = resource_path(name)
        if p.exists():
            return p
    return resource_path(names[0])


def _app_config_path() -> Path:
    # On Linux, prefer XDG_CONFIG_HOME for better standards compliance.
    if sys.platform.startswith("linux"):
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            return Path(xdg_config) / "sgm" / "sgm.ini"
        return Path.home() / ".config" / "sgm" / "sgm.ini"

    cfg_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
    return cfg_dir / "sgm.ini"


def _load_config() -> tuple[AppConfig, Path]:
    local_cfg = Path.cwd() / "sgm.ini"
    app_cfg = _app_config_path()

    # Prefer existing local config to preserve current Windows behavior.
    if local_cfg.exists():
        return (AppConfig.load_or_create(local_cfg), local_cfg)

    # Next prefer existing per-user app config (useful for macOS .app launches).
    if app_cfg.exists():
        return (AppConfig.load_or_create(app_cfg), app_cfg)

    # Neither exists: attempt to create/populate local first.
    try:
        return (AppConfig.load_or_create(local_cfg), local_cfg)
    except Exception:
        pass

    # Fallback: ensure AppConfigLocation exists, then create/populate there.
    app_cfg.parent.mkdir(parents=True, exist_ok=True)
    return (AppConfig.load_or_create(app_cfg), app_cfg)


def _setup_linux_env() -> None:
    """Configure environment hints for better Linux desktop integration."""
    # Enable HiDPI auto-scaling if not already set.
    if not os.environ.get("QT_AUTO_SCREEN_SCALE_FACTOR"):
        os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    # Prefer native file dialogs on GTK-based desktops.
    if not os.environ.get("QT_QPA_PLATFORMTHEME"):
        # Check for common GTK desktop environments.
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if any(de in desktop for de in ("gnome", "ubuntu", "pantheon", "cinnamon", "mate", "xfce", "lxde")):
            os.environ["QT_QPA_PLATFORMTHEME"] = "gtk3"

    # Improve Wayland compatibility.
    if not os.environ.get("QT_QPA_PLATFORM"):
        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session_type == "wayland":
            os.environ["QT_QPA_PLATFORM"] = "wayland"


def main() -> int:
    if os.name == "nt" and not os.environ.get("QT_QPA_FONTDIR"):
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        fonts_dir = windir / "Fonts"
        if fonts_dir.exists():
            os.environ["QT_QPA_FONTDIR"] = str(fonts_dir)

    if sys.platform.startswith("linux"):
        _setup_linux_env()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    icon_path = _pick_icon_path()
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    config, config_path = _load_config()

    window = MainWindow(config=config, config_path=config_path)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()

    # Auto-load last folder if present.
    if config.last_game_folder and config.last_game_folder.lower() != "none":
        last = Path(config.last_game_folder)
        if last.exists() and last.is_dir():
            window.load_folder(last)

    return app.exec()
