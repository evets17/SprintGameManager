"""Theme management for Sprint Game Manager."""

from __future__ import annotations

THEMES = ["system", "dark", "light", "nord", "dracula", "gruvbox"]

DARK_STYLESHEET = """
QMainWindow, QDialog, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
}

QLabel {
    color: #cdd6f4;
}

QGroupBox {
    border: 1px solid #45475a;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: bold;
    color: #cdd6f4;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 5px;
    color: #89b4fa;
}

QPushButton {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 3px 8px;
    color: #cdd6f4;
    min-height: 16px;
}

QPushButton:hover {
    background-color: #45475a;
    border-color: #89b4fa;
}

QPushButton:pressed {
    background-color: #585b70;
}

QPushButton:disabled {
    background-color: #1e1e2e;
    color: #6c7086;
    border-color: #313244;
}

QToolButton {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px;
    color: #cdd6f4;
}

QToolButton:hover {
    background-color: #45475a;
    border-color: #89b4fa;
}

QToolButton:pressed {
    background-color: #585b70;
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
    color: #cdd6f4;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {
    border-color: #89b4fa;
}

QComboBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
    color: #cdd6f4;
    min-height: 20px;
}

QComboBox:hover {
    border-color: #89b4fa;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #cdd6f4;
    margin-right: 6px;
}

QComboBox QAbstractItemView {
    background-color: #313244;
    border: 1px solid #45475a;
    selection-background-color: #45475a;
    selection-color: #cdd6f4;
    color: #cdd6f4;
}

QListWidget, QTreeWidget, QTableWidget {
    background-color: #1e1e2e;
    border: 1px solid #45475a;
    border-radius: 4px;
    color: #cdd6f4;
    outline: none;
}

QListWidget::item, QTreeWidget::item {
    padding: 4px 2px;
    border-radius: 4px;
}

QListWidget::item:selected, QTreeWidget::item:selected {
    background-color: #45475a;
    color: #cdd6f4;
}

QListWidget::item:hover, QTreeWidget::item:hover {
    background-color: #313244;
}

QTabWidget::pane {
    border: 1px solid #45475a;
    border-radius: 4px;
    background-color: #1e1e2e;
}

QTabBar::tab {
    background-color: #313244;
    border: 1px solid #45475a;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 6px 16px;
    color: #a6adc8;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #89b4fa;
    border-bottom: 2px solid #89b4fa;
}

QTabBar::tab:hover:!selected {
    background-color: #45475a;
    color: #cdd6f4;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollBar:vertical {
    background-color: #1e1e2e;
    width: 12px;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background-color: #45475a;
    border-radius: 6px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #585b70;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background-color: #1e1e2e;
    height: 12px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal {
    background-color: #45475a;
    border-radius: 6px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #585b70;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

QCheckBox {
    color: #cdd6f4;
    spacing: 6px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #45475a;
    background-color: #313244;
}

QCheckBox::indicator:checked {
    background-color: #89b4fa;
    border-color: #89b4fa;
}

QCheckBox::indicator:hover {
    border-color: #89b4fa;
}

QSplitter::handle {
    background-color: #45475a;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}

QFrame[frameShape="4"], QFrame[frameShape="5"] {
    color: #45475a;
}

QProgressBar {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    text-align: center;
    color: #cdd6f4;
}

QProgressBar::chunk {
    background-color: #89b4fa;
    border-radius: 3px;
}

QToolTip {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
    color: #cdd6f4;
}

QMessageBox, QInputDialog, QFileDialog {
    background-color: #1e1e2e;
}

QHeaderView::section {
    background-color: #313244;
    border: none;
    border-right: 1px solid #45475a;
    border-bottom: 1px solid #45475a;
    padding: 6px;
    color: #cdd6f4;
}

QMenu {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
    color: #cdd6f4;
}

QMenu::item:selected {
    background-color: #45475a;
}

QMenu::separator {
    height: 1px;
    background-color: #45475a;
    margin: 4px 8px;
}
"""


