from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication, QMessageBox, QTabWidget

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.character_editor import legacy_portrait_selectors
from dc_modifier.legacy_windows import DatabaseDialog
from fc_editor.codecs.character_attributes import CharacterAttributesCodec
from fc_rom_editor_core import RomProject


OUTPUT = ROOT / "output" / "verification" / "m06-character-acceptance-20260922"
EDITED_ROM = OUTPUT / "m06-edited.nes"
CLEARED_ROM = OUTPUT / "m06-transform-cleared.nes"
RESTORED_ROM = OUTPUT / "m06-transform-restored.nes"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def open_character_dialog(app: QApplication, project: RomProject):
    dialog = DatabaseDialog(project)
    dialog.show()
    dialog.tabs.setCurrentIndex(1)
    app.processEvents()
    return dialog, dialog.character_page


def finish_dialog(app: QApplication, dialog: DatabaseDialog, *, accept: bool) -> None:
    dialog.accept() if accept else dialog.reject()
    dialog.deleteLater()
    app.processEvents()


def save_widget(widget, name: str) -> str:
    path = OUTPUT / name
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(path), "PNG"):
        raise RuntimeError(f"无法保存验收截图：{path}")
    return str(path.relative_to(ROOT)).replace("\\", "/")


def select_tab(widget, label: str) -> QTabWidget:
    tabs = widget.findChild(QTabWidget)
    if tabs is None:
        raise AssertionError(f"{widget.objectName() or type(widget).__name__} 缺少页签")
    index = next((i for i in range(tabs.count()) if tabs.tabText(i) == label), -1)
    if index < 0:
        raise AssertionError(f"找不到页签：{label}")
    tabs.setCurrentIndex(index)
    return tabs


