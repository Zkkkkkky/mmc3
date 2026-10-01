from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from dc_modifier.app import ApplicationUiPolisher, MainWindow, STYLE_SHEET, VisibleArrowStyle
from dc_modifier.legacy_tools import (
    AttributeCalculatorDialog,
    FontLibraryDialog,
    OtherSettingsDialog,
)
from dc_modifier.legacy_windows import DatabaseDialog


OUTPUT = ROOT / "output" / "build" / "ui-global-theme"


def capture(widget, filename: str, application: QApplication) -> None:
    widget.show()
    application.processEvents()
    destination = OUTPUT / filename
    if not widget.grab().save(str(destination), "PNG"):
        raise RuntimeError(f"无法保存界面预览：{destination}")
    widget.close()
    application.processEvents()


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    application = QApplication.instance() or QApplication([])
    application.setStyle(VisibleArrowStyle("Fusion"))
    application.setFont(QFont("Microsoft YaHei UI", 10))
    application.setStyleSheet(STYLE_SHEET)
    polisher = ApplicationUiPolisher(application)
    application.installEventFilter(polisher)

    main_window = MainWindow(open_default=True)
    if main_window.project is None:
        raise RuntimeError("未能载入默认ROM，无法生成全局主题预览")
    capture(main_window, "01-main-map.png", application)

    database = DatabaseDialog(main_window.project)
    capture(database, "02-database-unit.png", application)

    calculator = AttributeCalculatorDialog(project=main_window.project)
    capture(calculator, "03-attribute-calculator.png", application)

    other = OtherSettingsDialog(project=main_window.project)
    capture(other, "04-other-settings.png", application)

    font_library = FontLibraryDialog(project=main_window.project)
    capture(font_library, "05-font-library.png", application)
    main_window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
