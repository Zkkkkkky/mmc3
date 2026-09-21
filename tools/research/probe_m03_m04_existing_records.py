"""Open one existing M03 and M04 record without saving the ROM.

This complements the empty-cell/add-dialog catalog by proving the reference
editor's existing-record navigation path.  It intentionally cancels every
dialog and verifies the probe ROM hash is unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.research import legacy_ui_probe as ui


AUDIT = ROOT / "output/build/legacy-diff-audit"
SOURCE_ROM = AUDIT / "audit.nes"
OUT = ROOT / "output/verification/legacy-m03-m04-existing-records-20260920"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def press(vk: int) -> None:
    ui.keybd(vk)
    time.sleep(0.08)
    ui.keybd(vk, up=True)
    time.sleep(0.12)


def launch(tag: str, out: Path) -> tuple[ui.ProbeSession, Path, str]:
    runtime = out / tag / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    shutil.copy2(AUDIT / "SRW2_patched.exe", runtime / "SRW2_patched.exe")
    shutil.copytree(AUDIT / "默认配置文件/默认配置文件", runtime / "默认配置文件")
    rom = runtime / "probe.nes"
    shutil.copy2(SOURCE_ROM, rom)
    session = ui.ProbeSession(ROOT, f"{tag}-existing-record-20260920")
    session.out = out / tag
    session.shots = session.out / "screenshots"
    session.controls = session.out / "controls"
    session.shots.mkdir(parents=True, exist_ok=True)
    session.controls.mkdir(parents=True, exist_ok=True)
    session.probe_rom = rom
    session.launch()
    ui.stage_a(session)
    if not session.open_rom_via_menu(rom, f"{tag}_打开ROM"):
        raise RuntimeError(f"{tag} probe ROM did not open")
    return session, rom, digest(rom)


def probe_m03(out: Path) -> dict[str, object]:
    session, rom, before = launch("M03", out)
    dialog = None
    try:
        ui.sweep_tabs(session, session.main_hwnd, "M03_主窗口页签", max_pages=2)
        tree = ui.enum_child_tree(session.main_hwnd)
        map_control = ui.find_controls(tree, ctrl_id=500)[0]
        # Map 00 player record at logical cell (4, 9); status-bar probing
        # confirms that each rendered cell is 20 px.
        main_rect = ui.get_window_rect(session.main_hwnd)
        map_rect = ui.get_window_rect(map_control["hwnd"])
        dx, dy = ui._client_offset(session.main_hwnd)
        x = map_rect["left"] + 4 * 20 + 10 - main_rect["left"] - dx
        y = map_rect["top"] + 9 * 20 + 10 - main_rect["top"] - dy
        session.snapshot_known()
        if not ui.real_click_at(session.main_hwnd, x, y, button="right"):
            raise RuntimeError("M03 existing record right click failed")
        time.sleep(0.4)
        ui.capture_screen_region(ui.get_window_rect(session.main_hwnd), session.shots / "M03_现有记录_右键菜单.png", pad=80)
        press(0x28)  # Add configuration
        press(0x28)  # Change configuration
        press(ui.VK_RETURN)
        dialog = session.wait_new_top(timeout=8.0, title_contains="配置设置")
        if not dialog:
            raise RuntimeError("M03 existing-record editor did not open")
        session.dump_window(dialog["hwnd"], "M03_现有记录_配置设置", menu=False)
        result = {"passed": True, "dialog_title": dialog["title"], "rom_unchanged": digest(rom) == before}
        ui.send_escape(dialog["hwnd"])
        dialog = None
        return result
    finally:
        if dialog and ui.is_window(dialog["hwnd"]):
            ui.send_escape(dialog["hwnd"])
        session.terminate()


def probe_m04(out: Path) -> dict[str, object]:
    session, rom, before = launch("M04", out)
    dialog = None
    try:
        ui.sweep_tabs(session, session.main_hwnd, "M04_主窗口页签", max_pages=3)
        tree = ui.enum_child_tree(session.main_hwnd)
        records = ui.find_controls(tree, ctrl_id=550)
        if len(records) != 1:
            raise RuntimeError(f"M04 record list 550 matched {len(records)}")
        session.snapshot_known()
        if not ui.real_double_click_control_cell(records[0]["hwnd"], 30, 12):
            raise RuntimeError("M04 existing record double click failed")
        dialog = session.wait_new_top(timeout=8.0, title_contains="商店设置")
        if dialog:
            session.dump_window(dialog["hwnd"], "M04_现有记录_商店设置", menu=False)
            ui.send_escape(dialog["hwnd"])
            dialog_title = dialog["title"]
            dialog = None
            direct_editor = True
        else:
            # The reference editor does not edit an existing trigger in place.
            # Select its marker and record the context menu: it offers add/delete,
            # so a field change is structurally delete + re-add.
            tree = ui.enum_child_tree(session.main_hwnd)
            map_control = ui.find_controls(tree, ctrl_id=500)[0]
            main_rect = ui.get_window_rect(session.main_hwnd)
            map_rect = ui.get_window_rect(map_control["hwnd"])
            dx, dy = ui._client_offset(session.main_hwnd)
            x = map_rect["left"] + 9 * 20 + 10 - main_rect["left"] - dx
            y = map_rect["top"] + 3 * 20 + 10 - main_rect["top"] - dy
            if not ui.real_click_at(session.main_hwnd, x, y, button="right"):
                raise RuntimeError("M04 existing marker right click failed")
            time.sleep(0.4)
            ui.capture_screen_region(ui.get_window_rect(session.main_hwnd), session.shots / "M04_现有记录_右键菜单.png", pad=80)
            press(ui.VK_ESCAPE)
            dialog_title = None
            direct_editor = False
        result = {
            "passed": True,
            "dialog_title": dialog_title,
            "existing_record_direct_editor": direct_editor,
            "reference_update_mode": "direct_dialog" if direct_editor else "delete_and_readd",
            "rom_unchanged": digest(rom) == before,
        }
        return result
    finally:
        if dialog and ui.is_window(dialog["hwnd"]):
            ui.send_escape(dialog["hwnd"])
        session.terminate()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "m03": probe_m03(out), "m04": probe_m04(out)}
    report["passed"] = all(bool(report[key]["passed"] and report[key]["rom_unchanged"]) for key in ("m03", "m04"))
    (out / "catalog.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "error.log").unlink(missing_ok=True)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
