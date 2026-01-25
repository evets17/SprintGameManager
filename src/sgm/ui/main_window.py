from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import os

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPalette, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
        QGridLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from shiboken6 import isValid

from PySide6.QtWidgets import QStyle

from sgm.config import AppConfig
from sgm.domain import GameAssets
from sgm.image_ops import (
    ImageProcessError,
    build_overlay_png,
    build_overlay_png_from_file,
    generate_qr_png,
    get_image_size,
    pil_from_qimage,
    save_png_resized_from_file,
)
from sgm.resources import resource_path, resources_dir
from sgm.io_utils import (
    RenameCollisionError,
    copy_file,
    plan_move_game_files,
    plan_rename_for_folder_support_files,
    plan_rename_for_game_files,
    rename_many,
    swap_files,
)
from sgm.scanner import _classify, scan_folder
from sgm.ui.advanced_json_dialog import AdvancedJsonDialog
from sgm.ui.bulk_json_update_dialog import BulkJsonUpdateDialog
from sgm.ui.overlay_cleaner_dialog import OverlayImageCleanerDialog
from sgm.ui.widgets import ImageCard, ImageSpec, OverlayCard, OverlayPrimaryCard, SnapshotCard
from sgm.ui.dialog_state import get_start_dir, remember_path
from sgm.version import main_window_title
from sgm.sprint_fs import sprint_name_key, sprint_path_key


ACCEPTED_ADD_EXTS = {".bin", ".int", ".rom", ".cfg", ".json", ".png"}


def _is_hidden_dir(p: Path) -> bool:
    name = p.name
    if name.startswith("."):
        return True
    if os.name == "nt":
        try:
            import ctypes

            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(p))
            if attrs in (-1, 0xFFFFFFFF, 4294967295):
                return False
            FILE_ATTRIBUTE_HIDDEN = 0x2
            return bool(attrs & FILE_ATTRIBUTE_HIDDEN)
        except Exception:
            return False
    return False


class GamesTreeWidget(QTreeWidget):
    def __init__(self, *, parent: QWidget, on_move_games, on_add_files):
        super().__init__(parent)
        self._on_move_games = on_move_games
        self._on_add_files = on_add_files
        self._drag_game_ids: list[str] = []
        self._drag_source_folders: set[Path] = set()
        self._root_folder: Path | None = None

        self._drop_hover_item: QTreeWidgetItem | None = None
        self._root_drop_active: bool = False
        self._base_stylesheet: str = self.styleSheet() or ""

        hi = self.palette().color(QPalette.ColorRole.Highlight)
        self._root_drop_border_color: str = QColor(hi).name()
        fill = QColor(hi)
        fill.setAlpha(60)
        self._drop_hover_brush = QBrush(fill)

        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAutoScroll(True)
        self.setAutoScrollMargin(24)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _set_root_drop_active(self, active: bool) -> None:
        if self._root_drop_active == active:
            return
        self._root_drop_active = active
        if active:
            extra = f"\nQTreeWidget {{ border: 2px dashed {self._root_drop_border_color}; }}\n"
            self.setStyleSheet(self._base_stylesheet + extra)
        else:
            self.setStyleSheet(self._base_stylesheet)

    def _set_drop_hover_item(self, item: QTreeWidgetItem | None) -> None:
        if self._drop_hover_item is item:
            return
        if self._drop_hover_item is not None:
            try:
                if isValid(self._drop_hover_item):
                    for col in range(max(1, self.columnCount())):
                        self._drop_hover_item.setBackground(col, QBrush())
            except Exception:
                pass
        self._drop_hover_item = item
        if item is not None:
            try:
                if isValid(item):
                    for col in range(max(1, self.columnCount())):
                        item.setBackground(col, self._drop_hover_brush)
            except Exception:
                pass

    def _update_drop_visuals(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            self._set_drop_hover_item(None)
            self._set_root_drop_active(True)
            return

        info = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(info, dict) and info.get("type") == "folder":
            self._set_drop_hover_item(item)
            self._set_root_drop_active(False)
            return
        if isinstance(info, dict) and info.get("type") == "game":
            parent = item.parent()
            pinfo = parent.data(0, Qt.ItemDataRole.UserRole) if parent is not None else None
            if isinstance(pinfo, dict) and pinfo.get("type") == "folder":
                self._set_drop_hover_item(parent)
                self._set_root_drop_active(False)
                return
            self._set_drop_hover_item(None)
            self._set_root_drop_active(True)
            return

        self._set_drop_hover_item(None)
        self._set_root_drop_active(False)

    def _clear_drop_visuals(self) -> None:
        self._set_drop_hover_item(None)
        self._set_root_drop_active(False)

    def set_root_folder(self, folder: Path | None) -> None:
        self._root_folder = folder

    def _auto_scroll_if_needed(self, pos) -> None:
        # QAbstractItemView autoScroll doesn't reliably kick in when we fully
        # override dragMoveEvent, so do a small manual scroll.
        try:
            margin = 24
            step = 24
            y = int(pos.y())
            h = int(self.viewport().height())
            sb = self.verticalScrollBar()
            if y < margin:
                sb.setValue(sb.value() - step)
            elif y > h - margin:
                sb.setValue(sb.value() + step)
        except Exception:
            return

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._clear_drop_visuals()
        super().dragLeaveEvent(event)

    def startDrag(self, supportedActions) -> None:
        self._drag_game_ids = []
        self._drag_source_folders = set()

        # Drag all selected games (folders are ignored).
        for item in self.selectedItems() or []:
            info = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
            if not isinstance(info, dict) or info.get("type") != "game":
                continue

            game_id = str(info.get("id") or "").strip()
            if not game_id:
                continue
            if game_id not in self._drag_game_ids:
                self._drag_game_ids.append(game_id)

            # Track source folders for no-op drops (same-folder drop).
            src_folder: Path | None = None
            p = info.get("folder") if isinstance(info, dict) else None
            if p:
                try:
                    src_folder = Path(str(p))
                except Exception:
                    src_folder = None
            parent = item.parent() if item is not None else None
            pinfo = parent.data(0, Qt.ItemDataRole.UserRole) if parent is not None else None
            if isinstance(pinfo, dict) and pinfo.get("type") == "folder":
                p = pinfo.get("path")
                if p:
                    try:
                        src_folder = Path(str(p))
                    except Exception:
                        src_folder = src_folder
            if src_folder is not None:
                self._drag_source_folders.add(src_folder)

        if not self._drag_game_ids:
            return
        super().startDrag(supportedActions)

    def dragMoveEvent(self, event) -> None:
        self._auto_scroll_if_needed(event.position().toPoint())
        pos = event.position().toPoint()

        # External file drops (from Explorer) should be allowed over folders
        # (and over games, where we treat it as that game's parent folder).
        if event.mimeData().hasUrls():
            item = self.itemAt(pos)
            if item is None:
                if self._root_folder is not None:
                    self._update_drop_visuals(pos)
                    event.acceptProposedAction()
                    return
                self._clear_drop_visuals()
                event.ignore()
                return

            info = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(info, dict) and info.get("type") in {"folder", "game"}:
                self._update_drop_visuals(pos)
                event.acceptProposedAction()
                return

            self._clear_drop_visuals()
            event.ignore()
            return

        if not self._drag_game_ids:
            self._clear_drop_visuals()
            event.ignore()
            return
        item = self.itemAt(pos)
        if item is None:
            if self._root_folder is not None:
                self._update_drop_visuals(pos)
                event.acceptProposedAction()
                return
            self._clear_drop_visuals()
            event.ignore()
            return

        info = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(info, dict) and info.get("type") == "folder":
            self._update_drop_visuals(pos)
            event.acceptProposedAction()
            return
        if isinstance(info, dict) and info.get("type") == "game":
            parent = item.parent()
            pinfo = parent.data(0, Qt.ItemDataRole.UserRole) if parent is not None else None
            if isinstance(pinfo, dict) and pinfo.get("type") == "folder":
                self._update_drop_visuals(pos)
                event.acceptProposedAction()
                return
        self._clear_drop_visuals()
        event.ignore()

    def dropEvent(self, event) -> None:
        try:
            if event.mimeData().hasUrls():
                item = self.itemAt(event.position().toPoint())
                if item is None:
                    dest = str(self._root_folder) if self._root_folder is not None else None
                else:
                    info = item.data(0, Qt.ItemDataRole.UserRole)
                    if isinstance(info, dict) and info.get("type") == "folder":
                        dest = info.get("path")
                    elif isinstance(info, dict) and info.get("type") == "game":
                        parent = item.parent()
                        if parent is None:
                            dest = str(self._root_folder) if self._root_folder is not None else None
                        else:
                            pinfo = parent.data(0, Qt.ItemDataRole.UserRole) if parent is not None else None
                            dest = pinfo.get("path") if isinstance(pinfo, dict) and pinfo.get("type") == "folder" else None
                    else:
                        dest = None

                if not dest:
                    event.ignore()
                    return

                files: list[Path] = []
                for u in event.mimeData().urls():
                    p = Path(u.toLocalFile())
                    if not p.exists() or not p.is_file():
                        continue
                    if p.suffix.lower() not in ACCEPTED_ADD_EXTS:
                        continue
                    files.append(p)

                if not files:
                    event.ignore()
                    return

                # Clear visuals *before* invoking handlers that may refresh/rebuild the tree.
                self._clear_drop_visuals()
                self._on_add_files(files, Path(dest))
                event.acceptProposedAction()
                return

            game_ids = list(self._drag_game_ids)
            src_folders = set(self._drag_source_folders)
            self._drag_game_ids = []
            self._drag_source_folders = set()
            if not game_ids:
                event.ignore()
                return

            item = self.itemAt(event.position().toPoint())
            if item is None:
                dest = str(self._root_folder) if self._root_folder is not None else None
            else:
                info = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(info, dict) and info.get("type") == "folder":
                    dest = info.get("path")
                elif isinstance(info, dict) and info.get("type") == "game":
                    parent = item.parent()
                    if parent is None:
                        dest = str(self._root_folder) if self._root_folder is not None else None
                    else:
                        pinfo = parent.data(0, Qt.ItemDataRole.UserRole) if parent is not None else None
                        dest = pinfo.get("path") if isinstance(pinfo, dict) and pinfo.get("type") == "folder" else None
                else:
                    dest = None

            if not dest:
                event.ignore()
                return

            dest_folder = Path(dest)
            # Dropping onto the same folder should be a no-op. If we accept the move,
            # Qt's internal drag handling may remove the item until a refresh.
            if len(src_folders) == 1:
                src_folder = next(iter(src_folders))
                try:
                    if src_folder.resolve() == dest_folder.resolve():
                        event.ignore()
                        return
                except Exception:
                    if str(src_folder) == str(dest_folder):
                        event.ignore()
                        return

            # Clear visuals *before* invoking handlers that may refresh/rebuild the tree.
            self._clear_drop_visuals()
            self._on_move_games(game_ids, dest_folder)
            event.acceptProposedAction()
        finally:
            self._clear_drop_visuals()

    def _show_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            # Right-clicked on empty space - show root folder option
            if self._root_folder and self._root_folder.exists():
                from PySide6.QtWidgets import QMenu
                menu = QMenu(self)
                open_action = menu.addAction("Open Root Folder in File Manager")
                action = menu.exec(self.viewport().mapToGlobal(pos))
                if action == open_action:
                    self._open_in_file_manager(self._root_folder)
            return

        info = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(info, dict):
            return

        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)

        folder_path: Path | None = None
        item_type = info.get("type")

        if item_type == "folder":
            # It's a folder item
            path_str = info.get("path")
            if path_str:
                folder_path = Path(str(path_str))
        elif item_type == "game":
            # It's a game item - get the folder it's in
            folder_info = info.get("folder")
            if folder_info:
                folder_path = Path(str(folder_info))
            elif self._root_folder:
                # Game is in root folder
                folder_path = self._root_folder

        if folder_path and folder_path.exists():
            open_action = menu.addAction("Open in File Manager")
            action = menu.exec(self.viewport().mapToGlobal(pos))
            if action == open_action:
                self._open_in_file_manager(folder_path)

    def _open_in_file_manager(self, folder: Path) -> None:
        """Open the given folder in the system file manager."""
        import subprocess
        import sys

        try:
            if sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(folder)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", str(folder)])
        except Exception:
            pass


class FileCard(QWidget):
    def __init__(self, *, title: str, allowed_exts: set[str], on_add_file):
        super().__init__()
        self._title = title
        self._allowed_exts = {e.lower() for e in allowed_exts}
        self._on_add_file = on_add_file

        self._folder: Path | None = None
        self._basename: str | None = None
        self._existing: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        row = QHBoxLayout()
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight: 600;")
        row.addWidget(lbl)
        row.addStretch(1)
        self._btn = QPushButton("Add")
        self._btn.clicked.connect(self._browse)
        row.addWidget(self._btn)
        layout.addLayout(row)

        self._path = QLabel("")
        self._path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._path)

        self._warning = QLabel("")
        self._warning.setWordWrap(True)
        layout.addWidget(self._warning)

        self.setAcceptDrops(True)

    def set_context(self, *, folder: Path | None, basename: str | None, existing: Path | None, warning: str | None) -> None:
        self._folder = folder
        self._basename = basename
        self._existing = existing
        self._path.setText(str(existing) if existing else "(missing)")
        self._warning.setText(warning or "")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return
        p = Path(urls[0].toLocalFile())
        if not p.exists() or not p.is_file():
            event.ignore()
            return
        if p.suffix.lower() not in self._allowed_exts:
            event.ignore()
            return

        self._on_add_file(p)


class ThinFileRow(QWidget):
    MAX_LABEL_CHARS = 80

    @staticmethod
    def _elide_left(text: str, *, max_chars: int) -> str:
        if max_chars <= 0:
            return ""
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return "." * max_chars
        return "..." + text[-(max_chars - 3) :]

    def __init__(self, *, title: str, allowed_exts: set[str], on_add_file):
        super().__init__()
        self._title = title
        self._allowed_exts = {e.lower() for e in allowed_exts}
        self._on_add_file = on_add_file

        self._folder: Path | None = None
        self._basename: str | None = None
        self._extra_handler = None
        self._open_handler = None
        self._open_tooltip_base = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        top = QHBoxLayout()
        self._lbl_title = QLabel(title)
        self._lbl_title.setStyleSheet("font-weight: 600;")
        top.addWidget(self._lbl_title)

        self._path = QLabel("(missing)")
        self._path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self._path, 1)

        self._warning = QLabel("")
        self._warning.setVisible(False)
        self._warning.setStyleSheet("color: red;")
        top.addWidget(self._warning)

        self._btn_extra = QPushButton("")
        self._btn_extra.setMaximumHeight(24)
        self._btn_extra.setVisible(False)
        self._btn_extra.setToolTip("")
        top.addWidget(self._btn_extra)

        self._btn = QPushButton("Add")
        self._btn.setMaximumHeight(24)
        self._btn.clicked.connect(self._browse)
        exts = ", ".join(sorted(self._allowed_exts))
        self._btn.setToolTip(f"Browse to add a {self._title} file ({exts})")
        top.addWidget(self._btn)

        self._btn_open = QToolButton()
        self._btn_open.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._btn_open.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self._btn_open.setFixedSize(QSize(24, 24))
        self._btn_open.setIconSize(QSize(16, 16))
        self._btn_open.setStyleSheet("QToolButton { padding: 0px; }")
        self._btn_open.setVisible(False)
        self._btn_open.setToolTip("")
        top.addWidget(self._btn_open)

        layout.addLayout(top)

        self.setAcceptDrops(True)

    def set_title(self, title: str) -> None:
        self._title = title
        self._lbl_title.setText(title)
        exts = ", ".join(sorted(self._allowed_exts))
        self._btn.setToolTip(f"Browse to add a {self._title} file ({exts})")

    def set_context(
        self,
        *,
        folder: Path | None,
        basename: str | None,
        existing: Path | None,
        warning: str | None,
        missing_text: str = "(missing)",
    ) -> None:
        self._folder = folder
        self._basename = basename
        full = str(existing) if existing else (missing_text or "")
        shown = self._elide_left(full, max_chars=self.MAX_LABEL_CHARS)
        self._path.setText(shown)
        self._path.setToolTip(full if existing else "")
        w = (warning or "").strip()
        self._warning.setText(w)
        self._warning.setVisible(bool(w))
        if self._btn_extra.isVisible():
            self._btn_extra.setEnabled(bool(self._folder and self._basename))

        if self._open_handler is not None:
            exists = bool(existing and existing.exists() and existing.is_file())
            self._btn_open.setVisible(exists)
            self._btn_open.setEnabled(exists)
            if exists and existing is not None:
                base = (self._open_tooltip_base or "").strip()
                if base:
                    self._btn_open.setToolTip(f"{base}\n{existing}")
                else:
                    self._btn_open.setToolTip(str(existing))
            else:
                self._btn_open.setToolTip("")
        else:
            self._btn_open.setVisible(False)

    def set_extra_action(self, label: str, handler, tooltip: str | None = None) -> None:
        self._btn_extra.setText(label)
        self._btn_extra.setToolTip((tooltip or "").strip())
        if self._extra_handler is not None and self._extra_handler is not handler:
            try:
                self._btn_extra.clicked.disconnect(self._extra_handler)
            except Exception:
                pass
        self._extra_handler = handler
        self._btn_extra.clicked.connect(handler)
        self._btn_extra.setVisible(True)
        self._btn_extra.setEnabled(bool(self._folder and self._basename))

    def set_open_action(self, handler, tooltip: str | None = None, *, icon: QIcon | None = None) -> None:
        if self._open_handler is not None and self._open_handler is not handler:
            try:
                self._btn_open.clicked.disconnect(self._open_handler)
            except Exception:
                pass
        self._open_handler = handler
        self._open_tooltip_base = (tooltip or "").strip()
        if icon is not None:
            self._btn_open.setIcon(icon)
        self._btn_open.clicked.connect(handler)
        # Visibility is controlled by set_context() based on whether the file exists.
        self._btn_open.setVisible(False)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return
        p = Path(urls[0].toLocalFile())
        if not p.exists() or not p.is_file():
            event.ignore()
            return
        if p.suffix.lower() not in self._allowed_exts:
            event.ignore()
            return
        self._on_add_file(p)
        event.acceptProposedAction()

    def _browse(self) -> None:
        start = get_start_dir(self._folder)
        path, _ = QFileDialog.getOpenFileName(self, f"Select {self._title}", start, "All files (*.*)")
        if not path:
            return
        remember_path(path)
        p = Path(path)
        if p.suffix.lower() not in self._allowed_exts:
            QMessageBox.warning(self, "Invalid file", f"Expected one of: {', '.join(sorted(self._allowed_exts))}")
            return
        self._on_add_file(p)