LIGHT_STYLESHEET = """
QMainWindow, QDialog, QWidget {
    background-color: #eff1f5;
    color: #4c4f69;
}

QLabel {
    color: #4c4f69;
}

QGroupBox {
    border: 1px solid #ccd0da;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: bold;
    color: #4c4f69;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 5px;
    color: #1e66f5;
}

QPushButton {
    background-color: #dce0e8;
    border: 1px solid #ccd0da;
    border-radius: 4px;
    padding: 3px 8px;
    color: #4c4f69;
    min-height: 16px;
}

QPushButton:hover {
    background-color: #ccd0da;
    border-color: #1e66f5;
}

QPushButton:pressed {
    background-color: #bcc0cc;
}

QPushButton:disabled {
    background-color: #eff1f5;
    color: #9ca0b0;
    border-color: #dce0e8;
}

QToolButton {
    background-color: #dce0e8;
    border: 1px solid #ccd0da;
    border-radius: 4px;
    padding: 4px;
    color: #4c4f69;
}

QToolButton:hover {
    background-color: #ccd0da;
    border-color: #1e66f5;
}

QToolButton:pressed {
    background-color: #bcc0cc;
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox {
    background-color: #ffffff;
    border: 1px solid #ccd0da;
    border-radius: 4px;
    padding: 4px 8px;
    color: #4c4f69;
    selection-background-color: #1e66f5;
    selection-color: #ffffff;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {
    border-color: #1e66f5;
}

QComboBox {
    background-color: #ffffff;
    border: 1px solid #ccd0da;
    border-radius: 4px;
    padding: 4px 8px;
    color: #4c4f69;
    min-height: 20px;
}

QComboBox:hover {
    border-color: #1e66f5;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #4c4f69;
    margin-right: 6px;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #ccd0da;
    selection-background-color: #dce0e8;
    selection-color: #4c4f69;
    color: #4c4f69;
}

QListWidget, QTreeWidget, QTableWidget {
    background-color: #ffffff;
    border: 1px solid #ccd0da;
    border-radius: 4px;
    color: #4c4f69;
    outline: none;
}

QListWidget::item, QTreeWidget::item {
    padding: 4px 2px;
    border-radius: 4px;
}

QListWidget::item:selected, QTreeWidget::item:selected {
    background-color: #dce0e8;
    color: #4c4f69;
}

QListWidget::item:hover, QTreeWidget::item:hover {
    background-color: #e6e9ef;
}

QTabWidget::pane {
    border: 1px solid #ccd0da;
    border-radius: 4px;
    background-color: #eff1f5;
}

QTabBar::tab {
    background-color: #dce0e8;
    border: 1px solid #ccd0da;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 6px 16px;
    color: #6c6f85;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #eff1f5;
    color: #1e66f5;
    border-bottom: 2px solid #1e66f5;
}

QTabBar::tab:hover:!selected {
    background-color: #ccd0da;
    color: #4c4f69;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollBar:vertical {
    background-color: #eff1f5;
    width: 12px;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background-color: #ccd0da;
    border-radius: 6px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #bcc0cc;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background-color: #eff1f5;
    height: 12px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal {
    background-color: #ccd0da;
    border-radius: 6px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #bcc0cc;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

QCheckBox {
    color: #4c4f69;
    spacing: 6px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #ccd0da;
    background-color: #ffffff;
}

QCheckBox::indicator:checked {
    background-color: #1e66f5;
    border-color: #1e66f5;
}

QCheckBox::indicator:hover {
    border-color: #1e66f5;
}

QSplitter::handle {
    background-color: #ccd0da;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}

QFrame[frameShape="4"], QFrame[frameShape="5"] {
    color: #ccd0da;
}

QProgressBar {
    background-color: #dce0e8;
    border: 1px solid #ccd0da;
    border-radius: 4px;
    text-align: center;
    color: #4c4f69;
}

QProgressBar::chunk {
    background-color: #1e66f5;
    border-radius: 3px;
}

QToolTip {
    background-color: #dce0e8;
    border: 1px solid #ccd0da;
    border-radius: 4px;
    padding: 4px 8px;
    color: #4c4f69;
}

QMessageBox, QInputDialog, QFileDialog {
    background-color: #eff1f5;
}

QHeaderView::section {
    background-color: #dce0e8;
    border: none;
    border-right: 1px solid #ccd0da;
    border-bottom: 1px solid #ccd0da;
    padding: 6px;
    color: #4c4f69;
}

QMenu {
    background-color: #ffffff;
    border: 1px solid #ccd0da;
    border-radius: 4px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
    color: #4c4f69;
}

QMenu::item:selected {
    background-color: #dce0e8;
}

QMenu::separator {
    height: 1px;
    background-color: #ccd0da;
    margin: 4px 8px;
}
"""

