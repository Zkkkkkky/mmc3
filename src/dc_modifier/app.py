from __future__ import annotations

import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QAction, QCloseEvent, QColor, QDragEnterEvent, QDropEvent, QFont,
    QKeySequence, QPolygon,
)
from PySide6.QtWidgets import (
    QApplication,
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


def _forget_active_editor() -> None:
    global _ACTIVE_EDITOR_WINDOW
    _ACTIVE_EDITOR_WINDOW = None


class VisibleArrowStyle(QProxyStyle):
    """Draw high-contrast arrows for every numeric spin control."""

    def drawPrimitive(self, element, option, painter, widget=None) -> None:  # noqa: N802
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


STYLE_SHEET = """
QMainWindow, QDialog, QWidget {
    background: #f3f7fb;
    color: #111111;
}
QMenuBar, QMenu, QStatusBar { background: #fbfdff; }
QMenuBar { border-bottom: 1px solid #86c7e7; }
QMenuBar::item { padding: 5px 12px; }
QMenuBar::item:selected, QMenu::item:selected {
    background: #cdefff;
    color: #092b3d;
}
QMenu::item { padding: 5px 30px 5px 22px; }
QTabWidget::pane {
    background: #f7fbfe;
    border: 1px solid #6fc4eb;
    top: -1px;
}
QTabBar::tab {
    background: #f7fbfe;
    border: 1px solid #8ebfd7;
    border-bottom: none;
    padding: 6px 13px;
    margin-right: 1px;
}
QTabBar::tab:selected {
    background: white;
    color: #1837a0;
}
QLabel#pageTitle, QLabel#pageSubtitle { max-height: 0px; min-height: 0px; }
QLabel#hintText { color: #53636e; }
QLabel#sectionTitle { color: #173b50; font-size: 16px; font-weight: 600; }
QLabel#romBadge, QLabel#countBadge {
    background: #e4f5fd;
    border: 1px solid #70bfdf;
    padding: 2px 7px;
}
QLabel#pendingBanner, QLabel#editState {
    background: #eef8f0;
    border: 1px solid #97caa2;
    color: #28643a;
    padding: 5px 8px;
}
QLabel#editState[pending="true"] {
    background: #fff8e5;
    border-color: #dcb768;
    color: #835100;
}
QFrame#metricCard, QGroupBox {
    background: #fbfdff;
    border: 1px solid #62c3ed;
    border-radius: 2px;
}
QGroupBox {
    margin-top: 10px;
    padding: 11px 7px 7px 7px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QLabel#metricLabel { color: #53636e; font-size: 12px; }
QLabel#metricValue { font-size: 15px; font-weight: 600; }
QLabel#emptyState {
    background: white;
    border: 1px dashed #8fb8cc;
    color: #5f6970;
    padding: 18px;
}
QPushButton, QToolButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffffff, stop:0.5 #d8f3ff, stop:1 #74ccef);
    border: 1px solid #478fac;
    border-radius: 2px;
    padding: 5px 11px;
}
QPushButton:hover, QToolButton:hover { background: #c5efff; }
QPushButton:pressed, QToolButton:pressed { background: #8fd7f4; }
QPushButton:disabled, QToolButton:disabled {
    background: #edf1f3;
    border-color: #bdc8ce;
    color: #8b969c;
}
QPushButton#primaryButton { font-weight: 600; }
QPushButton#terrainButton { min-width: 38px; min-height: 34px; padding: 1px; }
QPushButton#terrainButton:checked { border: 2px solid #164a9a; background: #b9e9ff; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTableWidget, QListWidget {
    background: white;
    border: 1px solid #77b8d4;
    border-radius: 0;
    padding: 3px;
    selection-background-color: #1686c4;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus,
QTableWidget:focus, QListWidget:focus { border: 1px solid #1879ac; }
QHeaderView::section {
    background: #e9f5fb;
    border: none;
    border-right: 1px solid #bed5df;
    border-bottom: 1px solid #a9c6d4;
    padding: 5px;
    font-weight: 600;
}
"""


class LauncherWindow(QDialog):
    """Reference-compatible launch screen shown before the editor session."""

    def __init__(self) -> None:
        super().__init__()
        self.main_window: MainWindow | None = None
        self.setWindowTitle(LAUNCHER_TITLE)
        self.resize(520, 360)
        self.setMinimumSize(400, 240)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 20, 15, 20)
        introduction = QLabel("作者 断月残心")
        introduction.setObjectName("launcherAuthor")
        introduction.setStyleSheet("color: #ef4e4e; font-family: SimSun; font-size: 20px;")
        introduction.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(introduction, 1)

        enter = QPushButton("进入修改器")
        enter.setObjectName("launcherEnterButton")
        enter.setMinimumSize(160, 58)
        enter.clicked.connect(self.enter_editor)
        enter_row = QHBoxLayout()
        enter_row.addStretch()
        enter_row.addWidget(enter)
        enter_row.addStretch()
        layout.addLayout(enter_row)

    def enter_editor(self) -> MainWindow:
        global _ACTIVE_EDITOR_WINDOW
        if self.main_window is not None:
            self.main_window.raise_()
            self.main_window.activateWindow()
            return self.main_window
        self.main_window = MainWindow(open_default=False)
        main = self.main_window
        _ACTIVE_EDITOR_WINDOW = main
        main.closed.connect(_forget_active_editor)
        main.show()
        # The launch window is not part of the editor's hidden-window session.
        self.close()
        return main


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
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        self._stale_pages: set[ProjectPage] = set()
        self._count_snapshot: bytes | None = None
        self._changed_byte_count = 0
        self._database_dialog: QDialog | None = None
        self._database_dialog_snapshot: bytes | None = None
        self.setAcceptDrops(True)

        # Keep a non-visual registry for automated functional checks. Only the
        # map page is part of the normal main-window route; all other editors
        # are constructed afresh in independent transaction dialogs.
        self.navigation = QListWidget(self)
        self.navigation.hide()
        self.pages: list[ProjectPage] = []
        self.page_index: dict[str, int] = {}
        self.page_stack_index: dict[str, int] = {}
        self.workspace = QStackedWidget()
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
        page.project_changed.connect(self._after_edit)
        page.navigation_requested.connect(self._open_extension_page)
        item = QListWidgetItem(label)
        item.setToolTip(label)
        self.navigation.addItem(item)
        self.page_stack_index[key] = self.workspace.addWidget(page)

    def _build_pages(self) -> None:
        self._add_page("maps", "战场地图", MapPage())
        self._add_page("units", "机体", UnitPage())
        self._add_page("characters", "人物", CharacterPage())
        self._add_page("weapons", "武器", WeaponPage())
        self._add_page("unit_import", "机体导入与图像", UnitImportPage())
        self._add_page("story", "剧情文本", StoryPage())
        self._add_page("events", "战场事件", EventPage())
        self._add_page("persuasion", "劝降条件", PersuasionPage())
        self._add_page("music", "背景音乐", MusicPage())
        self._add_page("overview", "工程概览", OverviewPage())
        self._add_page("resources", "容量规划", ResourcePage())
        self._add_page("changes", "变更与验证", ChangesPage())

    def show_page(self, key: str) -> None:
        """Select a registered page for tests/capture; menus use dialogs."""
        if key not in self.page_stack_index:
            raise KeyError(f"未知页面：{key}")
        page = self.pages[self.page_index[key]]
        if page in self._stale_pages and not page.has_pending_draft:
            page.refresh()
            self._stale_pages.discard(page)
        self.workspace.setCurrentIndex(self.page_stack_index[key])
        row = self.page_index[key]
        self.navigation.blockSignals(True)
        self.navigation.setCurrentRow(row)
        self.navigation.blockSignals(False)
        self.module_status.setText(self.navigation.item(row).text())

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
        self.export_avatar_action.setEnabled(False)
        self.export_avatar_action.setStatusTip(
            "参考版此入口不可触发；增强头像 BMP 导出已移至“扩展功能”。"
        )
        self.export_avatar_action.setToolTip(self.export_avatar_action.statusTip())
        self.export_avatar_extended_action = self._action(
            "导出头像 BMP（增强）", self.export_avatar
        )
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
        self.extension_menu.addAction(self.export_avatar_extended_action)
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
        help_menu.addAction(self.about_action)

    def _map_coordinate_changed(self, x: int, y: int) -> None:
        self.x_status.setText(f"X坐标：{x}")
        self.y_status.setText(f"Y坐标：{y}")

    def _run_project_dialog(self, dialog: QDialog, success_message: str) -> int:
        from .window_layout import fit_dialog_to_screen
        fit_dialog_to_screen(dialog)
        if hasattr(dialog, "project_changed"):
            dialog.project_changed.connect(self._dialog_edit_notice)
        result = dialog.exec()
        self._refresh_registered_pages(preserve_map_draft=True)
        self._update_window_state()
        if result == QDialog.DialogCode.Accepted:
            self.status.showMessage(success_message, 4000)
        dialog.deleteLater()
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
            dialog = DatabaseDialog(self.project, self)
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

        self._run_tool_dialog(RomDataBrowserDialog(self.project, self))

    def open_scenario(self) -> None:
        if self.project is None:
            return
        from .legacy_windows import ScenarioDialog

        self._run_project_dialog(ScenarioDialog(self.project, self), "剧情事件修改已确认")

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
            from .legacy_windows import DatabaseDialog

            dialog = DatabaseDialog(self.project, self)
            dialog.tabs.setCurrentIndex(
                {"units": 0, "characters": 1, "weapons": 2}[key]
            )
            self._run_project_dialog(dialog, "数据库修改已确认")
            return
        if key in {"story", "events", "persuasion"}:
            from .legacy_windows import ScenarioDialog

            dialog = ScenarioDialog(self.project, self)
            dialog.tabs.setCurrentIndex(
                {"events": 1, "persuasion": 2, "story": 4}[key]
            )
            self._run_project_dialog(dialog, "剧情事件修改已确认")
            return
        dialog = self._create_extension_dialog(key)
        requested: list[str] = []

        def finish_before_navigation(page_key: str) -> None:
            requested.append(page_key)
            dialog.accept()

        dialog.navigation_requested.connect(finish_before_navigation)
        self._run_project_dialog(dialog, f"{dialog.windowTitle()}已确认")
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
        from .portrait_export import export_portrait_bitmaps, portrait_export_paths

        root_name = QFileDialog.getExistingDirectory(
            self,
            "导出头像 · 选择根目录",
            str(_default_export_path("头像导出").parent),
        )
        if not root_name:
            return
        labels = [
            f"{character_id:03d} · {self.project.character_display_name(character_id)}"
            for character_id in range(1, self.project.profile.character_name_count)
        ]
        selected, accepted = QInputDialog.getItem(
            self, "导出头像", "选择人物：", labels, 0, False
        )
        if not accepted:
            return
        character_id = labels.index(selected) + 1
        try:
            root = writable_output_path(root_name)
            paths = portrait_export_paths(self.project, character_id, root)
            if any(path.exists() for path in paths):
                answer = QMessageBox.question(
                    self,
                    "覆盖头像文件",
                    f"{paths[0].parent.name} 已有头像文件。是否覆盖？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            back_path, front_path, effect_path = export_portrait_bitmaps(
                self.project, character_id, root
            )
            self.status.showMessage(
                f"头像已导出：{back_path.parent.name}（3 个 BMP）", 5000
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
        project.set_read_only_output_roots((ROOT / "references",))
        self.project_path = project_path
        self._saved_snapshot = bytes(project.working) if saved_snapshot is None else saved_snapshot
        self._saved_allocations = project.resource_allocator.allocations
        self._count_snapshot = None
        self._stale_pages.clear()
        for page in self.pages:
            page.set_project(project)
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

    def load_rom(self, path: str | Path, *, quiet: bool = False) -> bool:
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
                QMessageBox.critical(self, "无法打开ROM", str(error))
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
        self._stale_pages.update(self.pages)
        if isinstance(source, ProjectPage):
            source.refresh()
            self._stale_pages.discard(source)
        self._update_window_state()
        self.status.showMessage(message, 4000)

    def _refresh_registered_pages(self, *, preserve_map_draft: bool) -> None:
        self._stale_pages.update(self.pages)
        for page in self.pages:
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
            self.export_avatar_extended_action,
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
        # D2: preserve the reference command and Ctrl+L binding, but never
        # route it to the extension exporter because the stock entry is inert.
        self.export_avatar_action.setEnabled(False)
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
    arguments = [argument for argument in sys.argv if argument != "--self-test"]
    application = QApplication(arguments)
    application.setApplicationName(APP_TITLE)
    application.setOrganizationName("NewDCModding")
    application.setStyle(VisibleArrowStyle("Fusion"))
    application.setFont(QFont("Microsoft YaHei UI", 10))
    application.setStyleSheet(STYLE_SHEET)
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
    return application.exec()
