from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from dc_modifier.app import MainWindow, STYLE_SHEET
from dc_modifier.pages import ChangesPage
from dc_modifier.unit_import_page import UnitImportPage


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = ROOT / "docs" / "images" / "dc_modifier"
CAPTURES = (
    ("maps", "01-map-editor.png"),
    ("units", "02-unit-editor.png"),
    ("characters", "03-character-editor.png"),
    ("weapons", "04-weapon-editor.png"),
    ("unit_import", "05-unit-import.png"),
    ("story", "06-story-editor.png"),
    ("events", "07-event-editor.png"),
    ("persuasion", "08-persuasion-editor.png"),
    ("music", "09-music-editor.png"),
    ("resources", "10-resource-manager.png"),
    ("changes", "11-validation.png"),
    ("overview", "12-project-overview.png"),
)


def process_layout(application: QApplication) -> None:
    for _ in range(4):
        application.processEvents()


def main() -> int:
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("新DC篇完整修改器说明截图")
    application.setStyle("Fusion")
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
        raise RuntimeError("无法载入说明截图使用的微软雅黑字体。")
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
    application.setStyleSheet(STYLE_SHEET)
    window = MainWindow(open_default=True)
    if window.project is None:
        raise RuntimeError("无法载入默认 ROM，不能生成修改器说明截图。")

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    window.resize(1280, 900)
    window.show()
    process_layout(application)

    for page_key, filename in CAPTURES:
        window.show_page(page_key)
        if page_key == "changes":
            changes_page = window.pages[window.page_index["changes"]]
            if not isinstance(changes_page, ChangesPage):
                raise RuntimeError("变更验证页面类型不正确。")
            changes_page.run_validation()
        process_layout(application)
        destination = OUTPUT_DIRECTORY / filename
        if not window.grab().save(str(destination), "PNG"):
            raise RuntimeError(f"截图写入失败：{destination}")
        print(destination.relative_to(ROOT))

    window.show_page("unit_import")
    unit_import_page = window.pages[window.page_index["unit_import"]]
    if not isinstance(unit_import_page, UnitImportPage):
        raise RuntimeError("机体导入页面类型不正确。")
    unit_import_page.tabs.setCurrentIndex(1)
    process_layout(application)
    chr_destination = OUTPUT_DIRECTORY / "05b-chr-editor.png"
    if not window.grab().save(str(chr_destination), "PNG"):
        raise RuntimeError(f"截图写入失败：{chr_destination}")
    print(chr_destination.relative_to(ROOT))

    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
