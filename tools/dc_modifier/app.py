from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from fc_rom_editor_core import RomProject

from .pages import (
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
from .story_page import StoryPage
from .unit_import_page import UnitImportPage


def _workspace_root() -> Path:
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        for candidate in (executable_dir, executable_dir.parent, Path.cwd()):
            if (candidate / "FC模拟器" / "DC_kuorong.nes").is_file():
                return candidate
        return executable_dir
    return Path(__file__).resolve().parents[2]


ROOT = _workspace_root()
DEFAULT_ROM = ROOT / "FC模拟器" / "DC_kuorong.nes"
APP_TITLE = "新DC篇完整修改器"


STYLE_SHEET = """
QMainWindow, QWidget {
    background: #f4f6f8;
    color: #20262e;
}
QMenuBar, QMenu, QToolBar, QStatusBar {
    background: #ffffff;
}
QToolBar {
    border-bottom: 1px solid #d9dee5;
    spacing: 5px;
    padding: 5px;
}
QListWidget#navigation {
    background: #17212b;
    color: #dce5ee;
    border: none;
    padding: 8px;
    outline: 0;
}
QListWidget#navigation::item {
    border-radius: 6px;
    margin: 2px 0;
    padding: 10px 12px;
}
QListWidget#navigation::item:selected {
    background: #2878d0;
    color: white;
}
QLabel#pageTitle {
    color: #17212b;
    font-size: 24px;
    font-weight: 700;
}
QLabel#pageSubtitle, QLabel#hintText {
    color: #647180;
}
QLabel#sectionTitle {
    color: #17212b;
    font-size: 17px;
    font-weight: 650;
}
QFrame#metricCard, QGroupBox {
    background: white;
    border: 1px solid #dce1e7;
    border-radius: 8px;
}
QGroupBox {
    margin-top: 10px;
    padding: 12px 8px 8px 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
}
QLabel#metricLabel {
    color: #647180;
    font-size: 12px;
}
QLabel#metricValue {
    color: #17212b;
    font-size: 16px;
    font-weight: 650;
}
QLabel#emptyState {
    background: white;
    border: 1px dashed #b7c0ca;
    border-radius: 10px;
    color: #647180;
    padding: 24px;
}
QPushButton {
    background: white;
    border: 1px solid #bfc7d1;
    border-radius: 5px;
    padding: 6px 12px;
}
QPushButton:hover { background: #eef4fb; }
QPushButton#primaryButton {
    background: #2878d0;
    border-color: #2878d0;
    color: white;
    font-weight: 600;
}
QPushButton#primaryButton:hover { background: #1f68b8; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTableWidget, QListWidget {
    background: white;
    border: 1px solid #cfd6de;
    border-radius: 4px;
    padding: 4px;
    selection-background-color: #2878d0;
}
QHeaderView::section {
    background: #e9edf2;
    border: none;
    border-right: 1px solid #d7dce2;
    border-bottom: 1px solid #c8cfd7;
    padding: 6px;
    font-weight: 600;
}
"""


class MainWindow(QMainWindow):
    def __init__(self, *, open_default: bool = True) -> None:
        super().__init__()
        self.project: RomProject | None = None
        self.project_path: Path | None = None
        self._saved_snapshot: bytes | None = None
        self.setWindowTitle(APP_TITLE)
        self.resize(1220, 800)
        self.setMinimumSize(980, 650)
        self.setAcceptDrops(True)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setFixedWidth(195)
        self.pages_stack = QStackedWidget()
        self.pages: list[ProjectPage] = []
        self.page_index: dict[str, int] = {}
        self._build_pages()

        central = QWidget()
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.navigation)
        page_host = QWidget()
        page_layout = QVBoxLayout(page_host)
        page_layout.setContentsMargins(20, 16, 20, 16)
        page_layout.addWidget(self.pages_stack)
        central_layout.addWidget(page_host, 1)
        self.setCentralWidget(central)

        self.status = QStatusBar()
        self.path_status = QLabel("尚未载入ROM")
        self.status.addWidget(self.path_status, 1)
        self.change_status = QLabel("0 字节修改")
        self.status.addPermanentWidget(self.change_status)
        self.setStatusBar(self.status)

        self._create_actions()
        self._create_menus_and_toolbar()
        self.navigation.currentRowChanged.connect(self.pages_stack.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        self._update_action_state()

        if open_default and DEFAULT_ROM.exists():
            self.load_rom(DEFAULT_ROM, quiet=True)

    def _add_page(self, key: str, label: str, page: ProjectPage) -> None:
        self.page_index[key] = len(self.pages)
        self.pages.append(page)
        page.project_changed.connect(self._after_edit)
        self.pages_stack.addWidget(page)
        item = QListWidgetItem(label)
        item.setToolTip(label)
        self.navigation.addItem(item)

    def _build_pages(self) -> None:
        self._add_page("overview", "工程概览", OverviewPage())
        self._add_page("units", "机体", UnitPage())
        self._add_page("unit_import", "机体导入与图像", UnitImportPage())
        self._add_page("weapons", "武器", WeaponPage())
        self._add_page("story", "剧情文本", StoryPage())
        self._add_page("maps", "地图与部署", MapPage())
        self._add_page("events", "战场事件", EventPage())
        self._add_page("music", "背景音乐", MusicPage())
        self._add_page("resources", "资源占用", ResourcePage())
        self._add_page("changes", "变更与验证", ChangesPage())

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
        self.open_rom_action = self._action("打开ROM…", self.open_rom_dialog, QKeySequence.StandardKey.Open)
        self.open_project_action = self._action("打开工程…", self.open_project_dialog, "Ctrl+Shift+O")
        self.save_project_action = self._action("保存工程", self.save_project, QKeySequence.StandardKey.Save)
        self.save_project_as_action = self._action("工程另存为…", self.save_project_as, "Ctrl+Shift+S")
        self.save_rom_action = self._action("输出ROM…", self.save_rom_as, "Ctrl+Alt+S")
        self.export_ips_action = self._action("导出IPS…", self.export_ips)
        self.build_action = self._action("一键构建…", self.build_release, "Ctrl+B")
        self.exit_action = self._action("退出", self.close, QKeySequence.StandardKey.Quit)
        self.undo_action = self._action("撤销", self.undo, QKeySequence.StandardKey.Undo)
        self.redo_action = self._action("重做", self.redo, QKeySequence.StandardKey.Redo)
        self.validate_action = self._action("完整检查", self.validate_project, "F7")
        self.about_action = self._action("关于与安全说明", self.show_about)

    def _create_menus_and_toolbar(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(self.open_rom_action)
        file_menu.addAction(self.open_project_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_project_action)
        file_menu.addAction(self.save_project_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_rom_action)
        file_menu.addAction(self.export_ips_action)
        file_menu.addAction(self.build_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)
        edit_menu = self.menuBar().addMenu("编辑")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        tools_menu = self.menuBar().addMenu("工具")
        tools_menu.addAction(self.validate_action)
        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction(self.about_action)

        toolbar = QToolBar("常用操作")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        toolbar.addAction(self.open_rom_action)
        toolbar.addAction(self.save_project_action)
        toolbar.addSeparator()
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)
        toolbar.addSeparator()
        toolbar.addAction(self.validate_action)
        toolbar.addAction(self.build_action)
        self.addToolBar(toolbar)

    @property
    def has_unsaved_changes(self) -> bool:
        return (
            self.project is not None
            and self._saved_snapshot is not None
            and bytes(self.project.working) != self._saved_snapshot
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
        self.project_path = project_path
        self._saved_snapshot = bytes(project.working) if saved_snapshot is None else saved_snapshot
        for page in self.pages:
            page.set_project(project)
        self._update_window_state()

    def load_rom(self, path: str | Path, *, quiet: bool = False) -> bool:
        try:
            project = RomProject.load(path)
            if not project.rom_image.is_reference_base:
                raise ValueError(
                    "该ROM布局兼容，但不是当前 DC_kuorong.nes 基准哈希。"
                    "请从基准ROM建立工程，避免补丁重放到错误版本。"
                )
            self._set_project(project)
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
            self._set_project(project, project_path=Path(filename).resolve())
            self.status.showMessage("工程已载入", 4000)
        except Exception as error:
            QMessageBox.critical(self, "无法打开工程", str(error))

    def save_project(self) -> None:
        if self.project is None:
            return
        if self.project_path is None:
            self.save_project_as()
            return
        try:
            self.project.save_project(self.project_path)
            self._saved_snapshot = bytes(self.project.working)
            self._update_window_state()
            self.status.showMessage(f"工程已保存：{self.project_path.name}", 4000)
        except Exception as error:
            QMessageBox.critical(self, "无法保存工程", str(error))

    def save_project_as(self) -> None:
        if self.project is None:
            return
        default = self.project.path.with_suffix(".dcmod")
        filename, _ = QFileDialog.getSaveFileName(
            self, "工程另存为", str(default), "DC修改工程 (*.dcmod)"
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".dcmod":
            path = path.with_suffix(".dcmod")
        self.project_path = path.resolve()
        self.save_project()

    def save_rom_as(self) -> None:
        if self.project is None:
            return
        default = self.project.path.with_name(self.project.path.stem + "_modified.nes")
        filename, _ = QFileDialog.getSaveFileName(
            self, "输出修改后的ROM", str(default), "NES ROM (*.nes)"
        )
        if not filename:
            return
        destination = Path(filename).resolve()
        if destination == self.project.path.resolve():
            QMessageBox.warning(self, "禁止覆盖", "不能覆盖当前载入的基准ROM，请选择新文件名。")
            return
        try:
            self.project.save_as(destination)
            self.status.showMessage(f"ROM已输出：{destination.name}", 5000)
        except Exception as error:
            QMessageBox.critical(self, "无法输出ROM", str(error))

    def export_ips(self) -> None:
        if self.project is None:
            return
        default = self.project.path.with_name(self.project.path.stem + "_modified.ips")
        filename, _ = QFileDialog.getSaveFileName(
            self, "导出IPS补丁", str(default), "IPS补丁 (*.ips)"
        )
        if not filename:
            return
        try:
            path = self.project.export_ips(filename)
            self.status.showMessage(f"IPS已导出：{path.name}", 5000)
        except Exception as error:
            QMessageBox.critical(self, "无法导出IPS", str(error))

    def build_release(self) -> None:
        if self.project is None:
            return
        directory = QFileDialog.getExistingDirectory(self, "选择构建输出目录", str(ROOT / "build"))
        if not directory:
            return
        name, accepted = QInputDialog.getText(self, "构建名称", "输出文件名称（不含扩展名）：", text="DC_kuorong_mod")
        if not accepted:
            return
        try:
            artifacts = self.project.build_release(directory, name)
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
        if self.project is None or not self.project.can_undo:
            return
        try:
            description = self.project.undo()
            self._after_edit(f"已撤销：{description}")
        except Exception as error:
            QMessageBox.critical(self, "无法撤销", str(error))

    def redo(self) -> None:
        if self.project is None or not self.project.can_redo:
            return
        try:
            description = self.project.redo()
            self._after_edit(f"已重做：{description}")
        except Exception as error:
            QMessageBox.critical(self, "无法重做", str(error))

    def validate_project(self) -> None:
        if self.project is None:
            return
        self.navigation.setCurrentRow(self.page_index["changes"])
        page = self.pages[self.page_index["changes"]]
        assert isinstance(page, ChangesPage)
        page.refresh()
        page.run_validation()

    def _after_edit(self, message: str) -> None:
        for page in self.pages:
            if page is self.sender() and isinstance(page, ChangesPage):
                continue
            page.refresh()
        self._update_window_state()
        self.status.showMessage(message, 4000)

    def _update_action_state(self) -> None:
        loaded = self.project is not None
        for action in (
            self.save_project_action,
            self.save_project_as_action,
            self.save_rom_action,
            self.export_ips_action,
            self.build_action,
            self.validate_action,
        ):
            action.setEnabled(loaded)
        self.undo_action.setEnabled(loaded and bool(self.project and self.project.can_undo))
        self.redo_action.setEnabled(loaded and bool(self.project and self.project.can_redo))

    def _update_window_state(self) -> None:
        self._update_action_state()
        if self.project is None:
            self.setWindowTitle(APP_TITLE)
            self.path_status.setText("尚未载入ROM")
            self.change_status.setText("0 字节修改")
            return
        marker = " *" if self.has_unsaved_changes else ""
        project_name = self.project_path.name if self.project_path else "未命名工程"
        self.setWindowTitle(f"{project_name}{marker} — {APP_TITLE}")
        self.path_status.setText(str(self.project.path))
        self.change_status.setText(f"{len(self.project.change_rows())} 字节修改")

    def show_about(self) -> None:
        QMessageBox.information(
            self,
            "关于新DC篇完整修改器",
            "版本 1.1.0 已启用：机体与图像导入、武器与真实名称、内置剧情字库、地图与部署、"
            "增援/加入/说得等章节事件、战斗音乐绑定、扩展曲导入、工程保存、"
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
                self._set_project(project, project_path=path.resolve())
            except Exception as error:
                QMessageBox.critical(self, "无法打开工程", str(error))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()


def run() -> int:
    self_test = "--self-test" in sys.argv
    arguments = [argument for argument in sys.argv if argument != "--self-test"]
    application = QApplication(arguments)
    application.setApplicationName(APP_TITLE)
    application.setOrganizationName("NewDCModding")
    application.setStyle("Fusion")
    application.setFont(QFont("Microsoft YaHei UI", 10))
    application.setStyleSheet(STYLE_SHEET)
    window = MainWindow()
    window.show()
    if self_test:
        application.processEvents()
        valid = (
            window.project is not None
            and window.navigation.count() == 10
            and window.pages_stack.count() == 10
        )
        if window.project is not None:
            window._saved_snapshot = bytes(window.project.working)
        window.close()
        application.processEvents()
        return 0 if valid else 91
    return application.exec()
