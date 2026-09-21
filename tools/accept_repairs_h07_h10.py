from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

os.environ["QT_QPA_PLATFORM"] = "windows"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from dc_modifier.character_editor import legacy_portrait_selectors
from dc_modifier.database_records import CharacterAttributesCodec
from dc_modifier.legacy_windows import DatabaseDialog
from dc_modifier.map_page import MapPage
from dc_modifier.unit_appearance_dialog import UnitAppearanceDialog, read_unit_appearance
from dc_modifier.weapon_rule_library import WEAPON_RULE_TABLES, WeaponRuleLibraryDialog
from fc_rom_editor_core import RomProject


EVIDENCE = ROOT / "output" / "verification" / "manual-acceptance-fixes-20260921"
ORIGINAL_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
INPUT_ROM = EVIDENCE / "expanded-acceptance-before.nes"
OUTPUT_ROM = EVIDENCE / "expanded-acceptance-after.nes"
SOURCE_BMP = Path(r"C:\Users\hu\Desktop\千禧年号.bmp")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def capture(widget, filename: str, application: QApplication) -> str:
    widget.show()
    application.processEvents()
    path = EVIDENCE / filename
    if not widget.grab().save(str(path), "PNG"):
        raise RuntimeError(f"无法保存截图：{path}")
    widget.hide()
    return str(path.relative_to(ROOT)).replace("\\", "/")


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    application = QApplication.instance() or QApplication([])
    QMessageBox.warning = staticmethod(
        lambda _parent, title, message, *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(f"{title}：{message}")
        )
    )
    original_before = sha256(ORIGINAL_ROM)
    project = RomProject.load(ORIGINAL_ROM)
    project.configure_expansion(288, 64, 112)
    report: dict[str, object] = {
        "schema_version": 1,
        "input_rom": str(INPUT_ROM.relative_to(ROOT)).replace("\\", "/"),
        "input_sha256": sha256(INPUT_ROM),
        "configured_from_original_in_same_session": True,
        "source_bmp": str(SOURCE_BMP),
        "checks": {},
    }

    # H07: golden files prove the reference writes raw[4]/raw[6] for the
    # front selectors and raw[3]/raw[5] for the background selectors.
    database = DatabaseDialog(project)
    database.character_page.select_record_id(6)
    portrait = CharacterAttributesCodec(project).read_portrait(6)
    selectors = legacy_portrait_selectors(portrait)
    if selectors != (25, 1, 27, 2):
        raise AssertionError(selectors)
    report["checks"]["H07"] = {
        "status": "passed_false_positive_corrected",
        "selectors": {
            "front_bank": selectors[0],
            "front_slot": selectors[1],
            "back_bank": selectors[2],
            "back_slot": selectors[3],
        },
        "golden_front": "output/build/legacy-diff-audit/golden/M06-portrait_front_bank-cold_start_01.json",
        "golden_back": "output/build/legacy-diff-audit/golden/M06-portrait_back_bank-cold_start_01.json",
        "evidence": capture(database, "H07-character-06-reference-fields.png", application),
    }
    database.reject()

    # H08: production event/shop editing is enabled and survives a fresh ROM load.
    map_page = MapPage()
    map_page.resize(1280, 820)
    map_page.set_project(project)
    map_page.editor_tabs.setCurrentIndex(2)
    map_page._update_overlays()
    if not map_page.trigger_table.editing_enabled:
        raise AssertionError("商店/事件表仍为只读")
    test_trigger = (3, 4, 0xFF, 0xF2)
    map_page.trigger_table.set_rows([test_trigger])
    if not map_page.commit_pending_changes():
        raise AssertionError(map_page.pending_draft_error)
    report["checks"]["H08"] = {
        "status": "passed",
        "editing_enabled": True,
        "saved_trigger": list(test_trigger),
        "evidence": capture(map_page, "H08-shop-event-editing-enabled.png", application),
    }
    map_page.close()

    # H10: all four independent reference libraries exist and remain read-only.
    rules = WeaponRuleLibraryDialog(project)
    actual_counts = {
        table.title: rules.lists[table.key].count() for table in WEAPON_RULE_TABLES
    }
    expected_counts = {table.title: table.count for table in WEAPON_RULE_TABLES}
    if actual_counts != expected_counts:
        raise AssertionError(actual_counts)
    if any(not rules.codes[table.key].isReadOnly() for table in WEAPON_RULE_TABLES):
        raise AssertionError("武器规律代码存在非预期写入入口")
    report["checks"]["H10"] = {
        "status": "passed",
        "tab_count": rules.tabs.count(),
        "record_counts": actual_counts,
        "read_only": True,
        "evidence": capture(rules, "H10-four-weapon-rule-tabs.png", application),
    }
    rules.reject()

    # H09: use a real user BMP, a non-zero body offset, save, then reload.
    image = QImage(str(SOURCE_BMP))
    if image.isNull():
        raise AssertionError(f"无法读取真实 BMP：{SOURCE_BMP}")
    unit_id = 0x09
    appearance_before = read_unit_appearance(project, unit_id)
    appearance_dialog = UnitAppearanceDialog(project, unit_id)
    appearance_dialog.body_compress_upload.setChecked(True)
    body_offset = 1
    # Preserve the user's real pixels while trimming the square sample to a
    # 7x9-tile composition that deliberately exercises a non-zero offset.
    import_image = image.copy(8, 0, 112, 128)
    appearance_dialog.body_import_offset.setValue(body_offset)
    appearance_dialog._import_body_image(import_image)
    evidence = capture(
        appearance_dialog, "H09-real-bmp-import-offset-01.png", application
    )
    appearance_dialog.accept()
    if appearance_dialog.result() != appearance_dialog.DialogCode.Accepted:
        raise AssertionError("真实 BMP 导入未通过保存门禁")
    appearance_after = read_unit_appearance(project, unit_id)
    if appearance_after.body_script == appearance_before.body_script:
        raise AssertionError("导入后主体拼图脚本未改变")
    representative_tile = appearance_after.secondary_banks[0] * 64 + body_offset
    representative_pixels = tuple(project.chr_tile_pixels(representative_tile))
    project.save_as(OUTPUT_ROM, make_backup=False)

    reopened = RomProject.load(OUTPUT_ROM)
    reopened_appearance = read_unit_appearance(reopened, unit_id)
    if reopened_appearance.body_script != appearance_after.body_script:
        raise AssertionError("新进程式重开后主体拼图脚本不一致")
    if tuple(reopened.chr_tile_pixels(representative_tile)) != representative_pixels:
        raise AssertionError("新进程式重开后导入图块不一致")
    reopened_triggers = tuple(
        tuple(item.to_bytes()) for item in reopened.get_map_triggers(0)
    )
    if test_trigger not in reopened_triggers:
        raise AssertionError("新进程式重开后商店/事件记录不一致")
    report["checks"]["H09"] = {
        "status": "passed",
        "source_dimensions": [image.width(), image.height()],
        "import_dimensions": [import_image.width(), import_image.height()],
        "body_offset": body_offset,
        "unit_id": unit_id,
        "representative_tile": representative_tile,
        "fresh_reopen_equal": True,
        "evidence": evidence,
    }

    report["output_rom"] = str(OUTPUT_ROM.relative_to(ROOT)).replace("\\", "/")
    report["output_sha256"] = sha256(OUTPUT_ROM)
    report["original_rom_sha256_before"] = original_before
    report["original_rom_sha256_after"] = sha256(ORIGINAL_ROM)
    report["original_rom_unchanged"] = (
        report["original_rom_sha256_before"] == report["original_rom_sha256_after"]
    )
    report["passed"] = bool(report["original_rom_unchanged"])
    report_path = EVIDENCE / "repair-acceptance-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