# Nord - Arctic, north-bluish color palette
NORD_STYLESHEET = """
QMainWindow, QDialog, QWidget { background-color: #2e3440; color: #eceff4; }
QLabel { color: #eceff4; }
QGroupBox { border: 1px solid #4c566a; border-radius: 6px; margin-top: 12px; padding-top: 8px; font-weight: bold; color: #eceff4; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 10px; padding: 0 5px; color: #88c0d0; }
QPushButton { background-color: #3b4252; border: 1px solid #4c566a; border-radius: 4px; padding: 3px 8px; color: #eceff4; min-height: 16px; }
QPushButton:hover { background-color: #434c5e; border-color: #88c0d0; }
QPushButton:pressed { background-color: #4c566a; }
QPushButton:disabled { background-color: #2e3440; color: #4c566a; border-color: #3b4252; }
QToolButton { background-color: #3b4252; border: 1px solid #4c566a; border-radius: 4px; padding: 4px; color: #eceff4; }
QToolButton:hover { background-color: #434c5e; border-color: #88c0d0; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox { background-color: #3b4252; border: 1px solid #4c566a; border-radius: 4px; padding: 4px 8px; color: #eceff4; selection-background-color: #88c0d0; selection-color: #2e3440; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus { border-color: #88c0d0; }
QComboBox { background-color: #3b4252; border: 1px solid #4c566a; border-radius: 4px; padding: 4px 8px; color: #eceff4; min-height: 20px; }
QComboBox:hover { border-color: #88c0d0; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow { border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 6px solid #eceff4; margin-right: 6px; }
QComboBox QAbstractItemView { background-color: #3b4252; border: 1px solid #4c566a; selection-background-color: #434c5e; color: #eceff4; }
QListWidget, QTreeWidget, QTableWidget { background-color: #2e3440; border: 1px solid #4c566a; border-radius: 4px; color: #eceff4; outline: none; }
QListWidget::item, QTreeWidget::item { padding: 4px 2px; border-radius: 4px; }
QListWidget::item:selected, QTreeWidget::item:selected { background-color: #434c5e; color: #eceff4; }
QListWidget::item:hover, QTreeWidget::item:hover { background-color: #3b4252; }
QTabWidget::pane { border: 1px solid #4c566a; border-radius: 4px; background-color: #2e3440; }
QTabBar::tab { background-color: #3b4252; border: 1px solid #4c566a; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; padding: 6px 16px; color: #d8dee9; margin-right: 2px; }
QTabBar::tab:selected { background-color: #2e3440; color: #88c0d0; border-bottom: 2px solid #88c0d0; }
QTabBar::tab:hover:!selected { background-color: #434c5e; }
QScrollArea { border: none; background-color: transparent; }
QScrollBar:vertical { background-color: #2e3440; width: 12px; border-radius: 6px; }
QScrollBar::handle:vertical { background-color: #4c566a; border-radius: 6px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background-color: #5e81ac; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background-color: #2e3440; height: 12px; border-radius: 6px; }
QScrollBar::handle:horizontal { background-color: #4c566a; border-radius: 6px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background-color: #5e81ac; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QCheckBox { color: #eceff4; spacing: 6px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 1px solid #4c566a; background-color: #3b4252; }
QCheckBox::indicator:checked { background-color: #88c0d0; border-color: #88c0d0; }
QSplitter::handle { background-color: #4c566a; }
QProgressBar { background-color: #3b4252; border: 1px solid #4c566a; border-radius: 4px; text-align: center; color: #eceff4; }
QProgressBar::chunk { background-color: #88c0d0; border-radius: 3px; }
QToolTip { background-color: #3b4252; border: 1px solid #4c566a; border-radius: 4px; padding: 4px 8px; color: #eceff4; }
QMenu { background-color: #3b4252; border: 1px solid #4c566a; border-radius: 4px; padding: 4px; }
QMenu::item { padding: 6px 24px; border-radius: 4px; color: #eceff4; }
QMenu::item:selected { background-color: #434c5e; }
QMenu::separator { height: 1px; background-color: #4c566a; margin: 4px 8px; }
QHeaderView::section { background-color: #3b4252; border: none; border-right: 1px solid #4c566a; border-bottom: 1px solid #4c566a; padding: 6px; color: #eceff4; }
"""

