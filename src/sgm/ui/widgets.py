from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt
from PySide6.QtGui import QDrag, QImage, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QVBoxLayout,
    QWidget,
)

from sgm.config import AppConfig, Resolution
from sgm.image_ops import (
    ImageProcessError,
    get_image_size,
    pil_from_qimage,
    save_png_preserve_ratio_centered_on_canvas_from_file,
    save_png_preserve_ratio_centered_on_canvas_from_pil,
    save_png_resized_from_clipboard_qimage,
    save_png_resized_from_file,
)
from sgm.resources import resource_path
from sgm.ui.dialog_state import get_start_dir, remember_path


def _thumb_for(path: Path, *, max_w: int = 128, max_h: int = 128) -> QPixmap | None:
    if not path.exists():
        return None
    pix = QPixmap(str(path))
    if pix.isNull():
        return None
    return pix.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


class _ImagePreviewDialog(QDialog):
    def __init__(self, parent: QWidget, pixmap: QPixmap):
        super().__init__(parent)
        self.setWindowTitle("Preview")

        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setPixmap(pixmap)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(lbl)

        # Size the dialog reasonably for screen.
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        w = pixmap.width()
        h = pixmap.height()
        if avail is not None:
            w = min(w, max(200, int(avail.width() * 0.95)))
            h = min(h, max(200, int(avail.height() * 0.95)))
        self.resize(w, h)

    def mousePressEvent(self, event):
        # Click anywhere closes the preview.
        self.accept()


@dataclass(frozen=True)
class ImageSpec:
    title: str
    expected: Resolution
    filename: str
    paste_enabled: bool = True


