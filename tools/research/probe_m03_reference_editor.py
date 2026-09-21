"""Enumerate the owner-drawn M03 page, context menu and deployment editor."""

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


OUT = ROOT / "output/verification/legacy-m03-reference-controls-20260920"
SOURCE_RUNTIME = ROOT / "output/build/legacy-diff-audit"
SOURCE_ROM = ROOT / "output/build/legacy-diff-audit/audit.nes"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    out = args.out.resolve()
    runtime = ROOT / "output/build/legacy-ui-probe"
    runtime.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_RUNTIME / "SRW2_patched.exe", runtime / "SRW2_patched.exe")
    if not (runtime / "默认配置文件").exists():
        shutil.copytree(
            SOURCE_RUNTIME / "默认配置文件/默认配置文件",
            runtime / "默认配置文件",
        )
    probe_rom = runtime / "probe.nes"
    shutil.copy2(SOURCE_ROM, probe_rom)
    before = sha(probe_rom)

    session = ui.ProbeSession(ROOT, "m03-reference-controls-20260920")
    session.out = out
    session.shots = out / "screenshots"
    session.controls = out / "controls"
    session.shots.mkdir(parents=True, exist_ok=True)
    session.controls.mkdir(parents=True, exist_ok=True)
    session.probe_rom = probe_rom
    session.launch()
    dialog = None
    try:
        ui.stage_a(session)
        if not session.open_rom_via_menu(probe_rom, "M03_打开ROM对话框"):
            raise RuntimeError("M03 probe ROM did not open")
        # Stop after the second distinct main page: the initial-configuration page.
        ui.sweep_tabs(session, session.main_hwnd, "M03_主窗口页签", max_pages=2)
        tree = ui.enum_child_tree(session.main_hwnd)
        maps = ui.find_controls(tree, ctrl_id=500)
        if len(maps) != 1:
            raise RuntimeError(f"M03 map control 500 matched {len(maps)}")
        map_control = maps[0]
        session.snapshot_known()
        main_rect = ui.get_window_rect(session.main_hwnd)
        map_rect = ui.get_window_rect(map_control["hwnd"])
        dx, dy = ui._client_offset(session.main_hwnd)
        map_x = map_rect["left"] + 96 - main_rect["left"] - dx
        map_y = map_rect["top"] + 96 - main_rect["top"] - dy
        if not ui.real_click_at(session.main_hwnd, map_x, map_y, button="right"):
            raise RuntimeError("M03 map right click failed")
        time.sleep(0.4)
        ui.capture_screen_region(
            ui.get_window_rect(session.main_hwnd),
            session.shots / "M03_初始配置_右键菜单.png",
            pad=80,
        )
        # A freshly opened Win32 popup menu has no active item. Select the
        # first enabled command explicitly before confirming it.
        ui.keybd(0x28)  # VK_DOWN
        time.sleep(0.1)
        ui.keybd(0x28, up=True)
        time.sleep(0.1)
        ui.keybd(ui.VK_RETURN)
        time.sleep(0.1)
        ui.keybd(ui.VK_RETURN, up=True)
        dialog = session.wait_new_top(timeout=8.0, title_contains="配置设置")
        if not dialog:
            raise RuntimeError("M03 deployment editor dialog did not open")
        session.dump_window(dialog["hwnd"], "M03_配置设置", menu=False)
        payload = json.loads(
            (session.controls / "M03_配置设置.json").read_text(encoding="utf-8")
        )
        visible = [
            item
            for item in ui.flatten_tree(payload["tree"])
            if item.get("visible") and item.get("ctrl_id")
        ]
        report = {
            "passed": bool(visible) and sha(probe_rom) == before,
            "source_rom": SOURCE_ROM.relative_to(ROOT).as_posix(),
            "source_sha256": before,
            "rom_unchanged": sha(probe_rom) == before,
            "dialog_title": dialog["title"],
            "visible_control_count": len(visible),
            "visible_controls": [
                {
                    "control_id": int(item["ctrl_id"]),
                    "class": item["class"],
                    "text": item.get("text", ""),
                    "enabled": bool(item.get("enabled")),
                }
                for item in visible
            ],
        }
        (out / "catalog.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (out / "error.log").unlink(missing_ok=True)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["passed"] else 1
    finally:
        if dialog and ui.is_window(dialog["hwnd"]):
            ui.send_escape(dialog["hwnd"])
        session.terminate()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
