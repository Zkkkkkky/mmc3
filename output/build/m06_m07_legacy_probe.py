from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import win32api
import win32con
import win32gui


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.golden_pipeline_collect import Win32LegacyDriver  # noqa: E402
from tools.research.legacy_ui_probe import get_ctrl_text  # noqa: E402


AUDIT = ROOT / "output" / "build" / "legacy-diff-audit"
RUN = AUDIT / "cases" / "exploratory-m06-m07"
ROM = RUN / "probe.nes"
EXE = AUDIT / "SRW2_patched.exe"


def visible_controls(driver: Win32LegacyDriver) -> list[dict[str, object]]:
    result = []
    for item in driver.current_window.descendants():
        try:
            control_id = int(item.control_id())
            if control_id and item.is_visible():
                result.append(
                    {
                        "id": control_id,
                        "class": item.class_name(),
                        "text": item.window_text(),
                        "enabled": bool(item.is_enabled()),
                    }
                )
        except Exception:
            pass
    return sorted(result, key=lambda row: (int(row["id"]), str(row["class"])))


def top_windows(driver: Win32LegacyDriver) -> list[dict[str, object]]:
    result = []
    for item in driver.app.windows(visible_only=True):
        try:
            result.append(
                {
                    "handle": int(item.handle),
                    "class": item.class_name(),
                    "title": item.window_text(),
                    "controls": [
                        {
                            "id": int(child.control_id()),
                            "class": child.class_name(),
                            "text": child.window_text(),
                        }
                        for child in item.descendants()
                        if int(child.control_id())
                        and child.is_visible()
                    ],
                }
            )
        except Exception:
            pass
    return result


def select_list(driver: Win32LegacyDriver, control_id: int, row: int) -> None:
    driver.perform(
        ({"op": "list_select", "class": "ListBox", "control_id": control_id, "row": row},),
        0,
    )
    time.sleep(0.7)


def has_visible_id(driver: Win32LegacyDriver, control_id: int) -> bool:
    return any(
        int(item.control_id()) == control_id and item.is_visible()
        for item in driver.current_window.descendants()
    )


def select_database_tab(
    driver: Win32LegacyDriver, x: int, index: int, expected_id: int
) -> None:
    page = next(
        item
        for item in driver.current_window.descendants(class_name="CPageControl")
        if int(item.control_id()) == 100
    )
    point = win32api.MAKELONG(x, 24)
    win32gui.SendMessage(page.handle, win32con.WM_LBUTTONDOWN, 1, point)
    win32gui.SendMessage(page.handle, win32con.WM_LBUTTONUP, 0, point)
    time.sleep(0.4)
    if has_visible_id(driver, expected_id):
        return
    win32gui.SendMessage(page.handle, 0x130C, index, 0)  # TCM_SETCURSEL
    time.sleep(0.4)
    if has_visible_id(driver, expected_id):
        return
    win32gui.SendMessage(page.handle, win32con.WM_SETFOCUS, 0, 0)
    for _ in range(index):
        win32gui.SendMessage(page.handle, win32con.WM_KEYDOWN, win32con.VK_RIGHT, 0)
        win32gui.SendMessage(page.handle, win32con.WM_KEYUP, win32con.VK_RIGHT, 0)
        time.sleep(0.2)
    if has_visible_id(driver, expected_id):
        return
    for _ in range(index):
        win32gui.PostMessage(driver.current_window.handle, win32con.WM_KEYDOWN, win32con.VK_CONTROL, 0)
        win32gui.PostMessage(driver.current_window.handle, win32con.WM_KEYDOWN, win32con.VK_TAB, 0)
        win32gui.PostMessage(driver.current_window.handle, win32con.WM_KEYUP, win32con.VK_TAB, 0)
        win32gui.PostMessage(driver.current_window.handle, win32con.WM_KEYUP, win32con.VK_CONTROL, 0)
        time.sleep(0.3)
    if not has_visible_id(driver, expected_id):
        raise RuntimeError(f"无法通过窗口消息切换到含控件 {expected_id} 的页签")