class MetadataEditor(QWidget):
    LANGS = ["en", "fr", "es", "de", "it"]
    _KNOWN_TOP_LEVEL_KEYS = {"name", "nb_players", "editor", "year", "description"}

    @staticmethod
    def _desc_for_ui(value) -> str:
        if value is None:
            return ""
        s = str(value)
        return "" if s.strip() == "" else s

    @staticmethod
    def _desc_for_json(value: str) -> str:
        return " " if value.strip() == "" else value

    def __init__(
        self,
        *,
        on_saved,
        on_advanced=None,
        on_bulk_update=None,
        metadata_editors: list[str] | None = None,
        preferred_language: str = "en",
    ):
        super().__init__()
        self._on_saved = on_saved
        self._on_advanced = on_advanced
        self._on_bulk_update = on_bulk_update
        self._metadata_editors = list(metadata_editors or [])
        self._preferred_language = (preferred_language or "en").strip().lower() or "en"
        if self._preferred_language not in self.LANGS:
            self._preferred_language = "en"

        self._folder: Path | None = None
        self._basename: str | None = None
        self._path: Path | None = None
        self._dirty = False
        self._raw_json: dict = {}
        self._others_simple_widgets: dict[str, QWidget] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._top = QWidget()
        top_l = QVBoxLayout(self._top)
        top_l.setContentsMargins(0, 0, 0, 0)
        top_l.setSpacing(6)

        self._warning = QLabel("")
        self._warning.setWordWrap(True)
        self._warning.setStyleSheet("color: red;")
        top_l.addWidget(self._warning)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        self._btn_action = QPushButton("")
        self._btn_action.clicked.connect(self._action_clicked)
        btn_row.addWidget(self._btn_action)

        btn_row.addStretch(1)
        top_l.addLayout(btn_row)

        layout.addWidget(self._top)

        self._fields = QWidget()
        fields_l = QVBoxLayout(self._fields)
        fields_l.setContentsMargins(0, 0, 0, 0)

        self._form = QFormLayout()
        self._form.setContentsMargins(0, 0, 0, 0)
        try:
            self._form.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        try:
            self._form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            self._form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        except Exception:
            pass

        self._name = QLineEdit()
        self._name.setPlaceholderText("name")
        self._name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._form.addRow("Name", self._name)

        self._nb_players = QLineEdit()
        self._nb_players.setPlaceholderText("e.g. 1-2")
        self._nb_players.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._form.addRow("Players", self._nb_players)

        self._editor = QComboBox()
        self._editor.setEditable(True)
        self._editor.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Prefer a sensible minimum width while still allowing the control to stretch.
        self._editor.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._editor.setMinimumContentsLength(16)
        if self._metadata_editors:
            self._editor.addItems(self._metadata_editors)
        self._editor.setEditText("")
        self._form.addRow("Editor", self._editor)

        self._year = QSpinBox()
        self._year.setRange(0, 9999)
        # Qt shows the numeric minimum when specialValueText is empty.
        # Use a single space so year=0 displays as blank in the UI.
        self._year.setSpecialValueText(" ")
        self._form.addRow("Year", self._year)

        fields_l.addLayout(self._form)

        self._lbl_desc = QLabel("Description")
        fields_l.addWidget(self._lbl_desc)
        self._desc_tabs = QTabWidget()
        self._desc_edits: dict[str, QTextEdit] = {}
        for lang in self.LANGS:
            edit = QTextEdit()
            edit.setAcceptRichText(False)
            self._desc_edits[lang] = edit
            self._desc_tabs.addTab(edit, lang)

        # Set the initial Description tab once based on config Language.
        # After that, we do not auto-change it when navigating; the user's
        # tab choice remains active until they pick a different tab.
        try:
            self._desc_tabs.setCurrentIndex(self.LANGS.index(self._preferred_language))
        except Exception:
            self._desc_tabs.setCurrentIndex(0)
        fields_l.addWidget(self._desc_tabs, 1)

        adv_row = QHBoxLayout()
        adv_row.setContentsMargins(0, 0, 0, 0)
        self._btn_advanced = QPushButton("Advanced")
        self._btn_advanced.setToolTip("Open Advanced Settings (JSON) for save_highscores and jzintv_extra")
        self._btn_advanced.clicked.connect(self._advanced_clicked)
        adv_row.addWidget(self._btn_advanced)
        adv_row.addStretch(1)
        fields_l.addLayout(adv_row)

        self._others_group = QGroupBox("Others")
        self._others_group.setVisible(False)
        self._others_form = QFormLayout(self._others_group)
        try:
            self._others_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        try:
            self._others_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            self._others_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        except Exception:
            pass
        self._others_form.setContentsMargins(8, 8, 8, 8)
        self._others_form.setSpacing(6)
        fields_l.addWidget(self._others_group)

        layout.addWidget(self._fields, 1)

        # Only used to pin the top controls when fields are hidden.
        self._bottom_spacer = QWidget()
        self._bottom_spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._bottom_spacer)

        for w in [self._name, self._nb_players, self._year]:
            w.valueChanged.connect(self._mark_dirty) if hasattr(w, "valueChanged") else w.textChanged.connect(self._mark_dirty)
        self._name.textChanged.connect(self._mark_dirty)
        self._editor.currentTextChanged.connect(self._mark_dirty)
        for edit in self._desc_edits.values():
            edit.textChanged.connect(self._mark_dirty)

        # Keep required-field label styling in sync as the user edits.
        self._name.textChanged.connect(lambda *_: self._update_required_label_styles())
        self._nb_players.textChanged.connect(lambda *_: self._update_required_label_styles())
        self._editor.currentTextChanged.connect(lambda *_: self._update_required_label_styles())
        self._year.valueChanged.connect(lambda *_: self._update_required_label_styles())
        for edit in self._desc_edits.values():
            edit.textChanged.connect(lambda *_: self._update_required_label_styles())

        self._update_required_label_styles()

    def _set_label_missing(self, label: QWidget | None, missing: bool) -> None:
        if label is None:
            return
        if missing:
            label.setStyleSheet("color: red;")
        else:
            label.setStyleSheet("")

    def _update_required_label_styles(self) -> None:
        """Show missing standard fields in red; do not affect the 'Others' section."""

        # If fields are hidden/disabled, keep labels neutral.
        if not self._fields.isVisible() or not self._fields.isEnabled():
            self._set_label_missing(self._form.labelForField(self._name), False)
            self._set_label_missing(self._form.labelForField(self._nb_players), False)
            self._set_label_missing(self._form.labelForField(self._editor), False)
            self._set_label_missing(self._form.labelForField(self._year), False)
            self._set_label_missing(getattr(self, "_lbl_desc", None), False)
            return

        name_missing = (self._name.text() or "").strip() == ""

        players_s = (self._nb_players.text() or "").strip()
        players_missing = players_s == "" or players_s == "0"

        editor_missing = (self._editor.currentText() or "").strip() == ""
        year_missing = int(self._year.value()) == 0

        pref = (self._preferred_language or "en").strip().lower() or "en"
        if pref not in self.LANGS:
            pref = "en"
        desc_missing = (self._desc_edits.get(pref).toPlainText() if self._desc_edits.get(pref) else "").strip() == ""

        self._set_label_missing(self._form.labelForField(self._name), name_missing)
        self._set_label_missing(self._form.labelForField(self._nb_players), players_missing)
        self._set_label_missing(self._form.labelForField(self._editor), editor_missing)
        self._set_label_missing(self._form.labelForField(self._year), year_missing)
        self._set_label_missing(getattr(self, "_lbl_desc", None), desc_missing)

    def set_context(
        self,
        *,
        folder: Path | None,
        basename: str | None,
        path: Path | None,
        allow_advanced: bool = True,
    ) -> None:
        self._folder = folder
        self._basename = basename
        self._path = path
        self._dirty = False
        self._raw_json = {}
        self._clear_others()
        self._btn_action.setEnabled(False)
        self._btn_advanced.setEnabled(False)
        self._btn_advanced.setVisible(bool(allow_advanced))

        if not folder or not basename:
            self._warning.setText("")
            self._btn_action.setVisible(False)
            self._set_fields_enabled(False)
            self._fields.setVisible(False)
            self._bottom_spacer.setVisible(True)
            self._update_required_label_styles()
            return

        if path is None or not path.exists():
            self._warning.setText("Missing metadata: <basename>.json")
            self._btn_action.setText("Create JSON")
            self._btn_action.setVisible(True)
            self._btn_action.setEnabled(True)
            self._set_fields_enabled(False)
            self._set_defaults(basename)
            self._fields.setVisible(False)
            self._bottom_spacer.setVisible(True)
            self._update_required_label_styles()
            return

        self._warning.setText("")
        self._btn_action.setText("Save")
        self._btn_action.setVisible(True)
        self._btn_action.setEnabled(False)
        self._set_fields_enabled(True)
        self._fields.setVisible(True)
        self._bottom_spacer.setVisible(False)
        if allow_advanced:
            self._btn_advanced.setEnabled(True)
        self._load(path)
        self._update_required_label_styles()

    def set_bulk_context(self, game_ids: list[str]) -> None:
        # Multi-select: hide per-game controls; bulk updater is launched from the main window.
        self._btn_action.setVisible(False)
        self._btn_advanced.setVisible(False)
        self._set_fields_enabled(False)
        self._fields.setVisible(False)
        self._bottom_spacer.setVisible(True)
        self._warning.setText("")
        self._update_required_label_styles()

    def reload_from_disk(self) -> None:
        if self._path is None or not self._path.exists():
            return
        self._load(self._path)

    def retarget_context_preserve_edits(
        self,
        *,
        folder: Path | None,
        basename: str | None,
        path: Path | None,
        allow_advanced: bool = True,
    ) -> None:
        """Update the active game/folder context without reloading fields.

        Used when external actions (like renames) change the metadata path while the
        user has unsaved edits. This avoids wiping in-memory field edits.
        """

        self._folder = folder
        self._basename = basename
        self._path = path

        self._btn_advanced.setVisible(bool(allow_advanced))
        self._btn_advanced.setEnabled(bool(allow_advanced and path is not None and path.exists()))

        if not folder or not basename:
            self._update_required_label_styles()
            return

        if path is None or not path.exists():
            # Keep current field values, but reflect that the backing JSON is missing.
            self._warning.setText("Missing metadata: <basename>.json")
            self._btn_action.setText("Create JSON")
            self._btn_action.setVisible(True)
            self._btn_action.setEnabled(True)
            self._update_required_label_styles()
            return

        self._warning.setText("")
        self._btn_action.setText("Save")
        self._btn_action.setVisible(True)
        self._btn_action.setEnabled(bool(self._dirty))
        self._update_required_label_styles()

    def _advanced_clicked(self) -> None:
        if self._path is None or not self._path.exists():
            return
        if self._on_advanced is None:
            return

        if self.has_unsaved_changes():
            dlg = QMessageBox(self)
            dlg.setIcon(QMessageBox.Icon.Warning)
            dlg.setWindowTitle("Unsaved changes")
            dlg.setText("You have unsaved metadata changes.")
            dlg.setInformativeText("Save or discard changes before opening Advanced Settings?")
            btn_save = dlg.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
            btn_discard = dlg.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
            btn_cancel = dlg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            dlg.setDefaultButton(btn_save)
            dlg.exec()
            clicked = dlg.clickedButton()
            if clicked == btn_cancel:
                return
            if clicked == btn_save:
                if not self.save_changes():
                    return
            elif clicked == btn_discard:
                self.discard_changes()

        try:
            self._on_advanced(folder=self._folder, basename=self._basename, path=self._path)
        except Exception:
            # Avoid crashing the editor if the advanced handler fails.
            pass

    def _set_fields_enabled(self, enabled: bool) -> None:
        for w in [self._name, self._nb_players, self._editor, self._year, self._desc_tabs, self._others_group]:
            w.setEnabled(enabled)

    def _clear_others(self) -> None:
        self._others_simple_widgets.clear()
        while self._others_form.rowCount() > 0:
            self._others_form.removeRow(0)
        self._others_group.setVisible(False)

    def _rebuild_others_from_raw(self) -> None:
        self._clear_others()
        if not isinstance(self._raw_json, dict):
            return

        extras = {k: v for k, v in self._raw_json.items() if k not in self._KNOWN_TOP_LEVEL_KEYS}
        if not extras:
            return

        for key in sorted(extras.keys(), key=lambda s: str(s).casefold()):
            value = extras[key]

            # Editable simple types
            if isinstance(value, bool):
                w = QCheckBox()
                w.setChecked(bool(value))
                w.stateChanged.connect(self._mark_dirty)
                self._others_simple_widgets[str(key)] = w
                self._others_form.addRow(str(key), w)
                continue

            if isinstance(value, int) and not isinstance(value, bool):
                w = QSpinBox()
                w.setRange(-2147483648, 2147483647)
                w.setSpecialValueText(" ")
                w.setValue(int(value))
                w.valueChanged.connect(self._mark_dirty)
                self._others_simple_widgets[str(key)] = w
                self._others_form.addRow(str(key), w)
                continue

            if isinstance(value, str):
                w = QLineEdit()
                w.setText(value)
                w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                w.textChanged.connect(self._mark_dirty)
                self._others_simple_widgets[str(key)] = w
                self._others_form.addRow(str(key), w)
                continue

            # Complex values: show read-only text; do not allow editing.
            w = QPlainTextEdit()
            w.setReadOnly(True)
            try:
                w.setPlainText(json.dumps(value, ensure_ascii=False, indent=2))
            except Exception:
                w.setPlainText(str(value))
            w.setMinimumHeight(60)
            self._others_form.addRow(str(key), w)

        self._others_group.setVisible(True)

    def _set_defaults(self, basename: str) -> None:
        self._name.setText(basename)
        self._nb_players.setText("")
        self._editor.setEditText("")
        self._year.setValue(0)
        for lang, edit in self._desc_edits.items():
            edit.setPlainText("")
        self._update_required_label_styles()

    def _load(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

        if not isinstance(data, dict):
            data = {}

        # Keep a copy of the raw JSON so we can preserve unknown keys on save.
        self._raw_json = dict(data)

        blockers = [
            QSignalBlocker(self._name),
            QSignalBlocker(self._nb_players),
            QSignalBlocker(self._editor),
            QSignalBlocker(self._year),
            QSignalBlocker(self._desc_tabs),
        ]
        blockers.extend(QSignalBlocker(e) for e in self._desc_edits.values())
        _ = blockers

        self._name.setText(str(data.get("name", self._basename or "")))

        nb = data.get("nb_players", 0)
        try:
            if nb is None:
                self._nb_players.setText("")
            elif isinstance(nb, (int, float)) and not isinstance(nb, bool):
                # Legacy numeric JSON: show as text.
                self._nb_players.setText(str(int(nb)))
            else:
                s = str(nb)
                self._nb_players.setText(s if s.strip() != "" else "")
        except Exception:
            self._nb_players.setText("")

        self._editor.setEditText(str(data.get("editor", "")))

        yr = data.get("year", 0)
        try:
            self._year.setValue(int(yr) if yr is not None and str(yr).strip() != "" else 0)
        except Exception:
            self._year.setValue(0)

        desc = data.get("description", {})
        if not isinstance(desc, dict):
            desc = {}
        for lang in self.LANGS:
            self._desc_edits[lang].setPlainText(self._desc_for_ui(desc.get(lang, "")))

        self._rebuild_others_from_raw()

        self._dirty = False
        self._btn_action.setEnabled(False)
        self._update_required_label_styles()

    def _action_clicked(self) -> None:
        if not self._folder or not self._basename:
            return

        path = self._folder / f"{self._basename}.json"
        if not path.exists():
            self._create()
            return

        # Save mode
        self._save()

    def has_unsaved_changes(self) -> bool:
        return bool(self._dirty)

    def save_changes(self) -> bool:
        return self._save()

    def discard_changes(self) -> None:
        if self._path is not None and self._path.exists():
            self._load(self._path)
        else:
            self._dirty = False
            self._btn_action.setEnabled(False)

    def _create(self) -> None:
        if not self._folder or not self._basename:
            return
        path = self._folder / f"{self._basename}.json"
        if path.exists():
            self.set_context(folder=self._folder, basename=self._basename, path=path)
            return

        data = {
            "name": self._basename,
            "nb_players": "",
            "editor": "",
            "year": 0,
            "description": {lang: " " for lang in self.LANGS},
        }
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Create failed", str(e))
            return

        self._on_saved()
        # Show fields immediately for this selection.
        self.set_context(folder=self._folder, basename=self._basename, path=path)

    def _mark_dirty(self, *args) -> None:
        if self._path is None or not self._path.exists():
            return
        self._dirty = True
        if self._btn_action.text() == "Save":
            self._btn_action.setEnabled(True)

    def _save(self) -> bool:
        if not self._path:
            return False
        if not self._dirty:
            return True

        # Preserve unknown keys by starting from the last loaded JSON.
        data: dict = dict(self._raw_json) if isinstance(self._raw_json, dict) else {}
        data["name"] = self._name.text().strip()
        # Store as string (supports values like "1-2").
        data["nb_players"] = self._nb_players.text().strip()
        data["editor"] = self._editor.currentText().strip()
        data["year"] = int(self._year.value())

        existing_desc = data.get("description")
        desc_out: dict = dict(existing_desc) if isinstance(existing_desc, dict) else {}
        for lang in self.LANGS:
            desc_out[lang] = self._desc_for_json(self._desc_edits[lang].toPlainText())
        data["description"] = desc_out

        # Apply user edits for simple "Others" fields.
        for key, w in self._others_simple_widgets.items():
            try:
                if isinstance(w, QLineEdit):
                    data[key] = w.text()
                elif isinstance(w, QCheckBox):
                    data[key] = bool(w.isChecked())
                elif isinstance(w, QSpinBox):
                    data[key] = int(w.value())
            except Exception:
                # If a widget can't be read for some reason, leave the original value intact.
                pass

        try:
            self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))
            return False

        self._raw_json = dict(data)
        self._dirty = False
        self._btn_action.setEnabled(False)
        self._on_saved()
        return True


class SnapshotsWidget(QWidget):
    def __init__(self, *, cards: list[SnapshotCard], on_reorder):
        super().__init__()
        self._cards = cards
        self._on_reorder = on_reorder
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for c in cards:
            layout.addWidget(c)

    def on_snapshot_drop(self, src_index: int, dst_index: int) -> None:
        self._on_reorder(src_index, dst_index)


