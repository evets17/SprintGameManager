from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
        QGridLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

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
from sgm.io_utils import RenameCollisionError, copy_file, plan_rename_for_game_files, rename_many, swap_files
from sgm.scanner import scan_folder
from sgm.ui.widgets import ImageCard, ImageSpec, OverlayCard, OverlayPrimaryCard, SnapshotCard
from sgm.version import main_window_title


ACCEPTED_ADD_EXTS = {".bin", ".int", ".rom", ".cfg", ".json", ".png"}


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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        top = QHBoxLayout()
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight: 600;")
        top.addWidget(lbl)

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
        top.addWidget(self._btn_extra)

        self._btn = QPushButton("Add")
        self._btn.setMaximumHeight(24)
        self._btn.clicked.connect(self._browse)
        top.addWidget(self._btn)

        layout.addLayout(top)

        self.setAcceptDrops(True)

    def set_context(self, *, folder: Path | None, basename: str | None, existing: Path | None, warning: str | None) -> None:
        self._folder = folder
        self._basename = basename
        full = str(existing) if existing else "(missing)"
        shown = self._elide_left(full, max_chars=self.MAX_LABEL_CHARS)
        self._path.setText(shown)
        self._path.setToolTip(full if existing else "")
        w = (warning or "").strip()
        self._warning.setText(w)
        self._warning.setVisible(bool(w))
        if self._btn_extra.isVisible():
            self._btn_extra.setEnabled(bool(self._folder and self._basename))

    def set_extra_action(self, label: str, handler) -> None:
        self._btn_extra.setText(label)
        if self._extra_handler is not None and self._extra_handler is not handler:
            try:
                self._btn_extra.clicked.disconnect(self._extra_handler)
            except Exception:
                pass
        self._extra_handler = handler
        self._btn_extra.clicked.connect(handler)
        self._btn_extra.setVisible(True)
        self._btn_extra.setEnabled(bool(self._folder and self._basename))

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
        if not self._folder:
            start = ""
        else:
            start = str(self._folder)

        path, _ = QFileDialog.getOpenFileName(self, f"Select {self._title}", start, "All files (*.*)")
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() not in self._allowed_exts:
            QMessageBox.warning(self, "Invalid file", f"Expected one of: {', '.join(sorted(self._allowed_exts))}")
            return
        self._on_add_file(p)


class MetadataEditor(QWidget):
    LANGS = ["en", "fr", "es", "de", "it"]

    def __init__(self, *, on_saved, metadata_editors: list[str] | None = None):
        super().__init__()
        self._on_saved = on_saved
        self._metadata_editors = list(metadata_editors or [])

        self._folder: Path | None = None
        self._basename: str | None = None
        self._path: Path | None = None
        self._dirty = False

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

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)

        self._name = QLineEdit()
        self._name.setPlaceholderText("name")
        form.addRow("Name", self._name)

        self._nb_players = QSpinBox()
        self._nb_players.setRange(0, 8)
        self._nb_players.setSpecialValueText("")
        form.addRow("Players", self._nb_players)

        self._editor = QComboBox()
        self._editor.setEditable(True)
        self._editor.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._editor.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        if self._metadata_editors:
            self._editor.addItems(self._metadata_editors)
        self._editor.setEditText("")
        form.addRow("Editor", self._editor)

        self._year = QSpinBox()
        self._year.setRange(0, 9999)
        self._year.setSpecialValueText("")
        form.addRow("Year", self._year)

        fields_l.addLayout(form)

        fields_l.addWidget(QLabel("Description"))
        self._desc_tabs = QTabWidget()
        self._desc_edits: dict[str, QTextEdit] = {}
        for lang in self.LANGS:
            edit = QTextEdit()
            self._desc_edits[lang] = edit
            self._desc_tabs.addTab(edit, lang)
        fields_l.addWidget(self._desc_tabs, 1)

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

    def set_context(self, *, folder: Path | None, basename: str | None, path: Path | None) -> None:
        self._folder = folder
        self._basename = basename
        self._path = path
        self._dirty = False
        self._btn_action.setEnabled(False)

        if not folder or not basename:
            self._warning.setText("")
            self._btn_action.setVisible(False)
            self._set_fields_enabled(False)
            self._fields.setVisible(False)
            self._bottom_spacer.setVisible(True)
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
            return

        self._warning.setText("")
        self._btn_action.setText("Save")
        self._btn_action.setVisible(True)
        self._btn_action.setEnabled(False)
        self._set_fields_enabled(True)
        self._fields.setVisible(True)
        self._bottom_spacer.setVisible(False)
        self._load(path)

    def _set_fields_enabled(self, enabled: bool) -> None:
        for w in [self._name, self._nb_players, self._editor, self._year, self._desc_tabs]:
            w.setEnabled(enabled)

    def _set_defaults(self, basename: str) -> None:
        self._name.setText(basename)
        self._nb_players.setValue(0)
        self._editor.setEditText("")
        self._year.setValue(0)
        for lang, edit in self._desc_edits.items():
            edit.setPlainText("")

    def _load(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

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
            self._nb_players.setValue(int(nb) if nb is not None and str(nb).strip() != "" else 0)
        except Exception:
            self._nb_players.setValue(0)

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
            self._desc_edits[lang].setPlainText(str(desc.get(lang, "")))

        self._dirty = False
        self._btn_action.setEnabled(False)

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
            "nb_players": 0,
            "editor": "",
            "year": 0,
            "description": {lang: "" for lang in self.LANGS},
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

        data = {
            "name": self._name.text().strip(),
            "nb_players": int(self._nb_players.value()),
            "editor": self._editor.currentText().strip(),
            "year": int(self._year.value()),
            "description": {lang: self._desc_edits[lang].toPlainText() for lang in self.LANGS},
        }

        try:
            self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))
            return False

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

        layout.addWidget(QLabel("Enter URL:"))

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("https://...")
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
    def __init__(self, *, parent: QWidget, initial: str):
        super().__init__(parent)
        self._initial = initial

        self.setWindowTitle("Change File Name")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        layout.addWidget(QLabel("New basename:"))
        self._edit = QLineEdit()
        self._edit.setText(initial)
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