def list_state(driver: Win32LegacyDriver, control_id: int) -> dict[str, object]:
    item = driver._control(control_id, "ListBox")
    count = int(win32gui.SendMessage(item.handle, 0x018B, 0, 0))
    selected = int(win32gui.SendMessage(item.handle, 0x0188, 0, 0))
    texts = item.item_texts()
    return {"count": count, "selected": selected, "first": texts[:3], "last": texts[-3:]}


def click_and_observe(driver: Win32LegacyDriver, control_id: int) -> dict[str, object]:
    before = list_state(driver, 630 if control_id == 2120 else 610)
    driver._control(control_id, "Button").click()
    time.sleep(1.0)
    tops = top_windows(driver)
    after = None
    try:
        after = list_state(driver, 630 if control_id == 2120 else 610)
    except Exception as error:
        after = {"error": f"{type(error).__name__}: {error}"}
    # Dismiss any modal child without accepting it.
    main_handle = int(driver._main().handle)
    for top in driver.app.windows(visible_only=True):
        if int(top.handle) in {int(driver.current_window.handle), main_handle}:
            continue
        try:
            cancel = next(
                (
                    child
                    for child in top.descendants(class_name="Button")
                    if child.window_text().replace("&", "") in {"取消", "否", "关闭"}
                ),
                None,
            )
            if cancel is not None:
                cancel.click()
            else:
                win32gui.PostMessage(top.handle, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
    return {"before": before, "after": after, "top_windows": tops}


def click_control_and_observe(
    driver: Win32LegacyDriver, control_id: int
) -> dict[str, object]:
    control = driver._control(control_id)
    before = visible_controls(driver)
    win32gui.PostMessage(control.handle, win32con.BM_CLICK, 0, 0)
    time.sleep(1.2)
    result = {
        "clicked": {
            "id": control_id,
            "class": control.class_name(),
            "text": control.window_text(),
        },
        "top_windows": top_windows(driver),
        "visible_controls_before": before,
        "visible_controls_after": visible_controls(driver),
    }
    main_handle = int(driver._main().handle)
    current_handle = int(driver.current_window.handle)
    for top in driver.app.windows(visible_only=True):
        if int(top.handle) in {current_handle, main_handle}:
            continue
        try:
            cancel = next(
                (
                    child
                    for child in top.descendants(class_name="Button")
                    if child.window_text().replace("&", "")
                    in {"取消", "否", "关闭", "确定"}
                ),
                None,
            )
            if cancel is not None:
                win32gui.PostMessage(cancel.handle, win32con.BM_CLICK, 0, 0)
            else:
                win32gui.PostMessage(top.handle, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
    time.sleep(0.3)
    return result


def choice_state(window, control_id: int, class_name: str) -> dict[str, object]:
    control = next(
        item
        for item in window.descendants(class_name=class_name)
        if int(item.control_id()) == control_id
    )
    texts = control.item_texts()
    selected = control.selected_index() if class_name == "ComboBox" else int(
        win32gui.SendMessage(control.handle, 0x0188, 0, 0)
    )
    return {
        "id": control_id,
        "selected": int(selected),
        "count": len(texts),
        "first": texts[:5],
        "selected_text": texts[selected] if 0 <= selected < len(texts) else "",
        "last": texts[-5:],
    }


def edit_person_dialogue(
    driver: Win32LegacyDriver, control_id: int, selection: int | None
) -> dict[str, object]:
    control = driver._control(control_id, "Button")
    win32gui.PostMessage(control.handle, win32con.BM_CLICK, 0, 0)
    time.sleep(1.0)
    modal = next(
        item
        for item in driver.app.windows(visible_only=True)
        if int(item.handle) != int(driver.current_window.handle)
        and any(int(child.control_id()) == 180 for child in item.descendants())
    )
    result = {
        "window": top_windows(driver),
        "list": choice_state(modal, 100, "ListBox"),
        "mode": choice_state(modal, 190, "ComboBox"),
        "actor": choice_state(modal, 120, "ComboBox"),
        "weapon": choice_state(modal, 130, "ComboBox"),
        "segment": choice_state(modal, 140, "ComboBox"),
        "dialogue": choice_state(modal, 150, "ComboBox"),
    }
    if selection is None:
        cancel = next(
            item
            for item in modal.descendants(class_name="Button")
            if int(item.control_id()) == 170
        )
        win32gui.PostMessage(cancel.handle, win32con.BM_CLICK, 0, 0)
        time.sleep(0.4)
        return result
    combo = next(
        item
        for item in modal.descendants(class_name="ComboBox")
        if int(item.control_id()) == 150
    )
    if not 0 <= selection < len(combo.item_texts()):
        raise ValueError(f"对话选择 {selection} 越界")
    listing = next(
        item
        for item in modal.descendants(class_name="ListBox")
        if int(item.control_id()) == 100
    )
    win32gui.SendMessage(listing.handle, 0x0186, 0, 0)
    win32gui.SendMessage(
        modal.handle,
        win32con.WM_COMMAND,
        win32api.MAKELONG(100, 1),
        listing.handle,
    )
    time.sleep(0.2)
    combo.select(selection)
    time.sleep(0.3)
    result["list_after_selection"] = choice_state(modal, 100, "ListBox")
    confirm = next(
        item
        for item in modal.descendants(class_name="Button")
        if int(item.control_id()) == 180
    )
    win32gui.PostMessage(confirm.handle, win32con.BM_CLICK, 0, 0)
    time.sleep(0.6)
    result["changed_to"] = selection
    return result


def main() -> int:
    skip_add = "--skip-add" in sys.argv
    edit_field = next(
        (int(value.split("=", 1)[1]) for value in sys.argv if value.startswith("--edit-field=")),
        None,
    )
    edit_value = next(
        (value.split("=", 1)[1] for value in sys.argv if value.startswith("--edit-value=")),
        "__",
    )
    edit_row = next(
        (int(value.split("=", 1)[1]) for value in sys.argv if value.startswith("--row=")),
        0,
    )
    scan_rows = "--scan-rows" in sys.argv
    scan_dialogues = "--scan-dialogues" in sys.argv
    click_weapon = next(
        (
            int(value.split("=", 1)[1])
            for value in sys.argv
            if value.startswith("--click-weapon=")
        ),
        None,
    )
    click_person = next(
        (
            int(value.split("=", 1)[1])
            for value in sys.argv
            if value.startswith("--click-person=")
        ),
        None,
    )
    dialogue_select = next(
        (
            int(value.split("=", 1)[1])
            for value in sys.argv
            if value.startswith("--dialogue-select=")
        ),
        None,
    )
    transform_select = next(
        (
            int(value.split("=", 1)[1])
            for value in sys.argv
            if value.startswith("--transform-select=")
        ),
        None,
    )
    transform_clear = "--transform-clear" in sys.argv
    RUN.mkdir(parents=True, exist_ok=True)
    baseline_path = (
        ROOT / "references" / "rom" / "baselines" / "DC_kuorong.nes"
        if "--canonical" in sys.argv
        else AUDIT / "audit.nes"
    )
    baseline = baseline_path.read_bytes()
    shutil.copy2(baseline_path, ROM)
    cdl = AUDIT / "默认配置文件" / "测试.cdl"
    if cdl.is_file():
        shutil.copy2(cdl, ROM.with_suffix(".cdl"))
    report: dict[str, object] = {}
    driver = Win32LegacyDriver()
    try:
        driver.launch(EXE, AUDIT)
        driver.open_rom(ROM)
        driver.perform(
            (
                {"op": "menu", "path": "数据->数据库"},
                {"op": "window", "title": "数据库"},
            ),
            0,
        )

        # Owner-drawn top tabs: 人物修改, then 武器修改.
        select_database_tab(driver, 75, 1, 630)
        time.sleep(0.7)
        select_list(driver, 630, edit_row)
        if edit_field in {830, 2200}:
            driver._control(edit_field, "Edit").set_edit_text(edit_value)
            time.sleep(0.3)
        person_controls = visible_controls(driver)
        report["person"] = {
            "list": list_state(driver, 630),
            "controls": [row for row in person_controls if int(row["id"]) in {
                630, 830, 2200, 1420, 1430, 1440, 1450, 1460,
                1470, 1480, 1490, 1500, 1510, 1520, 1530, 1540, 2120,
            }],
            "add": None if skip_add else click_and_observe(driver, 2120),
        }
        if transform_select is not None:
            combo = driver._control(1540, "ComboBox")
            before_transform = choice_state(driver.current_window, 1540, "ComboBox")
            combo.select(transform_select)
            time.sleep(0.6)
            report["person"]["transform_change"] = {
                "before": before_transform,
                "after": choice_state(driver.current_window, 1540, "ComboBox"),
                "text": get_ctrl_text(driver._control(1530, "Button").handle),
            }
        if transform_clear:
            before_transform = choice_state(driver.current_window, 1540, "ComboBox")
            driver._control(2180, "Button").click()
            time.sleep(0.8)
            report["person"]["transform_clear"] = {
                "before": before_transform,
                "after": choice_state(driver.current_window, 1540, "ComboBox"),
                "text": get_ctrl_text(driver._control(1530, "Button").handle),
                "windows": top_windows(driver),
            }
        if click_person is not None:
            report["person"]["clicked_control"] = edit_person_dialogue(
                driver, click_person, dialogue_select
            )
        if scan_dialogues:
            dialogues = {}
            for control_id in range(1420, 1530, 10):
                try:
                    dialogues[str(control_id)] = edit_person_dialogue(
                        driver, control_id, None
                    )
                except Exception as error:
                    dialogues[str(control_id)] = {
                        "error": f"{type(error).__name__}: {error}",
                        "windows": top_windows(driver),
                    }
                    break
            report["person"]["dialogues"] = dialogues
        if scan_rows:
            scanned = []
            for row in range(12):
                select_list(driver, 630, row)
                scanned.append(
                    {
                        "row": row,
                        "name": get_ctrl_text(driver._control(830, "Edit").handle),
                        "battle_name": get_ctrl_text(driver._control(2200, "Edit").handle),
                        "attack": [
                            get_ctrl_text(driver._control(control_id, "Button").handle)
                            for control_id in range(1420, 1470, 10)
                        ],
                        "defense": [
                            get_ctrl_text(driver._control(control_id, "Button").handle)
                            for control_id in range(1470, 1530, 10)
                        ],
                        "transform": get_ctrl_text(driver._control(1530, "Button").handle),
                        "transform_selection": choice_state(
                            driver.current_window, 1540, "ComboBox"
                        ),
                    }
                )
            report["person"]["scan"] = scanned

        if edit_field is None:
            select_database_tab(driver, 135, 2, 610)
            time.sleep(0.7)
            select_list(driver, 610, 0)
            weapon_controls = visible_controls(driver)
            report["weapon"] = {
                "list": list_state(driver, 610),
                "controls": [row for row in weapon_controls if int(row["id"]) in {
                    610, 1180, 1190, 1200, 1210, 1220, 1230, 1240, 1250,
                    2130, 2520, 2530, 2540, 2550, 2560, 2710, 2740,
                }],
                "add": None if skip_add else click_and_observe(driver, 2130),
            }
            if click_weapon is not None:
                report["weapon"]["clicked_control"] = click_control_and_observe(
                    driver, click_weapon
                )
        driver._control(590, "Button").click()
        time.sleep(0.8)
        driver.save()
        saved = ROM.read_bytes()
        changed = [index for index, pair in enumerate(zip(baseline, saved)) if pair[0] != pair[1]]
        ranges = []
        for offset in changed:
            if ranges and offset == ranges[-1][1] + 1:
                ranges[-1][1] = offset
            else:
                ranges.append([offset, offset])
        report["save_diff"] = {
            "count": len(changed),
            "ranges": ranges,
            "bytes": [
                {
                    "offset": offset,
                    "before": baseline[offset],
                    "after": saved[offset],
                }
                for offset in changed[:128]
            ],
        }
    finally:
        driver.stop()
    (RUN / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