class SnapshotsRow(QWidget):
    def __init__(self, *, cards: list[SnapshotCard], on_reorder):
        super().__init__()
        self._on_reorder = on_reorder
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Keep snapshot cards a consistent width (like other image cards).
        w = max((c.sizeHint().width() for c in cards), default=0)
        for c in cards:
            if w > 0:
                c.setFixedWidth(w)
            layout.addWidget(c)
        layout.addStretch(1)

    def on_snapshot_drop(self, src_index: int, dst_index: int) -> None:
        self._on_reorder(src_index, dst_index)


class OverlayBuildDialog(QDialog):
    def __init__(self, *, parent: QWidget, can_use_big_overlay: bool):
        super().__init__(parent)
        self.choice: str | None = None
        self.setWindowTitle("Build Overlay")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        try:
            layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass

        layout.addWidget(QLabel("Choose source for the bottom image:"))

        row = QHBoxLayout()
        btn_browse = QPushButton("Browse")
        btn_paste = QPushButton("Paste")
        btn_big = QPushButton("Use Big Overlay")
        btn_big.setEnabled(can_use_big_overlay)

        btn_browse.clicked.connect(self._choose_browse)
        btn_paste.clicked.connect(self._choose_paste)
        btn_big.clicked.connect(self._choose_big)

        row.addWidget(btn_browse)
        row.addWidget(btn_paste)
        row.addWidget(btn_big)
        row.addStretch(1)
        layout.addLayout(row)

        cancel_row = QHBoxLayout()
        cancel_row.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        cancel_row.addWidget(btn_cancel)
        layout.addLayout(cancel_row)

    def _choose_browse(self) -> None:
        self.choice = "browse"
        self.accept()

    def _choose_paste(self) -> None:
        self.choice = "paste"
        self.accept()

    def _choose_big(self) -> None:
        self.choice = "big"
        self.accept()


class QrUrlDialog(QDialog):
    def __init__(self, *, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("QR Code")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        try:
            layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass

        layout.addWidget(QLabel("Enter URL:"))

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("https://...")
        self._edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(self._edit, 1)

        btn_paste = QPushButton("Paste")
        btn_paste.setMaximumHeight(24)
        btn_paste.setToolTip("Paste the current clipboard text into the URL field")
        btn_paste.clicked.connect(self._paste)
        row.addWidget(btn_paste)

        layout.addLayout(row)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addStretch(1)
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        # Roughly 150% of the default QInputDialog width.
        self.setMinimumWidth(600)
        self.resize(600, self.sizeHint().height())

    def value(self) -> str:
        return self._edit.text()

    def _paste(self) -> None:
        self._edit.setText(QApplication.clipboard().text() or "")
        self._edit.setFocus()
        self._edit.selectAll()


class ConfigLookupDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        rom_cfgs_dir: Path,
        mapping_path: Path,
    ):
        super().__init__(parent)
        self._rom_cfgs_dir = rom_cfgs_dir
        self._mapping_path = mapping_path
        self.selected_src: Path | None = None

        self.setWindowTitle("Config Lookup")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        try:
            layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs, 1)

        # --- Tab 1: Select Cfg ---
        tab_select = QWidget()
        tab_select_l = QVBoxLayout(tab_select)
        tab_select_l.setContentsMargins(0, 0, 0, 0)
        tab_select_l.setSpacing(6)

        tab_select_l.addWidget(QLabel("Select one of the bundled configs:"))
        self._list_cfg = QListWidget()
        tab_select_l.addWidget(self._list_cfg, 1)

        row1 = QHBoxLayout()
        row1.addStretch(1)
        self._btn_use_cfg = QPushButton("Use Selected")
        self._btn_use_cfg.setEnabled(False)
        self._btn_use_cfg.clicked.connect(self._use_selected_cfg)
        row1.addWidget(self._btn_use_cfg)
        tab_select_l.addLayout(row1)

        self._tabs.addTab(tab_select, "Select Cfg")

        # --- Tab 2: Search By Game ---
        tab_search = QWidget()
        tab_search_l = QVBoxLayout(tab_search)
        tab_search_l.setContentsMargins(0, 0, 0, 0)
        tab_search_l.setSpacing(6)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search, 1)
        tab_search_l.addLayout(search_row)

        self._list_games = QListWidget()
        tab_search_l.addWidget(self._list_games, 1)

        row2 = QHBoxLayout()
        row2.addStretch(1)
        self._btn_use_game = QPushButton("Use Selected")
        self._btn_use_game.setEnabled(False)
        self._btn_use_game.clicked.connect(self._use_selected_game)
        row2.addWidget(self._btn_use_game)
        tab_search_l.addLayout(row2)

        self._tabs.addTab(tab_search, "Search By Game")

        # Cancel row
        cancel_row = QHBoxLayout()
        cancel_row.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        cancel_row.addWidget(btn_cancel)
        layout.addLayout(cancel_row)

        self._cfg_items: list[Path] = []
        self._game_items: list[tuple[str, int]] = []

        self._load_cfgs()
        self._load_mapping()
        self._apply_filter("")

        self._list_cfg.currentRowChanged.connect(lambda _: self._btn_use_cfg.setEnabled(self._list_cfg.currentRow() >= 0))
        self._list_games.currentRowChanged.connect(lambda _: self._btn_use_game.setEnabled(self._list_games.currentRow() >= 0))

    def _load_cfgs(self) -> None:
        self._list_cfg.clear()
        self._cfg_items = []
        for i in range(10):
            p = self._rom_cfgs_dir / f"{i}.cfg"
            if p.exists() and p.is_file():
                self._cfg_items.append(p)
        for p in self._cfg_items:
            self._list_cfg.addItem(p.name)

    def _load_mapping(self) -> None:
        self._game_items = []
        if not self._mapping_path.exists():
            return
        try:
            text = self._mapping_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        seen: set[tuple[str, int]] = set()
        for i, line in enumerate(text.splitlines()):
            if i == 0:
                continue
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            title = parts[1].strip()
            try:
                map_no = int(parts[2].strip())
            except Exception:
                continue
            if not title:
                continue
            key = (title, map_no)
            if key in seen:
                continue
            seen.add(key)
            self._game_items.append(key)

        self._game_items.sort(key=lambda t: (t[0].lower(), t[1]))

    def _apply_filter(self, text: str) -> None:
        q = (text or "").strip().lower()
        self._list_games.clear()
        for title, map_no in self._game_items:
            if q and q not in title.lower():
                continue
            item = QListWidgetItem(f"{title}\t(Map {map_no})")
            item.setData(Qt.ItemDataRole.UserRole, map_no)
            self._list_games.addItem(item)

    def _use_selected_cfg(self) -> None:
        row = self._list_cfg.currentRow()
        if row < 0 or row >= len(self._cfg_items):
            return
        self.selected_src = self._cfg_items[row]
        self.accept()

    def _use_selected_game(self) -> None:
        item = self._list_games.currentItem()
        if item is None:
            return
        map_no = item.data(Qt.ItemDataRole.UserRole)
        try:
            map_no = int(map_no)
        except Exception:
            return
        src = self._rom_cfgs_dir / f"{map_no}.cfg"
        if not src.exists():
            QMessageBox.warning(self, "Config Lookup", f"Missing bundled cfg: {src.name}")
            return
        self.selected_src = src
        self.accept()


class RenameBasenameDialog(QDialog):
    def __init__(self, *, parent: QWidget, initial: str, title: str = "Change File Name"):
        super().__init__(parent)
        self._initial = initial

        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        try:
            layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass

        layout.addWidget(QLabel("New basename:"))
        self._edit = QLineEdit()
        self._edit.setText(initial)
        self._edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._edit.selectAll()
        layout.addWidget(self._edit)

        self._lbl_count = QLabel("")
        layout.addWidget(self._lbl_count)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.accept)
        row.addWidget(btn_ok)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        layout.addLayout(row)

        self._edit.textChanged.connect(self._update_count)
        self._update_count(self._edit.text())

        self._edit.setFocus()

    def value(self) -> str:
        return self._edit.text()

    def _update_count(self, text: str) -> None:
        self._lbl_count.setText(f"Characters: {len(text)}")


class CreateFolderDialog(QDialog):
    def __init__(self, *, parent: QWidget, root_folder: Path, initial_parent: Path):
        super().__init__(parent)
        self._root = root_folder
        self._parent_dir = initial_parent

        self.setWindowTitle("Create Folder")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        try:
            layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass

        layout.addWidget(QLabel("Create under:"))
        crumbs = QWidget()
        self._crumb_layout = QHBoxLayout(crumbs)
        self._crumb_layout.setContentsMargins(0, 0, 0, 0)
        self._crumb_layout.setSpacing(2)
        layout.addWidget(crumbs)

        layout.addWidget(QLabel("Folder name:"))
        self._edit = QLineEdit()
        self._edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._edit)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.accept)
        row.addWidget(btn_ok)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        layout.addLayout(row)

        self._rebuild_breadcrumb()
        self._edit.setFocus()

        # Roughly 150% wider than the default size hint.
        self.adjustSize()
        sh = self.sizeHint()
        self.resize(int(sh.width() * 1.5), sh.height())

    def parent_dir(self) -> Path:
        return self._parent_dir

    def value(self) -> str:
        return self._edit.text()

    def _set_parent_dir(self, p: Path) -> None:
        self._parent_dir = p
        self._rebuild_breadcrumb()

    def _rebuild_breadcrumb(self) -> None:
        # Clear existing crumbs.
        while self._crumb_layout.count() > 0:
            item = self._crumb_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        root = self._root
        try:
            rel = self._parent_dir.resolve().relative_to(root.resolve())
        except Exception:
            rel = Path(".")
            self._parent_dir = root

        def add_sep() -> None:
            lbl = QLabel(">")
            lbl.setStyleSheet("color: gray;")
            self._crumb_layout.addWidget(lbl)

        def add_crumb(label: str, target: Path) -> None:
            btn = QToolButton()
            btn.setText(label)
            btn.setAutoRaise(True)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            btn.clicked.connect(lambda _=False, t=target: self._set_parent_dir(t))
            self._crumb_layout.addWidget(btn)

        add_crumb("Root", root)
        cur = root
        if str(rel) not in {".", ""}:
            for part in rel.parts:
                cur = cur / part
                add_sep()
                add_crumb(part, cur)

        self._crumb_layout.addStretch(1)


class MoveGameDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        root_folder: Path,
        current_folder: Path,
        title: str = "Move",
        allow_copy: bool = True,
    ):
        super().__init__(parent)
        self._root = root_folder

        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        try:
            layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass

        layout.addWidget(QLabel("Move to:"))

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self._tree)

        row = QHBoxLayout()
        row.addStretch(1)
        self._chk_copy = QCheckBox("Make Copy")
        self._chk_copy.setChecked(False)
        self._chk_copy.setToolTip("If checked, copies the game files to the selected folder instead of moving them.")
        self._chk_copy.setVisible(bool(allow_copy))
        row.addWidget(self._chk_copy)
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.accept)
        row.addWidget(btn_ok)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        layout.addLayout(row)

        root_item = QTreeWidgetItem(["Root"])
        root_item.setData(0, Qt.ItemDataRole.UserRole, {"path": str(root_folder)})
        self._tree.addTopLevelItem(root_item)
        root_item.setExpanded(True)

        folder_items: dict[Path, QTreeWidgetItem] = {}
        for d in sorted(
            [p for p in root_folder.rglob("*") if p.is_dir() and not _is_hidden_dir(p)],
            key=lambda p: p.as_posix().lower(),
        ):
            try:
                rel = d.relative_to(root_folder)
            except Exception:
                continue
            parent_rel = rel.parent
            parent_item = root_item if parent_rel == Path(".") else folder_items.get(parent_rel)
            if parent_item is None:
                parent_item = root_item

            item = QTreeWidgetItem([d.name])
            item.setData(0, Qt.ItemDataRole.UserRole, {"path": str(d)})
            parent_item.addChild(item)
            folder_items[rel] = item

        # Preselect current folder.
        try:
            rel_cur = current_folder.resolve().relative_to(root_folder.resolve())
        except Exception:
            rel_cur = Path(".")

        if str(rel_cur) in {".", ""}:
            self._tree.setCurrentItem(root_item)
        else:
            cur_item = folder_items.get(rel_cur)
            if cur_item is not None:
                p = cur_item
                while p is not None:
                    p.setExpanded(True)
                    p = p.parent()
                self._tree.setCurrentItem(cur_item)
            else:
                self._tree.setCurrentItem(root_item)

        self.resize(520, 420)

    def selected_folder(self) -> Path | None:
        item = self._tree.currentItem()
        if item is None:
            return None
        info = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(info, dict):
            return None
        raw = info.get("path")
        if not raw:
            return None
        try:
            return Path(str(raw))
        except Exception:
            return None

    def make_copy(self) -> bool:
        return bool(self._chk_copy.isChecked())


