from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


DEFAULT_MEDIA_PREFIX = "/media/usb0"


def _normalize_media_prefix(prefix: str | None) -> str:
    s = (prefix or "").strip() or DEFAULT_MEDIA_PREFIX
    s = s.rstrip("/")
    return s or DEFAULT_MEDIA_PREFIX


def _load_json_dict(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_dict(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _split_flags(value: str) -> list[str]:
    s = (value or "").strip()
    if not s:
        return []
    try:
        return shlex.split(s, posix=True)
    except Exception:
        return [t for t in s.split(" ") if t.strip()]


def _strip_wrapping_quotes(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""

    # Accept both single- and double-quoted strings, including cases where the
    # user entered a shell-quoted token (e.g. via shlex.quote).
    try:
        parts = shlex.split(s, posix=True)
        if len(parts) == 1:
            return parts[0]
    except Exception:
        pass

    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    return s


def _find_equals_flag_value(tokens: list[str], flag_prefix: str) -> str | None:
    # Supports tokens like: --flag=value
    for t in tokens:
        if t.startswith(flag_prefix):
            return t[len(flag_prefix) :]
    return None


def _remove_equals_flag(tokens: list[str], flag_prefix: str) -> list[str]:
    return [t for t in tokens if not t.startswith(flag_prefix)]


def _quote_if_spaces(path_str: str) -> str:
    if any(ch.isspace() for ch in path_str):
        # Default to single quotes for shell-style quoting.
        return shlex.quote(path_str)
    return path_str


def _is_single_shell_token(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return True
    try:
        return len(shlex.split(s, posix=True)) == 1
    except Exception:
        return False


def _normalize_other_flag_token(token: str) -> str:
    """Normalize a token for storage/display as a single shell argument.

    We parse jzintv_extra via shlex, which strips quotes. If a token contains
    spaces (e.g. from --cheat='force ...'), it must be re-quoted so that when
    we rebuild the string (" ".join(tokens)) it remains a single argument.

    When the token contains '=', prefer quoting only the value side so the UI
    shows: --flag='value with spaces' rather than quoting the whole token.
    """

    t = (token or "").strip()
    if not t:
        return ""
    if not any(ch.isspace() for ch in t):
        return t

    # If the token is already quoted such that it's a single shell token, keep it.
    if _is_single_shell_token(t):
        return t

    if "=" in t:
        left, right = t.split("=", 1)
        # Only quote the value if there's actually a value.
        if right.strip() != "":
            return f"{left}={shlex.quote(right)}"

    # Fallback: quote the whole token.
    return shlex.quote(t)


def _local_to_device_path(*, root: Path, local_path: Path, media_prefix: str) -> str:
    try:
        rel = local_path.relative_to(root)
    except Exception:
        rel = local_path.name

    # On device, paths are posix.
    rel_posix = PurePosixPath(rel.as_posix())
    prefix = _normalize_media_prefix(media_prefix)
    return _quote_if_spaces(prefix + "/" + str(rel_posix))


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
    # If it isn't /media/usb0, we can't reliably map.
    return None


def _combo_add_disabled_blank(combo: QComboBox) -> None:
    # Add a disabled blank item used to represent "no selection".
    model = combo.model()
    if not isinstance(model, QStandardItemModel):
        return
    item = QStandardItem("")
    item.setEnabled(False)
    model.insertRow(0, item)


@dataclass(frozen=True)
class _FileOption:
    display: str
    path: Path


class AdvancedJsonDialog(QDialog):
    def __init__(
        self,
        *,
        parent,
        json_path: Path,
        root_folder: Path,
        palette_files: list[Path],
        keyboard_files: list[Path],
        media_prefix: str | None = None,
        on_written=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Advanced Settings (JSON)")

        self._json_path = json_path
        self._root = root_folder
        self._media_prefix = _normalize_media_prefix(media_prefix)
        self._on_written = on_written

        self._palette_options = self._build_file_options(palette_files)
        self._keyboard_options = self._build_file_options(keyboard_files)

        self._data: dict = _load_json_dict(self._json_path)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # save_highscores
        grp_save = QGroupBox("save_highscores")
        save_l = QVBoxLayout(grp_save)
        save_l.setContentsMargins(10, 10, 10, 10)
        save_l.setSpacing(6)

        self._chk_save = QCheckBox("Enabled")
        self._chk_save.setToolTip("Enable/disable save_highscores")
        self._chk_save.stateChanged.connect(self._save_highscores_toggled)

        self._lbl_save_warn = QLabel(
            "NOTE: Only enable for games that support saving. "
            "Original Intellivision games typically do not support save features."
        )
        self._lbl_save_warn.setWordWrap(True)

        row_btn = QHBoxLayout()
        self._btn_add_save = QPushButton("Add")
        self._btn_remove_save = QPushButton("Remove")
        self._btn_add_save.clicked.connect(self._add_save_highscores)
        self._btn_remove_save.clicked.connect(self._remove_save_highscores)
        row_btn.addWidget(self._btn_add_save)
        row_btn.addWidget(self._btn_remove_save)
        row_btn.addStretch(1)

        save_l.addWidget(self._chk_save)
        save_l.addWidget(self._lbl_save_warn)
        save_l.addLayout(row_btn)
        layout.addWidget(grp_save)

        # jzintv_extra
        grp_extra = QGroupBox("jzintv_extra")
        extra_l = QVBoxLayout(grp_extra)
        extra_l.setContentsMargins(10, 10, 10, 10)
        extra_l.setSpacing(8)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)

        self._cmb_kbd = QComboBox()
        self._cmb_kbd.setToolTip("Choose a keyboard hack file to set --kbdhackfile= (or Default to remove it)")
        self._cmb_kbd.currentIndexChanged.connect(lambda _: self._kbd_changed())

        self._lbl_kbd_missing = QLabel("")
        self._lbl_kbd_missing.setWordWrap(True)
        self._lbl_kbd_missing.setStyleSheet("color: red;")
        self._lbl_kbd_missing.setVisible(False)

        self._cmb_palette = QComboBox()
        self._cmb_palette.setToolTip("Choose a palette file to set --gfx-palette= (or Default to remove it)")
        self._cmb_palette.currentIndexChanged.connect(lambda _: self._palette_changed())

        self._lbl_palette_missing = QLabel("")
        self._lbl_palette_missing.setWordWrap(True)
        self._lbl_palette_missing.setStyleSheet("color: red;")
        self._lbl_palette_missing.setVisible(False)

        self._populate_combo(self._cmb_kbd, self._keyboard_options)
        self._populate_combo(self._cmb_palette, self._palette_options)

        if not self._keyboard_options:
            self._cmb_kbd.setEnabled(False)
            self._cmb_kbd.setToolTip("No .kbd files found in this games folder")
        if not self._palette_options:
            self._cmb_palette.setEnabled(False)
            self._cmb_palette.setToolTip("No palette files found ('.cfg' or '.txt' with 'palette' in the filename)")

        form.addRow("Keyboard Hack File:", self._cmb_kbd)
        form.addRow("", self._lbl_kbd_missing)
        form.addRow("Color Palette:", self._cmb_palette)
        form.addRow("", self._lbl_palette_missing)

        extra_l.addLayout(form)

        extra_l.addWidget(QLabel("Other flags"))
        self._list_flags = QListWidget()
        self._list_flags.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list_flags.currentRowChanged.connect(lambda _: self._update_flag_buttons())
        # Keep this list compact; it can grow large.
        self._list_flags.setMaximumHeight(120)
        extra_l.addWidget(self._list_flags)

        flags_btn_row = QHBoxLayout()
        self._btn_add_flag = QPushButton("Add Flag")
        self._btn_edit_flag = QPushButton("Edit")
        self._btn_remove_flag = QPushButton("Remove")
        self._btn_add_flag.clicked.connect(self._add_flag)
        self._btn_edit_flag.clicked.connect(self._edit_flag)
        self._btn_remove_flag.clicked.connect(self._remove_flag)
        flags_btn_row.addWidget(self._btn_add_flag)
        flags_btn_row.addWidget(self._btn_edit_flag)
        flags_btn_row.addWidget(self._btn_remove_flag)
        flags_btn_row.addStretch(1)
        extra_l.addLayout(flags_btn_row)

        self._lbl_full = QLabel("")
        self._lbl_full.setWordWrap(True)
        extra_l.addWidget(QLabel("Full jzintv_extra:"))
        extra_l.addWidget(self._lbl_full)

        layout.addWidget(grp_extra, 1)

        # Close button
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.setDefault(True)
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

        self._sync_from_json()

    def _build_file_options(self, paths: list[Path]) -> list[_FileOption]:
        opts: list[_FileOption] = []
        for p in paths:
            try:
                rel = p.relative_to(self._root)
                display = rel.as_posix()
            except Exception:
                display = str(p)
            opts.append(_FileOption(display=display, path=p))
        opts.sort(key=lambda o: o.display.casefold())
        return opts

    def _populate_combo(self, combo: QComboBox, opts: list[_FileOption]) -> None:
        combo.setModel(QStandardItemModel())
        _combo_add_disabled_blank(combo)
        combo.addItem("Default", None)
        for o in opts:
            combo.addItem(o.display, o.path)

    def _sync_from_json(self) -> None:
        # save_highscores
        has_save = isinstance(self._data, dict) and ("save_highscores" in self._data)
        self._btn_add_save.setEnabled(not has_save)
        self._btn_remove_save.setEnabled(has_save)
        with QSignalBlocker(self._chk_save):
            self._chk_save.setVisible(has_save)
            self._chk_save.setEnabled(has_save)
            if has_save:
                self._chk_save.setChecked(bool(self._data.get("save_highscores")))
            else:
                self._chk_save.setChecked(False)

        extra = ""
        if isinstance(self._data, dict):
            extra_val = self._data.get("jzintv_extra")
            extra = str(extra_val) if extra_val is not None else ""

        tokens = _split_flags(extra)

        # Specialized flags
        kbd_val = _find_equals_flag_value(tokens, "--kbdhackfile=")
        pal_val = _find_equals_flag_value(tokens, "--gfx-palette=")

        with QSignalBlocker(self._cmb_kbd):
            self._set_combo_from_flag(self._cmb_kbd, kbd_val)
        with QSignalBlocker(self._cmb_palette):
            self._set_combo_from_flag(self._cmb_palette, pal_val)

        self._update_missing_file_warnings(kbd_val=kbd_val, pal_val=pal_val)

        # Other flags list
        other = [t for t in tokens if not (t.startswith("--kbdhackfile=") or t.startswith("--gfx-palette="))]
        other = [_normalize_other_flag_token(t) for t in other]
        self._list_flags.clear()
        for t in other:
            if not str(t).strip():
                continue
            item = QListWidgetItem(t)
            item.setData(Qt.ItemDataRole.UserRole, t)
            self._list_flags.addItem(item)

        self._lbl_full.setText(extra.strip())
        self._update_flag_buttons()

    def _update_missing_file_warnings(self, *, kbd_val: str | None, pal_val: str | None) -> None:
        # If JSON references a file that does not exist locally, show a red warning.
        self._lbl_kbd_missing.setVisible(False)
        self._lbl_palette_missing.setVisible(False)

        if kbd_val is not None:
            local = _device_to_local_path(root=self._root, device_path=kbd_val, media_prefix=self._media_prefix)
            if local is None or not local.exists():
                expected = str(local) if local is not None else "(unable to map to local path)"
                self._lbl_kbd_missing.setText(
                    "Warning: referenced keyboard file does not exist.\n"
                    f"jzintv_extra: {kbd_val}\n"
                    f"Resolved local path: {expected}"
                )
                self._lbl_kbd_missing.setVisible(True)

        if pal_val is not None:
            local = _device_to_local_path(root=self._root, device_path=pal_val, media_prefix=self._media_prefix)
            if local is None or not local.exists():
                expected = str(local) if local is not None else "(unable to map to local path)"
                self._lbl_palette_missing.setText(
                    "Warning: referenced palette file does not exist.\n"
                    f"jzintv_extra: {pal_val}\n"
                    f"Resolved local path: {expected}"
                )
                self._lbl_palette_missing.setVisible(True)

    def _update_flag_buttons(self) -> None:
        has_sel = self._list_flags.currentRow() >= 0
        self._btn_edit_flag.setEnabled(has_sel)
        self._btn_remove_flag.setEnabled(has_sel)

    def _set_combo_from_flag(self, combo: QComboBox, value: str | None) -> None:
        # index 0: disabled blank, index 1: Default
        if value is None:
            combo.setCurrentIndex(1)
            return

        local = _device_to_local_path(root=self._root, device_path=value, media_prefix=self._media_prefix)
        if local is None:
            combo.setCurrentIndex(0)
            return

        # Find matching option.
        for i in range(combo.count()):
            p = combo.itemData(i)
            if isinstance(p, Path) and p.resolve() == local.resolve():
                combo.setCurrentIndex(i)
                return

        combo.setCurrentIndex(0)

    def _write(self) -> None:
        if not isinstance(self._data, dict):
            self._data = {}
        _write_json_dict(self._json_path, self._data)
        if self._on_written is not None:
            try:
                self._on_written()
            except Exception:
                pass

    # --- save_highscores ---
    def _add_save_highscores(self) -> None:
        if not isinstance(self._data, dict):
            self._data = {}
        self._data["save_highscores"] = True
        self._write()
        self._sync_from_json()

    def _remove_save_highscores(self) -> None:
        if not isinstance(self._data, dict) or ("save_highscores" not in self._data):
            return
        r = QMessageBox.question(
            self,
            "Remove setting?",
            "Remove save_highscores from this JSON?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        try:
            del self._data["save_highscores"]
        except Exception:
            pass
        self._write()
        self._sync_from_json()

    def _save_highscores_toggled(self) -> None:
        if not isinstance(self._data, dict) or ("save_highscores" not in self._data):
            return
        self._data["save_highscores"] = bool(self._chk_save.isChecked())
        self._write()
        self._sync_from_json()

    # --- jzintv_extra ---
    def _current_tokens(self) -> list[str]:
        if not isinstance(self._data, dict):
            return []
        extra_val = self._data.get("jzintv_extra")
        extra = str(extra_val) if extra_val is not None else ""
        tokens = _split_flags(extra)
        # Normalize: strip specialized flags we'll rebuild from UI
        tokens = _remove_equals_flag(tokens, "--kbdhackfile=")
        tokens = _remove_equals_flag(tokens, "--gfx-palette=")
        # Ensure other flags remain single shell tokens even if shlex stripped quotes.
        return [_normalize_other_flag_token(t) for t in tokens]

    def _rebuild_extra_and_write(self, *, kbd: Path | None, palette: Path | None, other_flags: list[str]) -> None:
        tokens: list[str] = []
        tokens.extend(other_flags)

        self._warn_if_not_under_root(kbd, label="Keyboard Hack File")
        self._warn_if_not_under_root(palette, label="Color Palette")

        if kbd is not None:
            tokens.append(
                f"--kbdhackfile={_local_to_device_path(root=self._root, local_path=kbd, media_prefix=self._media_prefix)}"
            )
        if palette is not None:
            tokens.append(
                f"--gfx-palette={_local_to_device_path(root=self._root, local_path=palette, media_prefix=self._media_prefix)}"
            )

        extra = " ".join(t for t in tokens if str(t).strip() != "").strip()

        if not isinstance(self._data, dict):
            self._data = {}

        if extra == "":
            # Keep jzintv_extra out of JSON unless it actually has content.
            if "jzintv_extra" in self._data:
                del self._data["jzintv_extra"]
        else:
            self._data["jzintv_extra"] = extra

        self._write()
        self._sync_from_json()

    def _warn_if_not_under_root(self, path: Path | None, *, label: str) -> None:
        if path is None:
            return
        try:
            _ = path.relative_to(self._root)
            return
        except Exception:
            pass

        msg = (
            f"{label} was selected from a location outside the games root folder.\n\n"
            f"Selected file:\n{path}\n\n"
            f"Games root:\n{self._root}\n\n"
            "Because it is outside the root, the jzintv_extra path will only use the filename\n"
            "(no subfolder), which may not round-trip when reopening this dialog."
        )
        QMessageBox.information(self, "Advanced Settings", msg)

    def _kbd_changed(self) -> None:
        idx = self._cmb_kbd.currentIndex()
        if idx < 0:
            return
        chosen = self._cmb_kbd.itemData(idx)
        # blank (0): do not change
        if idx == 0:
            return
        # Default (1): remove
        kbd_path = None
        if isinstance(chosen, Path):
            kbd_path = chosen

        pal_path = self._selected_path_or_none(self._cmb_palette)
        other = self._other_flags_from_ui()
        self._rebuild_extra_and_write(kbd=kbd_path, palette=pal_path, other_flags=other)

    def _palette_changed(self) -> None:
        idx = self._cmb_palette.currentIndex()
        if idx < 0:
            return
        if idx == 0:
            return

        pal_path = None
        chosen = self._cmb_palette.itemData(idx)
        if isinstance(chosen, Path):
            pal_path = chosen

        kbd_path = self._selected_path_or_none(self._cmb_kbd)
        other = self._other_flags_from_ui()
        self._rebuild_extra_and_write(kbd=kbd_path, palette=pal_path, other_flags=other)

    def _selected_path_or_none(self, combo: QComboBox) -> Path | None:
        idx = combo.currentIndex()
        if idx < 0:
            return None
        if idx in (0, 1):
            return None
        val = combo.itemData(idx)
        return val if isinstance(val, Path) else None

    def _other_flags_from_ui(self) -> list[str]:
        flags: list[str] = []
        for i in range(self._list_flags.count()):
            it = self._list_flags.item(i)
            t = it.data(Qt.ItemDataRole.UserRole)
            if isinstance(t, str) and t.strip() != "":
                flags.append(t)
        return flags

    def _add_flag(self) -> None:
        text, ok = QInputDialog.getText(self, "Add Flag", "Enter flag:")
        if not ok:
            return
        flag = (text or "").strip()
        if flag == "":
            return
        # If the user's entry already parses as a single shell token (e.g.
        # --cheat='force 0x00B5 0x00'), accept it as-is.
        if any(ch.isspace() for ch in flag) and not _is_single_shell_token(flag):
            flag = shlex.quote(flag)

        self._list_flags.addItem(QListWidgetItem(flag))
        self._list_flags.item(self._list_flags.count() - 1).setData(Qt.ItemDataRole.UserRole, flag)

        kbd = self._selected_path_or_none(self._cmb_kbd)
        pal = self._selected_path_or_none(self._cmb_palette)
        self._rebuild_extra_and_write(kbd=kbd, palette=pal, other_flags=self._other_flags_from_ui())

    def _edit_flag(self) -> None:
        row = self._list_flags.currentRow()
        if row < 0:
            return
        it = self._list_flags.item(row)
        cur = str(it.text())
        text, ok = QInputDialog.getText(self, "Edit Flag", "Edit flag:", text=cur)
        if not ok:
            return
        new = (text or "").strip()
        if new == "":
            return
        if any(ch.isspace() for ch in new) and not _is_single_shell_token(new):
            new = shlex.quote(new)

        it.setText(new)
        it.setData(Qt.ItemDataRole.UserRole, new)

        kbd = self._selected_path_or_none(self._cmb_kbd)
        pal = self._selected_path_or_none(self._cmb_palette)
        self._rebuild_extra_and_write(kbd=kbd, palette=pal, other_flags=self._other_flags_from_ui())

    def _remove_flag(self) -> None:
        row = self._list_flags.currentRow()
        if row < 0:
            return
        it = self._list_flags.item(row)
        flag = str(it.text())
        r = QMessageBox.question(
            self,
            "Remove flag?",
            f"Remove this flag?\n\n{flag}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return

        self._list_flags.takeItem(row)

        kbd = self._selected_path_or_none(self._cmb_kbd)
        pal = self._selected_path_or_none(self._cmb_palette)
        self._rebuild_extra_and_write(kbd=kbd, palette=pal, other_flags=self._other_flags_from_ui())
