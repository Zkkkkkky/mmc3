from __future__ import annotations

import importlib
import sys
import threading
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QCloseEvent, QColor, QDragEnterEvent, QDropEvent, QFont,
    QKeySequence, QPainter, QPen, QPolygon,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProxyStyle,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fc_rom_editor_core import RomProject

from .pages import (
    CharacterPage,
    ChangesPage,
    MusicPage,
    OverviewPage,
    PlaceholderPage,
    ProjectPage,
    ResourcePage,
    UnitPage,
    WeaponPage,
)
from .map_page import MapPage
from .event_page import EventPage
from .persuasion_page import PersuasionPage
from .story_page import StoryPage
from .unit_import_page import UnitImportPage
from .workspace import (
    DEFAULT_ROM,
    EXPANDED_ROM,
    LEGACY_ROM,
    ROOT,
    default_export_path as _default_export_path,
    writable_output_path,
)


APP_TITLE = "新DC篇完整修改器"
LEGACY_WINDOW_TITLE = "SRW2扩容版修改器V1.0"
LAUNCHER_TITLE = "SRW2修改器V1.5"
_ACTIVE_EDITOR_WINDOW: MainWindow | None = None
_RUNTIME_WARMUP_THREAD: threading.Thread | None = None
_RUNTIME_WARMUP_ERRORS: list[str] = []


def _warm_runtime_modules() -> None:
    """Load heavyweight dialog modules while the user chooses a ROM.

    PyInstaller's single-file archive makes the first dynamic import much
    slower than the same constructor in a source-process profiler.  These
    modules only define codecs and Qt widget classes; no widgets are created
    off the GUI thread.  If the user opens a tool before warm-up finishes,
    Python's import lock safely waits for the same import instead of loading a
    duplicate module.
    """

    for module_name in (
        "dc_modifier.legacy_windows",
        "dc_modifier.legacy_tools",
        "dc_modifier.rom_data_browser",
        "dc_modifier.production_credits_editor",
    ):
        try:
            importlib.import_module(module_name)
        except Exception as error:  # pragma: no cover - diagnostic fallback
            _RUNTIME_WARMUP_ERRORS.append(f"{module_name}: {error}")


def _start_runtime_warmup() -> None:
    global _RUNTIME_WARMUP_THREAD
    if _RUNTIME_WARMUP_THREAD is not None:
        return
    _RUNTIME_WARMUP_THREAD = threading.Thread(
        target=_warm_runtime_modules,
        name="dc-dialog-warmup",
        daemon=True,
    )
    _RUNTIME_WARMUP_THREAD.start()


def startup_rom_from_arguments(arguments: list[str]) -> Path | None:
    """Return the one ROM passed by Windows when it is dropped on the EXE."""
    if len(arguments) != 2:
        return None
    candidate = Path(arguments[1])
    return candidate if candidate.suffix.lower() == ".nes" else None


def _forget_active_editor() -> None:
    global _ACTIVE_EDITOR_WINDOW
    _ACTIVE_EDITOR_WINDOW = None


class _PageRegistry(list[ProjectPage | None]):
    """List-compatible page registry with transparent first-use population."""

    def __init__(self, initializer, materializer) -> None:
        super().__init__()
        self._initializer = initializer
        self._materializer = materializer

    def __getitem__(self, index):
        value = super().__getitem__(index)
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            value = [self[position] for position in range(start, stop, step)]
        else:
            if value is None:
                value = self._materializer(index)
            self._initializer(value)
        return value

    def __iter__(self):
        # External integrations historically see a concrete 12-page list.
        # Iteration remains compatible, while product internals use
        # ``materialized`` so ordinary ROM opening does not instantiate every
        # hidden editor merely to update its stale flag.
        for index in range(len(self)):
            yield self[index]

    def materialized(self) -> tuple[ProjectPage, ...]:
        return tuple(
            page for page in list.__iter__(self) if page is not None
        )