class MainWindow(QMainWindow):
    def __init__(self, *, config: AppConfig, config_path: Path):
        super().__init__()
        self._config = config
        self._config_path = config_path

        self._folder: Path | None = None
        self._games: dict[str, GameAssets] = {}
        self._current: str | None = None

        self._analysis_enabled: bool = False
        self._analysis_by_game: dict[str, set[str]] = {}
        self._filter_checks: dict[str, QCheckBox] = {}
        self._list_panel: QWidget | None = None
        self._filters_scroll: QScrollArea | None = None

        self.setWindowTitle(main_window_title())
        self.setAcceptDrops(True)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)

        # Top bar
        top = QHBoxLayout()
        self._btn_browse = QPushButton("Browse Folder")
        self._btn_browse.clicked.connect(self._browse_folder)
        top.addWidget(self._btn_browse)

        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.clicked.connect(self._refresh_clicked)
        top.addWidget(self._btn_refresh)

        self._btn_add_files = QPushButton("Add Files")
        self._btn_add_files.clicked.connect(self._add_files_dialog)
        top.addWidget(self._btn_add_files)

        top.addStretch(1)
        self._lbl_folder = QLabel("(no folder)")
        self._lbl_folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self._lbl_folder)

        self._lbl_warnings = QLabel("Warnings: 0")
        top.addWidget(self._lbl_warnings)

        root_layout.addLayout(top)

        # Main split
        split = QSplitter()

        self._list_panel = QWidget()
        list_l = QVBoxLayout(self._list_panel)
        list_l.setContentsMargins(0, 0, 0, 0)
        list_l.setSpacing(6)

        self._lbl_game_count = QLabel("Games: 0")
        list_l.addWidget(self._lbl_game_count)

        self._list = QListWidget()
        self._list.currentTextChanged.connect(self._select_game)
        list_l.addWidget(self._list, 1)

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
        self._btn_analyze.setMaximumHeight(24)
        self._btn_analyze.clicked.connect(self._analyze_folder)
        row.addWidget(self._btn_analyze)
        analyze_l.addLayout(row)

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

        split.addWidget(self._list_panel)

        self._detail_root = QWidget()
        split.addWidget(self._detail_root)
        split.setStretchFactor(1, 1)

        root_layout.addWidget(split, 1)
        self.setCentralWidget(root)

        self._build_details()

        self._init_analyze_filters()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_filter_scroll_height()

    # ---------- public ----------

    def load_folder(self, folder: Path) -> None:
        self._reset_analysis_state()
        self._folder = folder
        self._lbl_folder.setText(str(folder))

        self._config.last_game_folder = str(folder)
        try:
            self._config.save(self._config_path)
        except Exception:
            pass

        self.refresh()

    def _refresh_clicked(self) -> None:
        # Manual refresh resets Analyze results; user must Analyze again to filter.
        self._reset_analysis_state()
        self.refresh()

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

    def refresh(self) -> None:
        if not self._folder:
            return
        scan = scan_folder(self._folder)
        self._games = scan.games

        if self._analysis_enabled:
            self._analysis_by_game = {b: self._compute_warning_codes(g) for b, g in self._games.items()}
            self._update_filter_visibility()

        self._rebuild_game_list(preserve=self._current)

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

        self._analysis_enabled = True
        self._analysis_by_game = {b: self._compute_warning_codes(g) for b, g in self._games.items()}

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

    def _rebuild_game_list(self, preserve: str | None = None) -> None:
        prev = preserve
        self._list.blockSignals(True)
        self._list.clear()

        total_count = len(self._games)
        showing_count = 0

        enabled_codes = {code for code, chk in self._filter_checks.items() if chk.isChecked()}
        only_warn = bool(self._analysis_enabled and self._chk_only_warnings.isChecked())

        for base, game in self._games.items():
            codes = self._analysis_by_game.get(base, set()) if self._analysis_enabled else set()

            if self._analysis_enabled and enabled_codes:
                codes = {c for c in codes if c in enabled_codes}

            if only_warn and not codes:
                continue

            item = QListWidgetItem(base)
            if self._analysis_enabled and codes:
                item.setForeground(Qt.GlobalColor.red)
            self._list.addItem(item)
            showing_count += 1

        self._update_game_count_label(showing=showing_count, total=total_count)

        self._list.blockSignals(False)

        # Restore selection if possible.
        if prev:
            for i in range(self._list.count()):
                if self._list.item(i).text() == prev:
                    self._list.setCurrentRow(i)
                    return
        if self._list.count() > 0:
            self._list.setCurrentRow(0)
        else:
            self._select_game("")

    def _update_game_count_label(self, *, showing: int, total: int) -> None:
        if not hasattr(self, "_lbl_game_count"):
            return
        if total <= 0:
            self._lbl_game_count.setText("Games: 0")
            return
        if showing >= total:
            self._lbl_game_count.setText(f"Games: {total}")
        else:
            self._lbl_game_count.setText(f"Games: {showing} of {total}")

    def _compute_warning_codes(self, game: GameAssets) -> set[str]:
        codes: set[str] = set()

        if len(game.basename) > self._config.desired_max_base_file_length:
            codes.add("longname")

        if game.rom is None:
            codes.add("missing:rom")

        if game.rom is not None and game.rom.suffix.lower() in {".int", ".bin"} and game.config is None:
            codes.add("missing:cfg")

        if game.metadata is None:
            codes.add("missing:metadata")

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
        self._btn_rename = QPushButton("Change File Name")
        self._btn_rename.clicked.connect(self._rename)
        self._btn_rename.setMaximumHeight(24)
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
        self._cfg_row.set_extra_action("Lookup", self._lookup_cfg)
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
        )
        images_grid.addWidget(self._img_box, 0, 0)

        self._img_box_small = ImageCard(
            config=self._config,
            spec=ImageSpec(title="Box Small", expected=self._config.box_small_resolution, filename="{basename}_small.png"),
            on_changed=self._images_changed,
        )
        images_grid.addWidget(self._img_box_small, 0, 1)

        self._img_overlay_big = ImageCard(
            config=self._config,
            spec=ImageSpec(title="Overlay Big", expected=self._config.overlay_big_resolution, filename="{basename}_big_overlay.png"),
            on_changed=self._images_changed,
        )
        images_grid.addWidget(self._img_overlay_big, 1, 0)

        self._img_overlay1 = OverlayPrimaryCard(
            index=1,
            on_reorder=self._reorder_overlays,
            config=self._config,
            spec=ImageSpec(title="Overlay 1", expected=self._config.overlay_resolution, filename="{basename}_overlay.png"),
            on_changed=self._images_changed,
            keep_ratio_enabled=True,
            keep_ratio_tooltip="When checked, added overlay images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas.",
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
            keep_ratio_tooltip="When checked, added overlay images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas.",
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
            keep_ratio_tooltip="When checked, added overlay images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas.",
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
        )
        self._snap2 = SnapshotCard(
            index=2,
            config=self._config,
            spec=ImageSpec(title="Snap 2", expected=self._config.snap_resolution, filename="{basename}_snap2.png"),
            on_changed=self._images_changed,
        )
        self._snap3 = SnapshotCard(
            index=3,
            config=self._config,
            spec=ImageSpec(title="Snap 3", expected=self._config.snap_resolution, filename="{basename}_snap3.png"),
            on_changed=self._images_changed,
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
        self._meta_editor = MetadataEditor(on_saved=self.refresh, metadata_editors=self._config.metadata_editors)
        right_l.addWidget(framed(self._meta_editor), 1)

        details_split = QSplitter(Qt.Orientation.Horizontal)
        details_split.addWidget(left)
        details_split.addWidget(right)
        details_split.setStretchFactor(0, 2)
        details_split.setStretchFactor(1, 1)
        layout.addWidget(details_split, 1)

    # ---------- selection ----------

    def _set_current_in_list(self, basename: str | None) -> None:
        # Important: block signals so we don't re-enter _select_game() and
        # accidentally clear pending metadata edits.
        with QSignalBlocker(self._list):
            if not basename:
                self._list.setCurrentRow(-1)
                return

            for i in range(self._list.count()):
                item = self._list.item(i)
                if item is not None and item.text() == basename:
                    self._list.setCurrentRow(i)
                    return

    def _select_game(self, basename: str) -> None:
        prev = self._current
        next_base = basename if basename else None

        if prev != next_base and prev is not None and self._meta_editor.has_unsaved_changes():
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

        self._current = next_base

        game = self._games.get(basename) if basename else None

        if not game:
            self._base_name.setText("")
            self._base_warn.setText("")
            self._rom_row.set_context(folder=None, basename=None, existing=None, warning=None)
            self._cfg_row.set_context(folder=None, basename=None, existing=None, warning=None)
            self._meta_editor.set_context(folder=None, basename=None, path=None)
            self._set_images_context(None)
            self._lbl_warnings.setText("Warnings: 0")
            return

        self._base_name.setText(f"Basename: {game.basename}")
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

        cfg_warn = None
        if game.rom is not None:
            if game.rom.suffix.lower() in {".int", ".bin"} and game.config is None:
                cfg_warn = "Missing config for .int/.bin ROM (.cfg missing)"
        self._cfg_row.set_context(folder=game.folder, basename=game.basename, existing=game.config, warning=cfg_warn)

        self._meta_editor.set_context(folder=game.folder, basename=game.basename, path=game.metadata)

        self._set_images_context(game)
        self._lbl_warnings.setText(f"Warnings: {self._count_selected_warnings(game)}")

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

        self._add_files(files)
        event.acceptProposedAction()

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
        folder = QFileDialog.getExistingDirectory(self, "Select games folder")
        if not folder:
            return
        self.load_folder(Path(folder))

    def _add_files_dialog(self) -> None:
        if not self._folder:
            QMessageBox.information(self, "Add Files", "Choose a folder first")
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Add files",
            str(self._folder),
            "Accepted (*.bin *.int *.rom *.cfg *.json *.png);;All files (*.*)",
        )
        if not files:
            return
        self._add_files([Path(f) for f in files])

    # ---------- file add / copy ----------

    def _add_files(self, files: list[Path]) -> None:
        if not self._folder:
            return

        for src in files:
            if src.suffix.lower() not in ACCEPTED_ADD_EXTS:
                continue
            dest = self._folder / src.name
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

        self.refresh()

    def _current_game(self) -> GameAssets | None:
        if not self._current:
            return None
        return self._games.get(self._current)

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
        self.refresh()

    # ---------- rename ----------

    def _rename(self) -> None:
        game = self._current_game()
        if not game:
            return

        dlg = RenameBasenameDialog(parent=self, initial=game.basename)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_base = dlg.value().strip()
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

        self.refresh()
        # Select the renamed game
        if new_base in self._games:
            self._list.setCurrentRow(list(self._games.keys()).index(new_base))

    # ---------- images ----------

    def _images_changed(self) -> None:
        # In derived mode, after Box changes, regenerate Box Small.
        if self._config.use_box_image_for_box_small:
            game = self._current_game()
            if game:
                box_path = game.folder / f"{game.basename}.png"
                if box_path.exists():
                    small_dest = game.folder / f"{game.basename}_small.png"
                    try:
                        save_png_resized_from_file(box_path, small_dest, expected=self._config.box_small_resolution)
                    except Exception as e:
                        QMessageBox.warning(self, "Box Small", str(e))
        self.refresh()

    def _regenerate_box_small(self) -> None:
        if not self._config.use_box_image_for_box_small:
            return
        game = self._current_game()
        if not game:
            return
        box_path = game.folder / f"{game.basename}.png"
        if not box_path.exists():
            return
        dest = game.folder / f"{game.basename}_small.png"
        try:
            save_png_resized_from_file(box_path, dest, expected=self._config.box_small_resolution)
        except Exception as e:
            QMessageBox.warning(self, "Box Small", str(e))
            return
        self.refresh()

    def _build_overlay(self, which: int = 1) -> None:
        game = self._current_game()
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
                    str(game.folder),
                    "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*.*)",
                )
                if not path:
                    return
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
        game = self._current_game()
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
        game = self._current_game()
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
        self.refresh()

    def _reorder_snaps(self, src_index: int, dst_index: int) -> None:
        game = self._current_game()
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
        game = self._current_game()
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
