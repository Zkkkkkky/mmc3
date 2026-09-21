"""Collect resumable, isolated reference-save evidence for M12 edit controls."""

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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.golden_pipeline_collect import Win32LegacyDriver


AUDIT = ROOT / "output/build/legacy-diff-audit"
# M12 save behavior must use the reference editor's own compatible baseline.
# Opening audit.nes is useful for control enumeration, but any save causes the
# old editor to normalize thousands of unrelated bytes before discarding the
# requested pointer.  The bundled 测试.nes is the baseline used by the existing
# M12 positive/negative golden cases.
SOURCE = AUDIT / "默认配置文件" / "测试.nes"
CATALOG_PATH = ROOT / "output/reports/m12-reference-field-catalog.json"
OUT = ROOT / "output/verification/legacy-m12-all-fields-20260920"
RUNTIME = OUT / "reference-runtime"
WORK = OUT / "work.nes"
EVIDENCE = OUT / "field-save-chain.jsonl"
STATE = OUT / "state.json"
PROGRESS = OUT / "progress.log"
SUMMARY = OUT / "summary.json"
NORMALIZATION_OFFSETS = {0x4A101, 0x4A102, 0x4AE2A, 0x4AE2B, 0x79538, 0x79539}
FAMILY_ORDER = {
    "map_pointer_action_input": 0,
    "movement_code": 1,
    "sprite_code": 2,
    "sprite_x": 3,
    "sprite_y": 4,
    "background_code": 5,
    "spirit_animation": 6,
    "map_weapon_animation_1": 7,
    "map_weapon_animation_2": 8,
    "map_weapon_animation_3": 9,
    "map_weapon_animation_4": 10,
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with PROGRESS.open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def diff_ranges(before: bytes, after: bytes) -> list[dict[str, object]]:
    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    if not changed:
        return []
    result = []
    start = previous = changed[0]
    for offset in changed[1:] + [changed[-1] + 2]:
        if offset != previous + 1:
            end = previous + 1
            result.append(
                {
                    "start": start,
                    "end_exclusive": end,
                    "before_hex": before[start:end].hex().upper(),
                    "after_hex": after[start:end].hex().upper(),
                }
            )
            start = offset
        previous = offset
    return result


def fields() -> list[dict[str, object]]:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    result = [field for field in catalog["fields"] if field["family"] in FAMILY_ORDER]
    return sorted(result, key=lambda item: (FAMILY_ORDER[str(item["family"])], int(item["row"])))


def append_evidence(payload: dict[str, object]) -> None:
    with EVIDENCE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def save_state(completed: int, total: int) -> None:
    STATE.write_text(json.dumps({"completed": completed, "total": total}, indent=2) + "\n", encoding="utf-8")


def open_animation(driver: Win32LegacyDriver) -> None:
    main = driver._main()
    ctypes.windll.user32.PostMessageW(int(main.handle), win32con.WM_COMMAND, 20011, 0)
    driver.current_window = driver._wait_window(lambda item: item.window_text() == "地图动画")


def select_tab(driver: Win32LegacyDriver, x: int) -> None:
    rect = driver.current_window.rectangle()
    driver.current_window.click_input(coords=(int(x * rect.width() / 847), int(75 * rect.height() / 653)))
    time.sleep(0.12)


def select_listbox(driver: Win32LegacyDriver, control_id: int, row: int) -> None:
    box = driver._control(control_id, "ListBox")
    if win32gui.SendMessage(box.handle, 0x0186, row, 0) == -1:
        raise RuntimeError(f"ListBox {control_id} row {row} unavailable")
    win32gui.SendMessage(win32gui.GetParent(box.handle), win32con.WM_COMMAND, control_id | (1 << 16), box.handle)
    time.sleep(0.04)


def combo_index(driver: Win32LegacyDriver, control_id: int) -> int:
    raw = int(win32gui.SendMessage(driver._control(control_id, "ComboBox").handle, 0x0147, 0, 0))
    return -1 if raw == 0xFFFFFFFF else raw


def open_pointer_dialog(driver: Win32LegacyDriver):
    owner = driver.current_window
    button = driver._control(150, "Button")
    win32gui.PostMessage(button.handle, win32con.BM_CLICK, 0, 0)
    dialog = driver._wait_window(
        lambda item: item.is_visible() and int(item.handle) != int(owner.handle) and item.window_text().startswith("请输入"),
        timeout=4.0,
    )
    driver.current_window = dialog
    return owner, dialog


def close_dialog(driver: Win32LegacyDriver, owner, dialog, button_id: int) -> None:
    handle = int(dialog.handle)
    driver._control(button_id, "Button").click_input()
    deadline = time.monotonic() + 3.0
    while win32gui.IsWindow(handle) and time.monotonic() < deadline:
        time.sleep(0.02)
    if win32gui.IsWindow(handle):
        raise RuntimeError(f"dialog button {button_id} did not close window")
    driver.current_window = owner


def navigate(driver: Win32LegacyDriver, field: dict[str, object]) -> None:
    family = str(field["family"])
    row = int(field["row"])
    if family == "map_pointer_action_input":
        select_tab(driver, 45)
        select_listbox(driver, 110, row)
    elif family == "movement_code":
        select_tab(driver, 95)
        select_listbox(driver, 160, row)
    elif family.startswith("sprite_"):
        select_tab(driver, 95)
        select_listbox(driver, 220, row)
    elif family == "background_code":
        select_tab(driver, 95)
        select_listbox(driver, 530, row)
    elif family == "spirit_animation":
        select_tab(driver, 145)
        select_listbox(driver, 360, row)
    elif family.startswith("map_weapon_animation_"):
        select_tab(driver, 145)
        select_listbox(driver, 410, row)
    else:
        raise ValueError(f"unsupported family {family}")


def read_field(driver: Win32LegacyDriver, field: dict[str, object]) -> int | str:
    navigate(driver, field)
    family = str(field["family"])
    if family == "map_pointer_action_input":
        owner, dialog = open_pointer_dialog(driver)
        value = driver._control(1001, "Edit").window_text()
        close_dialog(driver, owner, dialog, 2)
        return value
    if family == "movement_code":
        return driver._control(190, "Edit").window_text()
    if family == "sprite_code":
        return driver._control(240, "Edit").window_text()
    if family == "sprite_x":
        return driver._control(630, "Edit").window_text()
    if family == "sprite_y":
        return driver._control(650, "Edit").window_text()
    if family == "background_code":
        return driver._control(550, "Edit").window_text()
    if family == "spirit_animation":
        return combo_index(driver, 400)
    return combo_index(driver, int(field["control_id"]))


def mutate_code(text: str, family: str) -> str:
    tokens = text.split()
    if not tokens:
        return "00 "
    if family == "sprite_code" and len(tokens) >= 3:
        index = 2
    else:
        candidates = [index for index, token in enumerate(tokens) if int(token, 16) < 0xEE]
        index = candidates[0] if candidates else 0
    value = int(tokens[index], 16)
    tokens[index] = f"{(value + 1) & 0xFF:02X}"
    return " ".join(tokens) + " "


def mutation(driver: Win32LegacyDriver, field: dict[str, object], actual: int | str) -> int | str:
    family = str(field["family"])
    if family == "map_pointer_action_input":
        value = int(str(actual), 16)
        return f"{(value + 1) & 0xFFFF:04X}"
    if family in {"movement_code", "sprite_code", "background_code"}:
        return mutate_code(str(actual), family)
    if family in {"sprite_x", "sprite_y"}:
        return str((int(actual) + 1) & 0xFF)
    combo_id = 400 if family == "spirit_animation" else int(field["control_id"])
    combo = driver._control(combo_id, "ComboBox")
    count = int(win32gui.SendMessage(combo.handle, 0x0146, 0, 0))
    return 0 if int(actual) < 0 else (int(actual) + 1) % max(count, 1)


def commit(driver: Win32LegacyDriver, field: dict[str, object], requested: int | str) -> None:
    family = str(field["family"])
    navigate(driver, field)
    if family == "map_pointer_action_input":
        owner, dialog = open_pointer_dialog(driver)
        driver.perform(({"op": "set_text", "class": "Edit", "control_id": 1001, "value": str(requested)},), requested)
        close_dialog(driver, owner, dialog, 1)
    elif family in {"movement_code", "sprite_code", "sprite_x", "sprite_y", "background_code"}:
        edit_id = {"movement_code": 190, "sprite_code": 240, "sprite_x": 630, "sprite_y": 650, "background_code": 550}[family]
        driver.perform(({"op": "set_text", "class": "Edit", "control_id": edit_id, "value": str(requested)},), requested)
    else:
        combo_id = 400 if family == "spirit_animation" else int(field["control_id"])
        driver.perform(({"op": "select_index_message", "class": "ComboBox", "control_id": combo_id, "value": int(requested)},), requested)
        set_button = 380 if family == "spirit_animation" else 430
        driver._control(set_button, "Button").click_input()
        time.sleep(0.08)
    window = driver.current_window
    driver.perform(({"op": "click_id", "class": "Button", "control_id": 310},), 0)
    time.sleep(0.2)
    driver.current_window = driver._main()


def close_without_commit(driver: Win32LegacyDriver) -> None:
    handle = int(driver.current_window.handle)
    driver.perform(({"op": "click_id", "class": "Button", "control_id": 300},), 0)
    deadline = time.monotonic() + 3.0
    while win32gui.IsWindow(handle) and win32gui.IsWindowVisible(handle) and time.monotonic() < deadline:
        time.sleep(0.02)
    driver.current_window = driver._main()


def save_with_retry(driver: Win32LegacyDriver) -> None:
    last: Exception | None = None
    for _ in range(3):
        try:
            driver.save()
            return
        except RuntimeError as error:
            last = error
    raise last or RuntimeError("save failed")


def launch_with_retry(label: str, sequence: int, field_id: str) -> Win32LegacyDriver:
    last: Exception | None = None
    for attempt in range(3):
        driver = Win32LegacyDriver()
        try:
            pid = driver.launch(RUNTIME / "SRW2_patched.exe", RUNTIME)
            log(f"{label} pid={pid} sequence={sequence} field={field_id} attempt={attempt + 1}")
            return driver
        except Exception as error:
            last = error
            log(f"{label} launch retry sequence={sequence} attempt={attempt + 1}: {error}")
            driver.stop()
            time.sleep(0.8)
    raise last or RuntimeError(f"{label} launch failed")


def collect_session(items: list[dict[str, object]], start: int, stop: int) -> None:
    for index in range(start, stop):
        field = items[index]
        before = WORK.read_bytes()
        save_driver = launch_with_retry("save", index, str(field["field_id"]))
        try:
            save_driver.open_rom(WORK)
            open_animation(save_driver)
            actual_before = read_field(save_driver, field)
            requested = mutation(save_driver, field, actual_before)
            commit(save_driver, field, requested)
            save_with_retry(save_driver)
        finally:
            save_driver.stop()
        observed = WORK.read_bytes()
        ranges = diff_ranges(before, observed)
        read_driver = launch_with_retry("cold-read", index, str(field["field_id"]))
        try:
            read_driver.open_rom(WORK)
            open_animation(read_driver)
            actual_after = read_field(read_driver, field)
        finally:
            read_driver.stop()
        semantic_changed = any(
            offset not in NORMALIZATION_OFFSETS
            for change in ranges
            for offset in range(int(change["start"]), int(change["end_exclusive"]))
        )
        if actual_after == requested and semantic_changed:
            status = "reference_saved_product_blocked"
        elif actual_after == actual_before and not semantic_changed:
            status = "no_effect"
        elif actual_after == requested:
            status = "readback_only_or_normalization_only"
        else:
            status = "unstable"
        append_evidence(
            {
                "sequence": index,
                "field_id": field["field_id"],
                "family": field["family"],
                "row": field["row"],
                "original": actual_before,
                "mutated": requested,
                "cold_process_readback": actual_after,
                "status": status,
                "before_sha256": sha(before),
                "observed_after_sha256": sha(observed),
                "changed_bytes": sum(int(item["end_exclusive"]) - int(item["start"]) for item in ranges),
                "semantic_changed": semantic_changed,
                "observed_ranges": ranges,
            }
        )
        shutil.copy2(SOURCE, WORK)
        save_state(index + 1, len(items))
        if (index + 1) % 10 == 0 or index + 1 == stop:
            log(f"probed {index + 1}/{len(items)}")


def write_summary(items: list[dict[str, object]]) -> None:
    lines = [json.loads(line) for line in EVIDENCE.read_text(encoding="utf-8").splitlines() if line.strip()]
    statuses: dict[str, int] = {}
    families: dict[str, int] = {}
    for item in lines:
        statuses[item["status"]] = statuses.get(item["status"], 0) + 1
        families[item["family"]] = families.get(item["family"], 0) + 1
    SUMMARY.write_text(
        json.dumps(
            {
                "passed": len(lines) == len(items),
                "logical_fields": len(items),
                "completed": len(lines),
                "statuses": dict(sorted(statuses.items())),
                "family_probe_counts": dict(sorted(families.items())),
                "baseline_sha256": sha(SOURCE.read_bytes()),
                "work_restored_to_baseline": sha(WORK.read_bytes()) == sha(SOURCE.read_bytes()),
                "evidence": EVIDENCE.relative_to(ROOT).as_posix(),
                "limitations": [
                    "每项为独立基线、单字段保存和全新 PID 冷读；产品未安全支持的完整代码框不会累计到最终 ROM。",
                    "保存入口全集与名称元数据链尚未完成；当前状态不得计入最终安全分母。",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    items = fields()
    if len(items) != 784:
        raise ValueError(f"expected 784 M12 save probes, got {len(items)}")
    if args.restart:
        if RUNTIME.exists():
            shutil.rmtree(RUNTIME)
        RUNTIME.mkdir(parents=True)
        shutil.copy2(AUDIT / "SRW2_patched.exe", RUNTIME / "SRW2_patched.exe")
        shutil.copytree(
            AUDIT / "默认配置文件" / "默认配置文件",
            RUNTIME / "默认配置文件",
        )
        shutil.copy2(SOURCE, WORK)
        for path in (EVIDENCE, STATE, SUMMARY, OUT / "error.log"):
            path.unlink(missing_ok=True)
        PROGRESS.write_text("restart\n", encoding="utf-8")
    elif not WORK.exists():
        shutil.copy2(SOURCE, WORK)
    if not (RUNTIME / "SRW2_patched.exe").is_file():
        raise RuntimeError("isolated M12 reference runtime is missing; rerun with --restart")
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"completed": 0}
    start = int(state["completed"])
    stop = len(items) if args.limit is None else min(len(items), start + args.limit)
    cursor = start
    while cursor < stop:
        session_stop = min(stop, cursor + 20)
        collect_session(items, cursor, session_stop)
        cursor = session_stop
    write_summary(items)
    (OUT / "error.log").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    raise SystemExit(result)