class VisibleArrowStyle(QProxyStyle):
    """Draw controls whose native Windows marks disappear under QSS.

    Qt's stylesheet proxy can leave a checkbox with only a bare tick on some
    Windows scaling/theme combinations.  Drawing the indicator here gives the
    complete editor one stable unchecked square and one unmistakable checked
    square, while retaining normal keyboard/focus behaviour.
    """

    def drawPrimitive(self, element, option, painter, widget=None) -> None:  # noqa: N802
        if element == QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            rect = option.rect.adjusted(1, 1, -1, -1)
            enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
            checked = bool(option.state & QStyle.StateFlag.State_On)
            partial = bool(option.state & QStyle.StateFlag.State_NoChange)
            hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
            border = QColor("#467985" if hovered else "#73949D")
            fill = QColor("#3F8797") if enabled else QColor("#AAB8BE")
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(border if enabled else QColor("#AEBBC1"), 1))
            painter.setBrush(fill if checked or partial else QColor(
                "#FFFFFF" if enabled else "#EDF1F2"
            ))
            painter.drawRoundedRect(rect, 2, 2)
            if checked:
                pen = QPen(QColor("#FFFFFF"), 2)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                left = rect.left() + max(2, rect.width() // 5)
                middle_x = rect.left() + rect.width() * 2 // 5
                middle_y = rect.top() + rect.height() * 3 // 5
                painter.drawLine(left, rect.center().y(), middle_x, middle_y)
                painter.drawLine(
                    middle_x,
                    middle_y,
                    rect.right() - max(2, rect.width() // 6),
                    rect.top() + max(2, rect.height() // 4),
                )
            elif partial:
                painter.setPen(QPen(QColor("#FFFFFF"), 2))
                painter.drawLine(
                    rect.left() + 3, rect.center().y(), rect.right() - 3, rect.center().y()
                )
            painter.restore()
            return
        arrows = (
            QStyle.PrimitiveElement.PE_IndicatorArrowUp,
            QStyle.PrimitiveElement.PE_IndicatorArrowDown,
            QStyle.PrimitiveElement.PE_IndicatorSpinUp,
            QStyle.PrimitiveElement.PE_IndicatorSpinDown,
            QStyle.PrimitiveElement.PE_IndicatorSpinPlus,
            QStyle.PrimitiveElement.PE_IndicatorSpinMinus,
        )
        if element not in arrows:
            super().drawPrimitive(element, option, painter, widget)
            return
        rect = option.rect
        half_width = max(3, min(5, rect.width() // 3))
        half_height = max(2, min(4, rect.height() // 3))
        center_x = rect.center().x()
        center_y = rect.center().y()
        if element in (
            QStyle.PrimitiveElement.PE_IndicatorArrowUp,
            QStyle.PrimitiveElement.PE_IndicatorSpinUp,
            QStyle.PrimitiveElement.PE_IndicatorSpinPlus,
        ):
            points = QPolygon((
                QPoint(center_x, center_y - half_height),
                QPoint(center_x - half_width, center_y + half_height),
                QPoint(center_x + half_width, center_y + half_height),
            ))
        else:
            points = QPolygon((
                QPoint(center_x - half_width, center_y - half_height),
                QPoint(center_x + half_width, center_y - half_height),
                QPoint(center_x, center_y + half_height),
            ))
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#26343D") if option.state & QStyle.StateFlag.State_Enabled
                         else QColor("#98A3AA"))
        painter.drawPolygon(points)
        painter.restore()

    def subControlRect(self, control, option, sub_control, widget=None):  # noqa: N802
        result = super().subControlRect(control, option, sub_control, widget)
        if control != QStyle.ComplexControl.CC_SpinBox:
            return result
        button_width = min(24, max(16, option.rect.width() // 4))
        button_x = option.rect.right() - button_width + 1
        upper_height = option.rect.height() // 2
        if sub_control == QStyle.SubControl.SC_SpinBoxUp:
            return QRect(button_x, option.rect.top(), button_width, upper_height)
        if sub_control == QStyle.SubControl.SC_SpinBoxDown:
            return QRect(
                button_x, option.rect.top() + upper_height,
                button_width, option.rect.height() - upper_height,
            )
        if sub_control == QStyle.SubControl.SC_SpinBoxEditField:
            result.setRight(button_x - 2)
        return result


class ControlWheelGuard(QObject):
    """Prevent an ordinary scroll gesture from silently editing a field."""

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.Type.Wheel
            and isinstance(watched, (QAbstractSpinBox, QComboBox))
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            event.ignore()
            return True
        return super().eventFilter(watched, event)


class ComboPopupGuard(QObject):
    """Bound every combo popup and reject press-drag-release misselection."""

    MAX_VISIBLE_ROWS = 10

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._opening_combo: QComboBox | None = None

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        event_type = event.type()
        if event_type == QEvent.Type.Show and isinstance(watched, QComboBox):
            watched.setMaxVisibleItems(
                min(watched.maxVisibleItems(), self.MAX_VISIBLE_ROWS)
            )
        elif (
            event_type == QEvent.Type.MouseButtonPress
            and isinstance(watched, QComboBox)
            and event.button() == Qt.MouseButton.LeftButton
            and not watched.view().isVisible()
        ):
            self._opening_combo = watched
        elif (
            event_type == QEvent.Type.MouseButtonRelease
            and self._opening_combo is not None
        ):
            combo = self._opening_combo
            self._opening_combo = None
            view = combo.view()
            if view.isVisible() and (
                watched is view
                or watched is view.viewport()
                or view.isAncestorOf(watched)
            ):
                # A combo opens on the original mouse press.  Windows then
                # treats releasing that same press over any hovered row as an
                # activation.  Swallow only this opening release; the popup
                # stays open and a subsequent deliberate click still works.
                event.accept()
                return True
        return super().eventFilter(watched, event)


class ApplicationUiPolisher(QObject):
    """Apply consistent semantic button roles to every lazily-created dialog."""

    _PRIMARY_BUTTONS = {
        QDialogButtonBox.StandardButton.Ok,
        QDialogButtonBox.StandardButton.Save,
        QDialogButtonBox.StandardButton.Apply,
        QDialogButtonBox.StandardButton.Yes,
    }
    _DEFAULT_BUTTON_LABELS = {
        "ok": "确定",
        "cancel": "取消",
        "close": "关闭",
        "save": "保存",
        "apply": "应用",
        "yes": "是",
        "no": "否",
        "open": "打开",
        "reset": "重置",
        "retry": "重试",
        "abort": "中止",
        "ignore": "忽略",
        "discard": "放弃修改",
        "restore defaults": "恢复默认",
        "help": "帮助",
    }

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Show and isinstance(watched, QDialog):
            self.polish_dialog(watched)
        return super().eventFilter(watched, event)

    @classmethod
    def polish_dialog(cls, dialog: QDialog) -> None:
        if dialog.property("uiPolished"):
            return
        dialog.setProperty("uiPolished", True)
        for button_box in dialog.findChildren(QDialogButtonBox):
            if button_box.layout() is not None:
                button_box.layout().setSpacing(8)
            for button in button_box.findChildren(QAbstractButton):
                role = button_box.buttonRole(button)
                standard = button_box.standardButton(button)
                # Qt's native button captions depend on the host locale.  The
                # legacy modifier and the rest of this editor use Chinese
                # action labels, so translate only untouched framework
                # defaults while preserving deliberate labels such as
                # “应用到草稿” and “确认输入”.
                default_label = button.text().replace("&", "").strip().lower()
                translated = cls._DEFAULT_BUTTON_LABELS.get(default_label)
                if translated is not None:
                    button.setText(translated)
                if role == QDialogButtonBox.ButtonRole.DestructiveRole:
                    button.setObjectName("destructiveButton")
                elif standard in cls._PRIMARY_BUTTONS and not button.objectName():
                    button.setObjectName("primaryButton")
                button.style().unpolish(button)
                button.style().polish(button)


STYLE_SHEET = """
QMainWindow, QDialog {
    background: #eef2f4;
    color: #26343d;
}
QWidget {
    background: transparent;
    color: #26343d;
}
QDialog { background: #f2f5f6; }
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {
    background: transparent;
}
QStackedWidget#mainWorkspace {
    background: #eef2f4;
}
QComboBox { combobox-popup: 0; }
QMenuBar, QMenu, QStatusBar { background: #ffffff; }
QMenuBar {
    border-bottom: 1px solid #d8e0e5;
    padding: 2px 4px;
}
QMenuBar::item {
    border-radius: 4px;
    padding: 6px 12px;
}
QMenuBar::item:selected, QMenu::item:selected {
    background: #e7f1f4;
    color: #245b6a;
}
QMenu {
    border: 1px solid #cfd9df;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    border-radius: 4px;
    padding: 6px 30px 6px 22px;
}
QMenu::item:enabled { color: #26343d; }
QMenu::item:disabled {
    background: #eef1f3;
    color: #a8b0b5;
}
QMenu::item:disabled:selected {
    background: #eef1f3;
    color: #a8b0b5;
}
QMenu::separator {
    height: 1px;
    background: #e2e8ec;
    margin: 4px 8px;
}
QTabWidget::pane {
    background: #f9fbfc;
    border: 1px solid #a9bac3;
    border-radius: 6px;
    top: -1px;
}
QTabBar::tab {
    background: #e7edef;
    color: #586873;
    border: 1px solid #adbdc5;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    padding: 7px 13px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #f9fbfc;
    color: #2c6879;
    border-top: 2px solid #4b8290;
    padding-top: 6px;
    font-weight: 600;
}
QTabBar::tab:hover:!selected {
    background: #e4ecef;
}
QLabel#pageTitle, QLabel#pageSubtitle { max-height: 0px; min-height: 0px; }
QLabel#hintText { color: #65747d; }
QLabel#infoPanel {
    background: #eef5f7;
    border: 1px solid #c2d7dd;
    border-radius: 6px;
    color: #49636e;
    padding: 8px 10px;
}
QLabel#deploymentSelectionPreview {
    background: #f1f7f8;
    border: 1px solid #c3d9df;
    border-radius: 5px;
    color: #315c68;
    padding: 5px 8px;
}
QLabel#sectionTitle { color: #315c68; font-size: 15px; font-weight: 600; }
QLabel#romBadge, QLabel#countBadge {
    background: #edf5f7;
    border: 1px solid #bfd6dc;
    border-radius: 9px;
    padding: 3px 8px;
}
QLabel#pendingBanner, QLabel#editState {
    background: #eef6f1;
    border: 1px solid #b9d5c2;
    border-radius: 5px;
    color: #376247;
    padding: 5px 8px;
}
QLabel#editState[pending="true"] {
    background: #fbf5e9;
    border-color: #dfc995;
    color: #745c24;
}
QFrame#metricCard, QGroupBox {
    background: #fbfcfd;
    border: 1px solid #a9bbc4;
    border-radius: 7px;
}
QGroupBox {
    margin-top: 9px;
    padding: 9px 7px 7px 7px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    background: #e7f0f3;
    color: #2f6170;
    border-radius: 3px;
    padding: 1px 6px;
}
QGroupBox QGroupBox {
    background: #f3f7f8;
    border-color: #bdccd3;
}
QGroupBox QGroupBox::title {
    background: #e6eff1;
    color: #3d6671;
}
QGroupBox QGroupBox QGroupBox {
    background: #f8fafb;
    border-color: #cad5da;
}
QFrame[frameShape="4"], QFrame[frameShape="5"] {
    color: #cbd6db;
}
QLabel#metricLabel { color: #65747d; font-size: 12px; }
QLabel#metricValue { font-size: 15px; font-weight: 600; }
QLabel#emptyState {
    background: white;
    border: 1px dashed #aebfc8;
    border-radius: 6px;
    color: #65747d;
    padding: 18px;
}
QPushButton, QToolButton {
    background: #f7fafb;
    color: #31444f;
    border: 1px solid #a6b6bf;
    border-radius: 5px;
    padding: 5px 10px;
}
QPushButton:hover, QToolButton:hover {
    background: #e8f1f3;
    border-color: #7fa8b4;
}
QPushButton:pressed, QToolButton:pressed { background: #dcebed; }
QPushButton:checked, QToolButton:checked {
    background: #deecef;
    border-color: #6f9da8;
    color: #285b68;
}
QPushButton:disabled, QToolButton:disabled {
    background: #f0f2f3;
    border-color: #d8dee2;
    color: #9aa5ab;
}
/* Compact reference-style tool buttons use explicit small geometries.  Give
   them matching padding instead of inheriting the general 5x10 px padding,
   which made otherwise complete captions look squeezed or disabled. */
QPushButton#databaseModuleMemoryDetails {
    padding: 2px 8px;
}
QPushButton#unitUploadButton,
QPushButton#unitClearButton,
QPushButton#unitNavigateButton,
QPushButton#puzzleClearButton,
QPushButton#puzzleTemplateButton,
QPushButton#puzzlePreviewButton,
QPushButton#puzzleDirectionButton {
    padding: 2px 6px;
}
QPushButton#primaryButton {
    background: #3f7f8f;
    border-color: #3f7f8f;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#primaryButton:hover { background: #356f7e; }
QPushButton#primaryButton:pressed { background: #2e6370; }
QPushButton#destructiveButton {
    background: #fff7f6;
    border-color: #d8aaa5;
    color: #9a3f36;
}
QPushButton#destructiveButton:hover {
    background: #fcecea;
    border-color: #c77d75;
}
QDialogButtonBox QPushButton { min-width: 72px; padding: 6px 12px; }
QPushButton#terrainButton {
    min-width: 32px; max-width: 32px;
    min-height: 32px; max-height: 32px;
    border: none; border-radius: 0; padding: 0; margin: 0;
    background: transparent;
}
QPushButton#terrainButton:hover,
QPushButton#terrainButton:pressed,
QPushButton#terrainButton:focus { border: none; background: transparent; }
QPushButton#terrainButton:checked {
    border: 1px solid #164a9a; background: transparent;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit,
QTableWidget, QTableView, QListWidget, QListView, QTreeWidget, QTreeView {
    background: #fcfefe;
    border: 1px solid #aebdc5;
    border-radius: 4px;
    padding: 3px 5px;
    selection-background-color: #4c8594;
    selection-color: #ffffff;
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover,
QPlainTextEdit:hover, QTextEdit:hover {
    background: #ffffff;
    border-color: #89aab3;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus, QTableWidget:focus, QTableView:focus,
QListWidget:focus, QListView:focus, QTreeWidget:focus, QTreeView:focus {
    border: 1px solid #5f94a2;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {
    background: #e9eef0;
    border-color: #cbd4d9;
    color: #849199;
}
QLineEdit[readOnly="true"], QPlainTextEdit[readOnly="true"],
QTextEdit[readOnly="true"] {
    background: #f2f6f7;
    border-color: #c4d0d5;
    color: #526670;
}
QCheckBox, QRadioButton { spacing: 6px; padding: 2px 0; }
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox:disabled, QRadioButton:disabled, QLabel:disabled { color: #8d989f; }
QAbstractItemView {
    background: #fcfefe;
    alternate-background-color: #f1f5f6;
    outline: 0;
}
QListWidget::item, QTableWidget::item { padding: 3px; }
QListWidget::item:alternate, QTableWidget::item:alternate { background: #f1f5f6; }
QListWidget::item:hover, QTableWidget::item:hover,
QTreeView::item:hover, QListView::item:hover { background: #e7f0f2; }
QListWidget::item:selected, QTableWidget::item:selected,
QTreeView::item:selected, QListView::item:selected,
QListWidget::item:selected:!active, QTableWidget::item:selected:!active,
QTreeView::item:selected:!active, QListView::item:selected:!active {
    background: #3f7f8f;
    color: #ffffff;
}
QHeaderView::section {
    background: #e8f0f2;
    color: #41545f;
    border: none;
    border-right: 1px solid #d6dfe4;
    border-bottom: 1px solid #c8d3d9;
    padding: 5px;
    font-weight: 600;
}
QScrollBar:vertical {
    background: transparent;
    width: 11px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #bdc9cf;
    border-radius: 4px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: #9eafb7; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent;
    height: 11px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #bdc9cf;
    border-radius: 4px;
    min-width: 28px;
}
QScrollBar::handle:horizontal:hover { background: #9eafb7; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QSplitter::handle { background: #d8e1e5; }
QSplitter::handle:hover { background: #adc2ca; }
QProgressBar {
    background: #e5ecef;
    border: 1px solid #bdcbd1;
    border-radius: 5px;
    color: #314852;
    text-align: center;
}
QProgressBar::chunk {
    background: #5f96a3;
    border-radius: 4px;
}
QSlider::groove:horizontal {
    background: #d8e3e7;
    height: 5px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #4c8594;
    border: 1px solid #356d7a;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: #3f7886; }
QToolTip {
    background: #26343d;
    color: #ffffff;
    border: 1px solid #526873;
    border-radius: 4px;
    padding: 5px 7px;
}
QWidget#transparentHost { background: transparent; }
QStatusBar {
    color: #5f6f78;
    border-top: 1px solid #d8e0e5;
}
QMessageBox {
    background: #f4f7f8;
}
QMessageBox QLabel { background: transparent; }
"""


class LauncherWindow(QDialog):
    """ROM-first launch screen shown before the editor session."""

    def __init__(self) -> None:
        super().__init__()
        self.main_window: MainWindow | None = None
        self.setWindowTitle(LAUNCHER_TITLE)
        # The launcher deliberately exposes only the two controls used by the
        # reference program.  Keep them in one compact visual group instead of
        # stretching the author label to fill the whole window, which used to
        # strand the ROM button at the bottom of a large empty panel.
        self.resize(460, 260)
        self.setMinimumSize(400, 230)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 22)
        layout.setSpacing(0)
        introduction = QLabel("作者 断月残心")
        introduction.setObjectName("launcherAuthor")
        introduction.setStyleSheet("color: #ef4e4e; font-family: SimSun; font-size: 20px;")
        introduction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(introduction)
        layout.addSpacing(28)

        open_rom = QPushButton("打开ROM")
        open_rom.setObjectName("launcherOpenRomButton")
        open_rom.setFixedSize(176, 54)
        open_rom.setToolTip("选择一个 .nes ROM；也可以把 ROM 文件拖到此窗口")
        open_rom.clicked.connect(self.choose_rom)
        open_row = QHBoxLayout()
        open_row.addStretch()
        open_row.addWidget(open_rom)
        open_row.addStretch()
        layout.addLayout(open_row)
        layout.addStretch(2)

    @staticmethod
    def _rom_path_from_urls(urls: list[object]) -> Path | None:
        if len(urls) != 1:
            return None
        path_text = urls[0].toLocalFile()
        if not path_text:
            return None
        path = Path(path_text)
        if path.suffix.lower() != ".nes":
            return None
        return path

    def choose_rom(self) -> MainWindow | None:
        # Native file dialogs keep processing the Qt event loop.  Prepare the
        # heavy main-window widget tree behind that already-visible dialog so
        # selecting a ROM does not then pay construction and layout costs.
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "打开ROM",
            str(DEFAULT_ROM.parent),
            "NES ROM (*.nes);;所有文件 (*)",
        )
        if not filename:
            return None
        return self.open_rom(filename)

    def open_rom(self, path: str | Path) -> MainWindow | None:
        global _ACTIVE_EDITOR_WINDOW
        if self.main_window is not None:
            self.main_window.raise_()
            self.main_window.activateWindow()
            return self.main_window
        main = MainWindow(open_default=False)
        if not main.load_rom(path, error_parent=self):
            main.close()
            main.deleteLater()
            return None
        self.main_window = main
        _ACTIVE_EDITOR_WINDOW = main
        main.closed.connect(_forget_active_editor)
        main.show()
        # The launch window is not part of the editor's hidden-window session and
        # only disappears after the selected ROM has been loaded successfully.
        self.close()
        return main

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        path = self._rom_path_from_urls(list(event.mimeData().urls()))
        if path is not None:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        path = self._rom_path_from_urls(list(event.mimeData().urls()))
        if path is None:
            return
        if self.open_rom(path) is not None:
            event.acceptProposedAction()


class MainWindow(QMainWindow):
    """The legacy map shell. Data editors are opened as independent dialogs."""

    closed = Signal()

    def __init__(self, *, open_default: bool = True) -> None:
        super().__init__()
        self.project: RomProject | None = None
        self.project_path: Path | None = None
        self.rom_output_path: Path | None = None
        self._saved_snapshot: bytes | None = None
        self._saved_allocations: tuple[object, ...] | None = None
        self.setWindowTitle(LEGACY_WINDOW_TITLE)
        # Keep the initial footprint close to the reference editor on a
        # 125%-scaled Windows desktop.  Users can still enlarge the window,
        # but opening a ROM should not occupy almost the entire screen.
        # The native frame adds 30 logical pixels on the reference Windows
        # desktop.  671 client pixels therefore produce a 701 logical / 876
        # physical-pixel outer window at 125% DPI, matching the legacy editor.
        self.resize(850, 671)
        self.setMinimumSize(800, 600)
        self._stale_pages: set[ProjectPage] = set()
        self._uninitialized_pages: set[ProjectPage] = set()
        self._count_snapshot: bytes | None = None
        self._changed_byte_count = 0
        self._database_dialog: QDialog | None = None
        self._database_dialog_snapshot: bytes | None = None
        self._dialog_cache: dict[
            str, tuple[RomProject, bytes, QDialog]
        ] = {}
        self.setAcceptDrops(True)

        # Keep a non-visual registry for automated functional checks. Only the
        # map page is part of the normal main-window route; all other editors
        # are constructed afresh in independent transaction dialogs.
        self.navigation = QListWidget(self)
        self.navigation.hide()
        self.pages: _PageRegistry = _PageRegistry(
            self._ensure_page_initialized,
            self._materialize_page,
        )
        self._lazy_page_factories: dict[int, tuple[str, object, QWidget]] = {}
        self.page_index: dict[str, int] = {}
        self.page_stack_index: dict[str, int] = {}
        self.workspace = QStackedWidget()
        self.workspace.setObjectName("mainWorkspace")
        self.blank_page = QWidget()
        self.workspace.addWidget(self.blank_page)
        self._build_pages()
        self.setCentralWidget(self.workspace)

        self.status = QStatusBar()
        self.session_status = QLabel("尚未载入ROM")
        self.status.addWidget(self.session_status, 1)
        self.x_status = QLabel("X坐标：—")
        self.y_status = QLabel("Y坐标：—")
        self.status.addPermanentWidget(self.x_status)
        self.status.addPermanentWidget(self.y_status)
        # Compatibility labels retained for existing integrations; they are
        # deliberately hidden to preserve the reference status-bar layout.
        self.path_status = QLabel("尚未载入ROM")
        self.module_status = QLabel("战场地图")
        self.change_status = QLabel("0 字节修改")
        for label in (self.path_status, self.module_status, self.change_status):
            label.hide()
        self.setStatusBar(self.status)
        # Save/errors and completion messages must remain visible to users.
        self.status.setSizeGripEnabled(True)

        self.map_page = self.pages[self.page_index["maps"]]
        assert isinstance(self.map_page, MapPage)
        self.map_page.canvas.coordinate_changed.connect(self._map_coordinate_changed)
        self.map_page.draft_state_changed.connect(self._update_window_state)
        self.map_page.attribute_calculator_requested.connect(
            self._open_deployment_attribute_calculator
        )
        self.map_page.database_record_requested.connect(
            self._open_database_record
        )
        self.map_page.defeat_experience_requested.connect(
            self._open_defeat_experience_calculator
        )

        self._create_actions()
        self._create_menus()
        self.navigation.currentRowChanged.connect(self._show_page_by_index)
        self.workspace.setCurrentWidget(self.map_page)
        self._update_action_state()
        self._update_window_state()

        if open_default and DEFAULT_ROM.exists():
            self.load_rom(DEFAULT_ROM, quiet=True)

    def _add_page(self, key: str, label: str, page: ProjectPage) -> None:
        self.page_index[key] = len(self.pages)
        self.pages.append(page)
        self._connect_page(page)
        item = QListWidgetItem(label)
        item.setToolTip(label)
        self.navigation.addItem(item)
        self.page_stack_index[key] = self.workspace.addWidget(page)

    def _add_lazy_page(self, key: str, label: str, factory) -> None:
        index = len(self.pages)
        self.page_index[key] = index
        self.pages.append(None)
        placeholder = QWidget()
        self._lazy_page_factories[index] = (key, factory, placeholder)
        item = QListWidgetItem(label)
        item.setToolTip(label)
        self.navigation.addItem(item)
        self.page_stack_index[key] = self.workspace.addWidget(placeholder)

    def _connect_page(self, page: ProjectPage) -> None:
        page.project_changed.connect(self._after_edit)
        page.navigation_requested.connect(self._open_extension_page)

    def _materialize_page(self, index: int) -> ProjectPage:
        existing = list.__getitem__(self.pages, index)
        if existing is not None:
            return existing
        key, factory, placeholder = self._lazy_page_factories.pop(index)
        page = factory()
        self._connect_page(page)
        stack_index = self.workspace.indexOf(placeholder)
        self.workspace.removeWidget(placeholder)
        self.workspace.insertWidget(stack_index, page)
        self.page_stack_index[key] = stack_index
        list.__setitem__(self.pages, index, page)
        placeholder.deleteLater()
        if self.project is not None:
            page.set_project_deferred(self.project)
            self._stale_pages.add(page)
            self._uninitialized_pages.add(page)
        return page

    def _build_pages(self) -> None:
        self._add_page("maps", "战场地图", MapPage())
        self._add_lazy_page("units", "机体", UnitPage)
        self._add_lazy_page("characters", "人物", CharacterPage)
        self._add_lazy_page("weapons", "武器", WeaponPage)
        self._add_lazy_page("unit_import", "机体导入与图像", UnitImportPage)
        self._add_lazy_page("story", "剧情文本", StoryPage)
        self._add_lazy_page("events", "战场事件", EventPage)
        self._add_lazy_page("persuasion", "劝降条件", PersuasionPage)
        self._add_lazy_page("music", "背景音乐", MusicPage)
        self._add_lazy_page("overview", "工程概览", OverviewPage)
        self._add_lazy_page("resources", "容量规划", ResourcePage)
        self._add_lazy_page("changes", "变更与验证", ChangesPage)

    def show_page(self, key: str) -> None:
        """Select a registered page for tests/capture; menus use dialogs."""
        if key not in self.page_stack_index:
            raise KeyError(f"未知页面：{key}")
        page = self.pages[self.page_index[key]]
        if page in self._uninitialized_pages:
            page.refresh()
            self._uninitialized_pages.discard(page)
            self._stale_pages.discard(page)
        elif page in self._stale_pages and not page.has_pending_draft:
            page.refresh()
            self._stale_pages.discard(page)
        self.workspace.setCurrentIndex(self.page_stack_index[key])
        row = self.page_index[key]
        self.navigation.blockSignals(True)
        self.navigation.setCurrentRow(row)
        self.navigation.blockSignals(False)
        self.module_status.setText(self.navigation.item(row).text())

    def _ensure_page_initialized(self, page: ProjectPage) -> None:
        """Populate a deferred page when UI routing or integrations request it."""

        if page in self._uninitialized_pages:
            page.refresh()
            self._uninitialized_pages.discard(page)
            self._stale_pages.discard(page)

    def _show_page_by_index(self, row: int) -> None:
        if not 0 <= row < len(self.pages):
            return
        key = next(key for key, index in self.page_index.items() if index == row)
        self.show_page(key)

    def _action(
        self,
        text: str,
        slot,
        shortcut: QKeySequence.StandardKey | str | None = None,
    ) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut is not None:
            action.setShortcut(shortcut)
        return action

    def _create_actions(self) -> None:
        self.open_rom_action = self._action("打开(&O)", self.open_rom_dialog, "Ctrl+O")
        self.save_rom_action = self._action("保存(&S)", self.save_rom, "Ctrl+S")
        self.exit_action = self._action("退出(&X)", self.close, "Ctrl+X")

        self.database_action = self._action("数据库(&D)", self.open_database, "Ctrl+D")
        self.rom_data_action = self._action("完整ROM数据读取", self.open_rom_data_browser)
        self.font_library_action = self._action("文字库(&W)", self.open_font_library, "Ctrl+W")
        self.map_animation_action = self._action("地图动画(&M)", self.open_map_animation, "Ctrl+M")
        self.text_converter_action = self._action("文字转换(&Z)", self.open_text_converter, "Ctrl+Z")
        self.scenario_action = self._action("剧情事件(&J)", self.open_scenario, "Ctrl+J")
        self.export_unit_action = self._action("导出机体(&P)", self.export_unit, "Ctrl+F")
        self.export_avatar_action = self._action("导出头像(&L)", self.export_avatar, "Ctrl+L")
        self.export_avatar_action.setStatusTip(
            "批量导出全部人物的背面、正面与效果头像；规则与人物页单个导出一致。"
        )
        self.export_avatar_action.setToolTip(self.export_avatar_action.statusTip())
        self.attribute_calculator_action = self._action("属性计算器", self.open_attribute_calculator)
        self.save_editor_action = self._action("存档修改器", self.open_save_editor)
        self.other_settings_action = self._action("其他(&T)", self.open_other_settings, "Ctrl+T")

        self.open_project_action = self._action("打开工程…", self.open_project_dialog, "Ctrl+Shift+O")
        self.save_project_action = self._action("保存工程", self.save_project, "Ctrl+Shift+S")
        self.save_project_as_action = self._action("工程另存为…", self.save_project_as)
        self.save_rom_as_action = self._action("ROM另存为…", self.save_rom_as, "Ctrl+Alt+S")
        self.export_ips_action = self._action("导出IPS…", self.export_ips)
        self.build_action = self._action("一键构建…", self.build_release, "Ctrl+B")
        # Ctrl+Z belongs to the reference editor's “文字转换” command. Keep
        # project-history shortcuts in the extension namespace to avoid an
        # ambiguous Qt shortcut that would make both commands unusable.
        self.undo_action = self._action("撤销", self.undo, "Ctrl+Alt+Z")
        self.redo_action = self._action("重做", self.redo, "Ctrl+Alt+Y")
        self.validate_action = self._action("完整检查", self.validate_project, "F7")
        self.beginner_guide_action = self._action(
            "新手操作向导", self.show_beginner_guide, "F1"
        )
        self.about_action = self._action("关于", self.show_about)
        self.page_actions = {
            key: self._action(
                text,
                lambda _checked=False, page_key=key: self._open_extension_page(page_key),
            )
            for key, text in (
                ("music", "战斗背景音乐"),
                ("unit_import", "机体导入与CHR图像"),
                ("overview", "工程概览"),
                ("resources", "扩展容量规划"),
                ("changes", "变更与验证"),
            )
        }
        self.legacy_commands = {
            command_id: action
            for command_id, action in (
                (20001, self.open_rom_action), (20004, self.save_rom_action),
                (20006, self.exit_action), (20008, self.database_action),
                (20009, self.font_library_action), (20011, self.map_animation_action),
                (20013, self.text_converter_action), (20015, self.scenario_action),
                (20017, self.export_unit_action), (20018, self.export_avatar_action),
                (20020, self.attribute_calculator_action), (20021, self.save_editor_action),
                (20023, self.other_settings_action), (20025, self.about_action),
            )
        }
        for command_id, action in self.legacy_commands.items():
            action.setData(command_id)

    @staticmethod
    def _legacy_separator(menu: QMenu, command_id: int) -> None:
        menu.addSeparator().setData(command_id)

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("文件(&F)")
        file_menu.addAction(self.open_rom_action)
        self._legacy_separator(file_menu, 20003)
        file_menu.addAction(self.save_rom_action)
        self._legacy_separator(file_menu, 20005)
        file_menu.addAction(self.exit_action)

        self.data_menu = self.menuBar().addMenu("数据(&A)")
        self.data_menu.addAction(self.database_action)
        self.data_menu.addAction(self.font_library_action)
        self._legacy_separator(self.data_menu, 20010)
        self.data_menu.addAction(self.map_animation_action)
        self._legacy_separator(self.data_menu, 20012)
        self.data_menu.addAction(self.text_converter_action)
        self._legacy_separator(self.data_menu, 20014)
        self.data_menu.addAction(self.scenario_action)
        self._legacy_separator(self.data_menu, 20016)
        self.data_menu.addAction(self.export_unit_action)
        self.data_menu.addAction(self.export_avatar_action)
        self._legacy_separator(self.data_menu, 20019)
        self.data_menu.addAction(self.attribute_calculator_action)
        self.data_menu.addAction(self.save_editor_action)
        self._legacy_separator(self.data_menu, 20022)
        self.data_menu.addAction(self.other_settings_action)

        self.extension_menu = self.menuBar().addMenu("扩展功能")
        self.extension_menu.addAction(self.rom_data_action)
        self.extension_menu.addSeparator()
        self.extension_menu.addAction(self.page_actions["music"])
        self.extension_menu.addAction(self.page_actions["unit_import"])
        self.extension_menu.addAction(self.page_actions["resources"])
        self.extension_menu.addSeparator()
        self.extension_menu.addAction(self.page_actions["overview"])
        self.extension_menu.addAction(self.page_actions["changes"])

        self.project_menu = self.menuBar().addMenu("工程")
        self.project_menu.addAction(self.open_project_action)
        self.project_menu.addAction(self.save_project_action)
        self.project_menu.addAction(self.save_project_as_action)
        self.project_menu.addSeparator()
        self.project_menu.addAction(self.save_rom_as_action)
        self.project_menu.addAction(self.export_ips_action)
        self.project_menu.addAction(self.build_action)
        self.project_menu.addSeparator()
        self.project_menu.addAction(self.undo_action)
        self.project_menu.addAction(self.redo_action)
        self.project_menu.addAction(self.validate_action)

        help_menu = self.menuBar().addMenu("帮助(&H)")
        help_menu.addAction(self.beginner_guide_action)
        help_menu.addSeparator()
        help_menu.addAction(self.about_action)

    def _map_coordinate_changed(self, x: int, y: int) -> None:
        self.x_status.setText(f"X坐标：{x}")
        self.y_status.setText(f"Y坐标：{y}")

    def _remember_dialog(self, key: str, dialog: QDialog) -> None:
        if self.project is not None:
            self._dialog_cache[key] = (
                self.project,
                bytes(self.project.working),
                dialog,
            )

    def _cached_dialog(self, key: str, factory) -> QDialog:
        assert self.project is not None
        current = bytes(self.project.working)
        cached = self._dialog_cache.get(key)
        if cached is not None:
            cached_project, snapshot, dialog = cached
            if cached_project is self.project and snapshot == current:
                return dialog
            dialog.deleteLater()
        dialog = factory()
        self._dialog_cache[key] = (self.project, current, dialog)
        return dialog

    def _run_project_dialog(
        self,
        dialog: QDialog,
        success_message: str,
        *,
        cache_key: str | None = None,
    ) -> int:
        from .window_layout import fit_dialog_to_screen
        fit_dialog_to_screen(dialog)
        if (
            hasattr(dialog, "project_changed")
            and not dialog.property("mainWindowNoticeConnected")
        ):
            dialog.project_changed.connect(self._dialog_edit_notice)
            dialog.setProperty("mainWindowNoticeConnected", True)
        result = dialog.exec()
        self._refresh_registered_pages(preserve_map_draft=True)
        self._update_window_state()
        if result == QDialog.DialogCode.Accepted:
            self.status.showMessage(success_message, 4000)
        if cache_key is None:
            dialog.deleteLater()
        else:
            self._remember_dialog(cache_key, dialog)
        return result

    def _dialog_edit_notice(self, message: str) -> None:
        self._update_window_state()
        self.status.showMessage(message, 4000)

    def open_database(self) -> None:
        dialog = self._prepare_database_dialog()
        if dialog is not None:
            self._execute_database_dialog(dialog)

    def _prepare_database_dialog(self):
        if self.project is None:
            return None
        from .legacy_windows import DatabaseDialog

        dialog = self._database_dialog
        current_snapshot = bytes(self.project.working)
        if not isinstance(dialog, DatabaseDialog):
            dialog = DatabaseDialog(self.project, self, lazy=True)
            dialog.project_changed.connect(self._dialog_edit_notice)
            self._database_dialog = dialog
        elif (
            dialog.project is not self.project
            or self._database_dialog_snapshot != current_snapshot
        ):
            # The same window is reused between visits.  Reload it only when
            # another editor (or a newly opened ROM) changed its backing data.
            dialog.set_project(self.project)
        return dialog

    def _execute_database_dialog(self, dialog: QDialog) -> None:
        if self.project is None:
            return
        from .window_layout import fit_dialog_to_screen

        fit_dialog_to_screen(dialog)
        result = dialog.exec()
        self._database_dialog_snapshot = bytes(self.project.working)
        self._refresh_registered_pages(preserve_map_draft=True)
        self._update_window_state()
        if result == QDialog.DialogCode.Accepted:
            self.status.showMessage("数据库修改已确认", 4000)

    def _open_database_record(self, record_kind: str, record_id: int) -> None:
        dialog = self._prepare_database_dialog()
        if dialog is None:
            return
        if record_kind == "units":
            dialog._select_unit(record_id)
        elif record_kind == "characters":
            dialog._select_character(record_id)
        else:
            return
        self._execute_database_dialog(dialog)

    def open_rom_data_browser(self) -> None:
        if self.project is None:
            return
        from .rom_data_browser import RomDataBrowserDialog

        dialog = self._cached_dialog(
            "rom_data", lambda: RomDataBrowserDialog(self.project, self)
        )
        from .window_layout import fit_dialog_to_screen
        fit_dialog_to_screen(dialog)
        dialog.exec()
        self._remember_dialog("rom_data", dialog)

    def open_scenario(self) -> None:
        if self.project is None:
            return
        from .legacy_windows import ScenarioDialog

        dialog = self._cached_dialog(
            "scenario", lambda: ScenarioDialog(self.project, self, lazy=True)
        )
        self._run_project_dialog(
            dialog, "剧情事件修改已确认", cache_key="scenario"
        )

    def _run_tool_dialog(self, dialog: QDialog) -> None:
        from .window_layout import fit_dialog_to_screen
        fit_dialog_to_screen(dialog)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            self._refresh_registered_pages(preserve_map_draft=True)
            self._update_window_state()
        dialog.deleteLater()

    def open_font_library(self) -> None:
        if self.project is None:
            return
        from .legacy_tools import FontLibraryDialog

        self._run_tool_dialog(FontLibraryDialog(parent=self, project=self.project))

    def open_map_animation(self) -> None:
        if self.project is None:
            return
        from .legacy_tools import MapAnimationDialog

        self._run_tool_dialog(MapAnimationDialog(parent=self, project=self.project))

    def open_text_converter(self) -> None:
        if self.project is None:
            return
        from .legacy_tools import TextConverterDialog

        self._run_tool_dialog(TextConverterDialog(parent=self, project=self.project))

    def open_attribute_calculator(self) -> None:
        if self.project is None:
            return
        from .legacy_tools import AttributeCalculatorDialog

        self._run_tool_dialog(AttributeCalculatorDialog(parent=self, project=self.project))

    def _open_deployment_attribute_calculator(
        self, character_id: int, unit_id: int, level: int
    ) -> None:
        if self.project is None:
            return
        from .legacy_tools import AttributeCalculatorDialog

        dialog = AttributeCalculatorDialog(parent=self, project=self.project)
        for side in (dialog.enemy, dialog.ally):
            side.character.setCurrentIndex(side.character.findData(character_id))
            side.unit.setCurrentIndex(side.unit.findData(unit_id))
            side.level.setCurrentIndex(max(0, min(59, level - 1)))
        self._run_tool_dialog(dialog)

    def _open_defeat_experience_calculator(
        self, unit_id: int, enemy_level: int
    ) -> None:
        if self.project is None:
            return
        from .legacy_tools import DefeatExperienceCalculatorDialog

        self._run_tool_dialog(
            DefeatExperienceCalculatorDialog(
                parent=self,
                project=self.project,
                unit_id=unit_id,
                enemy_level=enemy_level,
            )
        )

    def open_save_editor(self) -> None:
        from .legacy_tools import SaveEditorDialog

        self._run_tool_dialog(SaveEditorDialog(parent=self, project=self.project))

    def open_other_settings(self) -> None:
        if self.project is None:
            return
        from .legacy_tools import OtherSettingsDialog

        self._run_tool_dialog(OtherSettingsDialog(parent=self, project=self.project))

    def _create_extension_dialog(self, key: str) -> QDialog:
        if self.project is None:
            raise ValueError("请先打开ROM。")
        from .legacy_windows import TransactionalProjectDialog

        definitions: dict[str, tuple[str, type[ProjectPage]]] = {
            "music": ("战斗背景音乐", MusicPage),
            "unit_import": ("机体导入与CHR图像", UnitImportPage),
            "overview": ("工程概览", OverviewPage),
            "resources": ("扩展容量规划", ResourcePage),
            "changes": ("变更与验证", ChangesPage),
        }
        title, page_type = definitions[key]
        dialog = TransactionalProjectDialog(self.project, self)
        dialog.setWindowTitle(title)
        dialog.resize(1180, 820)
        layout = QVBoxLayout(dialog)
        page = dialog.register_page(page_type())
        if isinstance(page, ChangesPage):
            page.run_validation()
        layout.addWidget(page, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.page = page
        return dialog

    def _open_extension_page(self, key: str) -> None:
        if self.project is None:
            return
        if key == "maps":
            self.show_page("maps")
            self.raise_()
            self.activateWindow()
            return
        if key in {"units", "characters", "weapons"}:
            dialog = self._prepare_database_dialog()
            if dialog is None:
                return
            dialog.tabs.setCurrentIndex(
                {"units": 0, "characters": 1, "weapons": 2}[key]
            )
            self._execute_database_dialog(dialog)
            return
        if key in {"story", "events", "persuasion"}:
            from .legacy_windows import ScenarioDialog

            dialog = self._cached_dialog(
                "scenario", lambda: ScenarioDialog(self.project, self, lazy=True)
            )
            dialog.tabs.setCurrentIndex(
                {"events": 1, "persuasion": 2, "story": 4}[key]
            )
            self._run_project_dialog(
                dialog, "剧情事件修改已确认", cache_key="scenario"
            )
            return
        cache_key = f"extension:{key}"
        dialog = self._cached_dialog(
            cache_key, lambda: self._create_extension_dialog(key)
        )
        requested = getattr(dialog, "_navigation_requests", None)
        if requested is None:
            requested = []
            dialog._navigation_requests = requested

            def finish_before_navigation(page_key: str) -> None:
                dialog._navigation_requests.append(page_key)
                dialog.accept()

            dialog.navigation_requested.connect(finish_before_navigation)
        else:
            requested.clear()
        self._run_project_dialog(
            dialog, f"{dialog.windowTitle()}已确认", cache_key=cache_key
        )
        if requested:
            self._open_extension_page(requested[-1])

    def export_unit(self) -> None:
        if self.project is None:
            return
        from .legacy_unit_export import (
            LEGACY_UNIT_EXPORT_DIRECTORY,
            export_legacy_unit_bitmaps,
        )

        destination, _ = QFileDialog.getSaveFileName(
            self,
            "导出机体",
            str(_default_export_path(LEGACY_UNIT_EXPORT_DIRECTORY)),
            "导出位置 (*)",
        )
        if not destination:
            return
        try:
            # The reference uses a native Save dialog as a location picker;
            # the typed file component is only a marker.  The actual protocol
            # always creates the fixed “导出的机体” directory beside it.
            root = writable_output_path(Path(destination).parent)
            output_root = root / LEGACY_UNIT_EXPORT_DIRECTORY
            if output_root.exists():
                answer = QMessageBox.question(
                    self,
                    "覆盖机体导出",
                    "“导出的机体”目录已存在。是否覆盖其中同名的 1275 个 BMP？\n"
                    "其他文件不会被删除。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return

            before = bytes(self.project.working)

            def show_progress(done: int, total: int) -> None:
                self.status.showMessage(f"正在导出机体：{done}/{total}")
                QApplication.processEvents()

            result = export_legacy_unit_bitmaps(
                self.project,
                root,
                progress=show_progress,
            )
            if bytes(self.project.working) != before:
                raise RuntimeError("机体导出意外改动了当前 ROM，结果已标记为失败。")
            if result.failures:
                details = "\n".join(
                    f"{unit_id:03d}：{message}"
                    for unit_id, message in result.failures[:12]
                )
                QMessageBox.warning(
                    self,
                    "机体导出部分失败",
                    f"已写入 {len(result.written_files)} 个文件，"
                    f"{len(result.failures)} 个机体失败：\n{details}",
                )
                self.status.showMessage(
                    f"机体导出完成但有 {len(result.failures)} 项失败", 8000
                )
                return
            self.status.showMessage(
                f"机体已导出：{result.root}（{len(result.written_files)} 个 BMP）",
                8000,
            )
        except Exception as error:
            QMessageBox.critical(self, "导出机体失败", str(error))

    def export_avatar(self) -> None:
        if self.project is None:
            return
        from .portrait_export import export_all_portrait_bitmaps, portrait_export_paths

        directory = QFileDialog.getExistingDirectory(
            self,
            "导出全部头像 · 选择根目录",
            str(_default_export_path("导出的头像").parent),
        )
        if not directory:
            return
        try:
            root = writable_output_path(directory)
            character_count = (
                self.project.profile.character_normal_name_count
                or self.project.profile.character_name_count
            )
            existing = 0
            for character_id in range(1, character_count + 1):
                existing += sum(
                    path.exists()
                    for path in portrait_export_paths(self.project, character_id, root)
                )
            if existing:
                answer = QMessageBox.question(
                    self,
                    "覆盖头像文件",
                    f"所选目录中已有 {existing} 个同名头像文件。是否覆盖？\n"
                    "其他文件不会被删除。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return

            before = bytes(self.project.working)

            def show_progress(done: int, total: int) -> None:
                self.status.showMessage(f"正在导出头像：{done}/{total}")
                QApplication.processEvents()

            result = export_all_portrait_bitmaps(
                self.project,
                root,
                progress=show_progress,
            )
            if bytes(self.project.working) != before:
                raise RuntimeError("头像导出意外改动了当前 ROM，结果已标记为失败。")
            if result.failures:
                details = "\n".join(
                    f"{character_id}：{message}"
                    for character_id, message in result.failures[:12]
                )
                QMessageBox.warning(
                    self,
                    "头像导出部分失败",
                    f"已写入 {len(result.written_files)} 个文件，"
                    f"{len(result.failures)} 个人物失败：\n{details}",
                )
                self.status.showMessage(
                    f"头像导出完成但有 {len(result.failures)} 项失败", 8000
                )
                return
            self.status.showMessage(
                f"头像已导出：{result.root}（{len(result.written_files)} 个 BMP）",
                8000,
            )
        except Exception as error:
            QMessageBox.critical(self, "导出头像失败", str(error))

    @property
    def has_unsaved_changes(self) -> bool:
        return (
            self.project is not None
            and self._saved_snapshot is not None
            and (
                bytes(self.project.working) != self._saved_snapshot
                or self.project.resource_allocator.allocations
                != self._saved_allocations
                or self.map_page.has_pending_draft
            )
        )

    def _confirm_discard(self) -> bool:
        if not self.has_unsaved_changes:
            return True
        answer = QMessageBox.question(
            self,
            "尚未保存工程",
            "当前修改尚未保存到工程文件。要放弃这些修改吗？",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    def _set_project(
        self,
        project: RomProject,
        *,
        project_path: Path | None = None,
        saved_snapshot: bytes | None = None,
    ) -> None:
        self.project = project
        from .font_edit import render_character_glyph

        project.font_glyph_renderer = render_character_glyph
        project.set_read_only_output_roots((ROOT / "references",))
        self.project_path = project_path
        self._saved_snapshot = bytes(project.working) if saved_snapshot is None else saved_snapshot
        self._saved_allocations = project.resource_allocator.allocations
        self._count_snapshot = None
        materialized_pages = self.pages.materialized()
        self._stale_pages = set(materialized_pages)
        self._uninitialized_pages = set(materialized_pages)
        for page in materialized_pages:
            if page is self.map_page:
                page.set_project(project)
                self._stale_pages.discard(page)
                self._uninitialized_pages.discard(page)
            else:
                page.set_project_deferred(project)
        self._update_window_state()

    def _activate_project(
        self,
        project: RomProject,
        *,
        project_path: Path | None = None,
        saved_snapshot: bytes | None = None,
    ) -> None:
        self._set_project(
            project,
            project_path=project_path,
            saved_snapshot=saved_snapshot,
        )
        self.rom_output_path = None
        self.show_page("maps")
        if project.profile.key == "dc-kuorong-mmc3-v2" and project.expansion_plan is None:
            self.status.showMessage(
                "ROM已载入；扩展容量尚未规划，可稍后从“扩展功能”进入。",
                8000,
            )

    def load_rom(
        self,
        path: str | Path,
        *,
        quiet: bool = False,
        error_parent: QWidget | None = None,
    ) -> bool:
        try:
            project = RomProject.load(path)
            if not project.rom_image.is_reference_base:
                plan = project.expansion_plan
                if (
                    plan is None
                    and project.profile.key != "dc-kuorong-mmc3-v2"
                ):
                    raise ValueError(
                        f"该ROM布局兼容，但不是“{project.profile.label}”的基准哈希。"
                        "当前版本只能直接续改带有效自动容量表的输出ROM。"
                    )
                if plan is None:
                    for region in project.profile.free_prg_regions:
                        start = 16 + region.first_bank * 0x2000
                        end = 16 + region.end_bank * 0x2000
                        if any(project.original[start:end]):
                            raise ValueError(
                                f"无容量规划表的输出ROM在预留区域 {region.display} "
                                "含未登记的数据，不能安全直接续改。"
                            )
                errors = tuple(
                    issue for issue in project.validate() if issue.severity == "error"
                )
                if errors:
                    detail = "；".join(issue.message for issue in errors[:3])
                    raise ValueError(f"输出ROM完整性校验失败：{detail}")
            self._activate_project(project)
            self.status.showMessage("ROM已安全载入", 4000)
            return True
        except Exception as error:
            if not quiet:
                QMessageBox.critical(error_parent or self, "无法打开ROM", str(error))
            return False

    def open_rom_dialog(self) -> None:
        if not self._confirm_discard():
            return
        start = self.project.path.parent if self.project is not None else DEFAULT_ROM.parent
        filename, _ = QFileDialog.getOpenFileName(
            self, "打开基准ROM", str(start), "NES ROM (*.nes);;所有文件 (*)"
        )
        if filename:
            self.load_rom(filename)

    def open_project_dialog(self) -> None:
        if not self._confirm_discard():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "打开修改工程", str(ROOT), "DC修改工程 (*.dcmod *.json);;所有文件 (*)"
        )
        if not filename:
            return
        base_path = self.project.path if self.project is not None else DEFAULT_ROM
        if not base_path.exists():
            base_name, _ = QFileDialog.getOpenFileName(
                self, "选择工程使用的基准ROM", str(ROOT), "NES ROM (*.nes)"
            )
            if not base_name:
                return
            base_path = Path(base_name)
        try:
            project = RomProject.load_project(filename, base_path)
            self._activate_project(project, project_path=Path(filename).resolve())
            self.status.showMessage("工程已载入", 4000)
        except Exception as error:
            QMessageBox.critical(self, "无法打开工程", str(error))

    def save_project(self) -> None:
        if self.project is None:
            return
        if not self._commit_pending_map():
            return
        if self.project_path is None:
            self.save_project_as()
            return
        try:
            destination = writable_output_path(self.project_path)
            self.project.save_project(destination)
            self._saved_snapshot = bytes(self.project.working)
            self._saved_allocations = self.project.resource_allocator.allocations
            self._update_window_state()
            self.status.showMessage(f"工程已保存：{self.project_path.name}", 4000)
        except Exception as error:
            QMessageBox.critical(self, "无法保存工程", str(error))

    def save_rom(self) -> None:
        if self.project is None:
            return
        if self.rom_output_path is None:
            self.save_rom_as()
            return
        self._write_rom(self.rom_output_path)

    def save_project_as(self) -> None:
        if self.project is None:
            return
        default = _default_export_path(f"{self.project.path.stem}.dcmod")
        filename, _ = QFileDialog.getSaveFileName(
            self, "工程另存为", str(default), "DC修改工程 (*.dcmod)"
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".dcmod":
            path = path.with_suffix(".dcmod")
        try:
            self.project_path = writable_output_path(path)
            self.save_project()
        except Exception as error:
            QMessageBox.critical(self, "无法保存工程", str(error))

    def _commit_pending_map(self) -> bool:
        if not self.map_page.has_pending_draft:
            return True
        error = self.map_page.pending_draft_error
        if error is not None:
            QMessageBox.warning(
                self,
                "地图草稿无法保存",
                f"当前地图、部署或事件输入无效：\n{error}",
            )
            return False
        if not self.map_page.commit_pending_changes():
            QMessageBox.warning(
                self,
                "地图草稿无法保存",
                self.map_page.pending_draft_error
                or "当前地图、部署或事件草稿提交失败。",
            )
            return False
        return True

    def _write_rom(self, destination: Path) -> None:
        if self.project is None or not self._commit_pending_map():
            return
        try:
            destination = writable_output_path(destination)
            self.project.save_as(destination)
            self.rom_output_path = destination
            self._saved_snapshot = bytes(self.project.working)
            self._saved_allocations = self.project.resource_allocator.allocations
            self._update_window_state()
            self.status.showMessage(f"ROM已保存：{destination.name}", 5000)
        except Exception as error:
            QMessageBox.critical(self, "无法保存ROM", str(error))

    def save_rom_as(self) -> None:
        if self.project is None:
            return
        default = _default_export_path(self.project.path.stem + "_modified.nes")
        filename, _ = QFileDialog.getSaveFileName(
            self, "输出修改后的ROM", str(default), "NES ROM (*.nes)"
        )
        if not filename:
            return
        try:
            destination = writable_output_path(filename)
        except Exception as error:
            QMessageBox.critical(self, "无法保存ROM", str(error))
            return
        if destination == self.project.path.resolve():
            QMessageBox.warning(self, "禁止覆盖", "不能覆盖当前载入的基准ROM，请选择新文件名。")
            return
        self._write_rom(destination)

    def export_ips(self) -> None:
        if self.project is None or not self._commit_pending_map():
            return
        default = _default_export_path(self.project.path.stem + "_modified.ips")
        filename, _ = QFileDialog.getSaveFileName(
            self, "导出IPS补丁", str(default), "IPS补丁 (*.ips)"
        )
        if not filename:
            return
        try:
            path = writable_output_path(filename)
            if path.suffix.lower() != ".ips":
                path = path.with_suffix(".ips")
            path = self.project.export_ips(path)
            self.status.showMessage(f"IPS已导出：{path.name}", 5000)
        except Exception as error:
            QMessageBox.critical(self, "无法导出IPS", str(error))

    def build_release(self) -> None:
        if self.project is None or not self._commit_pending_map():
            return
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择构建输出目录",
            str(ROOT / "output" / "releases"),
        )
        if not directory:
            return
        name, accepted = QInputDialog.getText(self, "构建名称", "输出文件名称（不含扩展名）：", text="DC_kuorong_mod")
        if not accepted:
            return
        try:
            artifacts = self.project.build_release(writable_output_path(directory), name)
            QMessageBox.information(
                self,
                "构建完成",
                f"ROM、IPS、工程和报告已生成。\n\n"
                f"修改字节：{artifacts.changed_bytes}\n"
                f"输出哈希：{artifacts.output_sha256}",
            )
        except Exception as error:
            QMessageBox.critical(self, "构建失败", str(error))

    def undo(self) -> None:
        if self.project is None or not self._commit_pending_map():
            return
        if not self.project.can_undo:
            return
        try:
            description = self.project.undo()
            self._refresh_registered_pages(preserve_map_draft=False)
            self._after_edit(f"已撤销：{description}")
        except Exception as error:
            QMessageBox.critical(self, "无法撤销", str(error))

    def redo(self) -> None:
        if self.project is None:
            return
        if self.map_page.has_pending_draft:
            error = self.map_page.pending_draft_error
            detail = (
                f"当前地图、部署或事件输入无效：\n{error}"
                if error is not None
                else "当前地图、部署或事件存在尚未应用的草稿。"
            )
            QMessageBox.warning(
                self,
                "地图草稿阻止重做",
                f"{detail}\n请先应用或还原该草稿，再执行重做。",
            )
            return
        if not self.project.can_redo:
            return
        try:
            description = self.project.redo()
            self._refresh_registered_pages(preserve_map_draft=False)
            self._after_edit(f"已重做：{description}")
        except Exception as error:
            QMessageBox.critical(self, "无法重做", str(error))

    def validate_project(self) -> None:
        if self.project is None or not self._commit_pending_map():
            return
        self._open_extension_page("changes")

    def _after_edit(self, message: str) -> None:
        source = self.sender()
        self._stale_pages.update(self.pages.materialized())
        if isinstance(source, ProjectPage):
            source.refresh()
            self._stale_pages.discard(source)
        self._update_window_state()
        self.status.showMessage(message, 4000)

    def _refresh_registered_pages(self, *, preserve_map_draft: bool) -> None:
        materialized_pages = self.pages.materialized()
        self._stale_pages.update(materialized_pages)
        for page in materialized_pages:
            if (
                preserve_map_draft
                and page is self.map_page
                and self.map_page.has_pending_draft
            ):
                continue
            # Hidden editors are refreshed on their next visit. Rebuilding
            # their tables and previews after every modal close caused stalls.
            if page is self.workspace.currentWidget():
                page.refresh()
                self._stale_pages.discard(page)

    def _update_action_state(self) -> None:
        loaded = self.project is not None
        for action in (
            self.save_rom_action,
            self.save_project_action,
            self.save_project_as_action,
            self.save_rom_as_action,
            self.export_ips_action,
            self.build_action,
            self.validate_action,
            self.rom_data_action,
            self.database_action,
            self.font_library_action,
            self.map_animation_action,
            self.text_converter_action,
            self.scenario_action,
            self.export_unit_action,
            self.export_avatar_action,
            self.attribute_calculator_action,
            self.other_settings_action,
        ):
            action.setEnabled(loaded)
        # The save editor owns an independent SRAM file lifecycle and remains
        # usable before a ROM is loaded.  ROM-backed names/stat derivation is
        # added when a project is available, but is not required to open it.
        self.save_editor_action.setEnabled(True)
        for key, action in self.page_actions.items():
            action.setEnabled(loaded)
        self.undo_action.setEnabled(
            loaded
            and bool(
                (self.project and self.project.can_undo)
                or self.map_page.has_pending_draft
            )
        )
        self.redo_action.setEnabled(loaded and bool(self.project and self.project.can_redo))
        self.data_menu.menuAction().setVisible(True)
        self.extension_menu.menuAction().setVisible(loaded)
        self.project_menu.menuAction().setVisible(loaded)

    def _update_window_state(self) -> None:
        self._update_action_state()
        if self.project is None:
            self.setWindowTitle(LEGACY_WINDOW_TITLE)
            self.path_status.setText("尚未载入ROM")
            self.session_status.setText("尚未载入ROM · 按 Ctrl+O 或“文件→打开”")
            self.change_status.setText("0 字节修改")
            self.map_page.setEnabled(False)
            self.workspace.setCurrentWidget(self.map_page)
            return
        self.map_page.setEnabled(True)
        unsaved = self.has_unsaved_changes
        self.setWindowTitle(f"{LEGACY_WINDOW_TITLE}：{self.project.path}")
        self.path_status.setText(str(self.project.path))
        # Native bytes comparison is inexpensive; avoid enumerating the entire
        # ROM twice per pointer movement/draft notification.
        if self._count_snapshot != self.project.working:
            self._changed_byte_count = len(self.project.change_rows())
            self._count_snapshot = bytes(self.project.working)
        summary = f"{self._changed_byte_count} 字节修改"
        if self.map_page.has_pending_draft:
            summary += " · 地图有未应用草稿"
        self.session_status.setText(summary if unsaved else "已载入 · 无未保存修改")
        self.change_status.setText(summary)

    def show_about(self) -> None:
        QMessageBox.information(
            self,
            "关于新DC篇完整修改器",
            "版本 3.0.0 复刻 SRW2 修改器的主窗口、菜单快捷键、独立数据窗口与确认/取消流程，并启用："
            "机体与图像导入、武器与真实名称、内置剧情字库、地图/部署/踩点事件、"
            "增援/加入等章节事件、劝降条件、战斗音乐绑定、扩展曲导入、工程保存、"
            "撤销/重做、资源视图、ROM/IPS构建与结构验证。\n\n"
            "修改器不会覆盖基准ROM。对外发布时请优先分发IPS补丁，不要直接分发ROM。",
        )

    def show_beginner_guide(self) -> None:
        from .beginner_guide import BeginnerGuideDialog
        from .window_layout import fit_dialog_to_screen

        dialog = BeginnerGuideDialog(self, has_project=self.project is not None)
        dialog.route_requested.connect(
            lambda route: QTimer.singleShot(
                0, lambda selected=route: self._open_beginner_route(selected)
            )
        )
        fit_dialog_to_screen(dialog)
        dialog.exec()
        dialog.deleteLater()

    def _open_beginner_route(self, route: str) -> None:
        if route == "open_rom":
            self.open_rom_dialog()
            return
        if route == "save":
            self.open_save_editor()
            return
        if self.project is None:
            QMessageBox.information(self, "请先打开 ROM", "请先按 Ctrl+O 选择一个 .nes ROM。")
            return
        if route == "maps":
            self.show_page("maps")
            return
        if route.startswith("database:"):
            dialog = self._prepare_database_dialog()
            if dialog is None:
                return
            dialog.tabs.setCurrentIndex(int(route.split(":", 1)[1]))
            self._execute_database_dialog(dialog)
            return
        actions = {
            "scenario": self.open_scenario,
            "font": self.open_font_library,
            "animation": self.open_map_animation,
            "converter": self.open_text_converter,
            "credits": self.open_map_animation,
            "calculator": self.open_attribute_calculator,
            "music": lambda: self._open_extension_page("music"),
            "unit_import": lambda: self._open_extension_page("unit_import"),
            "resources": lambda: self._open_extension_page("resources"),
            "changes": lambda: self._open_extension_page("changes"),
        }
        action = actions.get(route)
        if action is None:
            QMessageBox.warning(self, "向导入口无效", f"未知的新手向导入口：{route}")
            return
        action()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if len(urls) == 1 and Path(urls[0].toLocalFile()).suffix.lower() in (".nes", ".dcmod", ".json"):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        if not self._confirm_discard():
            return
        path = Path(event.mimeData().urls()[0].toLocalFile())
        if path.suffix.lower() == ".nes":
            self.load_rom(path)
        else:
            try:
                base_path = self.project.path if self.project is not None else DEFAULT_ROM
                project = RomProject.load_project(path, base_path)
                self._activate_project(project, project_path=path.resolve())
            except Exception as error:
                QMessageBox.critical(self, "无法打开工程", str(error))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_discard():
            event.accept()
            self.closed.emit()
        else:
            event.ignore()

    def dispatch_legacy_command(self, command_id: int) -> bool:
        """Accept the reference editor's command IDs for Win32 automation."""
        action = self.legacy_commands.get(command_id)
        if action is None or not action.isEnabled():
            return False
        action.trigger()
        return True

    def nativeEvent(self, event_type, message):  # noqa: N802
        if sys.platform == "win32" and bytes(event_type) == b"windows_generic_MSG":
            native_message = wintypes.MSG.from_address(int(message))
            if native_message.message == 0x0111 and native_message.lParam == 0:
                command_id = native_message.wParam & 0xFFFF
                if self.dispatch_legacy_command(command_id):
                    return True, 0
        return super().nativeEvent(event_type, message)


def run() -> int:
    self_test = "--self-test" in sys.argv
    startup_self_test = "--self-test-startup-rom" in sys.argv
    internal_flags = {"--self-test", "--self-test-startup-rom"}
    arguments = [argument for argument in sys.argv if argument not in internal_flags]
    startup_rom = startup_rom_from_arguments(arguments)
    application = QApplication(arguments)
    application.setApplicationName(APP_TITLE)
    application.setOrganizationName("NewDCModding")
    application.setStyle(VisibleArrowStyle("Fusion"))
    application.setFont(QFont("Microsoft YaHei UI", 10))
    application.setStyleSheet(STYLE_SHEET)
    wheel_guard = ControlWheelGuard(application)
    application.installEventFilter(wheel_guard)
    combo_popup_guard = ComboPopupGuard(application)
    application.installEventFilter(combo_popup_guard)
    ui_polisher = ApplicationUiPolisher(application)
    application.installEventFilter(ui_polisher)
    if self_test:
        window = MainWindow(open_default=True)
        window.show()
        application.processEvents()
        valid = (
            window.project is not None
            and window.navigation.count() == 12
            and len(window.pages) == 12
            and window.workspace.currentWidget() is window.map_page
            and window.data_menu.menuAction().isVisible()
        )
        if window.project is not None:
            window._saved_snapshot = bytes(window.project.working)
        window.close()
        application.processEvents()
        return 0 if valid else 91
    launcher = LauncherWindow()
    launcher.show()
    if startup_self_test:
        main = launcher.open_rom(startup_rom) if startup_rom is not None else None
        valid = (
            main is not None
            and main.project is not None
            and main.project.path.resolve() == startup_rom.resolve()
            and not launcher.isVisible()
        )
        if main is not None:
            main._saved_snapshot = bytes(main.project.working) if main.project is not None else None
            main.close()
        if launcher.isVisible():
            launcher.close()
        application.processEvents()
        return 0 if valid else 92
    if startup_rom is not None:
        QTimer.singleShot(0, lambda: launcher.open_rom(startup_rom))
    QTimer.singleShot(0, _start_runtime_warmup)
    return application.exec()