def require(checks: dict[str, bool], name: str, condition: bool) -> None:
    checks[name] = bool(condition)
    if not condition:
        raise AssertionError(name)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in (EDITED_ROM, CLEARED_ROM, RESTORED_ROM):
        path.unlink(missing_ok=True)

    app = QApplication.instance() or QApplication([])
    checks: dict[str, bool] = {}
    artifacts: list[str] = []
    source_hash = sha256(DEFAULT_ROM)

    # A. Read the real controls and verify the corrected reference selector semantics.
    project = RomProject.load(DEFAULT_ROM)
    source_bytes = bytes(project.working)
    dialog, page = open_character_dialog(app, project)
    page.select_record_id(6)
    details = page.character_details
    portrait = CharacterAttributesCodec(project).read_portrait(6)
    require(checks, "人物06头像选择器为正面25/1、背景27/2", legacy_portrait_selectors(portrait) == (25, 1, 27, 2))
    require(checks, "人物06界面选择器与ROM一致", tuple(details.portrait_fields[key].value() for key in ("front_bank", "front_slot", "back_bank", "back_slot")) == (25, 1, 27, 2))
    image_both = details.portrait_preview.pixmap().toImage()
    require(checks, "头像预览为64x64真实合成图", (image_both.width(), image_both.height()) == (64, 64))
    details.show_back.setChecked(False)
    app.processEvents()
    image_front = details.portrait_preview.pixmap().toImage()
    require(checks, "头像前景/背景显示开关会改变预览", image_front != image_both)
    details.show_back.setChecked(True)
    require(checks, "预览开关不会写ROM", bytes(project.working) == source_bytes)
    require(checks, "预览开关不会产生字段草稿", not details.has_pending_changes())
    select_tab(details, "头像设置与上传")
    app.processEvents()
    artifacts.append(save_widget(details, "01-character-06-portrait.png"))

    add_button = page.add_record_button
    require(checks, "新增人物入口可见", add_button.isVisible())
    require(checks, "固定池满时新增人物入口禁用", not add_button.isEnabled())
    require(checks, "新增人物容量原因明确", "$01—$C8" in add_button.toolTip() and "固定名称、属性和头像池均无剩余容量" in add_button.toolTip())
    before_add = bytes(project.working)
    add_button.click()
    require(checks, "点击禁用新增入口不写ROM", bytes(project.working) == before_add)
    artifacts.append(save_widget(add_button.parentWidget(), "02-add-character-guard.png"))

    # B. Edit unique fixed-size fields, portrait color and a dialogue binding.
    page.select_record_id(75)
    details = page.character_details
    before_75 = CharacterAttributesCodec(project).read(75)
    details.fields["spirit"].setValue(before_75.spirit + 1)
    details.fields["growth"].setValue(before_75.growth + 1)
    details.fields["movement"].setValue((before_75.corrections[0] & 0x7F) + 1)
    details.survive.setChecked(True)
    old_cost = CharacterAttributesCodec(project).costs()[0]
    details.costs[0].setValue(old_cost + 1)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        page.apply_record()

    page.select_record_id(6)
    details = page.character_details
    dialogue = page.character_dialogue
    original_portrait = CharacterAttributesCodec(project).read_portrait(6)
    original_direct = project.character_dialogue_codec.read(6, project.working).direct[0]
    details.portrait_fields["color0"].setValue((original_portrait.colors[0] + 1) & 0x3F)
    dialogue.direct_controls[0][1].setValue((original_direct.dialogue + 1) & 0xFF)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        page.apply_record()
    select_tab(dialogue, "变形起飞")
    app.processEvents()
    artifacts.append(save_widget(dialogue, "03-character-06-dialogue.png"))
    finish_dialog(app, dialog, accept=True)
    project.save_as(EDITED_ROM, make_backup=False)

    reopened = RomProject.load(EDITED_ROM)
    codec = CharacterAttributesCodec(reopened)
    record_75 = codec.read(75)
    require(checks, "人物75精神值保存并重开一致", record_75.spirit == before_75.spirit + 1)
    require(checks, "人物75成长值保存并重开一致", record_75.growth == before_75.growth + 1)
    require(checks, "人物75机动与击落不消失保存并重开一致", record_75.corrections[0] == (((before_75.corrections[0] & 0x7F) + 1) | 0x80))
    require(checks, "全局精神消耗保存并重开一致", codec.costs()[0] == old_cost + 1)
    changed_portrait = codec.read_portrait(6)
    require(checks, "人物06头像颜色保存并重开一致", changed_portrait.colors[0] == ((original_portrait.colors[0] + 1) & 0x3F))
    require(checks, "人物06头像图库位置未漂移", legacy_portrait_selectors(changed_portrait) == (25, 1, 27, 2))
    require(checks, "人物06直接台词保存并重开一致", reopened.character_dialogue_codec.read(6, reopened.working).direct[0].dialogue == ((original_direct.dialogue + 1) & 0xFF))
    require(checks, "基准ROM未被覆盖", sha256(DEFAULT_ROM) == source_hash)

    # C. Cancel must restore both unstaged controls and already staged project bytes.
    cancel_project = RomProject.load(EDITED_ROM)
    cancel_before = bytes(cancel_project.working)
    cancel_dialog, cancel_page = open_character_dialog(app, cancel_project)
    cancel_page.select_record_id(6)
    cancel_details = cancel_page.character_details
    cancel_details.portrait_fields["color1"].setValue((cancel_details.portrait_fields["color1"].value() + 1) & 0x3F)
    cancel_page.apply_record()
    require(checks, "取消前修改已进入窗口会话", bytes(cancel_project.working) != cancel_before)
    finish_dialog(app, cancel_dialog, accept=False)
    require(checks, "数据库取消恢复打开前全部字节", bytes(cancel_project.working) == cancel_before)

    # D. Remove and add back one transform row, saving and reopening each time.
    clear_project = RomProject.load(EDITED_ROM)
    transform_codec = clear_project.character_dialogue_codec
    original_transforms = transform_codec.character_transform_bindings(6, clear_project.working)
    require(checks, "人物06原有4条变形绑定", len(original_transforms) == 4)
    removed = original_transforms[-1]
    clear_dialog, clear_page = open_character_dialog(app, clear_project)
    clear_page.select_record_id(6)
    transform = clear_page.character_dialogue
    transform.transform_table.setCurrentCell(transform.transform_table.rowCount() - 1, 0)
    transform._remove_transform()
    clear_page.apply_record()
    finish_dialog(app, clear_dialog, accept=True)
    clear_project.save_as(CLEARED_ROM, make_backup=False)
    cleared = RomProject.load(CLEARED_ROM)
    require(checks, "清空一条变形绑定后保存重开为3条", len(cleared.character_dialogue_codec.character_transform_bindings(6, cleared.working)) == 3)

    restore_project = RomProject.load(CLEARED_ROM)
    restore_dialog, restore_page = open_character_dialog(app, restore_project)
    restore_page.select_record_id(6)
    transform = restore_page.character_dialogue
    transform._add_transform()
    row = transform.transform_table.rowCount() - 1
    for column, value in enumerate((removed.unit_start, removed.unit_end, removed.dialogue)):
        transform.transform_table.setItem(row, column, transform._hex_item(value))
    restore_page.apply_record()
    finish_dialog(app, restore_dialog, accept=True)
    restore_project.save_as(RESTORED_ROM, make_backup=False)
    restored = RomProject.load(RESTORED_ROM)
    restored_transforms = restored.character_dialogue_codec.character_transform_bindings(6, restored.working)
    require(checks, "补回变形绑定后保存重开恢复原4条", restored_transforms == original_transforms)
    require(checks, "变形绑定删后补回字节完全可逆", sha256(RESTORED_ROM) == sha256(EDITED_ROM))

    # E. A known expanding edit is rejected atomically when the fixed pool is full.
    guard_project = RomProject.load(DEFAULT_ROM)
    guard_before = bytes(guard_project.working)
    guard_dialog, guard_page = open_character_dialog(app, guard_project)
    guard_page.select_record_id(1)
    guard_page.character_details.fields["spirit"].setValue(1)
    errors: list[str] = []
    guard_page.show_error = lambda error: errors.append(str(error))
    guard_page.apply_record()
    require(checks, "固定池扩容请求明确报容量不足", bool(errors) and "容量不足" in errors[-1])
    require(checks, "容量不足时ROM保持原样", bytes(guard_project.working) == guard_before)
    require(checks, "容量不足时表单草稿仍保留", guard_page.has_pending_draft)
    finish_dialog(app, guard_dialog, accept=False)

    report = {
        "module": "M06 人物修改",
        "result": "PASS" if all(checks.values()) else "FAIL",
        "scope": {
            "reference_golden_fields_and_actions": 106,
            "unsafe_add_character": "固定名称、属性和头像池均满，界面可见但禁用并说明原因",
        },
        "source_rom": str(Path(DEFAULT_ROM).relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": source_hash,
        "outputs": {
            "edited_rom": str(EDITED_ROM.relative_to(ROOT)).replace("\\", "/"),
            "edited_sha256": sha256(EDITED_ROM),
            "transform_cleared_rom": str(CLEARED_ROM.relative_to(ROOT)).replace("\\", "/"),
            "transform_restored_rom": str(RESTORED_ROM.relative_to(ROOT)).replace("\\", "/"),
            "transform_restored_sha256": sha256(RESTORED_ROM),
        },
        "artifacts": artifacts,
        "checks": checks,
        "note": "当前构建机器验收；不替代用户最终签收。",
    }
    (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
