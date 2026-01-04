from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QRect, QEvent
from PySide6.QtGui import QColor, QBrush, QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QStackedWidget,
    QToolButton,
    QToolTip,
    QSizePolicy,
)


_LANGS = ["en", "fr", "es", "de", "it"]

_NOT_DEFINED = "<Not Defined>"
_MISSING_FILE = "<Missing File>"

_MAX_PREVIEW_CHARS = 50


class _SortItem(QTableWidgetItem):
    def __init__(self, display_text: str = "", *, sort_key: object | None = None):
        super().__init__(display_text)
        self._sort_key = display_text if sort_key is None else sort_key

    def set_sort_key(self, sort_key: object) -> None:
        self._sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:  # type: ignore[override]
        if isinstance(other, _SortItem):
            a = self._sort_key
            b = other._sort_key
            try:
                return float(a) < float(b)
            except Exception:
                return str(a) < str(b)
        return super().__lt__(other)


class _ValueButtonDelegate(QStyledItemDelegate):
    def __init__(self, *, table: QTableWidget, on_button_clicked):
        super().__init__(table)
        self._table = table
        self._on_button_clicked = on_button_clicked

    def _button_rect(self, option) -> "QRect":
        r = option.rect
        h = max(14, min(r.height() - 4, 18))
        w = h + 6
        x = r.right() - w - 3
        y = r.top() + (r.height() - h) // 2
        return QRect(x, y, w, h)

    def paint(self, painter, option, index):
        # Paint background/selection via standard style, then draw text with padding and a small "..." button.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        full_text = str(opt.text or "")
        opt.text = ""

        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        btn_r = self._button_rect(option)
        text_r = QRect(opt.rect)
        text_r.adjust(4, 0, -(btn_r.width() + 8), 0)

        painter.save()
        try:
            # Respect palette (including dark mode and selection colors).
            pal = opt.palette
            role = QPalette.ColorRole.HighlightedText if (opt.state & QStyle.StateFlag.State_Selected) else QPalette.ColorRole.Text
            painter.setPen(pal.color(role))
            fm = painter.fontMetrics()
            elided = fm.elidedText(full_text, Qt.TextElideMode.ElideRight, max(10, text_r.width()))
            painter.drawText(text_r, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), elided)
        finally:
            painter.restore()

        # Draw a tiny button at the right side. On macOS, drawing CE_PushButton at
        # very small sizes can become visually imperceptible; draw the button panel
        # explicitly and then draw a centered ellipsis glyph.
        btn_opt = QStyleOptionButton()
        btn_opt.rect = btn_r
        btn_opt.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Raised
        btn_opt.palette = opt.palette
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelButtonCommand, btn_opt, painter, opt.widget)

        painter.save()
        try:
            painter.setPen(opt.palette.color(QPalette.ColorRole.ButtonText))
            painter.drawText(btn_r, int(Qt.AlignmentFlag.AlignCenter), "…")
        finally:
            painter.restore()

    def editorEvent(self, event, model, option, index):
        # Only act on mouse release inside the button.
        if event is not None and event.type() == QEvent.Type.MouseButtonRelease:
            btn_r = self._button_rect(option)
            try:
                pos = event.position().toPoint()
            except Exception:
                pos = event.pos()
            if btn_r.contains(pos):
                self._on_button_clicked(int(index.row()), int(index.column()))
                return True
        return super().editorEvent(event, model, option, index)

    def helpEvent(self, event, view, option, index):  # type: ignore[override]
        # Show a tooltip when hovering the small "..." button.
        try:
            if event is not None and event.type() == QEvent.Type.ToolTip:
                btn_r = self._button_rect(option)
                pos = event.pos()
                if btn_r.contains(pos):
                    col = int(index.column())
                    tip = "Open full value"
                    if col == 3:
                        tip = "Open full value (and edit if allowed)"
                    try:
                        QToolTip.showText(event.globalPos(), tip, view)
                    except Exception:
                        QToolTip.showText(event.globalPosition().toPoint(), tip, view)  # type: ignore[attr-defined]
                    return True
        except Exception:
            pass
        return super().helpEvent(event, view, option, index)


def _elide_text(s: str, *, max_chars: int = _MAX_PREVIEW_CHARS) -> str:
    s = str(s or "")
    if len(s) <= max_chars:
        return s
    if max_chars <= 3:
        return s[:max_chars]
    return s[: max_chars - 3] + "..."


def _elide_text_to_width(text: str, *, font_metrics: QFontMetrics, width_px: int) -> str:
    width_px = int(width_px or 0)
    if width_px <= 0:
        return _elide_text(text)
    # QLineEdit has some internal padding; be conservative.
    width_px = max(10, width_px - 6)
    return str(font_metrics.elidedText(str(text or ""), Qt.TextElideMode.ElideRight, width_px))


