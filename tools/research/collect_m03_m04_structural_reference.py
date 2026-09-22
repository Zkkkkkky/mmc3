"""Collect reference-editor add/delete evidence for M03 and M04.

Every case starts from the normalized reference-compatible ROM, saves through
the legacy UI, and is decoded again from disk.  The immutable audit input and
reference runtime are copied into an isolated verification directory.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fc_editor.codecs.scenario_layout import ScenarioLayoutCodec
from fc_editor.rom_image import RomImage
from tools.golden_pipeline_collect import Win32LegacyDriver
from tools.research import legacy_ui_probe as ui
from tools.research import reference_map_editor as ref


AUDIT = ROOT / "output/build/legacy-diff-audit"
SOURCE = AUDIT / "audit.nes"
OUT = ROOT / "output/verification/legacy-m03-m04-structural-20260921"
RUNTIME = OUT / "reference-runtime"
NORMALIZED = OUT / "normalized-baseline.nes"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def differences(before: bytes, after: bytes) -> list[dict[str, int]]:
    return [
        {"offset": index, "before": left, "after": right}
        for index, (left, right) in enumerate(zip(before, after, strict=True))
        if left != right
    ]


def prepare_runtime() -> None:
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    RUNTIME.mkdir(parents=True)
    shutil.copy2(AUDIT / "SRW2_patched.exe", RUNTIME / "SRW2_patched.exe")
    shutil.copytree(AUDIT / "默认配置文件/默认配置文件", RUNTIME / "默认配置文件")


def launch() -> Win32LegacyDriver:
    driver = Win32LegacyDriver()
    driver.launch(RUNTIME / "SRW2_patched.exe", RUNTIME)
    return driver


def right_click_delete_last(
    driver: Win32LegacyDriver,
    x: int,
    y: int,
    width: int,
    height: int,
) -> None:
    main = driver._main()
    point = ref.cell_client_point(driver, x, y, width, height)
    if not ui.real_click_at(int(main.handle), *point, button="right"):
        raise RuntimeError(f"reference context menu did not open at {(x, y)}")
    time.sleep(0.25)
    popups = [
        item
        for item in ui.enum_top_windows(ui.window_pid(int(main.handle)))
        if item["class"] == "#32768"
    ]
    if len(popups) != 1:
        raise RuntimeError(f"reference popup menu count is {len(popups)}, expected 1")
    rect = popups[0]["rect"]
    ui.user32.SetCursorPos((rect["left"] + rect["right"]) // 2, rect["bottom"] - 16)
    time.sleep(0.1)
    ui.user32.mouse_event(ui.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.04)
    ui.user32.mouse_event(ui.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.3)


def add_m03_enemy(driver: Win32LegacyDriver, x: int, y: int) -> None:
    ref.select_main_page(driver, 1)
    ref.select_map(driver, 0)
    ref.context_command(driver, x, y, 23, 21, 1)
    ref.wait_dialog(driver, "配置设置")
    ref.set_combo(driver, 120, 0)  # enemy
    ref.set_combo(driver, 140, 0)  # ROM pilot 01
    ref.set_combo(driver, 160, 0)  # ROM unit 01
    ref.set_combo(driver, 180, 0)  # level 01
    ref.set_combo(driver, 200, 0)  # action 00
    ref.click_button(driver, 240)
    driver.current_window = driver._main()


def add_m04_event(driver: Win32LegacyDriver, x: int, y: int) -> None:
    ref.select_main_page(driver, 2)
    ref.select_map(driver, 0)
    ref.context_command(driver, x, y, 23, 21, 1)
    ref.wait_dialog(driver, "商店设置")
    ref.set_combo(driver, 100, 0)  # any character -> FF
    ref.click_button(driver, 190)  # event
    ref.set_combo(driver, 170, 1)
    ref.click_button(driver, 140)
    driver.current_window = driver._main()


def scenario_counts(path: Path) -> dict[str, int]:
    layout = ScenarioLayoutCodec(RomImage.load(path)).decode(0)
    return {
        "enemy": len(layout.enemies),
        "guest": len(layout.guests),
        "player": len(layout.player_placements),
        "encoded_bytes": len(ScenarioLayoutCodec.encode(layout)),
    }


def run_case(
    driver: Win32LegacyDriver,
    name: str,
    action,
    *,
    decoder=None,
) -> dict[str, object]:
    target = OUT / f"{name}.nes"
    shutil.copy2(NORMALIZED, target)
    before = target.read_bytes()
    driver.open_rom(target)
    action(driver)
    ref.save(driver)
    after = target.read_bytes()
    result: dict[str, object] = {
        "case": name,
        "before_sha256": sha(before),
        "after_sha256": sha(after),
        "changed": differences(before, after),
        "changed_count": sum(left != right for left, right in zip(before, after, strict=True)),
    }
    if decoder is not None:
        result["decoded"] = decoder(target)
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    prepare_runtime()
    shutil.copy2(SOURCE, NORMALIZED)
    driver = launch()
    try:
        driver.open_rom(NORMALIZED)
        ref.save(driver)
        cases = [
            run_case(driver, "m03-add-enemy", lambda item: add_m03_enemy(item, 0, 0), decoder=scenario_counts),
            run_case(
                driver,
                "m03-delete-player",
                lambda item: (
                    ref.select_main_page(item, 1),
                    ref.select_map(item, 0),
                    right_click_delete_last(item, 4, 9, 23, 21),
                ),
                decoder=scenario_counts,
            ),
            run_case(driver, "m04-add-event", lambda item: add_m04_event(item, 0, 0)),
            run_case(
                driver,
                "m04-delete-event",
                lambda item: (
                    ref.select_main_page(item, 2),
                    ref.select_map(item, 0),
                    ref.context_command(item, 9, 3, 23, 21, 2),
                ),
            ),
        ]
    finally:
        driver.stop()
        time.sleep(2.0)

    report = {
        "schema_version": 1,
        "modules": ["M03", "M04"],
        "normalized_sha256": sha(NORMALIZED.read_bytes()),
        "cases": cases,
        "passed": all(case["changed_count"] > 0 for case in cases),
    }
    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / "error.log").unlink(missing_ok=True)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