class ImageCard(QFrame):
    def __init__(
        self,
        *,
        config: AppConfig,
        spec: ImageSpec,
        on_changed,
        drop_enabled: bool = True,
        before_write: Callable[[Path, str, Path], bool] | None = None,
        keep_ratio_enabled: bool = False,
        keep_ratio_tooltip: str | None = None,
    ):
        super().__init__()
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Plain)
        self.setLineWidth(1)
        self._config = config
        self._spec = spec
        self._on_changed = on_changed
        self._before_write = before_write

        self._folder: Path | None = None
        self._basename: str | None = None
        self._existing_path: Path | None = None
        self._extra_handler = None
        self._blank_handler = None
        self._extra_requires_image: bool = False
        self._keep_ratio_enabled = keep_ratio_enabled
        self._chk_keep_ratio: QCheckBox | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        title_row = QHBoxLayout()
        self._title = QLabel(f"{spec.title} ({spec.expected.to_string()})")
        self._title.setStyleSheet("font-weight: 600;")
        title_row.addWidget(self._title)

        if keep_ratio_enabled:
            self._chk_keep_ratio = QCheckBox("Keep Ratio")
            self._chk_keep_ratio.setChecked(False)
            self._chk_keep_ratio.setToolTip(
                keep_ratio_tooltip
                or "When checked, added images keep their aspect ratio (no stretching) by fitting inside the target resolution and centering on a transparent canvas."
            )
            title_row.addSpacing(8)
            title_row.addWidget(self._chk_keep_ratio)

        title_row.addStretch(1)
        outer.addLayout(title_row)

        body = QHBoxLayout()

        self._thumb = QLabel()
        self._thumb.setFixedSize(132, 132)
        self._thumb.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Plain)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.installEventFilter(self)
        body.addWidget(self._thumb)

        right = QVBoxLayout()

        self._info = QLabel("")
        self._info.setWordWrap(True)
        self._info_default_palette = self._info.palette()
        right.addWidget(self._info)

        btn_col = QVBoxLayout()
        btn_col.setContentsMargins(0, 0, 0, 0)
        btn_col.setSpacing(4)

        self._btn_browse = QPushButton("Browse")
        self._btn_browse.setMaximumHeight(24)
        self._btn_browse.setFixedWidth(64)
        self._btn_browse.setToolTip(
            "Choose an image file to use for this slot. The image will be resized and saved to the game folder using the expected resolution."
        )
        self._btn_browse.clicked.connect(self._browse)
        btn_col.addWidget(self._btn_browse)

        self._btn_resize = QPushButton("Resize")
        self._btn_resize.setMaximumHeight(24)
        self._btn_resize.setFixedWidth(64)
        self._btn_resize.setToolTip(
            "Resize the existing image in this slot to the expected resolution and overwrite it."
        )
        self._btn_resize.clicked.connect(self._resize_existing)
        self._btn_resize.setVisible(False)
        btn_col.addWidget(self._btn_resize)

        self._btn_extra = QPushButton("")
        self._btn_extra.setMaximumHeight(24)
        self._btn_extra.setFixedWidth(64)
        self._btn_extra.setToolTip("Run the extra action for this image slot.")
        self._btn_extra.setVisible(False)
        btn_col.addWidget(self._btn_extra)

        self._btn_blank = QPushButton("Blank")
        self._btn_blank.setMaximumHeight(24)
        self._btn_blank.setFixedWidth(64)
        self._btn_blank.setToolTip("Set an empty image for this slot.")
        self._btn_blank.setVisible(False)
        btn_col.addWidget(self._btn_blank)

        self._btn_paste = QPushButton("Paste")
        self._btn_paste.setMaximumHeight(24)
        self._btn_paste.setFixedWidth(64)
        self._btn_paste.setEnabled(spec.paste_enabled)
        self._btn_paste.setToolTip(
            "Paste an image from the clipboard into this slot. The image will be resized and saved to the game folder using the expected resolution."
        )
        self._btn_paste.clicked.connect(self._paste)
        btn_col.addWidget(self._btn_paste)
        btn_col.addStretch(1)

        right.addLayout(btn_col)
        right.addStretch(1)
        body.addLayout(right)
        outer.addLayout(body)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAcceptDrops(drop_enabled)

    def eventFilter(self, obj, event):
        if obj is self._thumb and event.type() == QEvent.Type.MouseButtonDblClick:
            self._open_preview()
            return True
        return super().eventFilter(obj, event)

    def _open_preview(self) -> None:
        p = self._existing_path
        if not p or not p.exists():
            return
        pix = QPixmap(str(p))
        if pix.isNull():
            return
        dlg = _ImagePreviewDialog(self, pix)
        dlg.exec()

    def set_controls_enabled(self, enabled: bool) -> None:
        # "Browse" should remain available whenever a game is selected.
        # If the Resize button is visible, it means the current image is the wrong
        # resolution; allow resizing even if other edits are disabled (e.g. derived slots).
        can_resize = enabled or (self._btn_resize.isVisible() and bool(self._folder and self._basename))
        self._btn_resize.setEnabled(can_resize)
        self._btn_extra.setEnabled(enabled)
        self._btn_blank.setEnabled(enabled)
        self._btn_paste.setEnabled(enabled and self._spec.paste_enabled)

    def set_extra_action(self, label: str, handler, tooltip: str | None = None) -> None:
        self._btn_extra.setText(label)
        self._btn_extra.setToolTip(tooltip or label)
        self._extra_requires_image = False
        if self._extra_handler is not None and self._extra_handler is not handler:
            try:
                self._btn_extra.clicked.disconnect(self._extra_handler)
            except Exception:
                pass
        self._extra_handler = handler
        self._btn_extra.clicked.connect(handler)
        self._btn_extra.setVisible(True)

    def set_extra_action_requires_existing_image(self, requires_image: bool) -> None:
        """Control whether the Extra button is enabled only when an image exists."""
        self._extra_requires_image = bool(requires_image)

    def set_blank_action(self, handler, tooltip: str | None = None) -> None:
        if self._blank_handler is not None and self._blank_handler is not handler:
            try:
                self._btn_blank.clicked.disconnect(self._blank_handler)
            except Exception:
                pass
        self._blank_handler = handler
        self._btn_blank.setToolTip(tooltip or "Blank")
        self._btn_blank.clicked.connect(handler)
        self._btn_blank.setVisible(True)

    def set_context(
        self,
        *,
        folder: Path | None,
        basename: str | None,
        existing_path: Path | None,
        warnings: list[str],
        needs_resize: bool = False,
    ) -> None:
        self._folder = folder
        self._basename = basename
        self._existing_path = existing_path

        has_image = bool(existing_path and existing_path.exists())
        self._btn_browse.setEnabled(bool(self._folder and self._basename))
        self._btn_resize.setVisible(has_image and needs_resize)
        self._btn_extra.setEnabled(bool(self._folder and self._basename) and (not self._extra_requires_image or has_image))
        self._btn_blank.setEnabled(bool(self._folder and self._basename))

        if existing_path and existing_path.exists():
            pix = _thumb_for(existing_path)
            if pix is not None:
                self._thumb.setPixmap(pix)
            else:
                self._thumb.setText("(no preview)")
        else:
            self._thumb.setPixmap(QPixmap())
            self._thumb.setText("(missing)")

        if warnings:
            full = "\n".join(warnings)
            self._info.setText(full)
            self._info.setToolTip(full)
            # Use stylesheet for warning color to work with custom themes.
            self._info.setStyleSheet("QLabel { color: #f38ba8; }")
        else:
            self._info.setToolTip("")
            if existing_path is None:
                self._info.setText("Optional")
            else:
                self._info.setText("OK")
            self._info.setStyleSheet("")

    def dest_path(self) -> Path | None:
        if not self._folder or not self._basename:
            return None
        return self._folder / self._spec.filename.format(basename=self._basename)

    def _overlay_empty_canvas_path(self) -> Path:
        return resource_path("Overlay_empty.png")

    def replace_from_file(self, src: Path, *, confirm_replace: bool = True) -> bool:
        if not src.exists() or not src.is_file():
            QMessageBox.warning(self, "Image", f"Missing source file: {src}")
            return False
        dest = self.dest_path()
        if dest is None:
            return False
        if confirm_replace and not self._confirm_replace_if_needed(dest):
            return False
        self._replace_from_file(src, preserve_ratio=False)
        return True

    def _confirm_replace_if_needed(self, dest: Path) -> bool:
        if not dest.exists():
            return True
        if not bool(getattr(self._config, "confirm_image_overwrite", True)):
            return True
        resp = QMessageBox.question(self, "Replace?", f"{dest.name} already exists. Replace it?")
        return resp == QMessageBox.StandardButton.Yes

    def _browse(self) -> None:
        if not self._folder or not self._basename:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select image",
            get_start_dir(self._folder),
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*.*)",
        )
        if not path:
            return
        remember_path(path)
        src = Path(path)
        dest = self.dest_path()
        if dest is None:
            return
        if not self._confirm_replace_if_needed(dest):
            return
        preserve = bool(self._keep_ratio_enabled and self._chk_keep_ratio and self._chk_keep_ratio.isChecked())
        self._replace_from_file(src, preserve_ratio=preserve)

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

        if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}:
            event.ignore()
            return

        dest = self.dest_path()
        if dest is None:
            event.ignore()
            return
        if not self._confirm_replace_if_needed(dest):
            event.ignore()
            return
        preserve = bool(self._keep_ratio_enabled and self._chk_keep_ratio and self._chk_keep_ratio.isChecked())
        self._replace_from_file(p, preserve_ratio=preserve)
        event.acceptProposedAction()

    def _paste(self) -> None:
        if not self._folder or not self._basename:
            return

        qimg: QImage = QApplication.clipboard().image()
        if qimg.isNull():
            QMessageBox.information(self, "Paste", "Clipboard does not contain an image")
            return

        dest = self.dest_path()
        if dest is None:
            return

        if self._before_write is not None and self._folder and self._basename:
            if not self._before_write(self._folder, self._basename, dest):
                return

        if not self._confirm_replace_if_needed(dest):
            return

        try:
            preserve = bool(self._keep_ratio_enabled and self._chk_keep_ratio and self._chk_keep_ratio.isChecked())
            if preserve:
                pil = pil_from_qimage(qimg)
                save_png_preserve_ratio_centered_on_canvas_from_pil(
                    pil,
                    dest,
                    expected=self._spec.expected,
                )
            else:
                save_png_resized_from_clipboard_qimage(qimg, dest, expected=self._spec.expected)
        except ImageProcessError as e:
            QMessageBox.warning(self, "Paste failed", str(e))
            return

        self._on_changed()

    def _replace_from_file(self, src: Path, *, preserve_ratio: bool) -> None:
        dest = self.dest_path()
        if dest is None:
            return

        if self._before_write is not None and self._folder and self._basename:
            if not self._before_write(self._folder, self._basename, dest):
                return

        try:
            if preserve_ratio:
                save_png_preserve_ratio_centered_on_canvas_from_file(
                    src,
                    dest,
                    expected=self._spec.expected,
                )
            else:
                save_png_resized_from_file(src, dest, expected=self._spec.expected)
        except ImageProcessError as e:
            QMessageBox.warning(self, "Image failed", str(e))
            return

        self._on_changed()

    def _resize_existing(self) -> None:
        if not self._folder or not self._basename:
            return

        src = self._existing_path
        if not src or not src.exists():
            return

        dest = self.dest_path() or src

        if self._before_write is not None and self._folder and self._basename:
            if not self._before_write(self._folder, self._basename, dest):
                return
        try:
            save_png_resized_from_file(src, dest, expected=self._spec.expected)
        except ImageProcessError as e:
            QMessageBox.warning(self, "Resize failed", str(e))
            return

        self._on_changed()
