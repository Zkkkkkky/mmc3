"""Exercise guarded M05 actions through the real current-build database page.

This records product-side behavior only.  It deliberately does not promote
reference-editor action gates or claim reference golden compatibility.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.database_graphics import read_unit_appearance, render_unit_battle_preview
from dc_modifier.legacy_windows import DatabaseDialog
from dc_modifier.unit_appearance_dialog import UnitAppearanceDialog, WORK_PALETTE
from dc_modifier.unit_icon_dialog import UnitIconBindingDialog
from fc_rom_editor_core import RomProject


OUT = ROOT / "output/verification/m05-actions-current-build-20260922"
UPLOADED = OUT / "m05-actions-uploaded.nes"
CLEARED = OUT / "m05-actions-cleared.nes"
UNIT_ID = 0x09


def digest(data: bytes | Path) -> str:
    payload = data.read_bytes() if isinstance(data, Path) else data
    return hashlib.sha256(payload).hexdigest().upper()


def require(checks: dict[str, bool], name: str, result: bool) -> None:
    checks[name] = bool(result)
    if not result:
        raise AssertionError(name)


def solid_image(path: Path, width: int, height: int, palette_index: int) -> None:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(WORK_PALETTE[palette_index])
    if not image.save(str(path), "BMP"):
        raise OSError(f"无法创建验收图片：{path}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    checks: dict[str, bool] = {}
    warnings: list[str] = []
    source_sha = digest(DEFAULT_ROM)

    project = RomProject.load(DEFAULT_ROM)
    project.configure_expansion(288, 64, 112)
    expanded_baseline = bytes(project.working)
    dialog = DatabaseDialog(project)
    dialog.show()
    app.processEvents()
    dialog._select_unit(UNIT_ID)
    page = dialog.unit_page
    require(checks, "数据库页定位目标机体", page.current_id == UNIT_ID)

    preview_count = 0
    previews_are_128 = True
    for unit_id in range(1, project.unit_count):
        preview = render_unit_battle_preview(
            project, read_unit_appearance(project, unit_id)
        )
        preview_count += 1
        previews_are_128 = previews_are_128 and (
            not preview.isNull() and (preview.width(), preview.height()) == (128, 128)
        )
    require(checks, "战斗预览遍历全部255个机体槽位", preview_count == 255)
    require(checks, "全部战斗预览均为有效128×128图像", previews_are_128)

    # F-026 is a byte-ID capacity boundary: every $01-$FF slot is already listed.
    before_add = bytes(project.working)
    page.add_button.click()
    require(checks, "新增机体按钮保持禁用", not page.add_button.isEnabled())
    require(
        checks,
        "新增机体提示说明255槽容量边界",
        "$01—$FF" in page.add_button.toolTip()
        and "第 256 个 ID" in page.add_button.toolTip(),
    )
    require(checks, "点击禁用按钮不写ROM", bytes(project.working) == before_add)

    # F-023: exercise the actual jump button and ensure the outer transaction
    # keeps the staged unit form while switching to the weapon page.
    old_hp = page.fields["hp"].value()
    page.fields["hp"].setValue(old_hp + 1)
    weapon_1 = int(page.weapon_slots[0].currentData() or 1)
    if page.weapon_slots[0].findData(weapon_1) < 0:
        weapon_1 = 1
    page.weapon_slots[0].setCurrentIndex(page.weapon_slots[0].findData(weapon_1))
    page.weapon_jump_buttons[0].click()
    require(checks, "转到武器1按钮切换武器页", dialog.tabs.currentIndex() == 2)
    require(checks, "转到武器1按钮定位对应武器", dialog.weapon_page.current_id == weapon_1)
    require(checks, "跳转前机体草稿已暂存", project.get_value(UNIT_ID, "hp") == old_hp + 1)
    dialog._select_unit(UNIT_ID)
    page = dialog.unit_page

    weapon_2 = int(page.weapon_slots[1].currentData() or 2)
    if page.weapon_slots[1].findData(weapon_2) < 0:
        weapon_2 = next(
            int(page.weapon_slots[1].itemData(index))
            for index in range(page.weapon_slots[1].count())
            if page.weapon_slots[1].itemData(index)
        )
    page.weapon_slots[1].setCurrentIndex(page.weapon_slots[1].findData(weapon_2))
    page.weapon_jump_buttons[1].click()
    require(checks, "转到武器2按钮切换武器页", dialog.tabs.currentIndex() == 2)
    require(checks, "转到武器2按钮定位对应武器", dialog.weapon_page.current_id == weapon_2)
    dialog._select_unit(UNIT_ID)
    page = dialog.unit_page

    # F-025: drive the real button and accept a deterministic scenario/icon.
    def accept_icon(binding: UnitIconBindingDialog) -> int:
        binding.scenario.setCurrentIndex(9)
        binding.icon_number.setCurrentIndex(47)
        binding.accept()
        return binding.result()

    with patch.object(UnitIconBindingDialog, "exec", accept_icon):
        page.bind_icon_button.click()
    require(checks, "更改图标按钮写入动态路由位置", project.record_bytes(UNIT_ID)[2] == 0xBC)
    require(checks, "更改图标后预览有效", page.icon_preview.pixmap() is not None and not page.icon_preview.pixmap().isNull())

    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        body_bmp = temporary / "body.bmp"
        fragment_bmp = temporary / "fragment.bmp"
        solid_image(body_bmp, 16, 8, 1)
        solid_image(fragment_bmp, 64, 128, 2)

        def accept_body(appearance: UnitAppearanceDialog) -> int:
            appearance._import_library("body")
            appearance.accept()
            return appearance.result()

        page.body_import_offset.setValue(2)
        page.body_compress_upload.setChecked(False)
        with (
            patch.object(UnitAppearanceDialog, "exec", accept_body),
            patch(
                "dc_modifier.unit_appearance_dialog.QFileDialog.getOpenFileName",
                return_value=(str(body_bmp), "BMP 图片 (*.bmp)"),
            ),
            patch(
                "dc_modifier.legacy_windows.QTimer.singleShot",
                return_value=None,
            ),
            patch(
                "dc_modifier.unit_appearance_dialog.QMessageBox.warning",
                side_effect=lambda _parent, _title, message: warnings.append(message),
            ),
        ):
            page.body_upload_button.click()
        appearance = read_unit_appearance(project, UNIT_ID)
        body_bank = appearance.configuration[8]
        body_pixels = project.chr_tile_pixels(body_bank * 64 + 2)
        require(checks, "上传机体按钮按偏移写入主体图块", body_pixels == (1,) * 64)
        require(checks, "上传机体按钮生成对应拼图脚本", bool(appearance.body_script))

        page.fragment_import_offset.setValue(2)
        page.fragment_compress_upload.setChecked(False)
        appearance = read_unit_appearance(project, UNIT_ID)
        fragment_bank = appearance.configuration[7] & 0xFE
        fragment_prefix = tuple(
            project.chr_tile_pixels(fragment_bank * 64 + index) for index in range(2)
        )
        def accept_fragment(appearance: UnitAppearanceDialog) -> int:
            appearance._import_library("fragment")
            appearance.accept()
            return appearance.result()

        with (
            patch.object(UnitAppearanceDialog, "exec", accept_fragment),
            patch(
                "dc_modifier.unit_appearance_dialog.QFileDialog.getOpenFileName",
                return_value=(str(fragment_bmp), "BMP 图片 (*.bmp)"),
            ),
            patch(
                "dc_modifier.legacy_windows.QTimer.singleShot",
                return_value=None,
            ),
            patch(
                "dc_modifier.unit_appearance_dialog.QMessageBox.warning",
                side_effect=lambda _parent, _title, message: warnings.append(message),
            ),
        ):
            page.fragment_upload_button.click()
        require(checks, "上传碎片按钮按偏移写入跨库图块", project.chr_tile_pixels(fragment_bank * 64 + 2) == (2,) * 64)
        require(checks, "上传碎片保留偏移前图块", tuple(project.chr_tile_pixels(fragment_bank * 64 + index) for index in range(2)) == fragment_prefix)

    require(checks, "上传动作没有警告", not warnings)
    uploaded_screenshot = OUT / "m05-actions-uploaded.png"
    require(checks, "上传后数据库页截图保存", dialog.grab().save(str(uploaded_screenshot), "PNG"))
    project.save_as(UPLOADED, make_backup=False)
    reopened = RomProject.load(UPLOADED)
    reopened_appearance = read_unit_appearance(reopened, UNIT_ID)
    require(checks, "上传结果另存重开后主体一致", reopened.chr_tile_pixels(reopened_appearance.configuration[8] * 64 + 2) == (1,) * 64)
    reopened_fragment_bank = reopened_appearance.configuration[7] & 0xFE
    require(checks, "上传结果另存重开后碎片一致", reopened.chr_tile_pixels(reopened_fragment_bank * 64 + 2) == (2,) * 64)
    require(checks, "图标绑定另存重开一致", reopened.record_bytes(UNIT_ID)[2] == 0xBC)

    # Drive both real clear buttons.  The inner dialogs commit to the outer
    # database session, which is still reversible by the database Cancel.
    def accept_clear(appearance: UnitAppearanceDialog) -> int:
        kind = "body" if appearance.preview_tabs.currentIndex() == 0 else "fragment"
        appearance._clear_library(kind)
        appearance.accept()
        return appearance.result()

    with (
        patch.object(UnitAppearanceDialog, "exec", accept_clear),
        patch(
            "dc_modifier.unit_appearance_dialog.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch(
            "dc_modifier.legacy_windows.QTimer.singleShot",
            return_value=None,
        ),
    ):
        page.body_clear_button.click()
        page.fragment_clear_button.click()
    cleared_appearance = read_unit_appearance(project, UNIT_ID)
    cleared_body_bank = cleared_appearance.configuration[8]
    cleared_fragment_bank = cleared_appearance.configuration[7] & 0xFE
    require(checks, "清除机体按钮清零当前主体图库", all(project.chr_tile_pixels(cleared_body_bank * 64 + index) == (0,) * 64 for index in range(64)))
    require(checks, "清除碎片按钮清零两个碎片图库", all(project.chr_tile_pixels(cleared_fragment_bank * 64 + index) == (0,) * 64 for index in range(128)))
    project.save_as(CLEARED, make_backup=False)
    cleared_reopened = RomProject.load(CLEARED)
    require(checks, "清除结果另存重开一致", all(cleared_reopened.chr_tile_pixels(cleared_fragment_bank * 64 + index) == (0,) * 64 for index in range(128)))

    dialog.reject()
    require(checks, "数据库取消逐字节回滚全部动作", bytes(project.working) == expanded_baseline)
    require(checks, "推荐输入ROM未改变", digest(DEFAULT_ROM) == source_sha)
    dialog.deleteLater()
    app.processEvents()

    report = {
        "module": "M05 机体修改动作",
        "result": "PASS" if all(checks.values()) else "FAIL",
        "evidence_level": "current_product_only",
        "reference_golden_status": "pending; no action gate released",
        "source_sha256": source_sha,
        "preview_unit_count": preview_count,
        "uploaded_rom": str(UPLOADED.relative_to(ROOT)).replace("\\", "/"),
        "uploaded_sha256": digest(UPLOADED),
        "cleared_rom": str(CLEARED.relative_to(ROOT)).replace("\\", "/"),
        "cleared_sha256": digest(CLEARED),
        "screenshot": str(uploaded_screenshot.relative_to(ROOT)).replace("\\", "/"),
        "checks": checks,
    }
    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
