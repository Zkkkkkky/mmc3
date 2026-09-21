"""Run one isolated save/cold-read probe for every M14 direct field family."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import shutil
import sys
import time
import traceback
from pathlib import Path

import win32con
import win32gui

ROOT_HINT = Path(__file__).resolve().parents[2]
if str(ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(ROOT_HINT))

from tools.golden_pipeline_collect import Win32LegacyDriver
from tools.research import probe_m14_reference_catalog as catalog


ROOT = catalog.ROOT
AUDIT = catalog.AUDIT
SOURCE = catalog.SOURCE
OUT = ROOT / "output/verification/legacy-m14-reference-family-saves-20260920"
RESULT = OUT / "summary.json"
CASES = (
    {"family": "chapter_title", "page": 0, "selector": (220, "ListBox", 0), "control": (600, "Edit")},
    {"family": "chapter_initial_victory", "page": 0, "selector": (220, "ListBox", 0), "control": (190, "Edit")},
    {"family": "action_name", "page": 1, "selector": (260, "ListBox", 0), "control": (390, "Edit")},
    {"family": "surrender_chapter", "page": 2, "selector": (310, "ListBox", 0), "control": (430, "ComboBox")},
    {"family": "surrender_ally", "page": 2, "selector": (310, "ListBox", 0), "control": (440, "ComboBox")},
    {"family": "surrender_enemy", "page": 2, "selector": (310, "ListBox", 0), "control": (460, "ComboBox")},
    {"family": "map_name", "page": 3, "selector": (360, "ListBox", 0), "control": (490, "Edit")},
    {"family": "map_name_empty", "page": 3, "selector": (360, "ListBox", 3), "control": (490, "Edit")},
    {"family": "story_text", "page": 4, "selector": ((570, "ComboBox", 0), (560, "ListBox", 0)), "control": (520, "Edit")},
    {"family": "story_text_empty", "page": 4, "selector": ((570, "ComboBox", 0), (560, "ListBox", 110)), "control": (520, "Edit")},
    {"family": "victory_text", "page": 5, "selector": (630, "ListBox", 0), "control": (650, "Edit")},
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def diff_ranges(before: bytes, after: bytes) -> list[dict[str, object]]:
    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    if not changed:
        return []
    result = []
    start = previous = changed[0]
    for offset in changed[1:] + [changed[-1] + 2]:
        if offset != previous + 1:
            end = previous + 1
            result.append({"start": start, "end_exclusive": end, "before_hex": before[start:end].hex().upper(), "after_hex": after[start:end].hex().upper()})
            start = offset
        previous = offset
    return result


def prepare_runtime(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    shutil.copy2(AUDIT / "SRW2_patched.exe", path / "SRW2_patched.exe")
    shutil.copytree(AUDIT / "默认配置文件/默认配置文件", path / "默认配置文件")


def launch(runtime: Path, rom: Path) -> Win32LegacyDriver:
    driver = Win32LegacyDriver()
    driver.launch(runtime / "SRW2_patched.exe", runtime)
    driver.open_rom(rom)
    catalog.open_editor(driver)
    return driver


def navigate(driver: Win32LegacyDriver, case: dict[str, object]) -> None:
    catalog.page(driver, int(case["page"]))
    selectors = case["selector"]
    if isinstance(selectors[0], int):
        selectors = (selectors,)
    for control_id, class_name, row in selectors:
        control = catalog.any_control(driver, int(control_id), str(class_name))
        if class_name == "ListBox":
            catalog.select_list(control, int(row))
        else:
            catalog.select_combo(control, int(row))


def read(driver: Win32LegacyDriver, case: dict[str, object]) -> int | str:
    navigate(driver, case)
    control_id, class_name = case["control"]
    control = catalog.any_control(driver, int(control_id), str(class_name))
    return int(control.selected_index()) if class_name == "ComboBox" else control.window_text()


def mutate(driver: Win32LegacyDriver, case: dict[str, object], original: int | str) -> int | str:
    control_id, class_name = case["control"]
    control = catalog.any_control(driver, int(control_id), str(class_name))
    if class_name == "ComboBox":
        count = len(control.item_texts())
        return (int(original) + 1) % count
    text = str(original)
    return "_" + text[1:] if text else "_"


def set_value(driver: Win32LegacyDriver, case: dict[str, object], value: int | str) -> None:
    control_id, class_name = case["control"]
    control = catalog.any_control(driver, int(control_id), str(class_name))
    if class_name == "ComboBox":
        catalog.select_combo(control, int(value))
        return
    control.set_edit_text(str(value))
    parent = win32gui.GetParent(control.handle)
    win32gui.SendMessage(parent, win32con.WM_COMMAND, int(control_id) | (0x0300 << 16), control.handle)
    time.sleep(0.1)


def commit_and_save(driver: Win32LegacyDriver) -> None:
    button = catalog.any_control(driver, 100, "Button")
    button.click()
    deadline = time.monotonic() + 5.0
    handle = int(driver.current_window.handle)
    while win32gui.IsWindow(handle) and time.monotonic() < deadline:
        time.sleep(0.05)
    driver.current_window = driver._main()
    driver.save()


def run_case(case: dict[str, object], index: int) -> dict[str, object]:
    family = str(case["family"])
    case_dir = OUT / family
    case_dir.mkdir(parents=True, exist_ok=True)
    progress_path = OUT / f"progress-{family}.json"

    def progress(stage: str, **details: object) -> None:
        progress_path.write_text(
            json.dumps({"family": family, "stage": stage, **details}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    progress("prepare")
    work = case_dir / "work.nes"
    shutil.copy2(SOURCE, work)
    baseline = work.read_bytes()
    save_runtime = case_dir / "save-runtime"
    cold_runtime = case_dir / "cold-runtime"
    prepare_runtime(save_runtime)
    progress("launch_save")
    driver = launch(save_runtime, work)
    try:
        progress("read_and_mutate", pid=driver.pid)
        original = read(driver, case)
        requested = mutate(driver, case, original)
        set_value(driver, case, requested)
        observed_before_commit = read(driver, case)
        progress("commit_and_save", pid=driver.pid, original=original, requested=requested)
        commit_and_save(driver)
    finally:
        driver.stop()
    # The reference launcher occasionally keeps a just-closed child alive for
    # a fraction of a second.  Let it release its single-instance state before
    # the required independent cold-read process starts.
    time.sleep(1.0)
    after = work.read_bytes()
    prepare_runtime(cold_runtime)
    progress("launch_cold")
    cold = launch(cold_runtime, work)
    try:
        progress("cold_read", pid=cold.pid)
        cold_readback = read(cold, case)
    finally:
        cold.stop()
    ranges = diff_ranges(baseline, after)
    if cold_readback == requested and ranges:
        status = "persistent"
    elif cold_readback == original and not ranges:
        status = "no_effect_or_volatile"
    elif cold_readback == requested:
        status = "readback_without_rom_diff"
    else:
        status = "unstable"
    result = {
        "sequence": index,
        "family": family,
        "original": original,
        "requested": requested,
        "observed_before_commit": observed_before_commit,
        "cold_readback": cold_readback,
        "status": status,
        "before_sha256": sha(baseline),
        "after_sha256": sha(after),
        "changed_bytes": sum(int(item["end_exclusive"]) - int(item["start"]) for item in ranges),
        "ranges": ranges,
    }
    progress("complete", status=status, cold_readback=cold_readback)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    selected = [case for case in CASES if args.family is None or case["family"] == args.family]
    if not selected:
        raise SystemExit(f"unknown family: {args.family}")
    for index, case in enumerate(selected):
        try:
            results.append(run_case(case, index))
        except Exception as exc:
            results.append({"sequence": index, "family": case["family"], "status": "error", "error": repr(exc), "traceback": traceback.format_exc()})
        target = RESULT if args.family is None else OUT / f"retry-{args.family}.json"
        target.write_text(json.dumps({"passed": False, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    passed = all(item["status"] != "error" and item["status"] != "unstable" for item in results)
    target = RESULT if args.family is None else OUT / f"retry-{args.family}.json"
    target.write_text(json.dumps({"passed": passed, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