class OverlayCard(ImageCard):
    MIME = "application/x-sgm-overlay-index"

    def __init__(self, *, index: int, on_reorder, **kwargs):
        self._index = index
        self._on_reorder = on_reorder
        super().__init__(**kwargs)
        self.setAcceptDrops(True)
        self._drag_start: QPoint | None = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        return super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is None:
            return super().mouseMoveEvent(event)

        if (event.position().toPoint() - self._drag_start).manhattanLength() < 8:
            return super().mouseMoveEvent(event)

        src = self._existing_path
        if src is None or not src.exists():
            return super().mouseMoveEvent(event)

        mime = QMimeData()
        mime.setData(self.MIME, str(self._index).encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(self.MIME) or event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasFormat(self.MIME):
            try:
                other = int(bytes(event.mimeData().data(self.MIME)).decode("utf-8"))
            except Exception:
                event.ignore()
                return

            if other != self._index and self._on_reorder is not None:
                self._on_reorder(other, self._index)
            event.acceptProposedAction()
            return

        # file-system drop: treat like replace image
        return super().dropEvent(event)


class OverlayPrimaryCard(OverlayCard):
    def dest_path(self) -> Path | None:
        if not self._folder or not self._basename:
            return None

        return self._folder / f"{self._basename}_overlay.png"


class SnapshotCard(ImageCard):
    MIME = "application/x-sgm-snapshot-index"

    def __init__(self, *, index: int, **kwargs):
        self._index = index
        super().__init__(**kwargs)
        self.setAcceptDrops(True)
        self._drag_start: QPoint | None = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        return super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is None:
            return super().mouseMoveEvent(event)

        if (event.position().toPoint() - self._drag_start).manhattanLength() < 8:
            return super().mouseMoveEvent(event)

        dest = self.dest_path()
        if dest is None or not dest.exists():
            return super().mouseMoveEvent(event)

        mime = QMimeData()
        mime.setData(self.MIME, str(self._index).encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(self.MIME) or event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasFormat(self.MIME):
            try:
                other = int(bytes(event.mimeData().data(self.MIME)).decode("utf-8"))
            except Exception:
                event.ignore()
                return

            if other != self._index:
                self.parent().on_snapshot_drop(other, self._index)
            event.acceptProposedAction()
            return

        # file-system drop: treat like replace image
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                p = Path(urls[0].toLocalFile())
                if p.exists() and p.is_file():
                    preserve = bool(self._keep_ratio_enabled and self._chk_keep_ratio and self._chk_keep_ratio.isChecked())
                    self._replace_from_file(p, preserve_ratio=preserve)
                    event.acceptProposedAction()
                    return

        event.ignore()
