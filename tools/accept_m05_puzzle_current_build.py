"""Exercise M05 puzzle controls against an isolated current-build ROM.

This is product-side acceptance, not a substitute for reference-editor golden
diffs for the guarded M05 graphic actions.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.database_graphics import read_unit_appearance
from dc_modifier.unit_appearance_dialog import (
    UnitAppearanceDialog,
    flip_fragment_script,
    move_body_script,
    move_fragment_script,
)
from fc_rom_editor_core import RomProject


OUT = ROOT / "output/verification/m05-puzzle-current-build-20260922"
SAVED = OUT / "m05-puzzle-moved.nes"
RESTORED = OUT / "m05-puzzle-restored.nes"
UNIT_ID = 0x09


def digest(data: bytes | Path) -> str:
    payload = data.read_bytes() if isinstance(data, Path) else data
    return hashlib.sha256(payload).hexdigest().upper()


def require(checks: dict[str, bool], name: str, result: bool) -> None:
    checks[name] = bool(result)
    if not result:
        raise AssertionError(name)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    checks: dict[str, bool] = {}
    source_sha = digest(DEFAULT_ROM)

    # The UI may stage scripts on an unexpanded project, but cannot write them.
    guarded = RomProject.load(DEFAULT_ROM)
    guarded_before = bytes(guarded.working)
    dialog = UnitAppearanceDialog(guarded, UNIT_ID)
    dialog._move_body(1, 0)
    warnings: list[str] = []
    with patch("dc_modifier.unit_appearance_dialog.QMessageBox.warning", side_effect=lambda _parent, _title, message: warnings.append(message)):
        dialog.accept()
    require(checks, "未扩容时拼图写入被门禁拒绝", bool(warnings) and "扩容" in warnings[-1])
    require(checks, "门禁失败保持ROM原字节", bytes(guarded.working) == guarded_before)
    dialog.reject()
    dialog.deleteLater()

    project = RomProject.load(DEFAULT_ROM)
    project.configure_expansion(288, 64, 112)
    baseline_bytes = bytes(project.working)
    baseline = read_unit_appearance(project, UNIT_ID)
    neighbor_before = read_unit_appearance(project, UNIT_ID + 1)
    dialog = UnitAppearanceDialog(project, UNIT_ID)
    dialog.show()
    app.processEvents()
    dialog._move_body(1, -1)
    dialog._move_fragment(2, 3)
    dialog._flip_fragment(0x40)
    expected_body = move_body_script(baseline.body_script, 1, -1)
    expected_fragment = flip_fragment_script(move_fragment_script(baseline.fragment_script, 2, 3), 0x40)
    require(checks, "移动翻转操作在拼图草稿中可见", dialog.body_script == expected_body and dialog.fragment_script == expected_fragment)
    require(checks, "子窗口确定前ROM未写入", bytes(project.working) == baseline_bytes)
    screenshot = OUT / "m05-puzzle-draft.png"
    require(checks, "拼图草稿截图保存", dialog.grab().save(str(screenshot), "PNG"))
    dialog.accept()
    require(checks, "子窗口确定后拼图脚本已写入", dialog.changed and read_unit_appearance(project, UNIT_ID).body_script == expected_body and read_unit_appearance(project, UNIT_ID).fragment_script == expected_fragment)
    require(checks, "相邻机体外观未变化", read_unit_appearance(project, UNIT_ID + 1) == neighbor_before)
    project.save_as(SAVED, make_backup=False)
    reopened = RomProject.load(SAVED)
    require(checks, "另存ROM全新工程重开两段脚本一致", read_unit_appearance(reopened, UNIT_ID).body_script == expected_body and read_unit_appearance(reopened, UNIT_ID).fragment_script == expected_fragment)

    # Cancel a new draft, then undo the accepted edit and verify byte reversal.
    cancel_before = bytes(reopened.working)
    cancel_dialog = UnitAppearanceDialog(reopened, UNIT_ID)
    cancel_dialog._move_body(-1, 0)
    cancel_dialog.reject()
    require(checks, "取消拼图草稿保持ROM字节", bytes(reopened.working) == cancel_before)
    project.undo()
    require(checks, "撤销整笔拼图事务逐字节恢复", bytes(project.working) == baseline_bytes)
    project.save_as(RESTORED, make_backup=False)
    require(checks, "撤销后另存ROM与扩容基线一致", digest(RESTORED) == digest(baseline_bytes))
    require(checks, "推荐输入ROM未改变", digest(DEFAULT_ROM) == source_sha)

    report = {
        "module": "M05 机体拼图",
        "result": "PASS" if all(checks.values()) else "FAIL",
        "evidence_level": "current_product_only",
        "reference_golden_status": "pending; no action gate released",
        "source_sha256": source_sha,
        "moved_rom": str(SAVED.relative_to(ROOT)).replace("\\", "/"),
        "moved_sha256": digest(SAVED),
        "restored_sha256": digest(RESTORED),
        "screenshot": str(screenshot.relative_to(ROOT)).replace("\\", "/"),
        "checks": checks,
    }
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
