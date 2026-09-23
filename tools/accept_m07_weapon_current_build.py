"""Verify the current weapon editor through real Qt controls and isolated ROMs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from unittest.mock import patch

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.database_records import weapon_extra_values
from dc_modifier.legacy_windows import DatabaseDialog
from dc_modifier.weapon_rule_library import WEAPON_RULE_TABLES, WeaponRuleLibraryDialog
from fc_editor.codecs.animation import AnimationCodec
from fc_rom_editor_core import RomProject


OUT = ROOT / "output/verification/m07-weapon-current-build-20260922"
EDIT_ROM = OUT / "m07-weapon-edited.nes"
REPORT = OUT / "report.json"
WEAPON_ID = 1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    source = Path(DEFAULT_ROM).resolve()
    source_hash = sha256(source)
    checks: dict[str, bool] = {}
    project = RomProject.load(source)
    before = bytes(project.working)
    offset = project.weapon_codec.record_offset(WEAPON_ID)
    old_record = project.weapon_record_bytes(WEAPON_ID)

    dialog = DatabaseDialog(project)
    dialog.show()
    app.processEvents()
    dialog._select_weapon(WEAPON_ID)
    page = dialog.weapon_page
    checks["weapon_unique_record"] = page.shared_weapon_record_ids(WEAPON_ID) == (WEAPON_ID,)
    checks["all_weapon_ids_visible"] = page.records.count() == 255
    checks["field_editor_enabled"] = page.fields["hit"].isEnabled() and page.weapon_skill.isEnabled()

    # F-039: the usage tab is built from the real unit weapon slots, and its
    # actual button must navigate back to the selected unit.
    expected_usage = tuple(
        unit_id
        for unit_id in range(1, project.unit_count)
        if WEAPON_ID in project.get_unit_weapons(unit_id)
    )
    actual_usage = tuple(
        int(page.usage_list.item(row).data(Qt.ItemDataRole.UserRole))
        for row in range(page.usage_list.count())
    )
    checks["usage_list_matches_real_slots"] = bool(expected_usage) and actual_usage == expected_usage
    page.weapon_animation.setCurrentIndex(2)
    page.usage_list.setCurrentRow(0)
    jump = next(
        button
        for button in page.findChildren(type(page.apply_button))
        if button.text() == "转到所选机体"
    )
    jump.click()
    app.processEvents()
    checks["usage_button_jumps_to_unit"] = (
        dialog.tabs.currentIndex() == 0
        and dialog.unit_page.current_id == expected_usage[0]
    )
    dialog._select_weapon(WEAPON_ID)
    page = dialog.weapon_page

    page.fields["hit"].setValue(111)
    page.weapon_skill.setCurrentIndex(11)
    page.distance_correction.setValue(2)
    checks["field_draft_exists"] = page.has_pending_draft
    checks["project_unchanged_before_apply"] = bytes(project.working) == before
    page.grab().save(str(OUT / "01-weapon-field-draft.png"))
    with patch("dc_modifier.database_records.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
        page.apply_record()
    checks["field_apply_clears_draft"] = not page.has_pending_draft
    checks["field_values_applied"] = (
        project.get_weapon_value(WEAPON_ID, "hit") == 111
        and weapon_extra_values(project, WEAPON_ID) == (11, 2)
    )
    changed = {index for index, (a, b) in enumerate(zip(before, project.working)) if a != b}
    checks["exact_three_byte_delta"] = changed == {offset, offset + 1, offset + 2}
    new_record = project.weapon_record_bytes(WEAPON_ID)
    checks["range_and_reserved_nibbles_preserved"] = (
        new_record[0] & 0x0F == old_record[0] & 0x0F
        and new_record[2] & 0xF0 == old_record[2] & 0xF0
    )

    # F-041: both mode tabs must decode real scripts and independently accept
    # one legal same-length parameter change through the normal Apply action.
    checks["ally_enemy_animation_tabs"] = (
        page.weapon_animation.count() == 3
        and page.weapon_animation.tabText(0) == "我方武器动画"
        and page.weapon_animation.tabText(1) == "敌方武器动画"
        and page.weapon_animation.tabText(2) == "使用此武器的机体"
    )
    expected_animation: dict[str, bytes] = {}
    animation_offsets: dict[str, int] = {}
    for kind, editor in zip(("ally", "enemy"), page.weapon_animation.editors):
        assert editor.record is not None
        replacement = bytearray(editor.record.raw)
        parameter_changed = False
        for instruction in editor.record.instructions:
            for local, low, high in instruction.editable:
                byte_index = instruction.offset - editor.record.offset + local
                candidate = low if replacement[byte_index] != low else high
                if candidate != replacement[byte_index]:
                    replacement[byte_index] = candidate
                    parameter_changed = True
                    break
            if parameter_changed:
                break
        checks[f"{kind}_animation_has_editable_parameter"] = parameter_changed
        expected_animation[kind] = bytes(replacement)
        animation_offsets[kind] = editor.record.offset
        editor.code_edit.setPlainText(bytes(replacement).hex(" ").upper())
    checks["both_animation_modes_pending"] = all(
        editor.has_pending_changes() for editor in page.weapon_animation.editors
    )
    with patch("dc_modifier.database_records.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
        page.apply_record()
    checks["both_animation_modes_applied"] = all(
        bytes(project.working[offset:offset + len(expected_animation[kind])])
        == expected_animation[kind]
        for kind, offset in animation_offsets.items()
    ) and not page.weapon_animation.has_pending_changes()
    page.weapon_animation.setCurrentIndex(1)
    page.grab().save(str(OUT / "02-weapon-modes-and-usage.png"))

    dialog.accept()
    checks["outer_dialog_accepted"] = dialog.result() == QDialog.DialogCode.Accepted
    project.save_as(EDIT_ROM, make_backup=False)
    dialog.deleteLater()
    app.processEvents()

    reopened = RomProject.load(EDIT_ROM)
    checks["save_reopen_exact"] = (
        reopened.weapon_record_bytes(WEAPON_ID) == new_record
        and reopened.get_weapon_value(WEAPON_ID, "hit") == 111
        and weapon_extra_values(reopened, WEAPON_ID) == (11, 2)
    )
    reopened_animations = AnimationCodec(reopened.working)
    checks["animation_modes_save_reopen_exact"] = all(
        reopened_animations.record(kind, WEAPON_ID).raw == expected
        for kind, expected in expected_animation.items()
    )

    # The four rule libraries keep code read-only while project-local names
    # are editable and cancelable without touching ROM bytes.
    rules_before = bytes(reopened.working)
    rules = WeaponRuleLibraryDialog(reopened)
    rules.show()
    app.processEvents()
    counts = {table.key: rules.lists[table.key].count() for table in WEAPON_RULE_TABLES}
    checks["four_rule_tabs_and_counts"] = (
        rules.tabs.count() == 4
        and list(counts.values()) == [255, 252, 250, 255]
    )
    checks["rule_names_editable_and_code_read_only"] = all(
        not rules.names[table.key].isReadOnly() and rules.codes[table.key].isReadOnly()
        for table in WEAPON_RULE_TABLES
    )
    for table in WEAPON_RULE_TABLES:
        rules.tabs.setCurrentIndex(next(index for index in range(4) if rules.tabs.tabText(index) == table.title))
        rules.lists[table.key].setCurrentRow(table.count - 1)
        app.processEvents()
    rules.grab().save(str(OUT / "03-four-rule-libraries.png"))
    rules.reject()
    rules.deleteLater()
    app.processEvents()
    checks["rule_browsing_zero_write"] = bytes(reopened.working) == rules_before

    # Invalid animation code must not partially commit a legal hit change.
    guard = DatabaseDialog(reopened)
    guard.show()
    app.processEvents()
    guard._select_weapon(WEAPON_ID)
    guard_page = guard.weapon_page
    guard_page.fields["hit"].setValue(112)
    guard_page.weapon_animation.editors[0].code_edit.setPlainText("ZZ")
    guard_before = bytes(reopened.working)
    with patch.object(guard_page, "show_error") as error:
        guard_page.apply_record()
    checks["invalid_animation_rejected"] = error.called and guard_page.has_pending_draft
    checks["invalid_animation_atomic"] = bytes(reopened.working) == guard_before
    guard.reject()
    guard.deleteLater()
    app.processEvents()
    checks["cancel_preserves_reopened_rom"] = bytes(reopened.working) == guard_before
    checks["recommended_rom_unchanged"] = sha256(source) == source_hash

    report = {
        "schema_version": 1,
        "module": "M07",
        "scope": "Current-build GUI-to-disk acceptance, without emulator combat playback",
        "passed": all(checks.values()),
        "checks": checks,
        "details": {
            "source_rom": str(source),
            "source_sha256": source_hash,
            "edited_rom_sha256": sha256(EDIT_ROM),
            "weapon_id": WEAPON_ID,
            "record_offset": f"0x{offset:06X}",
            "record_before": old_record.hex(" ").upper(),
            "record_after": new_record.hex(" ").upper(),
            "changed_offsets": [f"0x{index:06X}" for index in sorted(changed)],
            "usage_weapon_id": WEAPON_ID,
            "usage_unit_ids": list(expected_usage),
            "animation_offsets": {
                kind: f"0x{offset:06X}"
                for kind, offset in animation_offsets.items()
            },
            "rule_counts": counts,
        },
        "artifacts": [
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in (
                EDIT_ROM,
                OUT / "01-weapon-field-draft.png",
                OUT / "02-weapon-modes-and-usage.png",
                OUT / "03-four-rule-libraries.png",
            )
        ],
        "note": "Machine acceptance does not expand the 2026-09-21 user sign-off or unlock read-only rule code.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "passed": report["passed"], "checks": checks}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
