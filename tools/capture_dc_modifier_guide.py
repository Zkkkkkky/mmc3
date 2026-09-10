from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from dc_modifier.app import DEFAULT_ROM, LauncherWindow, MainWindow, STYLE_SHEET
from dc_modifier.legacy_tools import (
    AttributeCalculatorDialog,
    FontLibraryDialog,
    MapAnimationDialog,
    OtherSettingsDialog,
    SaveEditorDialog,
    TextConverterDialog,
)
from dc_modifier.legacy_windows import DatabaseDialog, ScenarioDialog
from dc_modifier.pages import ChangesPage
from dc_modifier.unit_import_page import UnitImportPage


OUTPUT_DIRECTORY = ROOT / "docs" / "images" / "dc_modifier"


def process_layout(application: QApplication) -> None:
    for _ in range(6):
        application.processEvents()


def report_capture(path: Path) -> None:
    try:
        print(path.relative_to(ROOT))
    except ValueError:
        print(path)


def save_capture(
    application: QApplication,
    widget: QWidget,
    filename: str,
) -> None:
    widget.show()
    process_layout(application)
    destination = OUTPUT_DIRECTORY / filename
    if not widget.grab().save(str(destination), "PNG"):
        raise RuntimeError(f"截图写入失败：{destination}")
    report_capture(destination)


def close_dialog(application: QApplication, dialog: QDialog) -> None:
    dialog.reject()
    dialog.deleteLater()
    process_layout(application)


def capture_dialog(
    application: QApplication,
    dialog: QDialog,
    filename: str,
) -> None:
    save_capture(application, dialog, filename)
    close_dialog(application, dialog)


def configure_font(application: QApplication) -> None:
    windows_directory = Path(os.environ.get("WINDIR", r"C:\Windows"))
    font_candidates = (
        windows_directory / "Fonts" / "msyh.ttc",
        windows_directory / "Fonts" / "simhei.ttf",
        windows_directory / "Fonts" / "simsun.ttc",
    )
    font_families: list[str] = []
    for font_path in font_candidates:
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        font_families = QFontDatabase.applicationFontFamilies(font_id)
        if font_families:
            break
    if not font_families:
        raise RuntimeError("无法载入说明截图使用的中文字体。")
    for symbol_font in ("seguisym.ttf", "seguiemj.ttf"):
        QFontDatabase.addApplicationFont(
            str(windows_directory / "Fonts" / symbol_font)
        )
    application_font = QFont()
    application_font.setFamilies(
        [font_families[0], "Segoe UI Symbol", "Segoe UI Emoji"]
    )
    application_font.setPointSize(10)
    application.setFont(application_font)


def capture_extension_dialog(
    application: QApplication,
    window: MainWindow,
    page_key: str,
    filename: str,
) -> QDialog:
    dialog = window._create_extension_dialog(page_key)
    save_capture(application, dialog, filename)
    return dialog


def main() -> int:
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("新DC篇完整修改器 3.0 说明截图")
    application.setStyle("Fusion")
    configure_font(application)
    application.setStyleSheet(STYLE_SHEET)
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    # Capture the actual 3.0 route instead of the removed flat page deck:
    # launcher -> empty editor -> explicit ROM open -> persistent map shell.
    launcher = LauncherWindow()
    save_capture(application, launcher, "00-launcher.png")
    launcher.enter_editor()
    process_layout(application)
    window = launcher.main_window
    if window is None:
        raise RuntimeError("启动器未能创建主窗口。")
    save_capture(application, window, "00b-empty-main.png")

    if not DEFAULT_ROM.is_file() or not window.load_rom(DEFAULT_ROM, quiet=True):
        raise RuntimeError("无法载入默认 ROM，不能生成修改器说明截图。")
    window.resize(1257, 998)
    window.show_page("maps")
    save_capture(application, window, "01-map-editor.png")
    assert window.project is not None

    capture_dialog(
        application,
        DatabaseDialog(window.project, window),
        "02-database.png",
    )
    capture_dialog(
        application,
        ScenarioDialog(window.project, window),
        "03-scenario-editor.png",
    )
    capture_dialog(
        application,
        FontLibraryDialog(parent=window, project=window.project),
        "04-font-library.png",
    )
    capture_dialog(
        application,
        MapAnimationDialog(parent=window, project=window.project),
        "05-map-animation.png",
    )
    capture_dialog(
        application,
        TextConverterDialog(parent=window, project=window.project),
        "06-text-converter.png",
    )
    capture_dialog(
        application,
        AttributeCalculatorDialog(parent=window, project=window.project),
        "07-attribute-calculator.png",
    )
    capture_dialog(
        application,
        SaveEditorDialog(parent=window, project=window.project),
        "08-save-editor.png",
    )
    capture_dialog(
        application,
        OtherSettingsDialog(parent=window, project=window.project),
        "09-other-settings.png",
    )

    resource_dialog = capture_extension_dialog(
        application, window, "resources", "10-resource-manager.png"
    )
    close_dialog(application, resource_dialog)

    validation_dialog = capture_extension_dialog(
        application, window, "changes", "11-validation.png"
    )
    validation_page = validation_dialog.page
    if not isinstance(validation_page, ChangesPage):
        raise RuntimeError("变更验证窗口页面类型不正确。")
    validation_page.run_validation()
    process_layout(application)
    destination = OUTPUT_DIRECTORY / "11-validation.png"
    if not validation_dialog.grab().save(str(destination), "PNG"):
        raise RuntimeError(f"截图写入失败：{destination}")
    close_dialog(application, validation_dialog)

    overview_dialog = capture_extension_dialog(
        application, window, "overview", "12-project-overview.png"
    )
    close_dialog(application, overview_dialog)

    import_dialog = capture_extension_dialog(
        application, window, "unit_import", "13-unit-import.png"
    )
    import_page = import_dialog.page
    if not isinstance(import_page, UnitImportPage):
        raise RuntimeError("机体导入窗口页面类型不正确。")
    import_page.tabs.setCurrentIndex(1)
    process_layout(application)
    chr_destination = OUTPUT_DIRECTORY / "13b-chr-editor.png"
    if not import_dialog.grab().save(str(chr_destination), "PNG"):
        raise RuntimeError(f"截图写入失败：{chr_destination}")
    report_capture(chr_destination)
    close_dialog(application, import_dialog)

    music_dialog = capture_extension_dialog(
        application, window, "music", "14-music-editor.png"
    )
    close_dialog(application, music_dialog)

    window._saved_snapshot = bytes(window.project.working)
    window.close()
    launcher.close()
    process_layout(application)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
