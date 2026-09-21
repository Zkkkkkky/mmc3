"""Measure the reference map geometry on the first map containing guests."""

from __future__ import annotations

import json
import shutil
import sys
import time
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.golden_pipeline_collect import Win32LegacyDriver
from tools.research import legacy_ui_probe as ui
from tools.research import reference_map_editor as ref


AUDIT = ROOT / "output/build/legacy-diff-audit"
OUT = ROOT / "output/verification/legacy-m03-guest-map-geometry-20260920"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    runtime = OUT / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir()
    shutil.copy2(AUDIT / "SRW2_patched.exe", runtime / "SRW2_patched.exe")
    shutil.copytree(AUDIT / "默认配置文件/默认配置文件", runtime / "默认配置文件")
    rom = runtime / "probe.nes"
    shutil.copy2(AUDIT / "audit.nes", rom)
    driver = Win32LegacyDriver()
    try:
        driver.launch(runtime / "SRW2_patched.exe", runtime)
        driver.open_rom(rom)
        ref.select_main_page(driver, 1)
        ref.select_map(driver, 17)
        main = driver._main()
        ui.capture_screen_region(ui.get_window_rect(int(main.handle)), OUT / "map17.png", pad=80)
        point = ref.cell_client_point(driver, 4, 27, 30, 30)
        ui.real_click_at(int(main.handle), *point, button="right")
        time.sleep(0.4)
        ui.capture_screen_region(ui.get_window_rect(int(main.handle)), OUT / "map17-point-4-27-menu.png", pad=80)
        tree = ui.enum_child_tree(int(main.handle))
        status = [
            {"control_id": item["ctrl_id"], "text": item["text"]}
            for item in ui.flatten_tree(tree)
            if item.get("visible") and item.get("ctrl_id") in {590, 600}
        ]
        ref.press(ui.VK_ESCAPE)
        result = {"passed": True, "requested_cell": [4, 27], "client_point": list(point), "status": status}
        (OUT / "geometry.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (OUT / "error.log").unlink(missing_ok=True)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        driver.stop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
