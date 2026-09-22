"""Exercise the current M04 GUI against an isolated ROM and reopen each save."""

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
from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.map_page import MapPage
from fc_rom_editor_core import RomProject


OUT = ROOT / "output/verification/m04-shop-events-20260922"
BASE_ROM = OUT / "m04-normalized-empty-baseline.nes"
FIELD_ROM = OUT / "m04-field-edit.nes"
ADD_ROM = OUT / "m04-add-shop.nes"
DELETE_ROM = OUT / "m04-delete-shop.nes"
REPORT = OUT / "report.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def trigger_rows(project: RomProject, map_id: int) -> list[list[int]]:
    return [list(row.to_bytes()) for row in project.get_map_triggers(map_id)]


def open_page(app: QApplication, project: RomProject, map_id: int) -> MapPage:
    page = MapPage()
    page.resize(1280, 820)
    page.set_project(project)
    page.show()
    app.processEvents()
    row = next(
        index
        for index in range(page.map_list.count())
        if page.map_list.item(index).data(Qt.ItemDataRole.UserRole) == map_id
    )
    page.map_list.setCurrentRow(row)
    page.editor_tabs.setCurrentIndex(2)
    app.processEvents()
    return page


def close_page(app: QApplication, page: MapPage) -> None:
    page.close()
    page.deleteLater()
    app.processEvents()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    source = Path(DEFAULT_ROM).resolve()
    source_hash = sha256(source)
    checks: dict[str, bool] = {}
    original = RomProject.load(source)
    baseline = {map_id: trigger_rows(original, map_id) for map_id in range(32)}
    empty_map = next(map_id for map_id, rows in baseline.items() if not rows)

    # A first write migrates legacy pointers to the deterministic managed
    # layout. Compare reversibility with that empty, normalized layout, not
    # with the source ROM's different but semantically equivalent layout.
    original.set_map_triggers(empty_map, tuple())
    original.save_as(BASE_ROM, make_backup=False)
    checks["normalized_baseline_semantics_unchanged"] = all(
        trigger_rows(original, map_id) == rows for map_id, rows in baseline.items()
    )

    # The recommended ROM's one existing event is outside the reference
    # editor's fixed viewport.  Do not treat it as a field-golden sample.
    # Create a visible, structurally verified shop first, then edit that row.
    page = open_page(app, original, empty_map)
    checks["event_tab_enabled"] = page.trigger_table.editing_enabled and page.canvas.trigger_edit_enabled
    checks["empty_map_is_empty_not_error"] = page.trigger_objects.count() == 0 and "没有" in page.trigger_summary.text()
    page._open_trigger_cell_editor(3, 4, shop=True)
    app.processEvents()
    checks["shop_editor_visible"] = page.trigger_cell_dialog.isVisible() and page.trigger_shop_radio.isChecked()
    shop_model = page.trigger_shop_combo.model()
    checks["invalid_shops_disabled"] = all(
        not shop_model.item(page.trigger_shop_combo.findData(shop_id)).isEnabled()
        for shop_id in range(0xF5, 0xFF)
    )
    page.trigger_shop_combo.setCurrentIndex(page.trigger_shop_combo.findData(0xF2))
    page._save_trigger_cell_editor()
    checks["add_draft_exact"] = page.trigger_table.rows() == [(3, 4, 0xFF, 0xF2)]
    page.grab().save(str(OUT / "02-added-shop.png"))
    checks["add_commit"] = page.commit_pending_changes()
    original.save_as(ADD_ROM, make_backup=False)
    close_page(app, page)
    added = RomProject.load(ADD_ROM)
    checks["add_reopen_exact"] = trigger_rows(added, empty_map) == [[3, 4, 0xFF, 0xF2]]
    checks["other_maps_unchanged_after_add"] = all(
        trigger_rows(added, map_id) == rows
        for map_id, rows in baseline.items() if map_id != empty_map
    )

    page = open_page(app, added, empty_map)
    checks["existing_record_visible"] = page.trigger_table.rows()[0] == (3, 4, 0xFF, 0xF2)
    page._open_trigger_cell_editor(3, 4, 0)
    app.processEvents()
    checks["event_editor_visible"] = page.trigger_cell_dialog.isVisible()
    page.trigger_shop_combo.setCurrentIndex(page.trigger_shop_combo.findData(0xF3))
    page._save_trigger_cell_editor()
    expected_field = [3, 4, 0xFF, 0xF3]
    checks["field_draft_exact"] = page.trigger_table.rows()[0] == tuple(expected_field)
    page.grab().save(str(OUT / "01-shop-rebind.png"))
    checks["field_commit"] = page.commit_pending_changes()
    added.save_as(FIELD_ROM, make_backup=False)
    close_page(app, page)
    field = RomProject.load(FIELD_ROM)
    checks["field_reopen_exact"] = trigger_rows(field, empty_map)[0] == expected_field
    checks["other_maps_unchanged_after_field"] = all(
        trigger_rows(field, map_id) == rows
        for map_id, rows in baseline.items() if map_id != empty_map
    )

    # Remove the same shop and require a semantic and byte-exact round trip.
    page = open_page(app, field, empty_map)
    page._remove_trigger_row(0)
    checks["delete_draft_empty"] = page.trigger_table.rows() == []
    checks["delete_commit"] = page.commit_pending_changes()
    field.save_as(DELETE_ROM, make_backup=False)
    close_page(app, page)
    deleted = RomProject.load(DELETE_ROM)
    checks["delete_reopen_empty"] = trigger_rows(deleted, empty_map) == []
    checks["delete_round_trip_byte_exact"] = sha256(DELETE_ROM) == sha256(BASE_ROM)

    # Closing an uncommitted dialog/page must leave project bytes unchanged.
    draft = RomProject.load(DELETE_ROM)
    working_before = bytes(draft.working)
    page = open_page(app, draft, empty_map)
    page._open_trigger_cell_editor(5, 6, shop=True)
    page._save_trigger_cell_editor()
    checks["cancel_has_pending_draft"] = page.has_pending_draft
    page.grab().save(str(OUT / "03-cancelled-draft.png"))
    close_page(app, page)
    checks["cancel_keeps_project_bytes"] = bytes(draft.working) == working_before

    structure = json.loads((ROOT / "output/reports/m03-m04-structural-compatibility.json").read_text(encoding="utf-8"))
    checks["reference_structure_report_passed"] = structure.get("passed") is True
    checks["recommended_rom_unchanged"] = sha256(source) == source_hash
    report = {
        "schema_version": 1,
        "module": "M04",
        "scope": "Current-build GUI-to-disk acceptance; not new reference golden or user signature",
        "passed": all(checks.values()),
        "checks": checks,
        "details": {
            "source_rom": str(source),
            "source_sha256": source_hash,
            "normalized_baseline_sha256": sha256(BASE_ROM),
            "empty_map": empty_map,
            "shop_added": [3, 4, 0xFF, 0xF2],
            "shop_rebound": expected_field,
            "field_sha256": sha256(FIELD_ROM),
            "add_sha256": sha256(ADD_ROM),
            "delete_sha256": sha256(DELETE_ROM),
        },
        "artifacts": [
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in (BASE_ROM, FIELD_ROM, ADD_ROM, DELETE_ROM, OUT / "01-shop-rebind.png", OUT / "02-added-shop.png", OUT / "03-cancelled-draft.png")
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "passed": report["passed"], "checks": checks}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
