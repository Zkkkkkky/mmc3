from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.map_page import MapPage
from fc_rom_editor_core import RomProject


OUTPUT = ROOT / "output" / "build" / "map-trigger-reference-style"


def main() -> int:
    application = QApplication.instance() or QApplication([])
    font_id = QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    families = QFontDatabase.applicationFontFamilies(font_id)
    if families:
        application.setFont(QFont(families[0], 10))
    page = MapPage()
    page.resize(1065, 876)
    page.set_project(RomProject.load(DEFAULT_ROM))
    page.editor_tabs.setCurrentIndex(2)
    page.trigger_table.set_rows(
        [
            (12, 18, 0xFF, 0x00),
            (13, 17, 0xFF, 0xF0),
        ]
    )
    page._refresh_object_lists()
    page._update_overlays()
    page.show()
    application.processEvents()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT / "地图事件与商店-参考式标识.png"
    if not page.grab().save(str(destination), "PNG"):
        return 1
    page._open_trigger_cell_editor(12, 18, 0)
    page.trigger_event_combo.setCurrentIndex(
        page.trigger_event_combo.findData(13)
    )
    page.trigger_event_combo.showPopup()
    application.processEvents()
    popup_destination = OUTPUT / "地图事件下拉-从事件1开始.png"
    if not page.trigger_event_combo.view().grab().save(
        str(popup_destination), "PNG"
    ):
        return 1
    page.trigger_event_combo.hidePopup()
    page.trigger_character_combo.setCurrentIndex(
        page.trigger_character_combo.findData(0x1D)
    )
    unknown_destination = OUTPUT / "设置地图事件-未知人物可用.png"
    if not page.trigger_cell_dialog.grab().save(
        str(unknown_destination), "PNG"
    ):
        return 1
    page.trigger_character_combo.showPopup()
    application.processEvents()
    character_destination = OUTPUT / "触发人物下拉-紧凑.png"
    if not page.trigger_character_combo.view().grab().save(
        str(character_destination), "PNG"
    ):
        return 1
    page.trigger_character_combo.hidePopup()
    page.trigger_cell_dialog.close()
    page.close()
    page.deleteLater()
    application.processEvents()
    print(destination)
    print(popup_destination)
    print(unknown_destination)
    print(character_destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