# Dracula - Dark theme with purple/pink accents
DRACULA_STYLESHEET = """
QMainWindow, QDialog, QWidget { background-color: #282a36; color: #f8f8f2; }
QLabel { color: #f8f8f2; }
QGroupBox { border: 1px solid #44475a; border-radius: 6px; margin-top: 12px; padding-top: 8px; font-weight: bold; color: #f8f8f2; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 10px; padding: 0 5px; color: #bd93f9; }
QPushButton { background-color: #44475a; border: 1px solid #6272a4; border-radius: 4px; padding: 3px 8px; color: #f8f8f2; min-height: 16px; }
QPushButton:hover { background-color: #6272a4; border-color: #bd93f9; }
QPushButton:pressed { background-color: #bd93f9; color: #282a36; }
QPushButton:disabled { background-color: #282a36; color: #6272a4; border-color: #44475a; }
QToolButton { background-color: #44475a; border: 1px solid #6272a4; border-radius: 4px; padding: 4px; color: #f8f8f2; }
QToolButton:hover { background-color: #6272a4; border-color: #bd93f9; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox { background-color: #44475a; border: 1px solid #6272a4; border-radius: 4px; padding: 4px 8px; color: #f8f8f2; selection-background-color: #bd93f9; selection-color: #282a36; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus { border-color: #bd93f9; }
QComboBox { background-color: #44475a; border: 1px solid #6272a4; border-radius: 4px; padding: 4px 8px; color: #f8f8f2; min-height: 20px; }
QComboBox:hover { border-color: #bd93f9; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow { border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 6px solid #f8f8f2; margin-right: 6px; }
QComboBox QAbstractItemView { background-color: #44475a; border: 1px solid #6272a4; selection-background-color: #6272a4; color: #f8f8f2; }
QListWidget, QTreeWidget, QTableWidget { background-color: #282a36; border: 1px solid #44475a; border-radius: 4px; color: #f8f8f2; outline: none; }
QListWidget::item, QTreeWidget::item { padding: 4px 2px; border-radius: 4px; }
QListWidget::item:selected, QTreeWidget::item:selected { background-color: #44475a; color: #f8f8f2; }
QListWidget::item:hover, QTreeWidget::item:hover { background-color: #383a46; }
QTabWidget::pane { border: 1px solid #44475a; border-radius: 4px; background-color: #282a36; }
QTabBar::tab { background-color: #44475a; border: 1px solid #6272a4; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; padding: 6px 16px; color: #f8f8f2; margin-right: 2px; }
QTabBar::tab:selected { background-color: #282a36; color: #bd93f9; border-bottom: 2px solid #bd93f9; }
QTabBar::tab:hover:!selected { background-color: #6272a4; }
QScrollArea { border: none; background-color: transparent; }
QScrollBar:vertical { background-color: #282a36; width: 12px; border-radius: 6px; }
QScrollBar::handle:vertical { background-color: #44475a; border-radius: 6px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background-color: #6272a4; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background-color: #282a36; height: 12px; border-radius: 6px; }
QScrollBar::handle:horizontal { background-color: #44475a; border-radius: 6px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background-color: #6272a4; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QCheckBox { color: #f8f8f2; spacing: 6px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 1px solid #6272a4; background-color: #44475a; }
QCheckBox::indicator:checked { background-color: #bd93f9; border-color: #bd93f9; }
QSplitter::handle { background-color: #44475a; }
QProgressBar { background-color: #44475a; border: 1px solid #6272a4; border-radius: 4px; text-align: center; color: #f8f8f2; }
QProgressBar::chunk { background-color: #bd93f9; border-radius: 3px; }
QToolTip { background-color: #44475a; border: 1px solid #6272a4; border-radius: 4px; padding: 4px 8px; color: #f8f8f2; }
QMenu { background-color: #44475a; border: 1px solid #6272a4; border-radius: 4px; padding: 4px; }
QMenu::item { padding: 6px 24px; border-radius: 4px; color: #f8f8f2; }
QMenu::item:selected { background-color: #6272a4; }
QMenu::separator { height: 1px; background-color: #6272a4; margin: 4px 8px; }
QHeaderView::section { background-color: #44475a; border: none; border-right: 1px solid #6272a4; border-bottom: 1px solid #6272a4; padding: 6px; color: #f8f8f2; }
"""