class MainWindow(QMainWindow):
    def __init__(self, *, config: AppConfig, config_path: Path, app: QApplication | None = None):
        super().__init__()
        self._config = config
        self._config_path = config_path
        self._app = app

        self._folder: Path | None = None
        self._games: dict[str, GameAssets] = {}
        self._folder_assets: dict[str, GameAssets] = {}
        self._palette_files: list[Path] = []
        self._keyboard_files: list[Path] = []
        self._current: str | None = None

        self._analysis_enabled: bool = False
        self._analysis_by_game: dict[str, set[str]] = {}
        self._analysis_include_json_checks: bool = False
        self._filter_checks: dict[str, QCheckBox] = {}
        self._list_panel: QWidget | None = None
        self._filters_scroll: QScrollArea | None = None

        self._force_expand_folder_paths: set[str] = set()
        self._post_move_select_id: str | None = None
        self._has_any_folders: bool = False

        self._multi_selected_game_ids: list[str] = []

        self.setWindowTitle(main_window_title())
        self.setAcceptDrops(True)

        # Add menu bar on Linux for better desktop integration.
        import sys
        if sys.platform.startswith("linux"):
            self._setup_menu_bar()

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)

        # Top bar
        top = QHBoxLayout()

        btn_size = QSize(28, 28)
        icon_size = QSize(18, 18)

        self._btn_browse = QToolButton()
        self._btn_browse.setToolTip("Browse games folder")
        self._btn_browse.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._btn_browse.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self._btn_browse.setFixedSize(btn_size)
        self._btn_browse.setIconSize(icon_size)
        self._btn_browse.setStyleSheet("QToolButton { padding: 0px; }")
        self._btn_browse.clicked.connect(self._browse_folder)
        top.addWidget(self._btn_browse)

        self._btn_refresh = QToolButton()
        self._btn_refresh.setToolTip("Refresh games list")
        self._btn_refresh.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._btn_refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self._btn_refresh.setFixedSize(btn_size)
        self._btn_refresh.setIconSize(icon_size)
        self._btn_refresh.setStyleSheet("QToolButton { padding: 0px; }")
        self._btn_refresh.clicked.connect(self._refresh_clicked)
        top.addWidget(self._btn_refresh)

        self._btn_add_files = QToolButton()
        self._btn_add_files.setToolTip("Add files to selected folder")
        self._btn_add_files.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._btn_add_files.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        self._btn_add_files.setFixedSize(btn_size)
        self._btn_add_files.setIconSize(icon_size)
        self._btn_add_files.setStyleSheet("QToolButton { padding: 0px; }")
        self._btn_add_files.clicked.connect(self._add_files_dialog)
        top.addWidget(self._btn_add_files)

        self._btn_create_folder = QToolButton()
        self._btn_create_folder.setToolTip("Create folder under selection")
        self._btn_create_folder.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._btn_create_folder.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder))
        self._btn_create_folder.setFixedSize(btn_size)
        self._btn_create_folder.setIconSize(icon_size)
        self._btn_create_folder.setStyleSheet("QToolButton { padding: 0px; }")
        self._btn_create_folder.clicked.connect(self._create_folder_clicked)
        top.addWidget(self._btn_create_folder)
        top.addStretch(1)
        self._lbl_folder = QLabel("(no folder)")
        self._lbl_folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self._lbl_folder)

        self._lbl_warnings = QLabel("Warnings: 0")
        top.addWidget(self._lbl_warnings)

        self._btn_open_ini = QToolButton()
        self._btn_open_ini.setToolTip("Open sgm.ini in default editor")
        self._btn_open_ini.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._btn_open_ini.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self._btn_open_ini.setFixedSize(btn_size)
        self._btn_open_ini.setIconSize(icon_size)
        self._btn_open_ini.setStyleSheet("QToolButton { padding: 0px; }")
        self._btn_open_ini.clicked.connect(self._open_ini_clicked)
        top.addWidget(self._btn_open_ini)

        # Theme selector
        from sgm.ui.theme import THEMES
        self._cmb_theme = QComboBox()
        self._cmb_theme.setToolTip("UI Theme")
        self._cmb_theme.addItems([t.capitalize() for t in THEMES])
        current_idx = THEMES.index(config.theme) if config.theme in THEMES else 0
        self._cmb_theme.setCurrentIndex(current_idx)
        self._cmb_theme.currentIndexChanged.connect(self._on_theme_changed)
        self._cmb_theme.setFixedWidth(80)
        top.addWidget(self._cmb_theme)

        root_layout.addLayout(top)

        # Main split
        split = QSplitter()

        self._list_panel = QWidget()
        list_l = QVBoxLayout(self._list_panel)
        list_l.setContentsMargins(0, 0, 0, 0)
        list_l.setSpacing(6)

        self._lbl_game_count = QLabel("Games: 0")
        list_l.addWidget(self._lbl_game_count)

        # Search/filter box
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search games...")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self._search_box)
        list_l.addLayout(search_row)

        self._tree = GamesTreeWidget(parent=self, on_move_games=self._move_games_to_folder, on_add_files=self._add_files_to_folder)
        self._tree.itemSelectionChanged.connect(self._tree_selection_changed)
        list_l.addWidget(self._tree, 1)

        analyze = QFrame()
        analyze.setFrameShape(QFrame.Shape.Box)
        analyze.setFrameShadow(QFrame.Shadow.Plain)
        analyze.setLineWidth(1)
        analyze_l = QVBoxLayout(analyze)
        analyze_l.setContentsMargins(6, 6, 6, 6)
        analyze_l.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Analyze")
        lbl.setStyleSheet("font-weight: 600;")
        row.addWidget(lbl)
        row.addStretch(1)
        self._btn_analyze = QPushButton("Analyze")
        self._btn_analyze.setToolTip(
            "Scan games and compute warnings so you can filter the games list. "
            "Optionally enable 'Include JSON Checks' to validate JSON metadata and referenced files (may take time)."
        )
        self._btn_analyze.setMaximumHeight(24)
        self._btn_analyze.clicked.connect(self._analyze_folder)
        row.addWidget(self._btn_analyze)
        analyze_l.addLayout(row)

        self._chk_include_json_checks = QCheckBox("Include JSON Checks")
        self._chk_include_json_checks.setChecked(False)
        self._chk_include_json_checks.setToolTip(
            "When enabled, Analyze also inspects each game's JSON metadata (name, players, editor, year, description, "
            "and jzintv_extra file references). This can take time to perform."
        )
        analyze_l.addWidget(self._chk_include_json_checks)

        self._lbl_analyze = QLabel("")
        self._lbl_analyze.setVisible(False)
        analyze_l.addWidget(self._lbl_analyze)

        self._chk_only_warnings = QCheckBox("Only games with warnings")
        self._chk_only_warnings.setEnabled(False)
        self._chk_only_warnings.stateChanged.connect(lambda _=None: self._rebuild_game_list())
        analyze_l.addWidget(self._chk_only_warnings)

        found_row = QHBoxLayout()
        found_row.setContentsMargins(0, 0, 0, 0)
        self._lbl_found_warnings = QLabel("Found Warnings:")
        self._lbl_found_warnings.setVisible(False)
        found_row.addWidget(self._lbl_found_warnings)
        found_row.addStretch(1)
        self._btn_select_all_warnings = QPushButton("✓")
        self._btn_select_all_warnings.setToolTip("Select all warning filters")
        self._btn_select_all_warnings.setMaximumHeight(24)
        self._btn_select_all_warnings.setFixedWidth(28)
        self._btn_select_all_warnings.setVisible(False)
        self._btn_select_all_warnings.clicked.connect(self._select_all_warning_filters)
        found_row.addWidget(self._btn_select_all_warnings)
        self._btn_clear_all_warnings = QPushButton("✕")
        self._btn_clear_all_warnings.setToolTip("Clear all warning filters")
        self._btn_clear_all_warnings.setMaximumHeight(24)
        self._btn_clear_all_warnings.setFixedWidth(28)
        self._btn_clear_all_warnings.setVisible(False)
        self._btn_clear_all_warnings.clicked.connect(self._clear_all_warning_filters)
        found_row.addWidget(self._btn_clear_all_warnings)
        analyze_l.addLayout(found_row)

        self._filters_scroll = QScrollArea()
        self._filters_scroll.setWidgetResizable(True)
        self._filters_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._filters_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._filters_scroll.setVisible(False)
        self._filters_scroll.setFrameShape(QFrame.Shape.NoFrame)
        filters_inner = QWidget()
        self._filters_l = QVBoxLayout(filters_inner)
        self._filters_l.setContentsMargins(0, 0, 0, 0)
        self._filters_l.setSpacing(2)
        self._filters_scroll.setWidget(filters_inner)
        analyze_l.addWidget(self._filters_scroll)

        list_l.addWidget(analyze)

        self._btn_json_bulk_update = QPushButton("JSON Bulk Update")
        self._btn_json_bulk_update.setToolTip("Visualize and update a JSON field across all games")
        self._btn_json_bulk_update.clicked.connect(self._open_json_bulk_update_all)
        self._btn_json_bulk_update.setEnabled(False)
        list_l.addWidget(self._btn_json_bulk_update)

        split.addWidget(self._list_panel)

        self._detail_root = QWidget()
        split.addWidget(self._detail_root)
        split.setStretchFactor(1, 1)

        root_layout.addWidget(split, 1)
        self.setCentralWidget(root)

        # Status bar
        from PySide6.QtWidgets import QStatusBar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

        self._build_details()

        self._init_analyze_filters()

    def _on_search_changed(self, text: str) -> None:
        """Filter the games tree based on search text."""
        search = text.strip().lower()

        def filter_item(item: QTreeWidgetItem) -> bool:
            """Returns True if item or any child matches search."""
            info = item.data(0, Qt.ItemDataRole.UserRole)
            item_type = info.get("type") if isinstance(info, dict) else None

            if item_type == "folder":
                any_child_visible = False
                for i in range(item.childCount()):
                    if filter_item(item.child(i)):
                        any_child_visible = True
                folder_matches = search in item.text(0).lower()
                visible = any_child_visible or folder_matches
                item.setHidden(not visible)
                if any_child_visible and search:
                    item.setExpanded(True)
                return visible
            else:
                matches = not search or search in item.text(0).lower()
                item.setHidden(not matches)
                return matches

        for i in range(self._tree.topLevelItemCount()):
            filter_item(self._tree.topLevelItem(i))

        # Update count
        visible = sum(1 for i in range(self._tree.topLevelItemCount())
                      for item in self._iter_tree_games(self._tree.topLevelItem(i))
                      if not item.isHidden())
        total = len(self._games)
        if search:
            self._lbl_game_count.setText(f"Games: {visible}/{total}")
        else:
            self._lbl_game_count.setText(f"Games: {total}")

    def _iter_tree_games(self, item: QTreeWidgetItem):
        """Yield all game items under an item."""
        info = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(info, dict) and info.get("type") == "game":
            yield item
        for i in range(item.childCount()):
            yield from self._iter_tree_games(item.child(i))

    def _set_status(self, message: str, timeout: int = 0) -> None:
        """Update status bar message. timeout=0 means permanent until next update."""
        if hasattr(self, "_status_bar"):
            self._status_bar.showMessage(message, timeout)

    def _tree_selection_changed(self) -> None:
        items = list(self._tree.selectedItems() or []) if hasattr(self, "_tree") else []
        if len(items) != 1:
            prev = self._current
            if prev is not None and self._meta_editor.has_unsaved_changes():
                dlg = QMessageBox(self)
                dlg.setIcon(QMessageBox.Icon.Warning)
                dlg.setWindowTitle("Unsaved Changes")
                dlg.setText("You have unsaved metadata changes.")
                dlg.setInformativeText("Save changes before switching selection?")
                dlg.setStandardButtons(
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel
                )
                dlg.setDefaultButton(QMessageBox.StandardButton.Save)
                resp = dlg.exec()

                if resp == QMessageBox.StandardButton.Save:
                    if not self._meta_editor.save_changes():
                        # Save failed; keep current selection and preserve edits.
                        blocker = QSignalBlocker(self._tree)
                        try:
                            self._tree.clearSelection()
                            self._set_current_in_tree(prev, silent=False)
                        finally:
                            _ = blocker
                        return
                elif resp == QMessageBox.StandardButton.Discard:
                    self._meta_editor.discard_changes()
                else:
                    # Cancel: keep current selection and preserve edits.
                    blocker = QSignalBlocker(self._tree)
                    try:
                        self._tree.clearSelection()
                        self._set_current_in_tree(prev, silent=False)
                    finally:
                        _ = blocker
                    return

            if not items:
                self._select_none()
            else:
                self._select_multi(items)
            return

        item = items[0]
        info = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(info, dict) and info.get("type") == "game":
            self._select_game(str(info.get("id") or ""))
            return
        if isinstance(info, dict) and info.get("type") == "folder":
            p = str(info.get("path") or "")
            if p:
                self._select_folder(p)
                return
        self._select_none()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_filter_scroll_height()

    # ---------- public ----------

    def load_folder(self, folder: Path) -> None:
        self._set_status(f"Loading {folder.name}...")
        self._reset_analysis_state()
        self._folder = folder
        self._lbl_folder.setText(str(folder))

        self._config.last_game_folder = str(folder)
        try:
            self._config.save(self._config_path)
        except Exception:
            pass

        self.refresh()
        self._set_status(f"Loaded {len(self._games)} games from {folder.name}")

    def _refresh_clicked(self) -> None:
        # Manual refresh resets Analyze results; user must Analyze again to filter.
        self._reset_analysis_state()
        self.refresh()

    def _open_ini_clicked(self) -> None:
        try:
            ini_path = self._config_path
            if not ini_path or not ini_path.exists():
                QMessageBox.warning(self, "Open sgm.ini", f"Config file not found:\n{ini_path}")
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(ini_path)))
        except Exception as e:
            QMessageBox.warning(self, "Open sgm.ini", str(e))

    def _on_theme_changed(self, index: int) -> None:
        from sgm.ui.theme import THEMES, get_stylesheet
        if index < 0 or index >= len(THEMES):
            return
        theme = THEMES[index]
        self._config.theme = theme
        self._config.save(self._config_path)
        if self._app is not None:
            self._app.setStyleSheet(get_stylesheet(theme))

    def _setup_menu_bar(self) -> None:
        """Create menu bar for Linux desktop integration."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        open_action = QAction("&Open Folder...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._browse_folder)
        file_menu.addAction(open_action)

        refresh_action = QAction("&Refresh", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self._refresh_clicked)
        file_menu.addAction(refresh_action)

        file_menu.addSeparator()

        add_files_action = QAction("&Add Files...", self)
        add_files_action.setShortcut("Ctrl+A")
        add_files_action.triggered.connect(self._add_files_dialog)
        file_menu.addAction(add_files_action)

        create_folder_action = QAction("&New Folder...", self)
        create_folder_action.setShortcut("Ctrl+N")
        create_folder_action.triggered.connect(self._create_folder_clicked)
        file_menu.addAction(create_folder_action)

        file_menu.addSeparator()

        open_ini_action = QAction("Open &Config (sgm.ini)...", self)
        open_ini_action.triggered.connect(self._open_ini_clicked)
        file_menu.addAction(open_ini_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")

        analyze_action = QAction("&Analyze Games", self)
        analyze_action.triggered.connect(self._analyze_folder)
        tools_menu.addAction(analyze_action)

        bulk_json_action = QAction("&JSON Bulk Update...", self)
        bulk_json_action.triggered.connect(lambda: self._open_bulk_json_update([]))
        tools_menu.addAction(bulk_json_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        from sgm.ui.theme import THEMES
        theme_menu = view_menu.addMenu("&Theme")
        for theme in THEMES:
            action = QAction(theme.capitalize(), self)
            action.setCheckable(True)
            action.setChecked(self._config.theme == theme)
            action.triggered.connect(lambda checked, t=theme: self._set_theme(t))
            theme_menu.addAction(action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _set_theme(self, theme: str) -> None:
        from sgm.ui.theme import THEMES, get_stylesheet
        if theme not in THEMES:
            return
        self._config.theme = theme
        self._config.save(self._config_path)
        if self._app is not None:
            self._app.setStyleSheet(get_stylesheet(theme))
        # Update combo box if present
        if hasattr(self, "_cmb_theme"):
            idx = THEMES.index(theme)
            self._cmb_theme.setCurrentIndex(idx)

    def _show_about(self) -> None:
        from sgm.version import APP_NAME, version_string
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME}</h3>"
            f"<p>Version: {version_string()}</p>"
            f"<p>Desktop GUI for managing Intellivision Sprint Console games.</p>"
            f"<p>Manage ROMs, config, metadata, and images for sideloading.</p>",
        )

    def _open_cfg_clicked(self) -> None:
        try:
            game = self._current_game()
            cfg_path = game.config if game is not None else None
            if not cfg_path or not cfg_path.exists():
                QMessageBox.warning(self, "Open Config", f"Config file not found:\n{cfg_path}")
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(cfg_path)))
        except Exception as e:
            QMessageBox.warning(self, "Open Config", str(e))

    def _reset_analysis_state(self) -> None:
        self._analysis_enabled = False
        self._analysis_by_game = {}

        if hasattr(self, "_lbl_analyze"):
            self._lbl_analyze.setText("")
            self._lbl_analyze.setVisible(False)
        if hasattr(self, "_chk_only_warnings"):
            with QSignalBlocker(self._chk_only_warnings):
                self._chk_only_warnings.setChecked(False)
            self._chk_only_warnings.setEnabled(False)

        for chk in self._filter_checks.values():
            with QSignalBlocker(chk):
                chk.setChecked(True)
            chk.setEnabled(False)
            chk.setVisible(False)

        self._update_filter_visibility()

    def refresh(self, *, preserve_metadata_edits: bool = False) -> None:
        if not self._folder:
            return
        scan = scan_folder(self._folder)
        self._games = scan.games
        self._folder_assets = scan.folders
        self._palette_files = list(scan.palette_files)
        self._keyboard_files = list(scan.keyboard_files)

        if self._analysis_enabled:
            self._analysis_by_game = {
                b: self._compute_warning_codes(g, include_json_checks=self._analysis_include_json_checks)
                for b, g in self._games.items()
            }
            self._update_filter_visibility()

        silent_preserve = bool(preserve_metadata_edits and self._meta_editor.has_unsaved_changes())
        self._rebuild_game_list(preserve=self._current, silent_preserve=silent_preserve)
        if silent_preserve:
            # We rebuilt the tree without emitting selection-changed signals.
            # Refresh image thumbnails/warnings for the current selection without
            # reloading metadata from disk (which would wipe unsaved edits).
            self._refresh_current_details_without_metadata_reload()

        if hasattr(self, "_btn_json_bulk_update"):
            self._btn_json_bulk_update.setEnabled(bool(self._games))

    def _refresh_current_details_without_metadata_reload(self) -> None:
        sel = self._current_selection()
        if sel is None:
            return

        kind, val = sel
        if kind == "game":
            game = self._games.get(val)
            if not game:
                return

            # Keep the header/controls in sync (without reloading metadata fields).
            self._rom_row.set_title("ROM")
            self._cfg_row.set_title("Config")
            self._btn_rename.setText("Change File Name")
            self._btn_rename.setToolTip("Rename this game's files (basename)")
            if hasattr(self, "_btn_move"):
                self._btn_move.setVisible(bool(self._has_any_folders))
                self._btn_move.setEnabled(bool(self._has_any_folders))
                self._btn_move.setToolTip("Move this game to a different folder")

            self._base_name.setText(f"Basename (game): {game.basename}")
            if len(game.basename) > self._config.desired_max_base_file_length:
                self._base_warn.setText(
                    f"Warning: basename length {len(game.basename)} exceeds DesiredMaxBaseFileLength={self._config.desired_max_base_file_length}"
                )
                self._base_warn.setVisible(True)
            else:
                self._base_warn.setText("")
                self._base_warn.setVisible(False)

            rom_warn = "Missing ROM" if game.rom is None else None
            self._rom_row.set_context(folder=game.folder, basename=game.basename, existing=game.rom, warning=rom_warn)
            self._rom_row.setEnabled(True)

            cfg_warn = None
            if game.rom is not None:
                if game.rom.suffix.lower() in {".int", ".bin"} and game.config is None:
                    cfg_warn = "Missing config for .int/.bin ROM (.cfg missing)"
            self._cfg_row.set_context(folder=game.folder, basename=game.basename, existing=game.config, warning=cfg_warn)
            self._cfg_row.setEnabled(True)

            self._set_images_context(game)
            self._lbl_warnings.setText(f"Warnings: {self._count_selected_warnings(game)}")
            return

        if kind == "folder":
            assets = self._current_assets()
            if not assets:
                return
            # Keep header/controls in sync (without reloading metadata fields).
            self._rom_row.set_title("ROM (Not Applicable)")
            self._cfg_row.set_title("Config (Not Applicable)")
            self._btn_rename.setText("Change Folder Name")
            self._btn_rename.setToolTip("Rename this folder and its folder-support files")
            if hasattr(self, "_btn_move"):
                self._btn_move.setVisible(True)
                self._btn_move.setEnabled(True)
                self._btn_move.setToolTip("Move this folder and its folder-support files")

            self._base_name.setText(f"Basename (folder): {assets.basename}")
            if len(assets.basename) > self._config.desired_max_base_file_length:
                self._base_warn.setText(
                    f"Warning: basename length {len(assets.basename)} exceeds DesiredMaxBaseFileLength={self._config.desired_max_base_file_length}"
                )
                self._base_warn.setVisible(True)
            else:
                self._base_warn.setText("")
                self._base_warn.setVisible(False)

            self._rom_row.set_context(folder=assets.folder, basename=assets.basename, existing=None, warning=None, missing_text="")
            self._cfg_row.set_context(folder=assets.folder, basename=assets.basename, existing=None, warning=None, missing_text="")
            self._rom_row.setEnabled(False)
            self._cfg_row.setEnabled(False)

            # Folder selections do not allow metadata editing; safe to refresh images.
            self._set_images_context(assets)
            self._lbl_warnings.setText(f"Warnings: {len(self._compute_warning_codes(assets, include_rom_cfg=False))}")
            return

    def _open_json_bulk_update_all(self) -> None:
        if not self._folder:
            return

        all_games: list[tuple[str, Path, str]] = []
        try:
            for gid, game in self._games.items():
                if not game:
                    continue
                all_games.append((str(gid), game.folder, game.basename))
        except Exception:
            all_games = []

        if not all_games:
            return

        # Stable ordering for the preview list.
        all_games = sorted(all_games, key=lambda t: (str(t[1]).casefold(), str(t[2]).casefold(), str(t[0]).casefold()))

        dlg = BulkJsonUpdateDialog(
            parent=self,
            games=all_games,
            all_games=all_games,
            json_keys=getattr(self._config, "json_keys", None),
        )
        dlg.exec()
        self.refresh()

    def _open_advanced_json(self, *, folder: Path | None, basename: str | None, path: Path | None) -> None:
        if not self._folder or path is None or not path.exists():
            return

        dlg = AdvancedJsonDialog(
            parent=self,
            json_path=path,
            root_folder=self._folder,
            palette_files=self._palette_files,
            keyboard_files=self._keyboard_files,
            media_prefix=getattr(self._config, "jzintv_media_prefix", "/media/usb0"),
            on_written=self._meta_editor.reload_from_disk,
        )
        dlg.exec()

    def _open_bulk_json_update(self, game_ids: list[str]) -> None:
        if not self._folder:
            return

        ids = [str(g or "").strip() for g in (game_ids or []) if str(g or "").strip()]
        if len(ids) < 2:
            return

        games: list[tuple[str, Path, str]] = []
        for gid in ids:
            game = self._games.get(gid)
            if not game:
                continue
            games.append((gid, game.folder, game.basename))

        if len(games) < 2:
            return

        all_games: list[tuple[str, Path, str]] = []
        try:
            for gid, game in self._games.items():
                if not game:
                    continue
                all_games.append((str(gid), game.folder, game.basename))
        except Exception:
            all_games = list(games)

        # Stable ordering for the preview list.
        all_games = sorted(all_games, key=lambda t: (str(t[1]).casefold(), str(t[2]).casefold(), str(t[0]).casefold()))

        dlg = BulkJsonUpdateDialog(
            parent=self,
            games=games,
            all_games=all_games,
            json_keys=getattr(self._config, "json_keys", None),
        )
        dlg.exec()
        self.refresh()

    def _iter_tree_items(self):
        def walk(item: QTreeWidgetItem):
            yield item
            for i in range(item.childCount()):
                yield from walk(item.child(i))

        for i in range(self._tree.topLevelItemCount()):
            yield from walk(self._tree.topLevelItem(i))

    def _expanded_folder_paths(self) -> set[str]:
        expanded: set[str] = set()
        for item in self._iter_tree_items():
            info = item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(info, dict) or info.get("type") != "folder":
                continue
            try:
                is_expanded = item.isExpanded()
            except Exception:
                try:
                    is_expanded = bool(self._tree.isItemExpanded(item))
                except Exception:
                    is_expanded = False
            if not is_expanded:
                continue
            p = info.get("path")
            if p:
                expanded.add(str(p))
        return expanded

    def _restore_expanded_folder_paths(self, expanded: set[str]) -> None:
        if not expanded:
            return
        for item in self._iter_tree_items():
            info = item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(info, dict) or info.get("type") != "folder":
                continue
            p = info.get("path")
            if p and str(p) in expanded:
                self._tree.expandItem(item)

    def _selected_tree_folder(self) -> Path | None:
        if not hasattr(self, "_tree"):
            return None
        item = self._tree.currentItem()
        if item is None:
            return self._folder

        info = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(info, dict) and info.get("type") == "folder":
            p = info.get("path")
            return Path(p) if p else self._folder

        if isinstance(info, dict) and info.get("type") == "game":
            parent = item.parent()
            pinfo = parent.data(0, Qt.ItemDataRole.UserRole) if parent is not None else None
            p = pinfo.get("path") if isinstance(pinfo, dict) and pinfo.get("type") == "folder" else None
            return Path(p) if p else self._folder

        return self._folder

    def _create_folder_clicked(self) -> None:
        if not self._folder:
            QMessageBox.information(self, "Create Folder", "Choose a folder first")
            return

        root = self._folder
        initial_parent = self._selected_tree_folder() or root

        dlg = CreateFolderDialog(parent=self, root_folder=root, initial_parent=initial_parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        parent_dir = dlg.parent_dir() or root
        name = (dlg.value() or "").strip()
        if not name:
            return

        if any(c in name for c in "\\/:*?\"<>|"):
            QMessageBox.warning(self, "Create Folder", "Folder name contains invalid filename characters")
            return

        # Prevent creating a folder that collides with an existing game basename
        # in the same parent folder.
        parent_key = sprint_path_key(parent_dir)
        name_key = sprint_name_key(name)
        for game in self._games.values():
            game_parent_key = sprint_path_key(game.folder)
            game_base_key = sprint_name_key(game.basename)
            if game_parent_key == parent_key and game_base_key == name_key:
                example = None
                try:
                    paths = game.all_paths()
                    example = str(paths[0]) if paths else None
                except Exception:
                    example = None

                details = f"\n\nExample file: {example}" if example else ""
                QMessageBox.warning(
                    self,
                    "Create Folder",
                    "Folder was not created.\n\n"
                    f"A game named '{name}' already exists in:\n{parent_dir}{details}\n\n"
                    "Choose a different folder name, or rename/move the game first.",
                )
                return

        new_dir = parent_dir / name
        try:
            new_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            QMessageBox.warning(self, "Create Folder", f"Folder already exists: {new_dir}")
            return
        except Exception as e:
            QMessageBox.warning(self, "Create Folder", str(e))
            return

        # Folder-like-game metadata: create sibling <folder>.json in the parent folder.
        json_path = parent_dir / f"{name}.json"
        if not json_path.exists():
            data = {
                "name": name,
                "nb_players": "",
                "editor": "",
                "year": 0,
                "description": {lang: " " for lang in MetadataEditor.LANGS},
            }
            try:
                json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            except Exception as e:
                QMessageBox.warning(self, "Create Folder", f"Folder created, but JSON creation failed: {e}")

        self.refresh()

    def _move_clicked(self) -> None:
        if not self._folder:
            return
        sel = self._current_selection()
        if sel is None:
            # Multi-select: only supported for games (not folders).
            game_ids = list(self._multi_selected_game_ids or [])
            if not game_ids:
                return
            if not self._has_any_folders:
                return

            first_game = self._games.get(game_ids[0])
            current_folder = first_game.folder if first_game is not None else self._folder
            dlg = MoveGameDialog(
                parent=self,
                root_folder=self._folder,
                current_folder=current_folder,
                title="Move Selected Games",
                allow_copy=True,
            )
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            dest = dlg.selected_folder()
            if dest is None:
                return

            make_copy = dlg.make_copy()
            if make_copy:
                # Batch copy.
                dest.mkdir(parents=True, exist_ok=True)

                # Preserve order but de-duplicate.
                ordered: list[str] = []
                seen: set[str] = set()
                for gid in game_ids:
                    g = str(gid or "").strip()
                    if not g or g in seen:
                        continue
                    seen.add(g)
                    ordered.append(g)

                moves: list[tuple[Path, Path]] = []
                for gid in ordered:
                    game = self._games.get(gid)
                    if not game:
                        continue
                    try:
                        if sprint_path_key(game.folder) == sprint_path_key(dest):
                            continue
                    except Exception:
                        continue

                    moves.extend(plan_move_game_files(game.folder, dest, game.basename))

                if not moves:
                    return

                # Detect duplicate destinations among the copy set.
                seen_dests: set[str] = set()
                for _, dst in moves:
                    key = sprint_path_key(dst)
                    if key in seen_dests:
                        QMessageBox.warning(self, "Copy blocked", f"Multiple selected games would collide at: {dst}")
                        return
                    seen_dests.add(key)

                # Ensure no destination already exists.
                for _, dst in moves:
                    if dst.exists():
                        QMessageBox.warning(self, "Copy blocked", f"Destination already exists: {dst}")
                        return

                try:
                    for src, dst in moves:
                        copy_file(src, dst, overwrite=False)
                except Exception as e:
                    QMessageBox.warning(self, "Copy failed", str(e))
                    return

                # Expand destination folder and refresh once.
                self._force_expand_folder_paths = {str(dest)}

                def do_refresh() -> None:
                    try:
                        QApplication.processEvents()
                        self.refresh()
                        if self._folder is not None:
                            try:
                                is_root = sprint_path_key(dest) == sprint_path_key(self._folder)
                            except Exception:
                                is_root = str(dest) == str(self._folder)
                            if not is_root:
                                self._current = f"f:{str(dest)}"
                                self._set_current_in_tree(self._current, silent=False)
                            else:
                                self._tree.clearSelection()
                                self._select_none()
                    finally:
                        self._force_expand_folder_paths = set()

                QTimer.singleShot(300, do_refresh)
                return

            # Batch move (existing helper).
            self._move_games_to_folder(game_ids, dest)
            return
        kind, val = sel
        if kind == "folder":
            folder_dir = Path(val)
            if not folder_dir.exists() or not folder_dir.is_dir():
                return

            dlg = MoveGameDialog(
                parent=self,
                root_folder=self._folder,
                current_folder=folder_dir.parent,
                title="Move Folder",
                allow_copy=False,
            )
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            dest_parent = dlg.selected_folder()
            if dest_parent is None:
                return

            try:
                if sprint_path_key(dest_parent) == sprint_path_key(folder_dir.parent):
                    QMessageBox.information(self, "Move Folder", "Folder is already in the selected folder.")
                    return
            except Exception:
                if str(dest_parent) == str(folder_dir.parent):
                    QMessageBox.information(self, "Move Folder", "Folder is already in the selected folder.")
                    return

            # Prevent moving a folder into itself (or into one of its descendants).
            src_key = sprint_path_key(folder_dir).rstrip("/")
            dst_key = sprint_path_key(dest_parent).rstrip("/")
            if dst_key == src_key or dst_key.startswith(src_key + "/"):
                QMessageBox.warning(self, "Move Folder", "Cannot move a folder into itself (or into one of its subfolders).")
                return

            # Prevent destination parent from containing a game with the same basename.
            parent_key = sprint_path_key(dest_parent)
            base_key = sprint_name_key(folder_dir.name)
            for game in self._games.values():
                game_parent_key = sprint_path_key(game.folder)
                game_base_key = sprint_name_key(game.basename)
                if game_parent_key == parent_key and game_base_key == base_key:
                    example = None
                    try:
                        paths = game.all_paths()
                        example = str(paths[0]) if paths else None
                    except Exception:
                        example = None
                    details = f"\n\nExample file: {example}" if example else ""
                    QMessageBox.warning(
                        self,
                        "Move Folder",
                        "Folder was not moved.\n\n"
                        f"A game named '{folder_dir.name}' already exists in:\n{dest_parent}{details}\n\n"
                        "Choose a different destination, or rename/move the game first.",
                    )
                    return

            dest_parent.mkdir(parents=True, exist_ok=True)
            new_dir = dest_parent / folder_dir.name
            if new_dir.exists():
                QMessageBox.warning(self, "Move Folder", f"Destination already exists: {new_dir}")
                return

            # Move folder-support files that live alongside the folder.
            moves: list[tuple[Path, Path]] = []
            src_parent = folder_dir.parent
            try:
                for entry in src_parent.iterdir():
                    if not entry.is_file():
                        continue
                    base, kind2 = _classify(entry)
                    if base != folder_dir.name or kind2 is None:
                        continue
                    if kind2 in {"rom", "config"}:
                        continue
                    moves.append((entry, dest_parent / entry.name))
            except Exception:
                pass

            # Move the folder directory itself.
            moves.append((folder_dir, new_dir))

            try:
                rename_many(moves)
            except RenameCollisionError as e:
                QMessageBox.warning(self, "Move Folder blocked", str(e))
                return
            except Exception as e:
                QMessageBox.warning(self, "Move Folder failed", str(e))
                return

            self._force_expand_folder_paths = {str(dest_parent), str(new_dir)}

            def do_refresh() -> None:
                try:
                    QApplication.processEvents()
                    self.refresh()
                    self._current = f"f:{str(new_dir)}"
                    self._set_current_in_tree(self._current, silent=False)
                finally:
                    self._force_expand_folder_paths = set()

            QTimer.singleShot(300, do_refresh)
            return

        # Game move
        game_id = val
        game = self._games.get(game_id)
        if not game:
            return
        if not self._has_any_folders:
            return

        dlg = MoveGameDialog(parent=self, root_folder=self._folder, current_folder=game.folder, title="Move", allow_copy=True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        dest = dlg.selected_folder()
        if dest is None:
            return

        make_copy = dlg.make_copy()

        try:
            if dest.resolve() == game.folder.resolve():
                QMessageBox.information(self, "Move", "Game is already in the selected folder.")
                return
        except Exception:
            if str(dest) == str(game.folder):
                QMessageBox.information(self, "Move", "Game is already in the selected folder.")
                return

        if make_copy:
            dest.mkdir(parents=True, exist_ok=True)
            moves = plan_move_game_files(game.folder, dest, game.basename)
            if not moves:
                return
            for _, dst in moves:
                if dst.exists():
                    QMessageBox.warning(self, "Copy blocked", f"Destination already exists: {dst}")
                    return
            try:
                for src, dst in moves:
                    copy_file(src, dst, overwrite=False)
            except Exception as e:
                QMessageBox.warning(self, "Copy failed", str(e))
                return
            self.refresh()
            return

        self._move_game_to_folder(game_id, dest)

    def _move_game_to_folder(self, game_id: str, dest_folder: Path) -> None:
        game = self._games.get(game_id)
        if not game:
            return
        if sprint_path_key(game.folder) == sprint_path_key(dest_folder):
            return

        dest_folder.mkdir(parents=True, exist_ok=True)
        moves = plan_move_game_files(game.folder, dest_folder, game.basename)
        if not moves:
            return

        try:
            rename_many(moves)
        except RenameCollisionError as e:
            QMessageBox.warning(self, "Move blocked", str(e))
            return
        except Exception as e:
            QMessageBox.warning(self, "Move failed", str(e))
            return

        # Compute the new game id (subfolder-aware).
        try:
            rel = dest_folder.relative_to(self._folder) if self._folder else Path(".")
        except Exception:
            rel = Path(".")
        new_id = game.basename if str(rel) in {".", ""} else f"{rel.as_posix()}/{game.basename}"

        # Preserve expanded folders and ensure the destination folder is visible.
        self._post_move_select_id = f"g:{new_id}"
        self._force_expand_folder_paths = {str(dest_folder)}

        def do_refresh() -> None:
            sel = self._post_move_select_id
            self._post_move_select_id = None
            try:
                QApplication.processEvents()
                self.refresh()
                if sel:
                    self._current = sel
                    self._set_current_in_tree(sel, silent=False)
            finally:
                self._force_expand_folder_paths = set()

        QTimer.singleShot(300, do_refresh)

    def _move_games_to_folder(self, game_ids: list[str], dest_folder: Path) -> None:
        # Batch move used by multi-select drag/drop.
        if not game_ids:
            return

        # Preserve order but de-duplicate.
        ordered: list[str] = []
        seen: set[str] = set()
        for gid in game_ids:
            g = str(gid or "").strip()
            if not g or g in seen:
                continue
            seen.add(g)
            ordered.append(g)

        moves: list[tuple[Path, Path]] = []
        for gid in ordered:
            game = self._games.get(gid)
            if not game:
                continue
            try:
                if sprint_path_key(game.folder) == sprint_path_key(dest_folder):
                    continue
            except Exception:
                continue

            dest_folder.mkdir(parents=True, exist_ok=True)
            moves.extend(plan_move_game_files(game.folder, dest_folder, game.basename))

        if not moves:
            return

        # Detect duplicate destinations among the move set (rename_many doesn't).
        seen_dests: set[str] = set()
        for _, dst in moves:
            key = sprint_path_key(dst)
            if key in seen_dests:
                QMessageBox.warning(self, "Move blocked", f"Multiple selected games would collide at: {dst}")
                return
            seen_dests.add(key)

        try:
            rename_many(moves)
        except RenameCollisionError as e:
            QMessageBox.warning(self, "Move blocked", str(e))
            return
        except Exception as e:
            QMessageBox.warning(self, "Move failed", str(e))
            return

        # Expand destination folder and refresh once.
        self._force_expand_folder_paths = {str(dest_folder)}

        def do_refresh() -> None:
            try:
                QApplication.processEvents()
                self.refresh()
                # Select destination folder (root has no visible folder node).
                if self._folder is not None:
                    try:
                        is_root = sprint_path_key(dest_folder) == sprint_path_key(self._folder)
                    except Exception:
                        is_root = str(dest_folder) == str(self._folder)
                    if not is_root:
                        self._current = f"f:{str(dest_folder)}"
                        self._set_current_in_tree(self._current, silent=False)
                    else:
                        self._tree.clearSelection()
                        self._select_none()
            finally:
                self._force_expand_folder_paths = set()

        QTimer.singleShot(300, do_refresh)

    def _init_analyze_filters(self) -> None:
        # Stable filter list so users can toggle specific warnings (e.g., missing overlay).
        ordered: list[tuple[str, str]] = [
            ("longname", "Long name"),
            ("missing:rom", "Missing ROM"),
            ("missing:cfg", "Missing Config"),
            ("missing:metadata", "Missing Metadata"),
            ("missing:box", "Missing Box"),
            ("missing:box_small", "Missing Box Small"),
            ("missing:overlay_big", "Missing Overlay Big"),
            ("missing:overlay", "Missing Overlay"),
            ("missing:qrcode", "Missing QR Code"),
            ("missing:snap1", "Missing Snap 1"),
            ("missing:snap2", "Missing Snap 2"),
            ("missing:snap3", "Missing Snap 3"),
            ("resolution:box", "Wrong Box resolution"),
            ("resolution:box_small", "Wrong Box Small resolution"),
            ("resolution:overlay_big", "Wrong Overlay Big resolution"),
            ("resolution:overlay", "Wrong Overlay resolution"),
            ("resolution:overlay2", "Wrong Overlay 2 resolution"),
            ("resolution:overlay3", "Wrong Overlay 3 resolution"),
            ("resolution:qrcode", "Wrong QR Code resolution"),
            ("resolution:snap1", "Wrong Snap 1 resolution"),
            ("resolution:snap2", "Wrong Snap 2 resolution"),
            ("resolution:snap3", "Wrong Snap 3 resolution"),
            ("json:empty:name", "JSON: Empty Name"),
            ("json:empty:nb_players", "JSON: Empty nb_players"),
            ("json:empty:editor", "JSON: Empty Editor"),
            ("json:empty:year", "JSON: Empty/0 Year"),
            ("json:empty:description", f"JSON: Empty Description ({getattr(self._config, 'language', 'en')})"),
            ("json:missing:kbdhackfile", "JSON: Missing kbdhackfile"),
            ("json:missing:gfx-palette", "JSON: Missing gfx-palette"),
        ]

        for code, label in ordered:
            chk = QCheckBox(label)
            chk.setChecked(True)
            chk.setEnabled(False)
            chk.stateChanged.connect(lambda _=None: self._rebuild_game_list())
            self._filters_l.addWidget(chk)
            self._filter_checks[code] = chk

    def _analyze_folder(self) -> None:
        if not self._folder:
            return

        busy = QProgressDialog("Analyzing...", None, 0, 0, self)
        busy.setWindowTitle("Analyze")
        busy.setWindowModality(Qt.WindowModality.ApplicationModal)
        busy.setCancelButton(None)
        busy.setMinimumDuration(0)
        busy.show()
        QApplication.processEvents()

        try:
            self._analysis_enabled = True
            self._analysis_include_json_checks = bool(self._chk_include_json_checks.isChecked())
            self._analysis_by_game = {
                b: self._compute_warning_codes(g, include_json_checks=self._analysis_include_json_checks)
                for b, g in self._games.items()
            }
        except Exception as e:
            # Qt can swallow exceptions in slots; show a visible error.
            QMessageBox.warning(self, "Analyze failed", str(e))
            self._analysis_enabled = False
            self._analysis_by_game = {}
            return
        finally:
            try:
                busy.close()
            except Exception:
                pass

        total = len(self._analysis_by_game)
        with_w = sum(1 for s in self._analysis_by_game.values() if s)
        self._lbl_analyze.setText(f"Analyzed: {total} games; {with_w} with warnings")
        self._lbl_analyze.setVisible(True)

        self._chk_only_warnings.setEnabled(True)
        self._update_filter_visibility()
        self._update_filter_scroll_height()

        self._rebuild_game_list(preserve=self._current)

    def _update_filter_visibility(self) -> None:
        if not self._analysis_enabled:
            if self._filters_scroll is not None:
                self._filters_scroll.setVisible(False)
            if hasattr(self, "_lbl_found_warnings"):
                self._lbl_found_warnings.setVisible(False)
            if hasattr(self, "_btn_select_all_warnings"):
                self._btn_select_all_warnings.setVisible(False)
            if hasattr(self, "_btn_clear_all_warnings"):
                self._btn_clear_all_warnings.setVisible(False)
            for chk in self._filter_checks.values():
                chk.setVisible(False)
                chk.setEnabled(False)
            return

        found: set[str] = set()
        for codes in self._analysis_by_game.values():
            found |= set(codes)

        any_visible = False
        for code, chk in self._filter_checks.items():
            vis = code in found
            chk.setVisible(vis)
            chk.setEnabled(vis)
            any_visible = any_visible or vis

        if self._filters_scroll is not None:
            self._filters_scroll.setVisible(any_visible)
        if hasattr(self, "_lbl_found_warnings"):
            self._lbl_found_warnings.setVisible(any_visible)
        if hasattr(self, "_btn_select_all_warnings"):
            self._btn_select_all_warnings.setVisible(any_visible)
        if hasattr(self, "_btn_clear_all_warnings"):
            self._btn_clear_all_warnings.setVisible(any_visible)

    def _set_all_warning_filters(self, checked: bool) -> None:
        any_changed = False
        for chk in self._filter_checks.values():
            if not chk.isVisible() or not chk.isEnabled():
                continue
            if chk.isChecked() == checked:
                continue
            with QSignalBlocker(chk):
                chk.setChecked(checked)
            any_changed = True
        if any_changed:
            self._rebuild_game_list(preserve=self._current)

    def _select_all_warning_filters(self) -> None:
        self._set_all_warning_filters(True)

    def _clear_all_warning_filters(self) -> None:
        self._set_all_warning_filters(False)

    def _update_filter_scroll_height(self) -> None:
        if self._filters_scroll is None or self._list_panel is None:
            return
        if not self._filters_scroll.isVisible():
            return
        # Cap filter area to ~1/3 of the list panel height.
        h = max(80, int(self._list_panel.height() / 3))
        self._filters_scroll.setMaximumHeight(h)

    def _rebuild_game_list(self, preserve: str | None = None, *, silent_preserve: bool = False) -> None:
        prev = preserve
        expanded_before = self._expanded_folder_paths() | set(self._force_expand_folder_paths)
        self._tree.blockSignals(True)
        self._tree.clear()

        total_count = len(self._games)
        showing_count = 0

        enabled_codes = {code for code, chk in self._filter_checks.items() if chk.isChecked()}
        only_warn = bool(self._analysis_enabled and self._chk_only_warnings.isChecked())

        root_folder = self._folder
        if not root_folder:
            self._tree.blockSignals(False)
            self._has_any_folders = False
            self._update_game_count_label(showing=0, total=0)
            return

        self._tree.set_root_folder(root_folder)

        folder_icon: QIcon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        game_icon: QIcon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

        # Build folder nodes (including empty). Top-level nodes are root contents.
        folder_items: dict[Path, QTreeWidgetItem] = {}
        for d in sorted(
            [p for p in root_folder.rglob("*") if p.is_dir() and not _is_hidden_dir(p)],
            key=lambda p: p.as_posix().lower(),
        ):
            try:
                rel = d.relative_to(root_folder)
            except Exception:
                continue
            parent_rel = rel.parent

            parent_item = folder_items.get(parent_rel) if parent_rel != Path(".") else None

            item = QTreeWidgetItem([d.name])
            item.setIcon(0, folder_icon)
            item.setToolTip(0, str(d))
            item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "path": str(d)})
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDropEnabled)
            if parent_item is None:
                self._tree.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            folder_items[rel] = item

        self._has_any_folders = bool(folder_items)

        # Add games under their folder nodes
        for game_id, game in self._games.items():
            codes = self._analysis_by_game.get(game_id, set()) if self._analysis_enabled else set()
            if self._analysis_enabled and enabled_codes:
                codes = {c for c in codes if c in enabled_codes}
            if only_warn and not codes:
                continue

            rel_folder = Path(".")
            try:
                rel_folder = game.folder.relative_to(root_folder)
            except Exception:
                rel_folder = Path(".")

            parent_item = folder_items.get(rel_folder) if rel_folder != Path(".") else None
            gitem = QTreeWidgetItem([game.basename])
            gitem.setIcon(0, game_icon)
            gitem.setToolTip(0, str(game.folder))
            gitem.setData(0, Qt.ItemDataRole.UserRole, {"type": "game", "id": game_id, "folder": str(game.folder)})
            gitem.setFlags(gitem.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            # Ensure games are not drop targets.
            gitem.setFlags(gitem.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            if self._analysis_enabled and codes:
                gitem.setForeground(0, Qt.GlobalColor.red)

            if parent_item is None:
                self._tree.addTopLevelItem(gitem)
            else:
                parent_item.addChild(gitem)
            showing_count += 1

        self._tree.blockSignals(False)
        self._update_game_count_label(showing=showing_count, total=total_count)

        self._restore_expanded_folder_paths(expanded_before)

        if prev:
            self._set_current_in_tree(prev, silent=bool(silent_preserve))
            return

        # Default selection: first visible game in the tree.
        def first_game(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            info = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(info, dict) and info.get("type") == "game":
                return item
            for i in range(item.childCount()):
                found = first_game(item.child(i))
                if found is not None:
                    return found
            return None

        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            found = first_game(top)
            if found is not None:
                self._tree.setCurrentItem(found)
                self._tree.scrollToItem(found)
                return

        self._select_none()

    def _update_game_count_label(self, *, showing: int, total: int) -> None:
        if not hasattr(self, "_lbl_game_count"):
            return
        # Always show total games across all folders/subfolders.
        self._lbl_game_count.setText(f"Games: {max(0, total)}")

    def _compute_warning_codes(
        self,
        game: GameAssets,
        *,
        include_rom_cfg: bool = True,
        include_json_checks: bool = False,
    ) -> set[str]:
        codes: set[str] = set()

        if len(game.basename) > self._config.desired_max_base_file_length:
            codes.add("longname")

        if include_rom_cfg:
            if game.rom is None:
                codes.add("missing:rom")

            if game.rom is not None and game.rom.suffix.lower() in {".int", ".bin"} and game.config is None:
                codes.add("missing:cfg")

        if game.metadata is None:
            codes.add("missing:metadata")

        def _is_blank(value) -> bool:
            if value is None:
                return True
            if isinstance(value, str):
                return value.strip() == ""
            return False

        def _strip_wrapping_quotes(s: str) -> str:
            s = (s or "").strip()
            if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
                return s[1:-1]
            return s

        def _split_flags(value: str) -> list[str]:
            s = (value or "").strip()
            if not s:
                return []
            try:
                return shlex.split(s, posix=True)
            except Exception:
                return [t for t in s.split(" ") if t.strip()]

        def _find_equals_flag_value(tokens: list[str], flag_prefix: str) -> str | None:
            for t in tokens:
                if t.startswith(flag_prefix):
                    return t[len(flag_prefix) :]
            return None

        def _normalize_media_prefix(prefix: str | None) -> str:
            s = (prefix or "").strip() or "/media/usb0"
            s = s.rstrip("/")
            return s or "/media/usb0"

        def _device_to_local_path(*, root: Path, device_path: str, media_prefix: str) -> Path | None:
            s = _strip_wrapping_quotes(device_path)
            prefix = _normalize_media_prefix(media_prefix)
            if s == prefix:
                return root
            if s.startswith(prefix + "/"):
                rel = s[len(prefix) + 1 :]
                if rel:
                    return root / Path(PurePosixPath(rel))
                return root
            return None

        def _exists_for_flag_path(flag_value: str) -> bool:
            root = self._folder or game.folder
            local = _device_to_local_path(
                root=root,
                device_path=flag_value,
                media_prefix=getattr(self._config, "jzintv_media_prefix", "/media/usb0"),
            )
            if local is not None:
                try:
                    return local.exists()
                except Exception:
                    return False
            try:
                return Path(_strip_wrapping_quotes(flag_value)).exists()
            except Exception:
                return False

        def add_image(kind: str, p: Path | None, expected) -> None:
            if p is None:
                codes.add(f"missing:{kind}")
                return
            size = get_image_size(p)
            if size is None:
                codes.add(f"resolution:{kind}")
                return
            if size != (expected.width, expected.height):
                codes.add(f"resolution:{kind}")

        def add_resolution_only(kind: str, p: Path | None, expected) -> None:
            if p is None:
                return
            size = get_image_size(p)
            if size is None:
                codes.add(f"resolution:{kind}")
                return
            if size != (expected.width, expected.height):
                codes.add(f"resolution:{kind}")

        add_image("box", game.box, self._config.box_resolution)
        add_image("box_small", game.box_small, self._config.box_small_resolution)
        add_image("overlay_big", game.overlay_big, self._config.overlay_big_resolution)
        add_image("overlay", game.overlay, self._config.overlay_resolution)

        # Multi-overlay support: only warn on resolution if the files exist.
        add_resolution_only("overlay2", game.overlay2, self._config.overlay_resolution)
        add_resolution_only("overlay3", game.overlay3, self._config.overlay_resolution)

        add_image("qrcode", game.qrcode, self._config.qrcode_resolution)

        desired = self._config.desired_number_of_snaps
        snaps = [(1, game.snap1), (2, game.snap2), (3, game.snap3)]
        for idx, p in snaps:
            if idx <= desired:
                add_image(f"snap{idx}", p, self._config.snap_resolution)

        if include_json_checks and game.metadata is not None and game.metadata.exists():
            try:
                data = json.loads(game.metadata.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {}

            if _is_blank(data.get("name")):
                codes.add("json:empty:name")

            nb = data.get("nb_players")
            nb_str = "" if nb is None else str(nb)
            if _is_blank(nb) or nb_str.strip() == "0":
                codes.add("json:empty:nb_players")
            else:
                try:
                    if int(nb_str.strip()) == 0:
                        codes.add("json:empty:nb_players")
                except Exception:
                    pass

            if _is_blank(data.get("editor")):
                codes.add("json:empty:editor")

            yr = data.get("year")
            if yr is None:
                codes.add("json:empty:year")
            else:
                try:
                    if int(str(yr).strip() or "0") == 0:
                        codes.add("json:empty:year")
                except Exception:
                    codes.add("json:empty:year")

            desc = data.get("description")
            lang = (getattr(self._config, "language", "en") or "en").strip().lower() or "en"
            if not isinstance(desc, dict):
                codes.add("json:empty:description")
            else:
                if _is_blank(desc.get(lang)):
                    codes.add("json:empty:description")

            extra = data.get("jzintv_extra")
            extra_s = ("" if extra is None else str(extra)).strip()
            if extra_s:
                tokens = _split_flags(extra_s)

                kbd = _find_equals_flag_value(tokens, "--kbdhackfile=")
                if kbd is not None:
                    if _is_blank(kbd) or not _exists_for_flag_path(kbd):
                        codes.add("json:missing:kbdhackfile")

                pal = _find_equals_flag_value(tokens, "--gfx-palette=")
                if pal is not None:
                    if _is_blank(pal) or not _exists_for_flag_path(pal):
                        codes.add("json:missing:gfx-palette")

        return codes

    # ---------- ui build ----------

    def _build_details(self) -> None:
        def framed(w: QWidget) -> QFrame:
            f = QFrame()
            f.setFrameShape(QFrame.Shape.Box)
            f.setFrameShadow(QFrame.Shadow.Plain)
            f.setLineWidth(1)
            l = QVBoxLayout(f)
            l.setContentsMargins(0, 0, 0, 0)
            l.addWidget(w)
            return f

        layout = QHBoxLayout(self._detail_root)
        layout.setContentsMargins(0, 0, 0, 0)

        # Left: ROM/CFG thin rows at top + images underneath
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(4)

        base_panel = QWidget()
        base_l = QVBoxLayout(base_panel)
        base_l.setContentsMargins(4, 2, 4, 2)
        base_l.setSpacing(2)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._base_name = QLabel("")
        self._base_name.setStyleSheet("font-weight: 600;")
        header.addWidget(self._base_name)
        header.addStretch(1)
        self._btn_move = QPushButton("Move")
        self._btn_move.clicked.connect(self._move_clicked)
        self._btn_move.setMaximumHeight(24)
        self._btn_move.setVisible(False)
        self._btn_move.setToolTip("Move this game to a different folder")
        header.addWidget(self._btn_move)
        self._btn_rename = QPushButton("Change File Name")
        self._btn_rename.clicked.connect(self._rename)
        self._btn_rename.setMaximumHeight(24)
        self._btn_rename.setToolTip("Rename this game's files (basename)")
        header.addWidget(self._btn_rename)
        base_l.addLayout(header)

        self._base_warn = QLabel("")
        self._base_warn.setWordWrap(True)
        self._base_warn.setVisible(False)
        self._base_warn.setStyleSheet("color: red;")
        base_l.addWidget(self._base_warn)
        left_l.addWidget(framed(base_panel))

        self._rom_row = ThinFileRow(title="ROM", allowed_exts={".int", ".bin", ".rom"}, on_add_file=self._add_rom)
        left_l.addWidget(framed(self._rom_row))

        self._cfg_row = ThinFileRow(title="Config", allowed_exts={".cfg"}, on_add_file=self._add_cfg)
        self._cfg_row.set_extra_action(
            "Lookup",
            self._lookup_cfg,
            "Find and copy a bundled .cfg by selecting a game from the lookup list",
        )
        self._cfg_row.set_open_action(
            self._open_cfg_clicked,
            "Open this game's .cfg in your default editor",
            icon=self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
        )
        left_l.addWidget(framed(self._cfg_row))

        # Images area
        scroll = QScrollArea()
        # Allow horizontal scrolling when the grid is wider than the view.
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        images_inner = QWidget()
        images_grid = QGridLayout(images_inner)
        images_grid.setContentsMargins(0, 0, 0, 0)
        images_grid.setHorizontalSpacing(8)
        images_grid.setVerticalSpacing(4)

        self._img_box = ImageCard(
            config=self._config,
            spec=ImageSpec(title="Box", expected=self._config.box_resolution, filename="{basename}.png"),
            on_changed=self._images_changed,
            keep_ratio_enabled=True,
            keep_ratio_tooltip="When checked, added images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas.",
        )
        images_grid.addWidget(self._img_box, 0, 0)

        self._img_box_small = ImageCard(
            config=self._config,
            spec=ImageSpec(title="Box Small", expected=self._config.box_small_resolution, filename="{basename}_small.png"),
            on_changed=self._images_changed,
            keep_ratio_enabled=True,
            keep_ratio_tooltip="When checked, added images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas.",
        )
        images_grid.addWidget(self._img_box_small, 0, 1)

        self._img_overlay_big = ImageCard(
            config=self._config,
            spec=ImageSpec(title="Overlay Big", expected=self._config.overlay_big_resolution, filename="{basename}_big_overlay.png"),
            on_changed=self._overlay_big_changed,
            keep_ratio_enabled=True,
            keep_ratio_tooltip="When checked, added images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas.",
        )
        self._img_overlay_big.set_extra_action(
            "Clean",
            self._clean_overlay_big,
            "Open Overlay Image Cleaner for this image.",
        )
        self._img_overlay_big.set_extra_action_requires_existing_image(True)
        images_grid.addWidget(self._img_overlay_big, 1, 0)

        self._img_overlay1 = OverlayPrimaryCard(
            index=1,
            on_reorder=self._reorder_overlays,
            config=self._config,
            spec=ImageSpec(title="Overlay 1", expected=self._config.overlay_resolution, filename="{basename}_overlay.png"),
            on_changed=self._images_changed,
            keep_ratio_enabled=True,
            keep_ratio_tooltip="When checked, added images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas.",
        )
        self._img_overlay1.set_extra_action(
            "Build",
            lambda: self._build_overlay(1),
            "Build the Overlay image from a template and a bottom image (browse/paste/big overlay).",
        )
        self._img_overlay1.set_blank_action(
            lambda: self._set_overlay_blank(1),
            "Set empty image for this overlay spot",
        )
        images_grid.addWidget(self._img_overlay1, 1, 1)

        self._img_overlay2 = OverlayCard(
            index=2,
            on_reorder=self._reorder_overlays,
            config=self._config,
            spec=ImageSpec(title="Overlay 2", expected=self._config.overlay_resolution, filename="{basename}_overlay2.png"),
            on_changed=self._images_changed,
            keep_ratio_enabled=True,
            keep_ratio_tooltip="When checked, added images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas.",
        )
        self._img_overlay2.set_extra_action(
            "Build",
            lambda: self._build_overlay(2),
            "Build the Overlay image from a template and a bottom image (browse/paste/big overlay).",
        )
        self._img_overlay2.set_blank_action(
            lambda: self._set_overlay_blank(2),
            "Set empty image for this overlay spot",
        )
        images_grid.addWidget(self._img_overlay2, 1, 2)

        self._img_overlay3 = OverlayCard(
            index=3,
            on_reorder=self._reorder_overlays,
            config=self._config,
            spec=ImageSpec(title="Overlay 3", expected=self._config.overlay_resolution, filename="{basename}_overlay3.png"),
            on_changed=self._images_changed,
            keep_ratio_enabled=True,
            keep_ratio_tooltip="When checked, added images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas.",
        )
        self._img_overlay3.set_extra_action(
            "Build",
            lambda: self._build_overlay(3),
            "Build the Overlay image from a template and a bottom image (browse/paste/big overlay).",
        )
        self._img_overlay3.set_blank_action(
            lambda: self._set_overlay_blank(3),
            "Set empty image for this overlay spot",
        )
        images_grid.addWidget(self._img_overlay3, 1, 3)

        self._img_qr = ImageCard(
            config=self._config,
            spec=ImageSpec(title="QR Code", expected=self._config.qrcode_resolution, filename="{basename}_qrcode.png"),
            on_changed=self._images_changed,
            keep_ratio_enabled=True,
            keep_ratio_tooltip="When checked, added images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas.",
        )
        self._img_qr.set_extra_action(
            "URL",
            self._create_qr_from_url,
            "Generate the QR Code image from a URL.",
        )
        images_grid.addWidget(self._img_qr, 0, 2)

        self._snap1 = SnapshotCard(
            index=1,
            config=self._config,
            spec=ImageSpec(title="Snap 1", expected=self._config.snap_resolution, filename="{basename}_snap1.png"),
            on_changed=self._images_changed,
            keep_ratio_enabled=True,
            keep_ratio_tooltip="When checked, added images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas.",
        )
        self._snap2 = SnapshotCard(
            index=2,
            config=self._config,
            spec=ImageSpec(title="Snap 2", expected=self._config.snap_resolution, filename="{basename}_snap2.png"),
            on_changed=self._images_changed,
            keep_ratio_enabled=True,
            keep_ratio_tooltip="When checked, added images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas.",
        )
        self._snap3 = SnapshotCard(
            index=3,
            config=self._config,
            spec=ImageSpec(title="Snap 3", expected=self._config.snap_resolution, filename="{basename}_snap3.png"),
            on_changed=self._images_changed,
            keep_ratio_enabled=True,
            keep_ratio_tooltip="When checked, added images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas.",
        )
        self._snaps = SnapshotsRow(cards=[self._snap1, self._snap2, self._snap3], on_reorder=self._reorder_snaps)
        images_grid.addWidget(self._snaps, 2, 0, 1, 4)

        images_grid.setColumnStretch(0, 1)
        images_grid.setColumnStretch(1, 1)
        images_grid.setColumnStretch(2, 1)
        images_grid.setColumnStretch(3, 1)

        # Ensure the grid keeps its natural width so the scroll area can scroll.
        images_inner.setMinimumWidth(images_inner.sizeHint().width())
        scroll.setWidget(images_inner)
        left_l.addWidget(scroll, 1)

        # Right: Metadata panel
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.addWidget(QLabel("Metadata"))
        self._meta_editor = MetadataEditor(
            on_saved=self.refresh,
            on_advanced=self._open_advanced_json,
            on_bulk_update=self._open_bulk_json_update,
            metadata_editors=self._config.metadata_editors,
            preferred_language=getattr(self._config, "language", "en"),
        )
        right_l.addWidget(framed(self._meta_editor), 1)

        details_split = QSplitter(Qt.Orientation.Horizontal)
        details_split.addWidget(left)
        details_split.addWidget(right)
        details_split.setStretchFactor(0, 2)
        details_split.setStretchFactor(1, 1)
        layout.addWidget(details_split, 1)

    # ---------- selection ----------

    def _set_current_in_list(self, basename: str | None) -> None:
        self._set_current_in_tree(basename, silent=True)

    def _set_current_in_tree(self, game_id: str | None, *, silent: bool) -> None:
        blocker = QSignalBlocker(self._tree) if silent else None
        try:
            if not game_id:
                self._tree.setCurrentItem(None)
                return

            target = str(game_id)
            want_type: str
            want_val: str
            if target.startswith("g:"):
                want_type = "game"
                want_val = target[2:]
            elif target.startswith("f:"):
                want_type = "folder"
                want_val = target[2:]
            else:
                want_type = "game"
                want_val = target

            def walk(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
                info = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(info, dict) and info.get("type") == want_type:
                    if want_type == "game" and str(info.get("id") or "") == want_val:
                        return item
                    if want_type == "folder" and str(info.get("path") or "") == want_val:
                        return item
                for i in range(item.childCount()):
                    found = walk(item.child(i))
                    if found is not None:
                        return found
                return None

            for i in range(self._tree.topLevelItemCount()):
                top = self._tree.topLevelItem(i)
                found = walk(top)
                if found is not None:
                    # Ensure the item is visible.
                    p = found.parent()
                    while p is not None:
                        self._tree.expandItem(p)
                        p = p.parent()
                    self._tree.setCurrentItem(found)
                    self._tree.scrollToItem(found)
                    return
        finally:
            # Keep blocker alive until after all operations.
            _ = blocker

    def _select_game(self, basename: str) -> None:
        self._multi_selected_game_ids = []
        game_id = (basename or "").strip()
        prev = self._current
        next_key = f"g:{game_id}" if game_id else None

        if prev != next_key and prev is not None and self._meta_editor.has_unsaved_changes():
            dlg = QMessageBox(self)
            dlg.setIcon(QMessageBox.Icon.Warning)
            dlg.setWindowTitle("Unsaved Changes")
            dlg.setText("You have unsaved metadata changes.")
            dlg.setInformativeText("Save changes before switching games?")
            dlg.setStandardButtons(
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
            )
            dlg.setDefaultButton(QMessageBox.StandardButton.Save)
            resp = dlg.exec()

            if resp == QMessageBox.StandardButton.Save:
                if not self._meta_editor.save_changes():
                    # Save failed; keep current selection and preserve edits.
                    self._set_current_in_list(prev)
                    return
            elif resp == QMessageBox.StandardButton.Discard:
                self._meta_editor.discard_changes()
            else:
                # Cancel: keep current selection and preserve edits.
                self._set_current_in_list(prev)
                return

        self._current = next_key

        game = self._games.get(game_id) if game_id else None

        # Game selection: ROM/CFG apply.
        self._rom_row.set_title("ROM")
        self._cfg_row.set_title("Config")
        self._btn_rename.setText("Change File Name")
        self._btn_rename.setToolTip("Rename this game's files (basename)")
        if hasattr(self, "_btn_move"):
            self._btn_move.setVisible(bool(self._has_any_folders))
            self._btn_move.setToolTip("Move this game to a different folder")

        if not game:
            self._base_name.setText("")
            self._base_warn.setText("")
            self._rom_row.set_context(folder=None, basename=None, existing=None, warning=None)
            self._cfg_row.set_context(folder=None, basename=None, existing=None, warning=None)
            self._rom_row.setEnabled(False)
            self._cfg_row.setEnabled(False)
            if hasattr(self, "_btn_move"):
                self._btn_move.setVisible(False)
                self._btn_move.setEnabled(False)
            self._btn_rename.setEnabled(False)
            self._meta_editor.set_context(folder=None, basename=None, path=None, allow_advanced=False)
            self._set_images_context(None)
            self._lbl_warnings.setText("Warnings: 0")
            return

        self._base_name.setText(f"Basename (game): {game.basename}")
        if len(game.basename) > self._config.desired_max_base_file_length:
            self._base_warn.setText(
                f"Warning: basename length {len(game.basename)} exceeds DesiredMaxBaseFileLength={self._config.desired_max_base_file_length}"
            )
            self._base_warn.setVisible(True)
        else:
            self._base_warn.setText("")
            self._base_warn.setVisible(False)

        rom_warn = "Missing ROM" if game.rom is None else None
        self._rom_row.set_context(folder=game.folder, basename=game.basename, existing=game.rom, warning=rom_warn)
        self._rom_row.setEnabled(True)

        cfg_warn = None
        if game.rom is not None:
            if game.rom.suffix.lower() in {".int", ".bin"} and game.config is None:
                cfg_warn = "Missing config for .int/.bin ROM (.cfg missing)"
        self._cfg_row.set_context(folder=game.folder, basename=game.basename, existing=game.config, warning=cfg_warn)
        self._cfg_row.setEnabled(True)

        if hasattr(self, "_btn_move"):
            self._btn_move.setVisible(bool(self._has_any_folders))
            self._btn_move.setEnabled(bool(self._has_any_folders))

        self._btn_rename.setEnabled(True)

        self._meta_editor.set_context(folder=game.folder, basename=game.basename, path=game.metadata, allow_advanced=True)

        self._set_images_context(game)
        self._lbl_warnings.setText(f"Warnings: {self._count_selected_warnings(game)}")

    def _select_folder(self, folder_path: str) -> None:
        self._multi_selected_game_ids = []
        folder_dir = Path(folder_path)
        if not folder_dir.exists() or not folder_dir.is_dir():
            self._select_none()
            return

        prev = self._current
        next_key = f"f:{str(folder_dir)}"

        if prev != next_key and prev is not None and self._meta_editor.has_unsaved_changes():
            dlg = QMessageBox(self)
            dlg.setIcon(QMessageBox.Icon.Warning)
            dlg.setWindowTitle("Unsaved Changes")
            dlg.setText("You have unsaved metadata changes.")
            dlg.setInformativeText("Save changes before switching selection?")
            dlg.setStandardButtons(
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
            )
            dlg.setDefaultButton(QMessageBox.StandardButton.Save)
            resp = dlg.exec()

            if resp == QMessageBox.StandardButton.Save:
                if not self._meta_editor.save_changes():
                    self._set_current_in_list(prev)
                    return
            elif resp == QMessageBox.StandardButton.Discard:
                self._meta_editor.discard_changes()
            else:
                self._set_current_in_list(prev)
                return

        self._current = next_key

        assets = self._folder_assets.get(str(folder_dir))
        if assets is None:
            assets = GameAssets(basename=folder_dir.name, folder=folder_dir.parent)

        # Folder selection: ROM/CFG do not apply.
        self._rom_row.set_title("ROM (Not Applicable)")
        self._cfg_row.set_title("Config (Not Applicable)")
        self._btn_rename.setText("Change Folder Name")
        self._btn_rename.setToolTip("Rename this folder and its folder-support files")
        if hasattr(self, "_btn_move"):
            self._btn_move.setVisible(True)
            self._btn_move.setEnabled(True)
            self._btn_move.setToolTip("Move this folder and its folder-support files")

        self._base_name.setText(f"Basename (folder): {assets.basename}")
        if len(assets.basename) > self._config.desired_max_base_file_length:
            self._base_warn.setText(
                f"Warning: basename length {len(assets.basename)} exceeds DesiredMaxBaseFileLength={self._config.desired_max_base_file_length}"
            )
            self._base_warn.setVisible(True)
        else:
            self._base_warn.setText("")
            self._base_warn.setVisible(False)

        self._rom_row.set_context(folder=assets.folder, basename=assets.basename, existing=None, warning=None, missing_text="")
        self._cfg_row.set_context(folder=assets.folder, basename=assets.basename, existing=None, warning=None, missing_text="")
        self._rom_row.setEnabled(False)
        self._cfg_row.setEnabled(False)
        self._btn_rename.setEnabled(True)

        self._meta_editor.set_context(folder=assets.folder, basename=assets.basename, path=assets.metadata, allow_advanced=False)
        self._set_images_context(assets)
        self._lbl_warnings.setText(f"Warnings: {len(self._compute_warning_codes(assets, include_rom_cfg=False))}")

    def _select_multi(self, items: list[QTreeWidgetItem]) -> None:
        # Multiple selection: do not show per-game details to avoid ambiguity.
        self._current = None

        self._multi_selected_game_ids = []

        game_count = 0
        folder_count = 0
        for item in items or []:
            info = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
            if isinstance(info, dict) and info.get("type") == "game":
                game_count += 1
                gid = str(info.get("id") or "").strip()
                if gid:
                    self._multi_selected_game_ids.append(gid)
            elif isinstance(info, dict) and info.get("type") == "folder":
                folder_count += 1

        if game_count and folder_count:
            self._base_name.setText(f"Multiple selected: {game_count} games, {folder_count} folders")
        elif game_count:
            self._base_name.setText(f"Multiple selected: {game_count} games")
        elif folder_count:
            self._base_name.setText(f"Multiple selected: {folder_count} folders")
        else:
            self._base_name.setText("Multiple selected")
        self._base_warn.setText("")

        self._rom_row.set_title("ROM")
        self._cfg_row.set_title("Config")
        self._btn_rename.setText("Change File Name")
        self._btn_rename.setToolTip("Rename this game's files (basename)")

        if hasattr(self, "_btn_move"):
            # Multi-select Move only supports games (no folders in selection).
            allow_multi_game_move = bool(self._has_any_folders and game_count > 0 and folder_count == 0)
            self._btn_move.setVisible(bool(self._has_any_folders))
            self._btn_move.setEnabled(allow_multi_game_move)
            if allow_multi_game_move:
                self._btn_move.setToolTip("Move all selected games to a different folder (supports Make Copy)")
            else:
                self._btn_move.setToolTip("Multi-select Move supports games only (no folders in selection)")

        self._rom_row.set_context(folder=None, basename=None, existing=None, warning=None)
        self._cfg_row.set_context(folder=None, basename=None, existing=None, warning=None)
        self._rom_row.setEnabled(False)
        self._cfg_row.setEnabled(False)
        self._btn_rename.setEnabled(False)
        if len(self._multi_selected_game_ids) >= 2:
            self._meta_editor.set_bulk_context(self._multi_selected_game_ids)
        else:
            self._meta_editor.set_context(folder=None, basename=None, path=None, allow_advanced=False)
        self._set_images_context(None)
        self._lbl_warnings.setText("Warnings: 0")

    def _select_none(self) -> None:
        self._current = None
        self._multi_selected_game_ids = []
        self._base_name.setText("")
        self._base_warn.setText("")

        self._rom_row.set_title("ROM")
        self._cfg_row.set_title("Config")
        self._btn_rename.setText("Change File Name")
        self._btn_rename.setToolTip("Rename this game's files (basename)")
        if hasattr(self, "_btn_move"):
            self._btn_move.setVisible(False)
            self._btn_move.setEnabled(False)

        self._rom_row.set_context(folder=None, basename=None, existing=None, warning=None)
        self._cfg_row.set_context(folder=None, basename=None, existing=None, warning=None)
        self._rom_row.setEnabled(False)
        self._cfg_row.setEnabled(False)
        self._btn_rename.setEnabled(False)
        self._meta_editor.set_context(folder=None, basename=None, path=None, allow_advanced=False)
        self._set_images_context(None)
        self._lbl_warnings.setText("Warnings: 0")

    def _count_selected_warnings(self, game: GameAssets) -> int:
        # Keep this in sync with analysis filters by using the same warning code generator.
        # This also ensures resolution mismatches count as warnings.
        return len(self._compute_warning_codes(game))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        if not self._folder:
            event.ignore()
            return
        urls = event.mimeData().urls()
        files: list[Path] = []
        for u in urls:
            p = Path(u.toLocalFile())
            if not p.exists() or not p.is_file():
                continue
            if p.suffix.lower() not in ACCEPTED_ADD_EXTS:
                continue
            files.append(p)

        if not files:
            event.ignore()
            return

        # Fallback: if drop lands on the main window (not the tree), add to the currently
        # selected folder in the tree (or root if nothing selected).
        self._add_files(files, dest_folder=self._selected_tree_folder() or self._folder)
        event.acceptProposedAction()

    def _add_files_to_folder(self, files: list[Path], dest_folder: Path) -> None:
        self._add_files(files, dest_folder=dest_folder)

    def _current_selection(self) -> tuple[str, str] | None:
        if not self._current:
            return None
        cur = str(self._current)
        if cur.startswith("g:"):
            return ("game", cur[2:])
        if cur.startswith("f:"):
            return ("folder", cur[2:])
        return ("game", cur)

    def _current_game(self) -> GameAssets | None:
        sel = self._current_selection()
        if sel is None:
            return None
        kind, val = sel
        if kind != "game":
            return None
        return self._games.get(val)

    def _current_assets(self) -> GameAssets | None:
        sel = self._current_selection()
        if sel is None:
            return None
        kind, val = sel
        if kind == "game":
            return self._games.get(val)

        folder_dir = Path(val)
        if not folder_dir.exists() or not folder_dir.is_dir():
            return None
        assets = self._folder_assets.get(str(folder_dir))
        if assets is not None:
            return assets
        return GameAssets(basename=folder_dir.name, folder=folder_dir.parent)

    def _set_images_context(self, game: GameAssets | None) -> None:
        folder = game.folder if game else None
        basename = game.basename if game else None

        def resolution_status(p: Path | None, expected) -> tuple[list[str], bool]:
            if p is None:
                return (["Missing"], False)
            size = get_image_size(p)
            if size is None:
                return (["Unreadable image"], False)
            if size != (expected.width, expected.height):
                return ([f"Resolution mismatch: expected {expected.width}x{expected.height}, got {size[0]}x{size[1]}"], True)
            return ([], False)

        if not game:
            for card in [
                self._img_box,
                self._img_box_small,
                self._img_overlay_big,
                self._img_overlay1,
                self._img_overlay2,
                self._img_overlay3,
                self._img_qr,
                self._snap1,
                self._snap2,
                self._snap3,
            ]:
                card.set_context(folder=None, basename=None, existing_path=None, warnings=[], needs_resize=False)
            return

        box_w, box_resize = resolution_status(game.box, self._config.box_resolution)
        self._img_box.set_context(folder=folder, basename=basename, existing_path=game.box, warnings=box_w, needs_resize=box_resize)

        if self._config.use_box_image_for_box_small:
            # Derived mode: show current file if present but disable editing.
            bs_warn: list[str]
            bs_resize = False
            if game.box_small:
                bs_warn, bs_resize = resolution_status(game.box_small, self._config.box_small_resolution)
            else:
                bs_warn = ["Missing (derived from Box)"] if game.box is not None else ["Missing Box (required for derived Box Small)"]

            self._img_box_small.set_context(
                folder=folder,
                basename=basename,
                existing_path=game.box_small,
                warnings=bs_warn,
                needs_resize=bs_resize,
            )
            self._img_box_small.set_controls_enabled(False)
        else:
            self._img_box_small.set_controls_enabled(True)

            bs_warn, bs_resize = resolution_status(game.box_small, self._config.box_small_resolution)
            self._img_box_small.set_context(
                folder=folder,
                basename=basename,
                existing_path=game.box_small,
                warnings=bs_warn,
                needs_resize=bs_resize,
            )

        ob_w, ob_resize = resolution_status(game.overlay_big, self._config.overlay_big_resolution)
        self._img_overlay_big.set_context(folder=folder, basename=basename, existing_path=game.overlay_big, warnings=ob_w, needs_resize=ob_resize)

        ov_w, ov_resize = resolution_status(game.overlay, self._config.overlay_resolution)
        self._img_overlay1.set_context(folder=folder, basename=basename, existing_path=game.overlay, warnings=ov_w, needs_resize=ov_resize)

        ov2_w, ov2_resize = resolution_status(game.overlay2, self._config.overlay_resolution) if game.overlay2 else ([], False)
        self._img_overlay2.set_context(folder=folder, basename=basename, existing_path=game.overlay2, warnings=ov2_w, needs_resize=ov2_resize)

        ov3_w, ov3_resize = resolution_status(game.overlay3, self._config.overlay_resolution) if game.overlay3 else ([], False)
        self._img_overlay3.set_context(folder=folder, basename=basename, existing_path=game.overlay3, warnings=ov3_w, needs_resize=ov3_resize)

        qr_w, qr_resize = resolution_status(game.qrcode, self._config.qrcode_resolution)
        self._img_qr.set_context(folder=folder, basename=basename, existing_path=game.qrcode, warnings=qr_w, needs_resize=qr_resize)

        # Snap warnings are governed by DesiredNumberOfSnaps (no warning for optional missing snaps)
        desired = self._config.desired_number_of_snaps

        def snap_warnings(idx: int, pth: Path | None) -> list[str]:
            if pth is None:
                return ["Missing"] if idx <= desired else []
            return resolution_status(pth, self._config.snap_resolution)[0]

        def snap_needs_resize(pth: Path | None) -> bool:
            if pth is None:
                return False
            return resolution_status(pth, self._config.snap_resolution)[1]

        self._snap1.set_context(folder=folder, basename=basename, existing_path=game.snap1, warnings=snap_warnings(1, game.snap1), needs_resize=snap_needs_resize(game.snap1))
        self._snap2.set_context(folder=folder, basename=basename, existing_path=game.snap2, warnings=snap_warnings(2, game.snap2), needs_resize=snap_needs_resize(game.snap2))
        self._snap3.set_context(folder=folder, basename=basename, existing_path=game.snap3, warnings=snap_warnings(3, game.snap3), needs_resize=snap_needs_resize(game.snap3))

    # ---------- top bar actions ----------

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select games folder", get_start_dir())
        if not folder:
            return
        remember_path(folder)
        self.load_folder(Path(folder))

    def _add_files_dialog(self) -> None:
        if not self._folder:
            QMessageBox.information(self, "Add Files", "Choose a folder first")
            return

        dest_dir = self._selected_tree_folder() or self._folder
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Add files",
            get_start_dir(dest_dir),
            "Accepted (*.bin *.int *.rom *.cfg *.json *.png);;All files (*.*)",
        )
        if not files:
            return
        remember_path(files[0])
        self._add_files([Path(f) for f in files], dest_folder=dest_dir)

    # ---------- file add / copy ----------

    def _add_files(self, files: list[Path], *, dest_folder: Path | None = None) -> None:
        if not self._folder:
            return

        dest_root = dest_folder or self._selected_tree_folder() or self._folder

        for src in files:
            if src.suffix.lower() not in ACCEPTED_ADD_EXTS:
                continue
            dest = dest_root / src.name
            overwrite = False
            if dest.exists():
                resp = QMessageBox.question(self, "Overwrite?", f"{dest.name} already exists. Overwrite?")
                if resp != QMessageBox.StandardButton.Yes:
                    continue
                overwrite = True
            try:
                copy_file(src, dest, overwrite=overwrite)
            except Exception as e:
                QMessageBox.warning(self, "Copy failed", str(e))
                return

        self.refresh(preserve_metadata_edits=True)

    def _add_rom(self, src: Path) -> None:
        game = self._current_game()
        if not game:
            return
        dest = game.folder / f"{game.basename}{src.suffix.lower()}"
        self._copy_with_prompt(src, dest)

    def _add_cfg(self, src: Path) -> None:
        game = self._current_game()
        if not game:
            return
        dest = game.folder / f"{game.basename}.cfg"
        self._copy_with_prompt(src, dest)

    def _lookup_cfg(self) -> None:
        game = self._current_game()
        if not game:
            return

        base = resources_dir()
        rom_cfgs_dir = base / "rom_cfgs"
        mapping_path = base / "cfg_game_mapping.tab"
        if not rom_cfgs_dir.exists():
            QMessageBox.warning(self, "Config Lookup", f"Missing folder: {rom_cfgs_dir}")
            return
        if not mapping_path.exists():
            QMessageBox.warning(self, "Config Lookup", f"Missing mapping file: {mapping_path}")
            return

        dlg = ConfigLookupDialog(parent=self, rom_cfgs_dir=rom_cfgs_dir, mapping_path=mapping_path)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.selected_src is None:
            return

        dest = game.folder / f"{game.basename}.cfg"
        self._copy_with_prompt(dlg.selected_src, dest)

    def _copy_with_prompt(self, src: Path, dest: Path) -> None:
        overwrite = False
        if dest.exists():
            resp = QMessageBox.question(self, "Overwrite?", f"{dest.name} already exists. Overwrite?")
            if resp != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        try:
            copy_file(src, dest, overwrite=overwrite)
        except Exception as e:
            QMessageBox.warning(self, "Copy failed", str(e))
            return
        self.refresh(preserve_metadata_edits=True)

    # ---------- rename ----------

    def _rename(self) -> None:
        sel = self._current_selection()
        if sel is None:
            return

        kind, val = sel
        if kind == "folder":
            folder_dir = Path(val)
            if not folder_dir.exists() or not folder_dir.is_dir():
                return

            dlg = RenameBasenameDialog(parent=self, initial=folder_dir.name, title="Change Folder Name")
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return

            new_name = dlg.value().strip()
            # Allow case-only renames (e.g. Baseball -> BaseBall).
            if not new_name or new_name == folder_dir.name:
                return

            if any(c in new_name for c in "\\/:*?\"<>|"):
                QMessageBox.warning(self, "Invalid name", "Folder name contains invalid filename characters")
                return

            parent = folder_dir.parent

            # Prevent renaming a folder to a name that collides with an existing game basename
            # in the same parent folder.
            parent_key = sprint_path_key(parent)
            name_key = sprint_name_key(new_name)
            for game in self._games.values():
                game_parent_key = sprint_path_key(game.folder)
                game_base_key = sprint_name_key(game.basename)
                if game_parent_key == parent_key and game_base_key == name_key:
                    example = None
                    try:
                        paths = game.all_paths()
                        example = str(paths[0]) if paths else None
                    except Exception:
                        example = None

                    details = f"\n\nExample file: {example}" if example else ""
                    QMessageBox.warning(
                        self,
                        "Rename blocked",
                        "Folder name was not changed.\n\n"
                        f"A game named '{new_name}' already exists in:\n{parent}{details}\n\n"
                        "Choose a different folder name, or rename/move the game first.",
                    )
                    return

            new_dir = parent / new_name
            # If new_dir exists but it's the same directory (case-only rename on a
            # case-insensitive filesystem), allow it.
            if new_dir.exists() and sprint_path_key(new_dir) != sprint_path_key(folder_dir):
                QMessageBox.warning(self, "Rename blocked", f"{new_dir.name} already exists")
                return

            # Rename any sibling support files that belong to this folder-like-game.
            try:
                moves = plan_rename_for_folder_support_files(parent, folder_dir.name, new_name)
                rename_many(moves)
            except RenameCollisionError as e:
                QMessageBox.warning(self, "Rename blocked", str(e))
                return
            except Exception as e:
                QMessageBox.warning(self, "Rename failed", str(e))
                return

            try:
                if sprint_path_key(new_dir) == sprint_path_key(folder_dir) and folder_dir.name != new_name:
                    # Windows/NTFS is case-preserving but typically case-insensitive;
                    # use a two-step rename to force a casing change.
                    tmp = parent / f"{folder_dir.name}.__tmp_rename__"
                    i = 0
                    while tmp.exists():
                        i += 1
                        tmp = parent / f"{folder_dir.name}.__tmp_rename__{i}"
                    folder_dir.rename(tmp)
                    tmp.rename(new_dir)
                else:
                    folder_dir.rename(new_dir)
            except Exception as e:
                QMessageBox.warning(self, "Rename failed", str(e))
                return

            # Preserve pending metadata edits, but retarget the editor to the new basename/path.
            if self._meta_editor.has_unsaved_changes():
                self._meta_editor.retarget_context_preserve_edits(
                    folder=parent,
                    basename=new_name,
                    path=(parent / f"{new_name}.json"),
                    allow_advanced=False,
                )

            self._current = f"f:{str(new_dir)}"
            self.refresh(preserve_metadata_edits=True)
            return

        game = self._current_game()
        if not game:
            return

        dlg = RenameBasenameDialog(parent=self, initial=game.basename, title="Change File Name")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_base = dlg.value().strip()
        # Allow case-only renames (e.g. Baseball -> BaseBall).
        if not new_base or new_base == game.basename:
            return

        if any(c in new_base for c in "\\/:*?\"<>|"):
            QMessageBox.warning(self, "Invalid name", "Basename contains invalid filename characters")
            return

        moves = plan_rename_for_game_files(game.folder, game.basename, new_base)
        try:
            rename_many(moves)
        except RenameCollisionError as e:
            QMessageBox.warning(self, "Rename blocked", str(e))
            return
        except Exception as e:
            QMessageBox.warning(self, "Rename failed", str(e))
            return

        try:
            rel = game.folder.relative_to(self._folder) if self._folder else Path(".")
        except Exception:
            rel = Path(".")
        new_id = new_base if str(rel) in {".", ""} else f"{rel.as_posix()}/{new_base}"
        # Preserve pending metadata edits, but retarget the editor to the new basename/path.
        if self._meta_editor.has_unsaved_changes():
            self._meta_editor.retarget_context_preserve_edits(
                folder=game.folder,
                basename=new_base,
                path=(game.folder / f"{new_base}.json"),
                allow_advanced=True,
            )

        self._current = f"g:{new_id}"
        self.refresh(preserve_metadata_edits=True)

    # ---------- images ----------

    def _images_changed(self) -> None:
        # In derived mode, after Box changes, regenerate Box Small.
        if self._config.use_box_image_for_box_small:
            assets = self._current_assets()
            if assets:
                box_path = assets.folder / f"{assets.basename}.png"
                if box_path.exists():
                    small_dest = assets.folder / f"{assets.basename}_small.png"
                    try:
                        save_png_resized_from_file(box_path, small_dest, expected=self._config.box_small_resolution)
                    except Exception as e:
                        QMessageBox.warning(self, "Box Small", str(e))
        # Preserve unsaved metadata edits when updating image thumbnails.
        self.refresh(preserve_metadata_edits=True)

    def _overlay_big_changed(self) -> None:
        """Handle updates to the Big Overlay image slot.

        If AutoBuildOverlay is enabled and Overlay 1 is missing, automatically build
        Overlay 1 from the Big Overlay image.
        """

        assets = self._current_assets()
        if not assets:
            self.refresh(preserve_metadata_edits=True)
            return

        # Default: behave like normal image updates.
        if not bool(getattr(self._config, "auto_build_overlay", False)):
            self.refresh(preserve_metadata_edits=True)
            return

        overlay1 = assets.folder / f"{assets.basename}_overlay.png"
        if overlay1.exists():
            self.refresh(preserve_metadata_edits=True)
            return

        big_overlay = assets.folder / f"{assets.basename}_big_overlay.png"
        if not big_overlay.exists():
            self.refresh(preserve_metadata_edits=True)
            return

        blank_default = resource_path("Overlay_blank.png")
        override_raw = (self._config.overlay_template_override or "").strip()
        blank = Path(override_raw).expanduser() if override_raw else blank_default
        if not blank.exists():
            msg = f"Missing overlay template. Expected {blank_default}"
            if override_raw:
                msg = f"Missing overlay template override: {blank}"
            QMessageBox.warning(self, "AutoBuildOverlay", msg)
            self.refresh(preserve_metadata_edits=True)
            return

        build_res = self._config.overlay_build_resolution
        pos = self._config.overlay_build_position

        try:
            build_overlay_png_from_file(
                blank,
                big_overlay,
                overlay1,
                overlay_resolution=self._config.overlay_resolution,
                build_resolution=build_res,
                position=pos,
            )
        except ImageProcessError as e:
            QMessageBox.warning(self, "AutoBuildOverlay", str(e))
        except Exception as e:
            QMessageBox.warning(self, "AutoBuildOverlay", str(e))

        self.refresh(preserve_metadata_edits=True)

    def _clean_overlay_big(self) -> None:
        assets = self._current_assets()
        if not assets:
            return

        src = assets.folder / f"{assets.basename}_big_overlay.png"
        if not src.exists():
            QMessageBox.information(self, "Overlay Image Cleaner", "Big Overlay is missing")
            return

        dlg = OverlayImageCleanerDialog(
            parent=self,
            image_path=src,
            target_resolution=self._config.overlay_big_resolution,
            cutter_template=getattr(self._config, "overlay_cutter_template", ""),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result_image is None:
            return

        try:
            dlg.result_image.save(src, "PNG")
        except Exception as e:
            QMessageBox.warning(self, "Overlay Image Cleaner", str(e))
            return

        self._overlay_big_changed()

    def _regenerate_box_small(self) -> None:
        if not self._config.use_box_image_for_box_small:
            return
        assets = self._current_assets()
        if not assets:
            return
        box_path = assets.folder / f"{assets.basename}.png"
        if not box_path.exists():
            return
        dest = assets.folder / f"{assets.basename}_small.png"
        try:
            save_png_resized_from_file(box_path, dest, expected=self._config.box_small_resolution)
        except Exception as e:
            QMessageBox.warning(self, "Box Small", str(e))
            return
        self.refresh(preserve_metadata_edits=True)

    def _build_overlay(self, which: int = 1) -> None:
        game = self._current_assets()
        if not game:
            return

        can_use_big = bool(game.overlay_big and game.overlay_big.exists())
        dlg = OverlayBuildDialog(parent=self, can_use_big_overlay=can_use_big)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.choice:
            return

        blank_default = resource_path("Overlay_blank.png")
        override_raw = (self._config.overlay_template_override or "").strip()
        blank = Path(override_raw).expanduser() if override_raw else blank_default
        if not blank.exists():
            msg = f"Missing overlay template. Expected {blank_default}"
            if override_raw:
                msg = f"Missing overlay template override: {blank}"
            QMessageBox.warning(self, "Build Overlay", msg)
            return

        if which not in (1, 2, 3):
            return

        overlay = game.folder / f"{game.basename}_overlay.png"
        overlay2 = game.folder / f"{game.basename}_overlay2.png"
        overlay3 = game.folder / f"{game.basename}_overlay3.png"

        if which == 1:
            dest = overlay
        elif which == 2:
            dest = overlay2
        else:
            dest = overlay3
        if dest.exists():
            resp = QMessageBox.question(self, "Replace?", f"{dest.name} already exists. Replace it?")
            if resp != QMessageBox.StandardButton.Yes:
                return

        build_res = self._config.overlay_build_resolution
        pos = self._config.overlay_build_position

        try:
            if dlg.choice == "browse":
                path, _ = QFileDialog.getOpenFileName(
                    self,
                    "Select bottom image",
                    get_start_dir(game.folder),
                    "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*.*)",
                )
                if not path:
                    return
                remember_path(path)
                build_overlay_png_from_file(
                    blank,
                    Path(path),
                    dest,
                    overlay_resolution=self._config.overlay_resolution,
                    build_resolution=build_res,
                    position=pos,
                )
            elif dlg.choice == "paste":
                qimg = QApplication.clipboard().image()
                if qimg.isNull():
                    QMessageBox.information(self, "Build Overlay", "Clipboard does not contain an image")
                    return
                bottom = pil_from_qimage(qimg)
                build_overlay_png(
                    blank,
                    bottom,
                    dest,
                    overlay_resolution=self._config.overlay_resolution,
                    build_resolution=build_res,
                    position=pos,
                )
            elif dlg.choice == "big":
                if not can_use_big or not game.overlay_big:
                    QMessageBox.information(self, "Build Overlay", "Big Overlay is missing")
                    return
                build_overlay_png_from_file(
                    blank,
                    game.overlay_big,
                    dest,
                    overlay_resolution=self._config.overlay_resolution,
                    build_resolution=build_res,
                    position=pos,
                )
            else:
                return
        except ImageProcessError as e:
            QMessageBox.warning(self, "Build Overlay", str(e))
            return
        except Exception as e:
            QMessageBox.warning(self, "Build Overlay", str(e))
            return

        self._images_changed()

    def _set_overlay_blank(self, which: int) -> None:
        game = self._current_assets()
        if not game:
            return

        if which not in (1, 2, 3):
            return

        empty = resource_path("Overlay_empty.png")
        if not empty.exists():
            QMessageBox.warning(self, "Overlay", f"Missing empty overlay image: {empty}")
            return

        if which == 1:
            self._img_overlay1.replace_from_file(empty)
        elif which == 2:
            self._img_overlay2.replace_from_file(empty)
        else:
            self._img_overlay3.replace_from_file(empty)

    def _create_qr_from_url(self) -> None:
        game = self._current_assets()
        if not game:
            return

        dlg = QrUrlDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        url = dlg.value().strip()
        if not url:
            return
        dest = game.folder / f"{game.basename}_qrcode.png"
        if dest.exists():
            resp = QMessageBox.question(self, "Replace?", f"{dest.name} already exists. Replace it?")
            if resp != QMessageBox.StandardButton.Yes:
                return
        try:
            generate_qr_png(url, dest, expected=self._config.qrcode_resolution)
        except Exception as e:
            QMessageBox.warning(self, "QR failed", str(e))
            return
        self.refresh(preserve_metadata_edits=True)

    def _reorder_snaps(self, src_index: int, dst_index: int) -> None:
        game = self._current_assets()
        if not game:
            return

        def p(i: int) -> Path:
            return game.folder / f"{game.basename}_snap{i}.png"

        a = p(src_index)
        b = p(dst_index)

        if a.exists() and b.exists():
            try:
                swap_files(a, b)
            except Exception as e:
                QMessageBox.warning(self, "Reorder failed", str(e))
                return
        elif a.exists() and not b.exists():
            try:
                a.rename(b)
            except Exception as e:
                QMessageBox.warning(self, "Reorder failed", str(e))
                return
        elif (not a.exists()) and b.exists():
            try:
                b.rename(a)
            except Exception as e:
                QMessageBox.warning(self, "Reorder failed", str(e))
                return

        self.refresh()

    def _reorder_overlays(self, src_index: int, dst_index: int) -> None:
        game = self._current_assets()
        if not game:
            return

        if src_index == dst_index:
            return

        if src_index not in (1, 2, 3) or dst_index not in (1, 2, 3):
            return

        folder = game.folder
        base = game.basename

        overlay = folder / f"{base}_overlay.png"
        overlay2 = folder / f"{base}_overlay2.png"
        overlay3 = folder / f"{base}_overlay3.png"

        # Only enable meaningful reorders when at least two overlay slots exist on disk.
        existing = [p for p in (overlay, overlay2, overlay3) if p.exists()]
        if len(existing) < 2:
            return

        def p(i: int) -> Path:
            if i == 1:
                return overlay
            if i == 2:
                return overlay2
            return overlay3

        a = p(src_index)
        b = p(dst_index)

        if a.exists() and b.exists():
            try:
                swap_files(a, b)
            except Exception as e:
                QMessageBox.warning(self, "Reorder failed", str(e))
                return
        elif a.exists() and not b.exists():
            try:
                a.rename(b)
            except Exception as e:
                QMessageBox.warning(self, "Reorder failed", str(e))
                return
        elif (not a.exists()) and b.exists():
            try:
                b.rename(a)
            except Exception as e:
                QMessageBox.warning(self, "Reorder failed", str(e))
                return

        self.refresh()
