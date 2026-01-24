from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageQt
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sgm.config import AppConfig, Resolution
from sgm.image_ops import ImageProcessError, build_overlay_png, pil_from_qimage
from sgm.resources import resource_path
from sgm.ui.dialog_state import get_start_dir, remember_path


AUTO_REPEAT_DELAY_MS = 250
AUTO_REPEAT_INTERVAL_MS = 30


def _pil_image_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    qimg = ImageQt.ImageQt(img)
    return QPixmap.fromImage(QImage(qimg))


def _parse_string_list(raw: str) -> list[str]:
    value = (raw or "").strip()
    if not value:
        return []
    parts = value.split("|") if "|" in value else value.split(",")
    out: list[str] = []
    for p in parts:
        s = p.strip()
        if not s:
            continue
        if s not in out:
            out.append(s)
    return out


def _path_key(value: str) -> str:
    try:
        return os.path.normcase(str(Path(value).expanduser()))
    except Exception:
        return value.casefold()


class OverlayBuilderDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        config: AppConfig,
        config_path: Path,
        overlay_dest: Path,
        big_overlay_path: Path | None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Controller Overlay Builder")
        self.setModal(True)

        self._config = config
        self._config_path = config_path
        self._overlay_dest = overlay_dest
        self._overlay_resolution = Resolution(config.overlay_resolution.width, config.overlay_resolution.height)
        self._build_resolution = Resolution(config.overlay_build_resolution.width, config.overlay_build_resolution.height)
        self._position = [int(config.overlay_build_position[0]), int(config.overlay_build_position[1])]

        self._default_template_path = resource_path("Overlay_blank.png")
        self._template_items: list[dict] = []
        self._template_img: Image.Image | None = None
        self._current_template_path: Path | None = None

        self._bottom_image: Image.Image | None = None
        self._bottom_source: str = ""
        self._big_overlay_path = big_overlay_path if big_overlay_path and big_overlay_path.exists() else None

        self._build_ui()
        self._load_templates()
        self._load_initial_overlay()
        self._update_preview()

    # -------------------- UI --------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)

        self._preview = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedSize(420, 580)
        root.addWidget(self._preview)

        ctrl = QVBoxLayout()

        tmpl_row = QHBoxLayout()
        tmpl_row.addWidget(QLabel("Controller template:"))
        self._combo_template = QComboBox()
        self._combo_template.currentIndexChanged.connect(self._on_template_changed)
        tmpl_row.addWidget(self._combo_template, 1)
        ctrl.addLayout(tmpl_row)

        self._lbl_template_warn = QLabel("")
        self._lbl_template_warn.setStyleSheet("color: #c05050;")
        self._lbl_template_warn.setWordWrap(True)
        self._lbl_template_warn.setVisible(False)
        ctrl.addWidget(self._lbl_template_warn)

        img_row = QHBoxLayout()
        img_row.addWidget(QLabel("Overlay image:"))

        btn_browse = QPushButton("Browse")
        btn_browse.setToolTip("Select an image file for the overlay")
        btn_browse.clicked.connect(self._choose_browse)
        img_row.addWidget(btn_browse)

        btn_paste = QPushButton("Paste")
        btn_paste.setToolTip("Use the current clipboard image as the overlay")
        btn_paste.clicked.connect(self._choose_paste)
        img_row.addWidget(btn_paste)

        self._btn_big = QPushButton("Use Big Overlay")
        self._btn_big.setToolTip("Use the game’s Big Overlay image")
        self._btn_big.setEnabled(self._big_overlay_path is not None)
        self._btn_big.clicked.connect(self._choose_big)
        img_row.addWidget(self._btn_big)

        img_row.addStretch(1)
        ctrl.addLayout(img_row)

        self._lbl_image_src = QLabel("No overlay image selected")
        self._lbl_image_src.setWordWrap(True)
        ctrl.addWidget(self._lbl_image_src)

        grp_move = QGroupBox("Position")
        move_layout = QVBoxLayout(grp_move)

        grid = QGridLayout()
        btn_up = QPushButton("Up")
        btn_up.setToolTip("Move overlay image up 1 px")
        btn_up.clicked.connect(lambda: self._move(0, -1))
        btn_down = QPushButton("Down")
        btn_down.setToolTip("Move overlay image down 1 px")
        btn_down.clicked.connect(lambda: self._move(0, 1))
        btn_left = QPushButton("Left")
        btn_left.setToolTip("Move overlay image left 1 px")
        btn_left.clicked.connect(lambda: self._move(-1, 0))
        btn_right = QPushButton("Right")
        btn_right.setToolTip("Move overlay image right 1 px")
        btn_right.clicked.connect(lambda: self._move(1, 0))

        for b in (btn_up, btn_down, btn_left, btn_right):
            b.setAutoRepeat(True)
            b.setAutoRepeatDelay(AUTO_REPEAT_DELAY_MS)
            b.setAutoRepeatInterval(AUTO_REPEAT_INTERVAL_MS)

        grid.addWidget(btn_up, 0, 1)
        grid.addWidget(btn_left, 1, 0)
        grid.addWidget(btn_right, 1, 2)
        grid.addWidget(btn_down, 2, 1)
        move_layout.addLayout(grid)

        sp_x = QSpinBox()
        sp_x.setRange(-5000, 5000)
        sp_x.setValue(self._position[0])
        sp_y = QSpinBox()
        sp_y.setRange(-5000, 5000)
        sp_y.setValue(self._position[1])
        sp_x.setMaximumWidth(90)
        sp_y.setMaximumWidth(90)
        sp_x.valueChanged.connect(lambda v: self._set_offset(v, None))
        sp_y.valueChanged.connect(lambda v: self._set_offset(None, v))

        offsets_row = QHBoxLayout()
        offsets_row.addWidget(QLabel("X"))
        offsets_row.addWidget(sp_x)
        offsets_row.addSpacing(8)
        offsets_row.addWidget(QLabel("Y"))
        offsets_row.addWidget(sp_y)
        offsets_row.addStretch(1)
        move_layout.addLayout(offsets_row)

        self._spin_x = sp_x
        self._spin_y = sp_y

        ctrl.addWidget(grp_move)

        grp_scale = QGroupBox("Scale")
        scale_layout = QVBoxLayout(grp_scale)

        def _scale_row(label_text: str, minus_cb, plus_cb):
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            btn_minus = QPushButton("-")
            btn_plus = QPushButton("+")
            btn_minus.setToolTip("Decrease by 1 px")
            btn_plus.setToolTip("Increase by 1 px")
            btn_minus.clicked.connect(minus_cb)
            btn_plus.clicked.connect(plus_cb)
            btn_minus.setMaximumWidth(40)
            btn_plus.setMaximumWidth(40)
            for b in (btn_minus, btn_plus):
                b.setAutoRepeat(True)
                b.setAutoRepeatDelay(AUTO_REPEAT_DELAY_MS)
                b.setAutoRepeatInterval(AUTO_REPEAT_INTERVAL_MS)
            row.addWidget(lbl)
            row.addStretch(1)
            row.addWidget(btn_minus)
            row.addWidget(btn_plus)
            return row

        scale_layout.addLayout(_scale_row("Uniform", self._shrink_uniform, self._grow_uniform))
        scale_layout.addLayout(_scale_row("Width", self._shrink_width, self._grow_width))
        scale_layout.addLayout(_scale_row("Height", self._shrink_height, self._grow_height))

        size_row = QHBoxLayout()
        sp_w = QSpinBox()
        sp_w.setRange(1, 5000)
        sp_w.setValue(self._build_resolution.width)
        sp_h = QSpinBox()
        sp_h.setRange(1, 5000)
        sp_h.setValue(self._build_resolution.height)
        sp_w.setMaximumWidth(90)
        sp_h.setMaximumWidth(90)
        sp_w.valueChanged.connect(lambda v: self._set_size(v, None))
        sp_h.valueChanged.connect(lambda v: self._set_size(None, v))

        size_row.addWidget(QLabel("Width"))
        size_row.addWidget(sp_w)
        size_row.addSpacing(8)
        size_row.addWidget(QLabel("Height"))
        size_row.addWidget(sp_h)
        size_row.addStretch(1)
        scale_layout.addLayout(size_row)

        self._spin_w = sp_w
        self._spin_h = sp_h

        ctrl.addWidget(grp_scale)

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color: #c05050;")
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setVisible(False)
        ctrl.addWidget(self._lbl_status)

        ctrl.addStretch(1)

        bottom = QHBoxLayout()
        btn_default = QPushButton("Set As Default")
        btn_default.setToolTip("Save the current position, size, and template as defaults")
        btn_default.clicked.connect(self._set_as_default)
        bottom.addWidget(btn_default)

        bottom.addStretch(1)

        self._btn_use = QPushButton("Use This Image")
        self._btn_use.setToolTip("Save overlay.png using the current settings")
        self._btn_use.clicked.connect(self._save_overlay)
        bottom.addWidget(self._btn_use)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_cancel)

        ctrl.addLayout(bottom)
        root.addLayout(ctrl)

    # -------------------- Template Handling --------------------

    def _load_templates(self) -> None:
        raw_list = _parse_string_list(self._config.overlay_template_override or "")
        seen: set[str] = set()
        items: list[dict] = []

        def add_item(label: str, path: Path, *, is_default: bool) -> None:
            key = _path_key(str(path))
            if key in seen:
                return
            seen.add(key)
            exists = path.exists() and path.is_file()
            items.append({"label": label, "path": path, "exists": exists, "is_default": is_default})

        add_item("Default (blue)", self._default_template_path, is_default=True)
        for raw in raw_list:
            try:
                p = Path(raw).expanduser()
            except Exception:
                p = Path(raw)
            label = p.name or raw
            add_item(label, p, is_default=False)

        self._template_items = items

        model = QStandardItemModel()
        self._combo_template.setModel(model)
        for item in items:
            label = item["label"]
            if not item["exists"]:
                label = f"{label} (missing)"
            qitem = QStandardItem(label)
            qitem.setToolTip(str(item["path"]))
            if not item["exists"]:
                qitem.setEnabled(False)
            qitem.setData(item, Qt.ItemDataRole.UserRole)
            model.appendRow(qitem)

        # Initial selection: first override if present, else default.
        index_to_select = 0
        if raw_list:
            desired_key = _path_key(str(Path(raw_list[0]).expanduser()))
            for i, item in enumerate(items):
                if _path_key(str(item["path"])) == desired_key:
                    index_to_select = i
                    break

        self._combo_template.setCurrentIndex(index_to_select)
        self._apply_template_from_index(index_to_select)
        self._update_missing_template_warning()

    def _apply_template_from_index(self, index: int) -> None:
        model = self._combo_template.model()
        if model is None:
            return
        if index < 0 or index >= model.rowCount():
            return
        item = model.item(index)
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(data, dict):
            return
        path = data.get("path")
        if not isinstance(path, Path):
            return
        self._current_template_path = path
        self._combo_template.setToolTip(str(path))
        self._load_template_image(path)

    def _load_template_image(self, path: Path | None) -> None:
        self._template_img = None
        if path is None or not path.exists():
            return
        try:
            img = Image.open(path).convert("RGBA")
            ow, oh = self._overlay_resolution.width, self._overlay_resolution.height
            if img.size != (ow, oh):
                img = img.resize((ow, oh), resample=Image.LANCZOS)
            self._template_img = img
        except Exception:
            self._template_img = None

    def _on_template_changed(self, index: int) -> None:
        self._apply_template_from_index(index)
        self._update_missing_template_warning()
        self._update_preview()

    def _update_missing_template_warning(self) -> None:
        missing = [str(item["path"]) for item in self._template_items if not item["exists"]]
        if missing:
            self._lbl_template_warn.setText(
                "Missing template path(s):\n" + "\n".join(missing)
            )
            self._lbl_template_warn.setVisible(True)
        else:
            self._lbl_template_warn.setVisible(False)

    # -------------------- Overlay Image Handling --------------------

    def _load_initial_overlay(self) -> None:
        if self._big_overlay_path is not None:
            self._load_bottom_from_file(self._big_overlay_path)

    def _load_bottom_from_file(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.warning(self, "Overlay Builder", f"Missing image: {path}")
            return
        try:
            self._bottom_image = Image.open(path).convert("RGBA")
            self._bottom_source = str(path)
            self._lbl_image_src.setText(f"{path.name}")
        except Exception as e:
            QMessageBox.warning(self, "Overlay Builder", f"Failed to load image: {e}")
            self._bottom_image = None
            self._bottom_source = ""
            self._lbl_image_src.setText("No overlay image selected")

    def _choose_browse(self) -> None:
        start_dir = get_start_dir(self._overlay_dest.parent)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select overlay image",
            start_dir,
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*.*)",
        )
        if not path:
            return
        remember_path(path)
        self._load_bottom_from_file(Path(path))
        self._update_preview()

    def _choose_paste(self) -> None:
        qimg = QApplication.clipboard().image()
        if qimg.isNull():
            QMessageBox.information(self, "Overlay Builder", "Clipboard does not contain an image")
            return
        try:
            self._bottom_image = pil_from_qimage(qimg)
            self._bottom_source = "clipboard"
            self._lbl_image_src.setText("(clipboard)")
            self._update_preview()
        except ImageProcessError as e:
            QMessageBox.warning(self, "Overlay Builder", str(e))

    def _choose_big(self) -> None:
        if self._big_overlay_path is None:
            QMessageBox.information(self, "Overlay Builder", "Big Overlay is missing")
            return
        self._load_bottom_from_file(self._big_overlay_path)
        self._update_preview()

    # -------------------- Transform Handling --------------------

    def _move(self, dx: int, dy: int) -> None:
        self._set_offset(self._position[0] + dx, self._position[1] + dy)

    def _set_offset(self, x: int | None, y: int | None) -> None:
        if x is not None:
            self._position[0] = int(x)
            if self._spin_x.value() != int(x):
                self._spin_x.blockSignals(True)
                self._spin_x.setValue(int(x))
                self._spin_x.blockSignals(False)
        if y is not None:
            self._position[1] = int(y)
            if self._spin_y.value() != int(y):
                self._spin_y.blockSignals(True)
                self._spin_y.setValue(int(y))
                self._spin_y.blockSignals(False)
        self._update_preview()

    def _set_size(self, w: int | None, h: int | None) -> None:
        if w is not None:
            w = max(1, int(w))
            self._build_resolution = Resolution(w, self._build_resolution.height)
            if self._spin_w.value() != w:
                self._spin_w.blockSignals(True)
                self._spin_w.setValue(w)
                self._spin_w.blockSignals(False)
        if h is not None:
            h = max(1, int(h))
            self._build_resolution = Resolution(self._build_resolution.width, h)
            if self._spin_h.value() != h:
                self._spin_h.blockSignals(True)
                self._spin_h.setValue(h)
                self._spin_h.blockSignals(False)
        self._update_preview()

    def _grow_uniform(self) -> None:
        self._set_size(self._build_resolution.width + 1, self._build_resolution.height + 1)

    def _shrink_uniform(self) -> None:
        self._set_size(self._build_resolution.width - 1, self._build_resolution.height - 1)

    def _grow_width(self) -> None:
        self._set_size(self._build_resolution.width + 1, None)

    def _shrink_width(self) -> None:
        self._set_size(self._build_resolution.width - 1, None)

    def _grow_height(self) -> None:
        self._set_size(None, self._build_resolution.height + 1)

    def _shrink_height(self) -> None:
        self._set_size(None, self._build_resolution.height - 1)

    # -------------------- Preview + Validation --------------------

    def _compose_preview(self) -> Image.Image | None:
        ow, oh = self._overlay_resolution.width, self._overlay_resolution.height
        if ow <= 0 or oh <= 0:
            return None

        canvas = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
        if self._bottom_image is not None:
            bw, bh = self._build_resolution.width, self._build_resolution.height
            if bw > 0 and bh > 0:
                bottom = self._bottom_image.resize((bw, bh), resample=Image.LANCZOS)
                canvas.alpha_composite(bottom, dest=(self._position[0], self._position[1]))

        if self._template_img is not None:
            canvas.alpha_composite(self._template_img, dest=(0, 0))

        return canvas

    def _validate(self) -> bool:
        ow, oh = self._overlay_resolution.width, self._overlay_resolution.height
        bw, bh = self._build_resolution.width, self._build_resolution.height
        x, y = self._position

        if self._template_img is None:
            self._set_status("Missing controller template.")
            return False
        if self._bottom_image is None:
            self._set_status("Select or paste an overlay image.")
            return False
        if bw <= 0 or bh <= 0:
            self._set_status("Overlay image size must be at least 1x1.")
            return False
        if bw > ow or bh > oh:
            self._set_status("Overlay image exceeds the template size.")
            return False

        self._set_status("")
        return True

    def _set_status(self, text: str) -> None:
        if text:
            self._lbl_status.setText(text)
            self._lbl_status.setVisible(True)
            self._btn_use.setEnabled(False)
        else:
            self._lbl_status.setVisible(False)
            self._btn_use.setEnabled(True)

    def _update_preview(self) -> None:
        self._validate()
        img = self._compose_preview()
        if img is None:
            self._preview.setPixmap(QPixmap())
            return
        pix = _pil_image_to_qpixmap(img)
        pix = pix.scaled(self._preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._preview.setPixmap(pix)

    # -------------------- Save + Defaults --------------------

    def _set_as_default(self) -> None:
        self._config.overlay_build_position = (self._position[0], self._position[1])
        self._config.overlay_build_resolution = Resolution(self._build_resolution.width, self._build_resolution.height)

        selected = self._current_template_path
        if selected and selected != self._default_template_path:
            raw_list = _parse_string_list(self._config.overlay_template_override or "")
            selected_key = _path_key(str(selected))
            new_list: list[str] = [str(selected)]
            for raw in raw_list:
                if _path_key(raw) == selected_key:
                    continue
                new_list.append(raw)
            self._config.overlay_template_override = "|".join(new_list)

        try:
            self._config.save(self._config_path)
        except Exception as e:
            QMessageBox.warning(self, "Overlay Builder", f"Failed to save defaults: {e}")
            return

        QMessageBox.information(self, "Overlay Builder", "Defaults saved to sgm.ini")

    def _save_overlay(self) -> None:
        if not self._validate():
            return
        if self._current_template_path is None:
            QMessageBox.warning(self, "Overlay Builder", "Missing controller template")
            return

        try:
            build_overlay_png(
                self._current_template_path,
                self._bottom_image,
                self._overlay_dest,
                overlay_resolution=self._overlay_resolution,
                build_resolution=self._build_resolution,
                position=(self._position[0], self._position[1]),
            )
        except ImageProcessError as e:
            QMessageBox.warning(self, "Overlay Builder", str(e))
            return
        except Exception as e:
            QMessageBox.warning(self, "Overlay Builder", str(e))
            return

        self.accept()