# Gruvbox - Retro groove color scheme
GRUVBOX_STYLESHEET = """
QMainWindow, QDialog, QWidget { background-color: #282828; color: #ebdbb2; }
QLabel { color: #ebdbb2; }
QGroupBox { border: 1px solid #504945; border-radius: 6px; margin-top: 12px; padding-top: 8px; font-weight: bold; color: #ebdbb2; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 10px; padding: 0 5px; color: #fabd2f; }
QPushButton { background-color: #3c3836; border: 1px solid #504945; border-radius: 4px; padding: 3px 8px; color: #ebdbb2; min-height: 16px; }
QPushButton:hover { background-color: #504945; border-color: #fabd2f; }
QPushButton:pressed { background-color: #665c54; }
QPushButton:disabled { background-color: #282828; color: #665c54; border-color: #3c3836; }
QToolButton { background-color: #3c3836; border: 1px solid #504945; border-radius: 4px; padding: 4px; color: #ebdbb2; }
QToolButton:hover { background-color: #504945; border-color: #fabd2f; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox { background-color: #3c3836; border: 1px solid #504945; border-radius: 4px; padding: 4px 8px; color: #ebdbb2; selection-background-color: #fabd2f; selection-color: #282828; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus { border-color: #fabd2f; }
QComboBox { background-color: #3c3836; border: 1px solid #504945; border-radius: 4px; padding: 4px 8px; color: #ebdbb2; min-height: 20px; }
QComboBox:hover { border-color: #fabd2f; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow { border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 6px solid #ebdbb2; margin-right: 6px; }
QComboBox QAbstractItemView { background-color: #3c3836; border: 1px solid #504945; selection-background-color: #504945; color: #ebdbb2; }
QListWidget, QTreeWidget, QTableWidget { background-color: #282828; border: 1px solid #504945; border-radius: 4px; color: #ebdbb2; outline: none; }
QListWidget::item, QTreeWidget::item { padding: 4px 2px; border-radius: 4px; }
QListWidget::item:selected, QTreeWidget::item:selected { background-color: #504945; color: #ebdbb2; }
QListWidget::item:hover, QTreeWidget::item:hover { background-color: #3c3836; }
QTabWidget::pane { border: 1px solid #504945; border-radius: 4px; background-color: #282828; }
QTabBar::tab { background-color: #3c3836; border: 1px solid #504945; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; padding: 6px 16px; color: #a89984; margin-right: 2px; }
QTabBar::tab:selected { background-color: #282828; color: #fabd2f; border-bottom: 2px solid #fabd2f; }
QTabBar::tab:hover:!selected { background-color: #504945; }
QScrollArea { border: none; background-color: transparent; }
QScrollBar:vertical { background-color: #282828; width: 12px; border-radius: 6px; }
QScrollBar::handle:vertical { background-color: #504945; border-radius: 6px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background-color: #665c54; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background-color: #282828; height: 12px; border-radius: 6px; }
QScrollBar::handle:horizontal { background-color: #504945; border-radius: 6px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background-color: #665c54; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QCheckBox { color: #ebdbb2; spacing: 6px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 1px solid #504945; background-color: #3c3836; }
QCheckBox::indicator:checked { background-color: #fabd2f; border-color: #fabd2f; }
QSplitter::handle { background-color: #504945; }
QProgressBar { background-color: #3c3836; border: 1px solid #504945; border-radius: 4px; text-align: center; color: #ebdbb2; }
QProgressBar::chunk { background-color: #fabd2f; border-radius: 3px; }
QToolTip { background-color: #3c3836; border: 1px solid #504945; border-radius: 4px; padding: 4px 8px; color: #ebdbb2; }
QMenu { background-color: #3c3836; border: 1px solid #504945; border-radius: 4px; padding: 4px; }
QMenu::item { padding: 6px 24px; border-radius: 4px; color: #ebdbb2; }
QMenu::item:selected { background-color: #504945; }
QMenu::separator { height: 1px; background-color: #504945; margin: 4px 8px; }
QHeaderView::section { background-color: #3c3836; border: none; border-right: 1px solid #504945; border-bottom: 1px solid #504945; padding: 6px; color: #ebdbb2; }
"""


def get_stylesheet(theme: str) -> str:
    """Return the stylesheet for the given theme name."""
    if theme == "dark":
        return DARK_STYLESHEET
    if theme == "light":
        return LIGHT_STYLESHEET
    if theme == "nord":
        return NORD_STYLESHEET
    if theme == "dracula":
        return DRACULA_STYLESHEET
    if theme == "gruvbox":
        return GRUVBOX_STYLESHEET
    return ""  # "system" uses native styling
