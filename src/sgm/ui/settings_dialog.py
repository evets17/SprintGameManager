from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sgm.config import AppConfig, Resolution
from sgm.resources import resource_path


LANGS = ["en", "fr", "es", "de", "it"]


def _parse_string_list(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
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


def _list_from_widget(widget: QListWidget) -> list[str]:
    items: list[str] = []
    for i in range(widget.count()):
        item = widget.item(i)
        if item is None:
            continue
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, str) and data.strip():
            items.append(data)
        else:
            items.append(item.text())
    return items


def _enable_reorder(widget: QListWidget, on_change) -> None:
    widget.setDragEnabled(True)
    widget.setAcceptDrops(True)
    widget.setDropIndicatorShown(True)
    widget.setDefaultDropAction(Qt.DropAction.MoveAction)
    widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
    model = widget.model()
    if model is not None:
        def _schedule_refresh(*_):
            QTimer.singleShot(0, on_change)

        model.rowsMoved.connect(_schedule_refresh)
        model.layoutChanged.connect(_schedule_refresh)


class SettingsDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        config: AppConfig,
        config_path: Path,
        on_changed,
        on_open_ini,
    ):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)

        self._config = config
        self._config_path = config_path
        self._on_changed = on_changed
        self._on_open_ini = on_open_ini

        self._build_ui()
        self._load_from_config()

    # -------------------- UI Helpers --------------------

    def _row(self, form: QFormLayout, label: str, control: QWidget, info_text: str) -> None:
        lbl = QLabel(label)
        if label:
            lbl.setToolTip(info_text)
        else:
            control.setToolTip(info_text)
        form.addRow(lbl, control)

    def _save_config(self, key: str) -> None:
        try:
            self._config.save(self._config_path)
        except Exception as e:
            QMessageBox.warning(self, "Settings", f"Failed to save settings: {e}")
            return
        if self._on_changed:
            self._on_changed(key)

    # -------------------- Build UI --------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs, 1)

        self._build_tab_general()
        self._build_tab_json()
        self._build_tab_warnings()
        self._build_tab_images()

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        root.addLayout(close_row)

    def _build_tab_general(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        layout.addLayout(form)

        self._edit_last_folder = QLineEdit()
        self._edit_last_folder.setReadOnly(True)
        self._row(
            form,
            "Last Game Folder",
            self._edit_last_folder,
            "Shows the last games folder you opened. This value updates automatically when you browse to a new folder.",
        )

        self._combo_lang = QComboBox()
        self._combo_lang.addItems(LANGS)
        self._combo_lang.currentTextChanged.connect(self._on_language_changed)
        self._row(
            form,
            "Language",
            self._combo_lang,
            "Select the preferred language for descriptions and related checks.",
        )

        self._list_palette_exts = QListWidget()
        self._list_palette_exts.setMinimumHeight(120)
        btn_add = QPushButton("Add")
        btn_remove = QPushButton("Remove")
        btn_add.clicked.connect(self._add_palette_ext)
        btn_remove.clicked.connect(self._remove_palette_ext)

        list_box = QVBoxLayout()
        list_box.addWidget(self._list_palette_exts)
        list_btn_row = QHBoxLayout()
        list_btn_row.addWidget(btn_add)
        list_btn_row.addWidget(btn_remove)
        list_btn_row.addStretch(1)
        list_box.addLayout(list_btn_row)
        list_widget = QWidget()
        list_widget.setLayout(list_box)

        self._row(
            form,
            "Palette Extensions",
            list_widget,
            "List of file extensions used to detect palette helper files. Example: .txt, .cfg. Extensions are stored as a | delimited list.",
        )

        btn_open_ini = QPushButton("Open sgm.ini in default editor")
        btn_open_ini.clicked.connect(self._on_open_ini)
        self._row(
            form,
            "",
            btn_open_ini,
            "Open the sgm.ini file in your system’s default editor.",
        )

        layout.addStretch(1)
        self._tabs.addTab(tab, "General")

    def _build_tab_json(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        layout.addLayout(form)

        self._list_editors = QListWidget()
        self._list_editors.setMinimumHeight(140)
        _enable_reorder(self._list_editors, lambda: self._sync_list_setting(self._list_editors))
        btn_add = QPushButton("Add")
        btn_rename = QPushButton("Rename")
        btn_delete = QPushButton("Delete")
        btn_add.clicked.connect(lambda: self._list_add(self._list_editors, "Add Editor", "Editor name:"))
        btn_rename.clicked.connect(lambda: self._list_rename(self._list_editors, "Rename Editor", "Editor name:"))
        btn_delete.clicked.connect(lambda: self._list_delete(self._list_editors))

        list_box = QVBoxLayout()
        list_box.addWidget(self._list_editors)
        list_btn_row = QHBoxLayout()
        list_btn_row.addWidget(btn_add)
        list_btn_row.addWidget(btn_rename)
        list_btn_row.addWidget(btn_delete)
        list_btn_row.addStretch(1)
        list_box.addLayout(list_btn_row)
        list_widget = QWidget()
        list_widget.setLayout(list_box)

        self._row(
            form,
            "Editors",
            list_widget,
            "List of common editor names used in metadata drop-downs.",
        )

        self._edit_media_prefix = QLineEdit()
        self._edit_media_prefix.textChanged.connect(self._on_media_prefix_changed)
        self._row(
            form,
            "Media Prefix",
            self._edit_media_prefix,
            "Prefix used for media paths in jzintv flags (e.g., /media/usb0).",
        )

        self._list_json_keys = QListWidget()
        self._list_json_keys.setMinimumHeight(140)
        _enable_reorder(self._list_json_keys, lambda: self._sync_list_setting(self._list_json_keys))
        btn_add = QPushButton("Add")
        btn_rename = QPushButton("Rename")
        btn_delete = QPushButton("Delete")
        btn_add.clicked.connect(lambda: self._list_add(self._list_json_keys, "Add JSON Key", "Key:"))
        btn_rename.clicked.connect(lambda: self._list_rename(self._list_json_keys, "Rename JSON Key", "Key:"))
        btn_delete.clicked.connect(lambda: self._list_delete(self._list_json_keys))

        list_box = QVBoxLayout()
        list_box.addWidget(self._list_json_keys)
        list_btn_row = QHBoxLayout()
        list_btn_row.addWidget(btn_add)
        list_btn_row.addWidget(btn_rename)
        list_btn_row.addWidget(btn_delete)
        list_btn_row.addStretch(1)
        list_box.addLayout(list_btn_row)
        list_widget = QWidget()
        list_widget.setLayout(list_box)

        self._row(
            form,
            "Valid Json Keys",
            list_widget,
            "Common JSON keys used for bulk updates and validation (supports nested paths like description/en).",
        )

        layout.addStretch(1)
        self._tabs.addTab(tab, "JSON")

    def _build_tab_warnings(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        layout.addLayout(form)

        self._spin_max_len = QSpinBox()
        self._spin_max_len.setRange(0, 999)
        self._spin_max_len.valueChanged.connect(self._on_max_len_changed)
        self._row(
            form,
            "Max File Length",
            self._spin_max_len,
            "Maximum recommended base filename length for warning checks.",
        )

        self._spin_snaps = QSpinBox()
        self._spin_snaps.setRange(0, 3)
        self._spin_snaps.valueChanged.connect(self._on_snaps_changed)
        self._row(
            form,
            "Number Of Expected Snaps",
            self._spin_snaps,
            "Number of snapshot images expected per game (0 to 3).",
        )

        layout.addStretch(1)
        self._tabs.addTab(tab, "Warnings")

    def _build_tab_images(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        layout.addLayout(form)

        self._edit_build_res = QLineEdit()
        self._edit_build_res.editingFinished.connect(self._on_build_res_changed)
        self._row(
            form,
            "Overlay Build Resolution",
            self._edit_build_res,
            "Resolution used when building overlays (format: WxH, e.g. 175x279).",
        )

        pos_row = QHBoxLayout()
        self._spin_build_x = QSpinBox()
        self._spin_build_x.setRange(-5000, 5000)
        self._spin_build_x.valueChanged.connect(self._on_build_pos_changed)
        self._spin_build_y = QSpinBox()
        self._spin_build_y.setRange(-5000, 5000)
        self._spin_build_y.valueChanged.connect(self._on_build_pos_changed)
        pos_row.addWidget(QLabel("X"))
        pos_row.addWidget(self._spin_build_x)
        pos_row.addSpacing(6)
        pos_row.addWidget(QLabel("Y"))
        pos_row.addWidget(self._spin_build_y)
        pos_row.addStretch(1)
        pos_widget = QWidget()
        pos_widget.setLayout(pos_row)
        self._row(
            form,
            "Overlay Build Offset",
            pos_widget,
            "Position of the overlay image on the template (stored as x,y). Negative values are allowed.",
        )

        self._list_templates = QListWidget()
        self._list_templates.setMinimumHeight(160)
        _enable_reorder(self._list_templates, self._save_templates)
        btn_add = QPushButton("Add (Browse)")
        btn_remove = QPushButton("Remove")
        btn_default = QPushButton("Set As Default")
        btn_add.clicked.connect(self._add_template)
        btn_remove.clicked.connect(self._remove_template)
        btn_default.clicked.connect(self._set_default_template)

        list_box = QVBoxLayout()
        list_box.addWidget(self._list_templates)
        list_btn_row = QHBoxLayout()
        list_btn_row.addWidget(btn_add)
        list_btn_row.addWidget(btn_remove)
        list_btn_row.addWidget(btn_default)
        list_btn_row.addStretch(1)
        list_box.addLayout(list_btn_row)
        list_widget = QWidget()
        list_widget.setLayout(list_box)

        self._row(
            form,
            "Overlay Templates",
            list_widget,
            "List of controller template files used for overlay building. The first item is the default.",
        )

        self._chk_box_small = QCheckBox()
        self._chk_box_small.stateChanged.connect(self._on_box_small_changed)
        self._row(
            form,
            "Auto Set Small Box",
            self._chk_box_small,
            "When enabled, Box Small is generated automatically from Box.",
        )

        self._chk_auto_overlay = QCheckBox()
        self._chk_auto_overlay.stateChanged.connect(self._on_auto_build_overlay_changed)
        self._row(
            form,
            "Auto-Build Overlay",
            self._chk_auto_overlay,
            "When enabled, Overlay 1 is auto-built from Big Overlay when missing.",
        )

        self._chk_confirm_overwrite = QCheckBox()
        self._chk_confirm_overwrite.stateChanged.connect(self._on_confirm_overwrite_changed)
        self._row(
            form,
            "Confirm Image Overwrite",
            self._chk_confirm_overwrite,
            "When enabled, the app asks before overwriting existing images.",
        )

        layout.addStretch(1)
        self._tabs.addTab(tab, "Images")

    # -------------------- Load / Save --------------------

    def _load_from_config(self) -> None:
        self._combo_lang.blockSignals(True)
        self._edit_media_prefix.blockSignals(True)
        self._spin_max_len.blockSignals(True)
        self._spin_snaps.blockSignals(True)
        self._edit_build_res.blockSignals(True)
        self._spin_build_x.blockSignals(True)
        self._spin_build_y.blockSignals(True)
        self._chk_box_small.blockSignals(True)
        self._chk_auto_overlay.blockSignals(True)
        self._chk_confirm_overwrite.blockSignals(True)

        self._edit_last_folder.setText(self._config.last_game_folder or "")

        lang = (self._config.language or "en").strip().lower() or "en"
        if lang not in LANGS:
            lang = "en"
        self._combo_lang.setCurrentText(lang)

        self._list_palette_exts.clear()
        for ext in _normalize_extensions(self._config.palette_extensions or []):
            self._list_palette_exts.addItem(ext)

        self._list_editors.clear()
        for e in self._config.metadata_editors or []:
            self._list_editors.addItem(e)

        self._edit_media_prefix.setText(self._config.jzintv_media_prefix or "")

        self._list_json_keys.clear()
        for k in self._config.json_keys or []:
            self._list_json_keys.addItem(k)

        self._spin_max_len.setValue(int(self._config.desired_max_base_file_length))
        self._spin_snaps.setValue(int(self._config.desired_number_of_snaps))

        self._edit_build_res.setText(self._config.overlay_build_resolution.to_string())
        self._spin_build_x.setValue(int(self._config.overlay_build_position[0]))
        self._spin_build_y.setValue(int(self._config.overlay_build_position[1]))

        self._list_templates.clear()
        for p in _parse_string_list(self._config.overlay_template_override or ""):
            self._add_template_item(p)

        self._chk_box_small.setChecked(bool(self._config.use_box_image_for_box_small))
        self._chk_auto_overlay.setChecked(bool(self._config.auto_build_overlay))
        self._chk_confirm_overwrite.setChecked(bool(getattr(self._config, "confirm_image_overwrite", True)))

        self._combo_lang.blockSignals(False)
        self._edit_media_prefix.blockSignals(False)
        self._spin_max_len.blockSignals(False)
        self._spin_snaps.blockSignals(False)
        self._edit_build_res.blockSignals(False)
        self._spin_build_x.blockSignals(False)
        self._spin_build_y.blockSignals(False)
        self._chk_box_small.blockSignals(False)
        self._chk_auto_overlay.blockSignals(False)
        self._chk_confirm_overwrite.blockSignals(False)

    # -------------------- Handlers --------------------

    def _on_language_changed(self, value: str) -> None:
        lang = (value or "").strip().lower() or "en"
        if lang not in LANGS:
            lang = "en"
        if self._config.language == lang:
            return
        self._config.language = lang
        self._save_config("Language")

    def _on_media_prefix_changed(self, value: str) -> None:
        val = (value or "").strip()
        if self._config.jzintv_media_prefix == val:
            return
        self._config.jzintv_media_prefix = val
        self._save_config("JzIntvMediaPrefix")

    def _on_max_len_changed(self, value: int) -> None:
        v = int(value)
        if self._config.desired_max_base_file_length == v:
            return
        self._config.desired_max_base_file_length = v
        self._save_config("DesiredMaxBaseFileLength")

    def _on_snaps_changed(self, value: int) -> None:
        v = int(value)
        if self._config.desired_number_of_snaps == v:
            return
        self._config.desired_number_of_snaps = v
        self._save_config("DesiredNumberOfSnaps")

    def _on_build_res_changed(self) -> None:
        text = (self._edit_build_res.text() or "").strip()
        current = self._config.overlay_build_resolution
        parsed = Resolution.parse(text, default=current)
        if text.lower() != parsed.to_string():
            QMessageBox.warning(self, "Settings", "Overlay Build Resolution must be in the form WxH (e.g., 175x279).")
            self._edit_build_res.setText(current.to_string())
            return
        if parsed == current:
            return
        self._config.overlay_build_resolution = parsed
        self._save_config("OverlayBuildResolution")

    def _on_build_pos_changed(self) -> None:
        x = int(self._spin_build_x.value())
        y = int(self._spin_build_y.value())
        if self._config.overlay_build_position == (x, y):
            return
        self._config.overlay_build_position = (x, y)
        self._save_config("OverlayBuildPosition")

    def _on_box_small_changed(self) -> None:
        val = bool(self._chk_box_small.isChecked())
        if self._config.use_box_image_for_box_small == val:
            return
        self._config.use_box_image_for_box_small = val
        self._save_config("UseBoxImageForBoxSmall")

    def _on_auto_build_overlay_changed(self) -> None:
        val = bool(self._chk_auto_overlay.isChecked())
        if self._config.auto_build_overlay == val:
            return
        self._config.auto_build_overlay = val
        self._save_config("AutoBuildOverlay")

    def _on_confirm_overwrite_changed(self) -> None:
        val = bool(self._chk_confirm_overwrite.isChecked())
        if bool(getattr(self._config, "confirm_image_overwrite", True)) == val:
            return
        self._config.confirm_image_overwrite = val
        self._save_config("ConfirmImageOverwrite")

    def _add_palette_ext(self) -> None:
        text, ok = QInputDialog.getText(self, "Add Extension", "Extension (e.g., .cfg):")
        if not ok:
            return
        ext = (text or "").strip()
        if not ext:
            return
        if not ext.startswith("."):
            ext = "." + ext
        ext = ext.lower()

        existing = _list_from_widget(self._list_palette_exts)
        if ext in existing:
            return
        self._list_palette_exts.addItem(ext)
        self._config.palette_extensions = _normalize_extensions(_list_from_widget(self._list_palette_exts))
        self._save_config("PaletteExtensions")

    def _remove_palette_ext(self) -> None:
        row = self._list_palette_exts.currentRow()
        if row < 0:
            return
        self._list_palette_exts.takeItem(row)
        self._config.palette_extensions = _normalize_extensions(_list_from_widget(self._list_palette_exts))
        self._save_config("PaletteExtensions")

    def _list_add(self, widget: QListWidget, title: str, label: str) -> None:
        text, ok = QInputDialog.getText(self, title, label)
        if not ok:
            return
        val = (text or "").strip()
        if not val:
            return
        current = _list_from_widget(widget)
        if val in current:
            return
        widget.addItem(val)
        self._sync_list_setting(widget)

    def _list_rename(self, widget: QListWidget, title: str, label: str) -> None:
        row = widget.currentRow()
        if row < 0:
            return
        item = widget.item(row)
        if item is None:
            return
        text, ok = QInputDialog.getText(self, title, label, text=item.text())
        if not ok:
            return
        val = (text or "").strip()
        if not val:
            return
        current = _list_from_widget(widget)
        if val in current and val != item.text():
            return
        item.setText(val)
        self._sync_list_setting(widget)

    def _list_delete(self, widget: QListWidget) -> None:
        row = widget.currentRow()
        if row < 0:
            return
        widget.takeItem(row)
        self._sync_list_setting(widget)

    def _sync_list_setting(self, widget: QListWidget) -> None:
        items = _list_from_widget(widget)
        if widget is self._list_editors:
            self._config.metadata_editors = items
            self._save_config("MetadataEditors")
        elif widget is self._list_json_keys:
            self._config.json_keys = items
            self._save_config("JsonKeys")

    def _add_template(self) -> None:
        start = Path(self._config.last_game_folder) if self._config.last_game_folder else None
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select overlay template",
            str(start) if start and start.exists() else "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*.*)",
        )
        if not path:
            return
        items = _list_from_widget(self._list_templates)
        if path in items:
            return
        self._add_template_item(path)
        self._save_templates()

    def _remove_template(self) -> None:
        row = self._list_templates.currentRow()
        if row < 0:
            return
        self._list_templates.takeItem(row)
        self._save_templates()

    def _set_default_template(self) -> None:
        row = self._list_templates.currentRow()
        if row < 0:
            return
        items = _list_from_widget(self._list_templates)
        selected = items.pop(row)
        items.insert(0, selected)
        self._list_templates.clear()
        for i in items:
            self._add_template_item(i)
        self._save_templates()

    def _save_templates(self) -> None:
        items = _list_from_widget(self._list_templates)
        self._config.overlay_template_override = "|".join(items)
        self._save_config("OverlayTemplateOverride")

    def _add_template_item(self, path: str) -> None:
        p = Path(path)
        label = f"{p.name} - {path}"
        item = QListWidgetItem(label)
        item.setToolTip(path)
        item.setData(Qt.ItemDataRole.UserRole, path)
        self._list_templates.addItem(item)