class _TextPopupDialog(QDialog):
    def __init__(self, *, parent: QWidget, title: str, text: str, editable: bool):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._editable = bool(editable)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        try:
            layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass

        self._edit = QPlainTextEdit()
        self._edit.setPlainText(str(text or ""))
        self._edit.setReadOnly(not self._editable)
        layout.addWidget(self._edit, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        if self._editable:
            ok = QPushButton("OK")
            ok.clicked.connect(self.accept)
            btns.addWidget(ok)
            cancel = QPushButton("Cancel")
            cancel.clicked.connect(self.reject)
            btns.addWidget(cancel)
        else:
            close = QPushButton("Close")
            close.clicked.connect(self.accept)
            btns.addWidget(close)
        layout.addLayout(btns)

        self.resize(760, 460)

    def text_value(self) -> str:
        return self._edit.toPlainText()


@dataclass
class _FieldSpec:
    label: str
    key_path: str
    field_type: str  # "text" | "number" | "bool" | "other"


_STANDARD_FIELDS: list[_FieldSpec] = [
    _FieldSpec("Players", "nb_players", "text"),
    _FieldSpec("Editor", "editor", "text"),
    _FieldSpec("Year", "year", "number"),
    _FieldSpec("Description (en)", "description/en", "text"),
    _FieldSpec("Description (fr)", "description/fr", "text"),
    _FieldSpec("Description (es)", "description/es", "text"),
    _FieldSpec("Description (de)", "description/de", "text"),
    _FieldSpec("Description (it)", "description/it", "text"),
    _FieldSpec("JZINTV Extra", "jzintv_extra", "text"),
    _FieldSpec("Save High Scores", "save_highscores", "bool"),
    _FieldSpec("Other", "", "other"),
]


@dataclass
class _Row:
    game_id: str
    basename: str
    folder: Path

    json_path: Path

    has_file: bool
    had_key: bool

    current_value_raw: object
    current_value_display: str

    new_value_display: str

    include_enabled: bool
    include_checked: bool

    new_value_editable: bool

    base_action: str
    action: str


def _load_json_dict(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_dict(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _split_key_path(key_path: str) -> list[str]:
    parts = [p for p in str(key_path or "").split("/") if p.strip() != ""]
    return [str(p) for p in parts]


def _get_at_path(data: dict, parts: list[str]) -> tuple[bool, object]:
    if not parts:
        return (False, None)
    cur: object = data
    for i, p in enumerate(parts):
        if not isinstance(cur, dict):
            return (False, None)
        if p not in cur:
            return (False, None)
        cur = cur[p]
        if i == len(parts) - 1:
            return (True, cur)
    return (False, None)


def _ensure_dict_path(data: dict, parts: list[str]) -> dict:
    cur: dict = data
    for p in parts:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    return cur


def _set_at_path(data: dict, parts: list[str], value: object) -> None:
    if not parts:
        return
    if len(parts) == 1:
        data[parts[0]] = value
        return
    parent = _ensure_dict_path(data, parts[:-1])
    parent[parts[-1]] = value


def _del_at_path(data: dict, parts: list[str]) -> bool:
    if not parts:
        return False
    if len(parts) == 1:
        return data.pop(parts[0], None) is not None
    cur: object = data
    for p in parts[:-1]:
        if not isinstance(cur, dict):
            return False
        cur = cur.get(p)
    if not isinstance(cur, dict):
        return False
    return cur.pop(parts[-1], None) is not None


def _desc_for_json(value: str) -> str:
    return " " if (value or "").strip() == "" else str(value)


def _display_value(value: object, *, field_type: str, key_path: str) -> str:
    if value is None:
        return ""
    if field_type == "bool":
        return "true" if bool(value) else "false"
    if field_type == "number":
        try:
            return str(int(value))
        except Exception:
            return str(value)

    # text / other
    s = str(value)
    if key_path.startswith("description/"):
        return "" if s.strip() == "" else s
    return "" if s.strip() == "" else s


def _normalize_for_compare(value: object, *, field_type: str) -> object:
    if field_type == "bool":
        return bool(value)
    if field_type == "number":
        try:
            return int(value)
        except Exception:
            return None
    # text
    if value is None:
        return ""
    return str(value)


class BulkJsonUpdateDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        games: list[tuple[str, Path, str]],
        all_games: list[tuple[str, Path, str]] | None = None,
        json_keys: list[str] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("JSON Bulk Updater")

        self._all_games = list(all_games or games)
        self._json_keys = [str(k).strip() for k in (json_keys or []) if str(k).strip()]

        self._field_spec: _FieldSpec = _STANDARD_FIELDS[0]
        self._key_path: str = ""
        self._field_type: str = "text"  # text|number|bool
        self._update_option: str = "no_change"
        self._rows: list[_Row] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --- Field selection (collapsible) ---
        self._field_root = QWidget()
        field_root_l = QVBoxLayout(self._field_root)
        field_root_l.setContentsMargins(0, 0, 0, 0)
        field_root_l.setSpacing(4)

        self._btn_field_toggle = QToolButton()
        self._btn_field_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._btn_field_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self._btn_field_toggle.setAutoRaise(True)
        self._btn_field_toggle.setStyleSheet(
            "QToolButton { background: transparent; }"
            "QToolButton:checked { background: transparent; }"
            "QToolButton:!checked { background: transparent; }"
        )
        self._btn_field_toggle.setToolTip("Show/hide field + bulk option controls")
        self._btn_field_toggle.setCheckable(True)
        self._btn_field_toggle.setChecked(True)
        self._btn_field_toggle.clicked.connect(self._toggle_field_visibility)
        field_root_l.addWidget(self._btn_field_toggle)

        self._field_content = QGroupBox()
        self._field_content.setFlat(True)
        form_field = QFormLayout(self._field_content)
        form_field.setContentsMargins(10, 0, 10, 10)
        form_field.setSpacing(8)
        try:
            form_field.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        try:
            form_field.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            form_field.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        except Exception:
            pass

        self._cmb_field = QComboBox()
        for spec in _STANDARD_FIELDS:
            self._cmb_field.addItem(spec.label, spec)
        self._cmb_field.currentIndexChanged.connect(self._field_changed)
        form_field.addRow("Field to Update", self._cmb_field)

        self._cmb_key = QComboBox()
        self._cmb_key.setEditable(True)
        self._cmb_key.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for k in self._json_keys:
            self._cmb_key.addItem(k)
        try:
            le = self._cmb_key.lineEdit()
            if le is not None:
                le.setPlaceholderText("e.g. some_key or description/en")
                le.textChanged.connect(self._inputs_changed)
        except Exception:
            pass
        self._cmb_key.currentIndexChanged.connect(self._inputs_changed)
        form_field.addRow("JSON Key Name", self._cmb_key)

        self._cmb_type = QComboBox()
        self._cmb_type.addItem("Text", "text")
        self._cmb_type.addItem("Number", "number")
        self._cmb_type.addItem("True/False", "bool")
        self._cmb_type.currentIndexChanged.connect(self._inputs_changed)
        form_field.addRow("Field Type", self._cmb_type)

        field_root_l.addWidget(self._field_content)
        layout.addWidget(self._field_root)

        # --- Bulk update options (collapses with Field) ---
        self._grp_opt = QGroupBox("Bulk Update Options")
        form_opt = QFormLayout(self._grp_opt)
        form_opt.setContentsMargins(10, 10, 10, 10)
        form_opt.setSpacing(8)
        try:
            form_opt.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        try:
            form_opt.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            form_opt.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        except Exception:
            pass

        self._cmb_update = QComboBox()
        self._cmb_update.addItem("No Change", "no_change")
        self._cmb_update.addItem("Set Value", "set")
        self._cmb_update.addItem("Replace Text", "replace")
        self._cmb_update.addItem("Prefix Text", "prefix")
        self._cmb_update.addItem("Append Text", "append")
        self._cmb_update.addItem("Remove Entry", "remove")
        self._cmb_update.addItem("Regular Expression", "regex")
        self._cmb_update.setToolTip(
            "Select how to compute the proposed New Value for each game.\n"
            "No Change: keep existing value\n"
            "Set Value: force a specific value\n"
            "Replace/Prefix/Append/Regex: text-only transforms\n"
            "Remove Entry: delete the key from JSON"
        )
        self._cmb_update.currentIndexChanged.connect(self._inputs_changed)
        form_opt.addRow("Bulk Update Option", self._cmb_update)

        # Option-specific inputs (stacked to save vertical space)
        self._opt_inputs = QStackedWidget()

        self._opt_none = QWidget()
        self._opt_inputs.addWidget(self._opt_none)

        self._opt_set = QWidget()
        opt_set_form = QFormLayout(self._opt_set)
        opt_set_form.setContentsMargins(0, 0, 0, 0)
        opt_set_form.setSpacing(6)
        try:
            opt_set_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        try:
            opt_set_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            opt_set_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        except Exception:
            pass

        opt_set_value = QWidget()
        opt_set_l = QHBoxLayout(opt_set_value)
        opt_set_l.setContentsMargins(0, 0, 0, 0)
        opt_set_l.setSpacing(6)
        self._value_text = QLineEdit()
        self._value_text.setPlaceholderText("Value to set (text)")
        self._value_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._value_text.setToolTip("Set Value: the exact text to store in the JSON field")
        self._value_text.textChanged.connect(self._inputs_changed)
        self._value_num = QSpinBox()
        self._value_num.setRange(-2147483648, 2147483647)
        self._value_num.setValue(0)
        self._value_num.setToolTip("Set Value: the number to store in the JSON field")
        self._value_num.valueChanged.connect(self._inputs_changed)
        self._value_bool = QCheckBox("true")
        self._value_bool.setChecked(True)
        self._value_bool.setToolTip("Set Value: when checked stores true, otherwise false")
        self._value_bool.toggled.connect(self._inputs_changed)
        opt_set_l.addWidget(self._value_text, 1)
        opt_set_l.addWidget(self._value_num)
        opt_set_l.addWidget(self._value_bool)
        opt_set_form.addRow("Value", opt_set_value)
        self._opt_inputs.addWidget(self._opt_set)

        self._opt_replace = QWidget()
        opt_replace_l = QFormLayout(self._opt_replace)
        opt_replace_l.setContentsMargins(0, 0, 0, 0)
        opt_replace_l.setSpacing(6)
        try:
            opt_replace_l.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        try:
            opt_replace_l.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            opt_replace_l.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        except Exception:
            pass
        self._txt_find = QLineEdit()
        self._txt_find.setPlaceholderText("Text to find")
        self._txt_find.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._txt_find.setToolTip("Replace Text: substring to search for in the current value")
        self._txt_find.textChanged.connect(self._inputs_changed)
        self._txt_replace = QLineEdit()
        self._txt_replace.setPlaceholderText("Replacement text")
        self._txt_replace.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._txt_replace.setToolTip("Replace Text: replacement for each occurrence of the Find text")
        self._txt_replace.textChanged.connect(self._inputs_changed)
        opt_replace_l.addRow("Find", self._txt_find)
        opt_replace_l.addRow("With", self._txt_replace)
        self._opt_inputs.addWidget(self._opt_replace)

        self._opt_prefix = QWidget()
        opt_prefix_l = QFormLayout(self._opt_prefix)
        opt_prefix_l.setContentsMargins(0, 0, 0, 0)
        opt_prefix_l.setSpacing(6)
        try:
            opt_prefix_l.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        try:
            opt_prefix_l.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            opt_prefix_l.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        except Exception:
            pass
        self._txt_prefix = QLineEdit()
        self._txt_prefix.setPlaceholderText("Prefix to add")
        self._txt_prefix.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._txt_prefix.setToolTip(
            "Prefix Text: prepends this text to the current value.\n"
            "Tip: include a trailing space if you want a separator (e.g. 'MyPrefix ').\n"
            "If the current value is blank/<Not Defined>, the prefix is trimmed."
        )
        self._txt_prefix.textChanged.connect(self._inputs_changed)
        opt_prefix_l.addRow("Prefix", self._txt_prefix)
        self._opt_inputs.addWidget(self._opt_prefix)

        self._opt_append = QWidget()
        opt_append_l = QFormLayout(self._opt_append)
        opt_append_l.setContentsMargins(0, 0, 0, 0)
        opt_append_l.setSpacing(6)
        try:
            opt_append_l.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        try:
            opt_append_l.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            opt_append_l.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        except Exception:
            pass
        self._txt_append = QLineEdit()
        self._txt_append.setPlaceholderText("Text to append")
        self._txt_append.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._txt_append.setToolTip(
            "Append Text: appends this text to the current value.\n"
            "Tip: include a leading space if you want a separator (e.g. ' Suffix').\n"
            "If the current value is blank/<Not Defined>, the append text is trimmed."
        )
        self._txt_append.textChanged.connect(self._inputs_changed)
        opt_append_l.addRow("Append", self._txt_append)
        self._opt_inputs.addWidget(self._opt_append)

        self._opt_regex = QWidget()
        opt_regex_l = QFormLayout(self._opt_regex)
        opt_regex_l.setContentsMargins(0, 0, 0, 0)
        opt_regex_l.setSpacing(6)
        try:
            opt_regex_l.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        try:
            opt_regex_l.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            opt_regex_l.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        except Exception:
            pass
        self._txt_regex = QLineEdit()
        self._txt_regex.setPlaceholderText("Regex pattern")
        self._txt_regex.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._txt_regex.setToolTip(
            "Regular Expression: Python-style regex pattern applied to the current value.\n"
            "Example: '^The\\s+' to remove a leading 'The '."
        )
        self._txt_regex.textChanged.connect(self._inputs_changed)
        self._txt_regex_repl = QLineEdit()
        self._txt_regex_repl.setPlaceholderText("Regex replacement")
        self._txt_regex_repl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._txt_regex_repl.setToolTip(
            "Regular Expression: replacement text. You can use capture groups like \\1, \\2, etc.\n"
            "If the current value is missing, it is treated as empty string for regex evaluation."
        )
        self._txt_regex_repl.textChanged.connect(self._inputs_changed)
        opt_regex_l.addRow("Pattern", self._txt_regex)
        opt_regex_l.addRow("Replacement", self._txt_regex_repl)
        self._opt_inputs.addWidget(self._opt_regex)

        self._opt_inputs.setVisible(False)
        form_opt.addRow("Option Inputs", self._opt_inputs)

        field_root_l.addWidget(self._grp_opt)

        # --- Preview / include toggles ---
        row_btns = QHBoxLayout()
        self._btn_check_all = QPushButton("Check All")
        self._btn_check_all.setToolTip("Check Include for all visible, eligible rows")
        self._btn_check_all.clicked.connect(lambda: self._bulk_set_include(True))
        self._btn_check_all.setEnabled(False)
        row_btns.addWidget(self._btn_check_all)

        self._btn_uncheck_all = QPushButton("Uncheck All")
        self._btn_uncheck_all.setToolTip("Uncheck Include for all visible, eligible rows")
        self._btn_uncheck_all.clicked.connect(lambda: self._bulk_set_include(False))
        self._btn_uncheck_all.setEnabled(False)
        row_btns.addWidget(self._btn_uncheck_all)

        row_btns.addStretch(1)
        self._btn_preview = QPushButton("Preview Updates")
        self._btn_preview.setToolTip("Build the preview table using the current field, option, and filters")
        self._btn_preview.clicked.connect(self._preview_clicked)
        self._btn_preview.setEnabled(False)
        row_btns.addWidget(self._btn_preview)
        layout.addLayout(row_btns)

        # --- Filters (collapsible) ---
        self._filter_root = QWidget()
        filter_root_l = QVBoxLayout(self._filter_root)
        filter_root_l.setContentsMargins(0, 0, 0, 0)
        filter_root_l.setSpacing(4)

        self._btn_filter_toggle = QToolButton()
        self._btn_filter_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._btn_filter_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self._btn_filter_toggle.setAutoRaise(True)
        self._btn_filter_toggle.setStyleSheet(
            "QToolButton { background: transparent; }"
            "QToolButton:checked { background: transparent; }"
            "QToolButton:!checked { background: transparent; }"
        )
        self._btn_filter_toggle.setToolTip("Show/hide filter controls")
        self._btn_filter_toggle.setCheckable(True)
        self._btn_filter_toggle.setChecked(True)
        self._btn_filter_toggle.clicked.connect(self._toggle_filter_visibility)
        filter_root_l.addWidget(self._btn_filter_toggle)

        self._filter_content = QGroupBox()
        self._filter_content.setFlat(True)
        form_filter = QFormLayout(self._filter_content)
        form_filter.setContentsMargins(10, 0, 10, 10)
        form_filter.setSpacing(8)
        try:
            form_filter.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            form_filter.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        except Exception:
            pass

        self._cmb_filter_game_op = QComboBox()
        for label, code in (
            ("Equals", "eq"),
            ("Not Equals", "neq"),
            ("Contains", "contains"),
            ("Does Not Contain", "ncontains"),
        ):
            self._cmb_filter_game_op.addItem(label, code)
        self._cmb_filter_game_op.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        idx_contains = self._cmb_filter_game_op.findData("contains")
        if idx_contains >= 0:
            self._cmb_filter_game_op.setCurrentIndex(idx_contains)
        self._txt_filter_game = QLineEdit()
        self._txt_filter_game.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._txt_filter_game.textChanged.connect(self._apply_filters)
        self._cmb_filter_game_op.currentIndexChanged.connect(self._apply_filters)
        w_game_filter = QWidget()
        w_game_filter_l = QHBoxLayout(w_game_filter)
        w_game_filter_l.setContentsMargins(0, 0, 0, 0)
        w_game_filter_l.setSpacing(6)
        w_game_filter_l.addWidget(self._cmb_filter_game_op)
        w_game_filter_l.addWidget(self._txt_filter_game, 1)

        self._btn_clear_filters = QToolButton()
        self._btn_clear_filters.setAutoRaise(True)
        self._btn_clear_filters.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._btn_clear_filters.setText("✕")
        self._btn_clear_filters.setFixedWidth(24)
        self._btn_clear_filters.setStyleSheet("QToolButton { color: rgb(200, 0, 0); font-weight: 700; }")
        self._btn_clear_filters.setToolTip("Clear all filters (resets operators to Contains)")
        self._btn_clear_filters.clicked.connect(self._clear_filters)
        w_game_filter_l.addWidget(self._btn_clear_filters)
        form_filter.addRow("Name/Path", w_game_filter)

        self._cmb_filter_cur_op = QComboBox()
        for label, code in (
            ("Equals", "eq"),
            ("Not Equals", "neq"),
            ("Contains", "contains"),
            ("Does Not Contain", "ncontains"),
            ("Is Empty", "empty"),
            ("Is Not Empty", "nempty"),
            (_NOT_DEFINED, "not_defined"),
            (_MISSING_FILE, "missing_file"),
        ):
            self._cmb_filter_cur_op.addItem(label, code)
        self._cmb_filter_cur_op.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        idx_contains = self._cmb_filter_cur_op.findData("contains")
        if idx_contains >= 0:
            self._cmb_filter_cur_op.setCurrentIndex(idx_contains)
        self._txt_filter_cur = QLineEdit()
        self._txt_filter_cur.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._txt_filter_cur.textChanged.connect(self._apply_filters)
        self._cmb_filter_cur_op.currentIndexChanged.connect(self._apply_filters)
        w_cur_filter = QWidget()
        w_cur_filter_l = QHBoxLayout(w_cur_filter)
        w_cur_filter_l.setContentsMargins(0, 0, 0, 0)
        w_cur_filter_l.setSpacing(6)
        w_cur_filter_l.addWidget(self._cmb_filter_cur_op)
        w_cur_filter_l.addWidget(self._txt_filter_cur, 1)
        form_filter.addRow("Current Value", w_cur_filter)

        filter_root_l.addWidget(self._filter_content)
        layout.addWidget(self._filter_root)

        # --- Preview table ---
        self._tbl = QTableWidget(0, 5)
        self._tbl.setHorizontalHeaderLabels(["Include", "Game", "Current Value", "New Value", "Action"])
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setAlternatingRowColors(True)
        self._tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._tbl.setWordWrap(False)
        try:
            self._tbl.setTextElideMode(Qt.TextElideMode.ElideRight)
        except Exception:
            pass
        self._tbl.setSortingEnabled(True)
        # Inline editing for New Value (text) uses itemChanged.
        self._tbl.itemChanged.connect(self._table_item_changed)
        self._tbl.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )

        # Replace single-click popups with a small in-cell button.
        self._tbl.setItemDelegateForColumn(2, _ValueButtonDelegate(table=self._tbl, on_button_clicked=self._value_button_clicked))
        self._tbl.setItemDelegateForColumn(3, _ValueButtonDelegate(table=self._tbl, on_button_clicked=self._value_button_clicked))
        layout.addWidget(self._tbl, 1)

        bottom = QHBoxLayout()
        self._lbl_row_count = QLabel("Rows: 0")
        bottom.addWidget(self._lbl_row_count)
        bottom.addStretch(1)

        self._lbl_apply_count = QLabel("Will update: 0")
        bottom.addWidget(self._lbl_apply_count)

        self._btn_apply = QPushButton("Perform Updates")
        self._btn_apply.setToolTip("Write included rows to their JSON files")
        self._btn_apply.clicked.connect(self._perform_updates)
        self._btn_apply.setEnabled(False)
        bottom.addWidget(self._btn_apply)
        btn_close = QPushButton("Close")
        btn_close.setToolTip("Close this dialog")
        btn_close.clicked.connect(self.accept)
        bottom.addWidget(btn_close)
        layout.addLayout(bottom)

        self._field_changed()
        self._update_field_header()
        self._update_filter_header()
        self.resize(980, 720)

    # ---------- helpers ----------

    def _game_text(self, row: _Row) -> str:
        return f"{row.basename}  —  {row.folder}"

    def _game_id_for_view_row(self, view_row: int) -> str | None:
        if view_row < 0 or view_row >= self._tbl.rowCount():
            return None
        it = self._tbl.item(view_row, 0)
        if it is None:
            return None
        v = it.data(Qt.ItemDataRole.UserRole)
        return None if v is None else str(v)

    def _model_row_index_for_game_id(self, game_id: str) -> int | None:
        for i, row in enumerate(self._rows or []):
            if row.game_id == game_id:
                return i
        return None

    def _view_row_for_game_id(self, game_id: str) -> int | None:
        for r in range(self._tbl.rowCount()):
            if self._game_id_for_view_row(r) == game_id:
                return r
        return None

    def _update_apply_enabled(self) -> None:
        enabled = False
        will_update = 0
        visible_rows = 0
        for view_row in range(self._tbl.rowCount()):
            if self._tbl.isRowHidden(view_row):
                continue
            visible_rows += 1
            w = self._tbl.cellWidget(view_row, 0)
            if isinstance(w, QCheckBox) and w.isEnabled() and w.isChecked():
                enabled = True
                will_update += 1
        self._btn_apply.setEnabled(bool(enabled))
        try:
            self._lbl_apply_count.setText(f"Will update: {int(will_update)}")
            self._lbl_row_count.setText(f"Rows: {int(visible_rows)}")
        except Exception:
            pass

    def _apply_row_background(self, view_row: int, action: str) -> None:
        # Grey = No Change, Green = Adding, Orange = Updating
        grey = QBrush(QColor(222, 222, 222))
        green = QBrush(QColor(198, 240, 198))
        orange = QBrush(QColor(245, 218, 176))
        black = QBrush(QColor(0, 0, 0))

        if action in {"No Change", "Missing File", "Skipped"}:
            brush = grey
        elif action in {"Set Value"}:
            brush = green
        else:
            brush = orange

        for col in range(self._tbl.columnCount()):
            it = self._tbl.item(view_row, col)
            if it is not None:
                it.setBackground(brush)
                it.setForeground(black)

    def _bulk_set_include(self, checked: bool) -> None:
        if not self._rows:
            return

        self._tbl.setSortingEnabled(False)
        try:
            for view_row in range(self._tbl.rowCount()):
                if self._tbl.isRowHidden(view_row):
                    continue
                gid = self._game_id_for_view_row(view_row)
                if gid is None:
                    continue
                model_idx = self._model_row_index_for_game_id(gid)
                if model_idx is None:
                    continue
                row = self._rows[model_idx]
                if not row.has_file or not row.include_enabled:
                    continue

                row.include_checked = bool(checked)
                row.action = row.base_action if row.include_checked else "Skipped"

                w_inc = self._tbl.cellWidget(view_row, 0)
                if isinstance(w_inc, QCheckBox):
                    w_inc.blockSignals(True)
                    try:
                        w_inc.setChecked(bool(row.include_checked))
                    finally:
                        w_inc.blockSignals(False)

                it_act = self._tbl.item(view_row, 4)
                if it_act is not None:
                    it_act.setText(row.action)
                    if isinstance(it_act, _SortItem):
                        it_act.set_sort_key(row.action)

                self._apply_row_background(view_row, row.action)
        finally:
            self._tbl.setSortingEnabled(True)

        self._update_apply_enabled()

    # ---------- inputs ----------

    def _field_changed(self) -> None:
        spec = self._cmb_field.currentData()
        self._field_spec = spec if isinstance(spec, _FieldSpec) else _STANDARD_FIELDS[-1]
        is_other = self._field_spec.field_type == "other"

        if not is_other:
            self._cmb_key.setCurrentText(self._field_spec.key_path)
            self._cmb_key.setEnabled(False)

            self._field_type = self._field_spec.field_type
            idx = self._cmb_type.findData(self._field_type)
            if idx >= 0:
                self._cmb_type.setCurrentIndex(idx)
            self._cmb_type.setEnabled(False)
        else:
            self._cmb_key.setEnabled(True)
            self._cmb_key.setCurrentText("")
            self._cmb_type.setEnabled(True)

        self._inputs_changed()
        self._update_field_header()

    def _inputs_changed(self, *args) -> None:
        self._key_path = (self._cmb_key.currentText() or "").strip()
        self._field_type = str(self._cmb_type.currentData() or "text")
        self._update_option = str(self._cmb_update.currentData() or "no_change")

        # Standard year constraints
        if self._key_path == "year" and self._field_type == "number":
            self._value_num.setRange(0, 9999)
        else:
            self._value_num.setRange(-2147483648, 2147483647)

        # Field-type dependent controls
        is_text = self._field_type == "text"
        self._value_text.setVisible(self._field_type == "text")
        self._value_num.setVisible(self._field_type == "number")
        self._value_bool.setVisible(self._field_type == "bool")

        # Option input panel
        show_inputs = False
        if self._update_option == "set":
            self._opt_inputs.setCurrentWidget(self._opt_set)
            show_inputs = True
        elif self._update_option == "replace" and is_text:
            self._opt_inputs.setCurrentWidget(self._opt_replace)
            show_inputs = True
        elif self._update_option == "prefix" and is_text:
            self._opt_inputs.setCurrentWidget(self._opt_prefix)
            show_inputs = True
        elif self._update_option == "append" and is_text:
            self._opt_inputs.setCurrentWidget(self._opt_append)
            show_inputs = True
        elif self._update_option == "regex" and is_text:
            self._opt_inputs.setCurrentWidget(self._opt_regex)
            show_inputs = True
        else:
            self._opt_inputs.setCurrentWidget(self._opt_none)
            show_inputs = False
        self._opt_inputs.setVisible(bool(show_inputs))

        # Disable text-only options for non-text fields.
        for code in ("replace", "prefix", "append", "regex"):
            idx = self._cmb_update.findData(code)
            if idx >= 0:
                self._cmb_update.model().item(idx).setEnabled(bool(is_text))
        if self._update_option in {"replace", "prefix", "append", "regex"} and not is_text:
            self._cmb_update.setCurrentIndex(self._cmb_update.findData("no_change"))
            self._update_option = "no_change"

        # Preview enabled only when key is valid, and regex has a pattern if selected.
        ok = bool(self._key_path)
        if self._update_option == "regex":
            ok = ok and bool((self._txt_regex.text() or "").strip())
        self._btn_preview.setEnabled(bool(ok))

        # If filters are visible, keep title updated as user types.
        self._update_field_header()
        self._update_filter_header()

    def _toggle_field_visibility(self, checked: bool) -> None:
        is_open = bool(checked)
        self._field_content.setVisible(is_open)
        try:
            self._grp_opt.setVisible(is_open)
        except Exception:
            pass
        self._btn_field_toggle.setArrowType(Qt.ArrowType.DownArrow if is_open else Qt.ArrowType.RightArrow)

    def _update_field_header(self) -> None:
        spec = self._field_spec
        is_other = bool(spec.field_type == "other")
        field_label = str(spec.label or "")
        key = (self._key_path or "").strip()
        type_label = str(self._cmb_type.currentText() or "Text")

        opt_label = str(self._cmb_update.currentText() or "").strip()

        if not is_other:
            # Standard field: label is enough.
            title = f"Field ({field_label})"
        else:
            key_part = key if key else "<enter key>"
            title = f"Field (Other: {key_part} [{type_label}])"

        if opt_label:
            title += f" — Option ({opt_label})"

        self._btn_field_toggle.setText(title)

    # ---------- preview logic ----------

    def _proposed_new_text(self, *, cur: str, key_present: bool) -> str:
        cur_s = str(cur or "")
        if self._update_option == "no_change":
            return cur_s if key_present else _NOT_DEFINED
        if self._update_option == "remove":
            return _NOT_DEFINED
        if self._update_option == "set":
            return str(self._value_text.text() or "")
        if self._update_option == "replace":
            return cur_s.replace(str(self._txt_find.text() or ""), str(self._txt_replace.text() or ""))
        if self._update_option == "prefix":
            p = str(self._txt_prefix.text() or "")
            if cur_s.strip() == "":
                return p.strip()
            return p + cur_s
        if self._update_option == "append":
            a = str(self._txt_append.text() or "")
            if cur_s.strip() == "":
                return a.strip()
            return cur_s + a
        if self._update_option == "regex":
            pattern = str(self._txt_regex.text() or "")
            repl = str(self._txt_regex_repl.text() or "")
            try:
                return re.sub(pattern, repl, cur_s)
            except Exception:
                return repl
        return cur_s

    def _proposed_new_display(self, *, cur_raw: object, key_present: bool) -> str:
        if self._field_type == "number":
            if self._update_option == "remove":
                return _NOT_DEFINED
            if self._update_option == "no_change":
                return _display_value(cur_raw, field_type="number", key_path=self._key_path) if key_present else _NOT_DEFINED
            return str(int(self._value_num.value()))

        if self._field_type == "bool":
            if self._update_option == "remove":
                return _NOT_DEFINED
            if self._update_option == "no_change":
                return _display_value(cur_raw, field_type="bool", key_path=self._key_path) if key_present else _NOT_DEFINED
            return "true" if self._value_bool.isChecked() else "false"

        # text
        cur_s = "" if (not key_present or cur_raw is None) else str(cur_raw)
        proposed = self._proposed_new_text(cur=cur_s, key_present=key_present)

        # For missing key, blank new value should remain Not Defined.
        if not key_present and str(proposed).strip() == "":
            return _NOT_DEFINED
        return str(proposed)

    def _evaluate_row(self, *, game_id: str, folder: Path, basename: str, json_path: Path, has_file: bool, had_key: bool, cur_raw: object, cur_disp: str, new_disp: str) -> _Row:
        if not has_file:
            return _Row(
                game_id=game_id,
                basename=basename,
                folder=folder,
                json_path=json_path,
                has_file=False,
                had_key=False,
                current_value_raw=None,
                current_value_display=_MISSING_FILE,
                new_value_display="",
                include_enabled=False,
                include_checked=False,
                new_value_editable=False,
                base_action="Missing File",
                action="Missing File",
            )

        # Compare normalized values.
        if self._field_type == "number":
            cur_norm = None if not had_key else _normalize_for_compare(cur_raw, field_type="number")
            try:
                new_norm = None if new_disp == _NOT_DEFINED else int(str(new_disp).strip() or "0")
            except Exception:
                new_norm = 0
        elif self._field_type == "bool":
            cur_norm = None if not had_key else _normalize_for_compare(cur_raw, field_type="bool")
            new_norm = None if new_disp == _NOT_DEFINED else str(new_disp).strip().lower() in {"1", "true", "yes", "on"}
        else:
            cur_norm = None if not had_key else str(cur_raw or "")
            new_norm = None if new_disp == _NOT_DEFINED else str(new_disp)

        same = (cur_norm is None and new_norm is None) or (cur_norm is not None and new_norm is not None and cur_norm == new_norm)

        # Situation 2: New == Current
        if same:
            return _Row(
                game_id=game_id,
                basename=basename,
                folder=folder,
                json_path=json_path,
                has_file=True,
                had_key=had_key,
                current_value_raw=cur_raw,
                current_value_display=cur_disp,
                new_value_display=new_disp,
                include_enabled=False,
                include_checked=False,
                new_value_editable=True,
                base_action="No Change",
                action="No Change",
            )

        # Situation 3: Not Defined -> non-blank
        if not had_key and str(new_disp).strip() != "" and new_disp != _NOT_DEFINED:
            return _Row(
                game_id=game_id,
                basename=basename,
                folder=folder,
                json_path=json_path,
                has_file=True,
                had_key=False,
                current_value_raw=cur_raw,
                current_value_display=cur_disp,
                new_value_display=new_disp,
                include_enabled=True,
                include_checked=True,
                new_value_editable=True,
                base_action="Set Value",
                action="Set Value",
            )

        # Situation 4: Change Value
        return _Row(
            game_id=game_id,
            basename=basename,
            folder=folder,
            json_path=json_path,
            has_file=True,
            had_key=had_key,
            current_value_raw=cur_raw,
            current_value_display=cur_disp,
            new_value_display=new_disp,
            include_enabled=True,
            include_checked=True,
            new_value_editable=True,
            base_action="Change Value",
            action="Change Value",
        )

    def _preview_clicked(self) -> None:
        try:
            parts = _split_key_path(self._key_path)
            if not parts:
                return

            rows: list[_Row] = []
            for game_id, folder, basename in (self._all_games or []):
                json_path = Path(folder) / f"{basename}.json"
                has_file = bool(json_path.exists())
                data = _load_json_dict(json_path) if has_file else {}
                had_key, cur_raw = _get_at_path(data, parts) if has_file else (False, None)

                if not has_file:
                    cur_disp = _MISSING_FILE
                else:
                    cur_disp = _display_value(cur_raw, field_type=self._field_type, key_path=self._key_path) if had_key else _NOT_DEFINED

                new_disp = "" if not has_file else self._proposed_new_display(cur_raw=cur_raw, key_present=had_key)

                row = self._evaluate_row(
                    game_id=str(game_id),
                    folder=Path(folder),
                    basename=str(basename),
                    json_path=json_path,
                    has_file=has_file,
                    had_key=had_key,
                    cur_raw=cur_raw,
                    cur_disp=cur_disp,
                    new_disp=new_disp,
                )
                rows.append(row)

            self._rows = rows
            self._rebuild_table()
            self._btn_check_all.setEnabled(True)
            self._btn_uncheck_all.setEnabled(True)
            self._apply_filters()
            self._update_apply_enabled()
        except Exception as e:
            QMessageBox.warning(self, "JSON Bulk Updater", str(e))

    # ---------- table + interactions ----------

    def _rebuild_table(self) -> None:
        was_sorting = self._tbl.isSortingEnabled()
        self._tbl.setSortingEnabled(False)
        self._tbl.blockSignals(True)
        try:
            for rr in range(self._tbl.rowCount()):
                for cc in range(self._tbl.columnCount()):
                    if self._tbl.cellWidget(rr, cc) is not None:
                        self._tbl.removeCellWidget(rr, cc)

            self._tbl.clearContents()
            self._tbl.setRowCount(0)
            self._tbl.setRowCount(len(self._rows))

            for r, row in enumerate(self._rows):
                # Include
                include_chk = QCheckBox()
                include_chk.setChecked(bool(row.include_checked))
                include_chk.setEnabled(bool(row.include_enabled))
                include_chk.toggled.connect(lambda checked, gid=row.game_id: self._include_toggled(gid, checked))
                self._tbl.setCellWidget(r, 0, include_chk)

                it_inc = _SortItem("", sort_key=1 if row.include_checked else 0)
                it_inc.setData(Qt.ItemDataRole.UserRole, row.game_id)
                it_inc.setFlags(it_inc.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._tbl.setItem(r, 0, it_inc)

                # Game
                game_text = self._game_text(row)
                it_game = _SortItem(game_text, sort_key=game_text.casefold())
                it_game.setToolTip(game_text)
                it_game.setFlags(it_game.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._tbl.setItem(r, 1, it_game)

                # Current Value
                if not row.has_file:
                    link = QLabel('<a style="text-decoration: underline; color: #1a73e8;" href="create">Create JSON</a>')
                    link.setTextFormat(Qt.TextFormat.RichText)
                    link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
                    link.setOpenExternalLinks(False)
                    link.linkActivated.connect(lambda _href, gid=row.game_id: self._create_json_clicked(gid))
                    self._tbl.setCellWidget(r, 2, link)
                    it_cur = _SortItem("", sort_key=_MISSING_FILE)
                    it_cur.setFlags(it_cur.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._tbl.setItem(r, 2, it_cur)
                else:
                    cur_text = str(row.current_value_display or "")
                    it_cur = _SortItem(cur_text, sort_key=cur_text.casefold())
                    it_cur.setToolTip(cur_text)
                    it_cur.setFlags(it_cur.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._tbl.setItem(r, 2, it_cur)

                # New Value
                if not row.has_file:
                    it_new = _SortItem("", sort_key="")
                    it_new.setFlags(it_new.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._tbl.setItem(r, 3, it_new)
                elif self._field_type == "number":
                    sb = QSpinBox()
                    if self._key_path == "year":
                        sb.setRange(0, 9999)
                    else:
                        sb.setRange(-2147483648, 2147483647)
                    try:
                        sb.setValue(int(str(row.new_value_display).strip() or "0"))
                    except Exception:
                        sb.setValue(0)
                    sb.valueChanged.connect(lambda _v, gid=row.game_id: self._new_value_widget_changed(gid))
                    self._tbl.setCellWidget(r, 3, sb)
                    it_ph = _SortItem("", sort_key=str(row.new_value_display))
                    it_ph.setFlags(it_ph.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._tbl.setItem(r, 3, it_ph)
                elif self._field_type == "bool":
                    cb = QCheckBox()
                    cb.setChecked(str(row.new_value_display).strip().lower() in {"1", "true", "yes", "on"})
                    cb.toggled.connect(lambda _v, gid=row.game_id: self._new_value_widget_changed(gid))
                    self._tbl.setCellWidget(r, 3, cb)
                    it_ph = _SortItem("", sort_key=str(row.new_value_display))
                    it_ph.setFlags(it_ph.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._tbl.setItem(r, 3, it_ph)
                else:
                    new_text = str(row.new_value_display or "")
                    it_new = _SortItem(new_text, sort_key=new_text.casefold())
                    it_new.setToolTip(new_text)
                    if row.new_value_editable:
                        it_new.setFlags(it_new.flags() | Qt.ItemFlag.ItemIsEditable)
                    else:
                        it_new.setFlags(it_new.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._tbl.setItem(r, 3, it_new)

                # Action
                it_act = _SortItem(row.action, sort_key=row.action)
                it_act.setFlags(it_act.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._tbl.setItem(r, 4, it_act)

                self._apply_row_background(r, row.action)

            self._tbl.resizeColumnsToContents()

            # Cap auto-sized widths to ~40 characters so the table doesn't blow out the dialog.
            fm = QFontMetrics(self._tbl.font())
            max_px = int(fm.horizontalAdvance("M") * 40 + 24)

            def _cap(col: int, *, min_px: int = 0) -> None:
                w = int(self._tbl.columnWidth(col) or 0)
                w = max(w, int(min_px))
                w = min(w, int(max_px)) if max_px > 0 else w
                self._tbl.setColumnWidth(col, w)

            _cap(1, min_px=320)
            _cap(2, min_px=200)
            _cap(3, min_px=200)
            _cap(4, min_px=140)
        finally:
            self._tbl.blockSignals(False)
            self._tbl.setSortingEnabled(bool(was_sorting))

    def _include_toggled(self, game_id: str, checked: bool) -> None:
        model_idx = self._model_row_index_for_game_id(game_id)
        view_row = self._view_row_for_game_id(game_id)
        if model_idx is None or view_row is None:
            return
        row = self._rows[model_idx]
        if not row.include_enabled:
            return
        row.include_checked = bool(checked)
        row.action = row.base_action if row.include_checked else "Skipped"

        it_act = self._tbl.item(view_row, 4)
        if it_act is not None:
            it_act.setText(row.action)
            if isinstance(it_act, _SortItem):
                it_act.set_sort_key(row.action)
        self._apply_row_background(view_row, row.action)
        self._update_apply_enabled()

    def _new_value_widget_changed(self, game_id: str) -> None:
        model_idx = self._model_row_index_for_game_id(game_id)
        view_row = self._view_row_for_game_id(game_id)
        if model_idx is None or view_row is None:
            return
        row = self._rows[model_idx]
        if not row.has_file:
            return

        if self._field_type == "number":
            w = self._tbl.cellWidget(view_row, 3)
            if isinstance(w, QSpinBox):
                row.new_value_display = str(int(w.value()))
        elif self._field_type == "bool":
            w = self._tbl.cellWidget(view_row, 3)
            if isinstance(w, QCheckBox):
                row.new_value_display = "true" if w.isChecked() else "false"

        self._recompute_row_state(game_id)

    def _value_button_clicked(self, view_row: int, col: int) -> None:
        gid = self._game_id_for_view_row(view_row)
        if gid is None:
            return
        model_idx = self._model_row_index_for_game_id(gid)
        if model_idx is None:
            return
        row = self._rows[model_idx]

        if col == 2:
            if not row.has_file:
                return
            dlg = _TextPopupDialog(parent=self, title="Current Value", text=str(row.current_value_display or ""), editable=False)
            dlg.exec()
            return

        if col == 3:
            if not row.has_file:
                return
            editable = bool(self._field_type == "text" and row.new_value_editable)
            dlg = _TextPopupDialog(parent=self, title="New Value", text=str(row.new_value_display or ""), editable=editable)
            result = dlg.exec()
            if editable and result == QDialog.DialogCode.Accepted:
                row.new_value_display = dlg.text_value()
                it = self._tbl.item(view_row, 3)
                if it is not None:
                    self._tbl.blockSignals(True)
                    try:
                        it.setText(str(row.new_value_display or ""))
                        it.setToolTip(str(row.new_value_display or ""))
                        if isinstance(it, _SortItem):
                            it.set_sort_key(str(row.new_value_display or "").casefold())
                    finally:
                        self._tbl.blockSignals(False)
                self._recompute_row_state(gid)
            return

    def _table_item_changed(self, it: QTableWidgetItem) -> None:
        if it is None:
            return
        col = int(it.column())
        if col != 3:
            return
        if self._field_type != "text":
            return

        view_row = int(it.row())
        gid = self._game_id_for_view_row(view_row)
        if gid is None:
            return
        model_idx = self._model_row_index_for_game_id(gid)
        if model_idx is None:
            return
        row = self._rows[model_idx]
        if not row.has_file or not row.new_value_editable:
            return

        row.new_value_display = str(it.text() or "")
        it.setToolTip(str(row.new_value_display or ""))
        if isinstance(it, _SortItem):
            it.set_sort_key(str(row.new_value_display or "").casefold())

        self._recompute_row_state(gid)

    def _recompute_row_state(self, game_id: str) -> None:
        model_idx = self._model_row_index_for_game_id(game_id)
        view_row = self._view_row_for_game_id(game_id)
        if model_idx is None or view_row is None:
            return
        row = self._rows[model_idx]
        if not row.has_file:
            return

        parts = _split_key_path(self._key_path)
        data = _load_json_dict(row.json_path)
        had_key, cur_raw = _get_at_path(data, parts)
        cur_disp = _display_value(cur_raw, field_type=self._field_type, key_path=self._key_path) if had_key else _NOT_DEFINED

        updated = self._evaluate_row(
            game_id=row.game_id,
            folder=row.folder,
            basename=row.basename,
            json_path=row.json_path,
            has_file=True,
            had_key=had_key,
            cur_raw=cur_raw,
            cur_disp=cur_disp,
            new_disp=str(row.new_value_display or ""),
        )

        # Preserve user 'Skipped' if they unchecked.
        if row.include_enabled and not row.include_checked and updated.include_enabled:
            updated.include_checked = False
            updated.action = "Skipped"

        self._rows[model_idx] = updated

        # Update UI.
        self._tbl.blockSignals(True)
        try:
            it_cur = self._tbl.item(view_row, 2)
            if it_cur is not None:
                it_cur.setText(cur_disp)
                it_cur.setToolTip(cur_disp)
                if isinstance(it_cur, _SortItem):
                    it_cur.set_sort_key(str(cur_disp).casefold())

            w_inc = self._tbl.cellWidget(view_row, 0)
            if isinstance(w_inc, QCheckBox):
                w_inc.blockSignals(True)
                try:
                    w_inc.setEnabled(bool(updated.include_enabled))
                    w_inc.setChecked(bool(updated.include_checked))
                finally:
                    w_inc.blockSignals(False)

            it_act = self._tbl.item(view_row, 4)
            if it_act is not None:
                it_act.setText(updated.action)
                if isinstance(it_act, _SortItem):
                    it_act.set_sort_key(updated.action)
        finally:
            self._tbl.blockSignals(False)

        self._apply_row_background(view_row, updated.action)
        self._update_apply_enabled()

    # ---------- filters ----------

    def _matches_text_filter(self, haystack: str, *, op: str, needle: str) -> bool:
        h = str(haystack or "")
        n = str(needle or "")
        hc = h.casefold()
        nc = n.casefold()
        if op == "eq":
            return hc == nc
        if op == "neq":
            return hc != nc
        if op == "contains":
            return nc in hc
        if op == "ncontains":
            return nc not in hc
        return True

    def _apply_filters(self) -> None:
        if not self._rows:
            return

        game_op = str(self._cmb_filter_game_op.currentData() or "contains")
        game_val = str(self._txt_filter_game.text() or "")

        cur_op = str(self._cmb_filter_cur_op.currentData() or "contains")
        cur_val = str(self._txt_filter_cur.text() or "")

        # Disable current value filter text input for non-text ops.
        self._txt_filter_cur.setEnabled(cur_op in {"eq", "neq", "contains", "ncontains"})

        for view_row in range(self._tbl.rowCount()):
            gid = self._game_id_for_view_row(view_row)
            if gid is None:
                continue
            model_idx = self._model_row_index_for_game_id(gid)
            if model_idx is None:
                continue
            row = self._rows[model_idx]
            game_text = self._game_text(row)
            cur_text = str(row.current_value_display or "")

            ok_game = True
            if game_val.strip() != "":
                ok_game = self._matches_text_filter(game_text, op=game_op, needle=game_val)

            ok_cur = True
            if cur_op == "missing_file":
                ok_cur = (cur_text == _MISSING_FILE)
            elif cur_op == "not_defined":
                ok_cur = (cur_text == _NOT_DEFINED)
            elif cur_op == "empty":
                ok_cur = (cur_text.strip() == "")
            elif cur_op == "nempty":
                ok_cur = (cur_text.strip() != "")
            elif cur_val.strip() != "":
                ok_cur = self._matches_text_filter(cur_text, op=cur_op, needle=cur_val)

            self._tbl.setRowHidden(view_row, not (ok_game and ok_cur))

        self._update_apply_enabled()
        self._update_filter_header()

    def _clear_filters(self) -> None:
        # Reset to defaults: both ops = Contains, and clear filter text.
        try:
            self._cmb_filter_game_op.blockSignals(True)
            self._cmb_filter_cur_op.blockSignals(True)
            self._txt_filter_game.blockSignals(True)
            self._txt_filter_cur.blockSignals(True)

            idx = self._cmb_filter_game_op.findData("contains")
            if idx >= 0:
                self._cmb_filter_game_op.setCurrentIndex(idx)
            idx = self._cmb_filter_cur_op.findData("contains")
            if idx >= 0:
                self._cmb_filter_cur_op.setCurrentIndex(idx)

            self._txt_filter_game.setText("")
            self._txt_filter_cur.setText("")
        finally:
            try:
                self._cmb_filter_game_op.blockSignals(False)
                self._cmb_filter_cur_op.blockSignals(False)
                self._txt_filter_game.blockSignals(False)
                self._txt_filter_cur.blockSignals(False)
            except Exception:
                pass

        self._apply_filters()

    def _toggle_filter_visibility(self, checked: bool) -> None:
        is_open = bool(checked)
        self._filter_content.setVisible(is_open)
        self._btn_filter_toggle.setArrowType(Qt.ArrowType.DownArrow if is_open else Qt.ArrowType.RightArrow)

    def _update_filter_header(self) -> None:
        parts: list[str] = []

        game_op = str(self._cmb_filter_game_op.currentData() or "contains")
        game_val = str(self._txt_filter_game.text() or "").strip()
        if game_val:
            op_label = str(self._cmb_filter_game_op.currentText() or "Contains")
            parts.append(f"Name/Path {op_label} '{game_val}'")

        cur_op = str(self._cmb_filter_cur_op.currentData() or "contains")
        cur_val = str(self._txt_filter_cur.text() or "").strip()
        cur_label = str(self._cmb_filter_cur_op.currentText() or "Contains")

        if cur_op in {"missing_file", "not_defined", "empty", "nempty"}:
            parts.append(f"Current Value {cur_label}")
        elif cur_val:
            parts.append(f"Current Value {cur_label} '{cur_val}'")

        title = "Filter (none)" if not parts else "Filter (" + " AND ".join(parts) + ")"
        self._btn_filter_toggle.setText(title)

    # ---------- create + apply ----------

    def _create_json_clicked(self, game_id: str) -> None:
        model_idx = self._model_row_index_for_game_id(game_id)
        view_row = self._view_row_for_game_id(game_id)
        if model_idx is None or view_row is None:
            return
        row = self._rows[model_idx]
        if row.has_file:
            return

        data = {
            "name": row.basename,
            "nb_players": "",
            "editor": "",
            "year": 0,
            "description": {lang: " " for lang in _LANGS},
        }
        try:
            _write_json_dict(row.json_path, data)
        except Exception as e:
            QMessageBox.warning(self, "Create JSON", str(e))
            return

        # Recompute just this row.
        row.has_file = True
        parts = _split_key_path(self._key_path)
        data2 = _load_json_dict(row.json_path)
        had_key, cur_raw = _get_at_path(data2, parts)
        cur_disp = _display_value(cur_raw, field_type=self._field_type, key_path=self._key_path) if had_key else _NOT_DEFINED
        row.current_value_display = cur_disp
        row.current_value_raw = cur_raw

        row.new_value_display = self._proposed_new_display(cur_raw=cur_raw, key_present=had_key)

        updated = self._evaluate_row(
            game_id=row.game_id,
            folder=row.folder,
            basename=row.basename,
            json_path=row.json_path,
            has_file=True,
            had_key=had_key,
            cur_raw=cur_raw,
            cur_disp=cur_disp,
            new_disp=str(row.new_value_display or ""),
        )
        self._rows[model_idx] = updated
        self._rebuild_table()
        self._apply_filters()
        self._update_apply_enabled()

    def _perform_updates(self) -> None:
        parts = _split_key_path(self._key_path)
        if not parts:
            return

        # Apply only to rows that are included AND visible.
        for view_row in range(self._tbl.rowCount()):
            if self._tbl.isRowHidden(view_row):
                continue
            gid = self._game_id_for_view_row(view_row)
            if gid is None:
                continue
            model_idx = self._model_row_index_for_game_id(gid)
            if model_idx is None:
                continue
            row = self._rows[model_idx]
            if not row.has_file:
                continue

            w_inc = self._tbl.cellWidget(view_row, 0)
            if not isinstance(w_inc, QCheckBox) or not w_inc.isEnabled() or not w_inc.isChecked():
                continue

            data = _load_json_dict(row.json_path)

            # Treat <Not Defined> as delete.
            if str(row.new_value_display) == _NOT_DEFINED:
                _del_at_path(data, parts)
            else:
                new_raw: object
                if self._field_type == "number":
                    try:
                        new_raw = int(str(row.new_value_display).strip() or "0")
                    except Exception:
                        new_raw = 0
                elif self._field_type == "bool":
                    new_raw = str(row.new_value_display).strip().lower() in {"1", "true", "yes", "on"}
                else:
                    new_raw = str(row.new_value_display)
                    if self._key_path.startswith("description/"):
                        new_raw = _desc_for_json(str(new_raw))

                _set_at_path(data, parts, new_raw)

            try:
                _write_json_dict(row.json_path, data)
            except Exception as e:
                QMessageBox.warning(self, "JSON Bulk Updater", f"Failed updating {row.json_path}: {e}")
                return

        # Refresh table state after applying.
        self._preview_clicked()
