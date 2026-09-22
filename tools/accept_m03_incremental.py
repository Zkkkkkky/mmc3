"""Run the M03 deployment-editing incremental acceptance on an isolated ROM.

This drives the real MapPage widgets off-screen, saves each committed step,
reopens the resulting ROM in a fresh project, and records machine-readable
evidence without changing the recommended input ROM.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.map_page import MapPage
from fc_rom_editor_core import RomProject


OUT = ROOT / "output" / "verification" / "m03-incremental-acceptance-20260922"
FIELD_ROM = OUT / "m03-field-edit.nes"
ADD_ROM = OUT / "m03-add-enemy.nes"
DELETE_ROM = OUT / "m03-delete-enemy.nes"
REPORT = OUT / "report.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def layout_signature(project: RomProject, map_id: int = 0) -> dict[str, object]:
    layout = project.get_scenario_layout(map_id)
    return {
        "prelude": list(layout.prelude),
        "enemies": [list(row.to_bytes()) for row in layout.enemies],
        "guests": [list(row.to_bytes()) for row in layout.guests],
        "players": [list(row.to_bytes()) for row in layout.player_placements],
    }


def open_page(app: QApplication, project: RomProject, map_id: int) -> MapPage:
    page = MapPage()
    page.resize(1280, 820)
    page.set_project(project)
    page.show()
    app.processEvents()
    row = next(
        (
            index
            for index in range(page.map_list.count())
            if page.map_list.item(index).data(Qt.ItemDataRole.UserRole) == map_id
        ),
        -1,
    )
    if row < 0:
        raise RuntimeError(f"界面关卡列表中找不到地图 {map_id:02X}")
    page.map_list.setCurrentRow(row)
    page.editor_tabs.setCurrentIndex(1)
    app.processEvents()
    return page


def close_page(app: QApplication, page: MapPage) -> None:
    page.close()
    page.deleteLater()
    app.processEvents()


def find_empty_cell(page: MapPage) -> tuple[int, int]:
    occupied = {
        (row[0], row[1])
        for table in (page.enemy_table, page.guest_table, page.player_table)
        for row in table.rows()
    }
    for y in range(page.staged_height):
        for x in range(page.staged_width):
            if (x, y) not in occupied:
                return x, y
    raise RuntimeError("地图没有可用于验收的空格")


def main() -> int:
    def progress(message: str) -> None:
        print(message, flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    source = Path(DEFAULT_ROM).resolve()
    source_hash_before = sha256(source)
    checks: dict[str, bool] = {}
    details: dict[str, object] = {
        "source_rom": str(source),
        "source_profile": None,
        "edit_map_id": None,
        "structure_map_id": None,
    }

    # 1—2. Open the actual compact editor, edit one field, save, and reopen.
    project = RomProject.load(source)
    progress("[1/6] 已载入推荐 ROM")
    details["source_profile"] = project.profile.key
    edit_map_id = next(
        map_id
        for map_id in range(project.scenario_count)
        if 0 < len(project.get_scenario_layout(map_id).enemies) < 18
    )
    details["edit_map_id"] = edit_map_id
    original = layout_signature(project, edit_map_id)
    page = open_page(app, project, edit_map_id)
    progress(f"[2/6] 已打开地图 {edit_map_id:02X} 初始配置")
    checks["editor_is_enabled"] = (
        page.enemy_table.isEnabled()
        and page.enemy_table.editing_enabled
        and page.canvas.deployment_edit_enabled
    )
    if not page.enemy_table.rows():
        raise RuntimeError("地图 00 没有敌军记录，无法执行字段编辑验收")
    before_row = page.enemy_table.rows()[0]
    page._open_deployment_cell_editor("敌", before_row[0], before_row[1], 0)
    app.processEvents()
    checks["editor_opens_existing_record"] = (
        page.deployment_cell_dialog.isVisible()
        and page.deployment_side_combo.currentData() == "敌"
        and page.deployment_level_editor.isEnabled()
    )
    page.deployment_cell_dialog.grab().save(
        str(OUT / "01-existing-record-editor.png")
    )
    changed_level = 1 if before_row[4] == 0xFF else before_row[4] + 1
    page.deployment_level_editor.setValue(changed_level)
    page._save_deployment_cell_editor()
    checks["field_draft_changed_only_target"] = (
        page.enemy_table.rows()[0]
        == (*before_row[:4], changed_level, before_row[5])
    )
    checks["field_commit_succeeded"] = page.commit_pending_changes()
    project.save_as(FIELD_ROM, make_backup=False)
    close_page(app, page)
    progress("[3/6] 字段修改已保存并关闭页面")

    reopened = RomProject.load(FIELD_ROM)
    field_layout = layout_signature(reopened, edit_map_id)
    expected_field = json.loads(json.dumps(original))
    expected_field["enemies"][0][4] = changed_level
    checks["field_reopen_exact"] = field_layout == expected_field

    # 3. Add one enemy through the same compact editor and reopen.
    codec = reopened.scenario_layout_codec
    structure_map_id = next(
        candidate
        for candidate in range(reopened.scenario_count)
        if (
            codec.capacities[candidate]
            - len(codec.encode(reopened.get_scenario_layout(candidate)))
            >= 6
            and len(reopened.get_scenario_layout(candidate).enemies) < 18
            and reopened.get_scenario_layout(candidate).player_placements
        )
    )
    details["structure_map_id"] = structure_map_id
    structure_baseline = layout_signature(reopened, structure_map_id)
    page = open_page(app, reopened, structure_map_id)
    progress("[4/6] 字段结果已重开，开始新增")
    empty_x, empty_y = find_empty_cell(page)
    count_before_add = len(page.enemy_table.rows())
    progress("[4.1/6] 已找到空格，打开新增编辑器")
    page._open_deployment_cell_editor("敌", empty_x, empty_y)
    app.processEvents()
    progress("[4.2/6] 新增编辑器已打开，写入草稿")
    page._save_deployment_cell_editor()
    progress("[4.3/6] 新增草稿已写入，截取界面")
    added_row = page.enemy_table.rows()[-1]
    checks["add_draft_created"] = (
        len(page.enemy_table.rows()) == count_before_add + 1
        and added_row[:2] == (empty_x, empty_y)
    )
    page.grab().save(str(OUT / "02-added-enemy.png"))
    progress("[4.4/6] 截图完成，提交草稿")
    checks["add_commit_succeeded"] = page.commit_pending_changes()
    progress("[4.5/6] 草稿提交完成，保存 ROM")
    reopened.save_as(ADD_ROM, make_backup=False)
    close_page(app, page)
    progress("[5/6] 新增记录已保存并关闭页面")

    added = RomProject.load(ADD_ROM)
    added_layout = layout_signature(added, structure_map_id)
    checks["add_reopen_exact"] = (
        len(added_layout["enemies"]) == len(structure_baseline["enemies"]) + 1
        and added_layout["enemies"][-1] == list(added_row)
        and added_layout["guests"] == structure_baseline["guests"]
        and added_layout["players"] == structure_baseline["players"]
    )

    # 4. Delete the exact newly added row, save, and require the same bytes as
    # the field-edited baseline.
    page = open_page(app, added, structure_map_id)
    page._remove_deployment_row("敌", page.enemy_table.rowCount() - 1)
    checks["delete_draft_restores_count"] = (
        page.enemy_table.rowCount() == count_before_add
    )
    checks["delete_commit_succeeded"] = page.commit_pending_changes()
    added.save_as(DELETE_ROM, make_backup=False)
    close_page(app, page)
    deleted = RomProject.load(DELETE_ROM)
    checks["delete_reopen_restores_layout"] = (
        layout_signature(deleted, structure_map_id) == structure_baseline
    )
    checks["delete_round_trip_byte_exact"] = sha256(DELETE_ROM) == sha256(FIELD_ROM)

    # 5. Copy/paste and drag only in the page draft, then close without commit.
    draft_project = RomProject.load(DELETE_ROM)
    working_before_cancel = bytes(draft_project.working)
    page = open_page(app, draft_project, structure_map_id)
    original_row = page.player_table.rows()[0]
    cancel_x, cancel_y = find_empty_cell(page)
    page._copy_deployment_record("我", 0)
    page._paste_deployment_at(cancel_x, cancel_y)
    page._overlay_moved("我", 0, cancel_x, cancel_y)
    checks["copy_paste_and_drag_create_draft"] = (
        page.has_pending_draft
        and len(page.player_table.rows()) == len(structure_baseline["players"]) + 1
        and page.player_table.rows()[0][:2] == (cancel_x, cancel_y)
        and page.player_table.rows()[-1][2:] == original_row[2:]
    )
    page.grab().save(str(OUT / "03-cancelled-draft.png"))
    close_page(app, page)
    checks["cancel_keeps_project_bytes"] = bytes(draft_project.working) == working_before_cancel
    checks["cancel_reopen_keeps_layout"] = (
        layout_signature(RomProject.load(DELETE_ROM), structure_map_id)
        == structure_baseline
    )

    # 6. Consume the already collected reference structural evidence.
    structural_report_path = ROOT / "output" / "reports" / "m03-m04-structural-compatibility.json"
    structural_report = json.loads(structural_report_path.read_text(encoding="utf-8"))
    checks["structural_report_passed"] = structural_report.get("passed") is True
    checks["recommended_rom_hash_unchanged"] = sha256(source) == source_hash_before
    progress("[6/6] 删除、取消与结构报告检查完成")

    report = {
        "schema_version": 1,
        "module": "M03",
        "scope": "2026-09-22 deployment editing incremental acceptance",
        "passed": all(checks.values()),
        "checks": checks,
        "details": {
            **details,
            "source_sha256": source_hash_before,
            "field_rom_sha256": sha256(FIELD_ROM),
            "add_rom_sha256": sha256(ADD_ROM),
            "delete_rom_sha256": sha256(DELETE_ROM),
            "edited_enemy_before": list(before_row),
            "edited_enemy_after": list(field_layout["enemies"][0]),
            "added_enemy": list(added_row),
            "cancel_coordinate": [cancel_x, cancel_y],
        },
        "artifacts": [
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in (
                FIELD_ROM,
                ADD_ROM,
                DELETE_ROM,
                OUT / "01-existing-record-editor.png",
                OUT / "02-added-enemy.png",
                OUT / "03-cancelled-draft.png",
            )
        ],
        "note": "Machine acceptance only; the user-signature row remains user-owned.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
