"""Cover all M11 glyph fields with 12 page saves and 12 isolated writes."""

from __future__ import annotations

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
from pywinauto import Desktop


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.golden_pipeline_collect import Win32LegacyDriver, _control_pixel_sha256_hwnd
from tools.report_m11_reference_field_catalog import DEFAULT_JSON as CATALOG_PATH

AUDIT = ROOT / "output/build/legacy-diff-audit"
BASELINE = AUDIT / "audit.nes"
OUT = ROOT / "output/verification/legacy-m11-all-fields-20260920"
CASES = OUT / "cases"
PAGE_EVIDENCE = OUT / "glyph-page-save-evidence.jsonl"
CASE_REPORT = OUT / "save-cases.json"
SUMMARY = OUT / "summary.json"
PROGRESS = OUT / "progress.log"
NORMALIZATION = {0x4A101, 0x4A102, 0x4AE2A, 0x4AE2B, 0x79538, 0x79539}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with PROGRESS.open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def open_font(driver: Win32LegacyDriver) -> None:
    main = driver._main()
    ctypes.windll.user32.PostMessageW(int(main.handle), win32con.WM_COMMAND, 20009, 0)
    driver.current_window = driver._wait_window(lambda item: item.window_text() == "字库编辑")


def post_click(item) -> None:
    if not ctypes.windll.user32.PostMessageW(int(item.handle), 0x00F5, 0, 0):
        raise RuntimeError("BM_CLICK failed")


def accept_prompt(driver: Win32LegacyDriver) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        for window in Desktop(backend="win32").windows(process=driver.pid, visible_only=True):
            try:
                if window.window_text() in {"字库编辑"} or window.window_text().startswith("SRW2扩容版修改器"):
                    continue
                buttons = [button for button in window.descendants(class_name="Button") if button.window_text().replace("&", "") in {"是", "确定", "保存"}]
                if buttons:
                    buttons[0].click()
                    time.sleep(0.2)
                    return
            except Exception:
                continue
        time.sleep(0.05)


def select_page(driver: Win32LegacyDriver, page_index: int) -> None:
    driver.perform(({"op": "select_index_message", "class": "ComboBox", "control_id": 130, "value": page_index},), 0)


def click_cell(driver: Win32LegacyDriver, row: int = 0, column: int = 0) -> None:
    grid = driver._control(110)
    rect = grid.rectangle()
    grid.click_input(coords=(int((column + 0.5) * rect.width() / 16), int((row + 0.5) * rect.height() / 16)))
    time.sleep(0.1)


def close_font(driver: Win32LegacyDriver) -> None:
    hwnd = int(driver.current_window.handle)
    post_click(driver._control(170, "Button"))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and win32gui.IsWindow(hwnd):
        time.sleep(0.05)
    if win32gui.IsWindow(hwnd):
        raise RuntimeError("font window did not close")
    driver.current_window = driver._main()


def semantic_offsets(before: bytes, after: bytes) -> set[int]:
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1] and index not in NORMALIZATION}


def save_cases(catalog: dict[str, object]) -> list[dict[str, object]]:
    pages = list(catalog["pages"])
    baseline = BASELINE.read_bytes()
    results: list[dict[str, object]] = []
    for page_index, page in enumerate(pages):
        page_fields = [field for field in catalog["fields"] if field["page"] == page]
        allowed = {offset for field in page_fields for offset in range(int(field["offset"]), int(field["offset"]) + 18)}
        reserved = {int(page_fields[0]["offset"]) + row * 0x100 + offset for row in range(16) for offset in range(252, 256)}
        for kind in ("clear_page", "single_glyph"):
            case_dir = CASES / f"{page}-{kind}"
            case_dir.mkdir(parents=True, exist_ok=True)
            before_path, after_path = case_dir / "before.nes", case_dir / "after.nes"
            before_path.write_bytes(baseline)
            after_path.write_bytes(baseline)
            driver = Win32LegacyDriver()
            try:
                driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
                driver.open_rom(after_path)
                open_font(driver)
                select_page(driver, page_index)
                click_cell(driver)
                if kind == "clear_page":
                    post_click(driver._control(310, "Button"))
                    accept_prompt(driver)
                else:
                    driver.perform(({"op": "set_text_notify", "class": "Edit", "control_id": 300, "value": "一"},), "一")
                    post_click(driver._control(260, "Button"))
                    time.sleep(0.25)
                warm_hash = _control_pixel_sha256_hwnd(int(driver._control(110).handle))
                close_font(driver)
                driver.save()
            finally:
                driver.stop()
            after = after_path.read_bytes()
            changed = semantic_offsets(baseline, after)
            target = allowed if kind == "clear_page" else set(range(int(page_fields[0]["offset"]), int(page_fields[0]["offset"]) + 18))
            result = {"page": page, "kind": kind, "before": before_path.relative_to(ROOT).as_posix(), "after": after_path.relative_to(ROOT).as_posix(), "before_sha256": sha(baseline), "after_sha256": sha(after), "changed_offsets": sorted(changed), "changed_count": len(changed), "allowed_only": bool(changed) and changed <= target, "reserved_unchanged": all(after[offset] == baseline[offset] for offset in reserved), "warm_grid_sha256": warm_hash}
            if kind == "clear_page":
                patterns = {after[int(field["offset"]):int(field["offset"]) + 18].hex().upper() for field in page_fields}
                result["post_clear_patterns"] = sorted(patterns)
                result["all_224_fields_blank"] = len(patterns) == 1
            else:
                result["target_field_id"] = page_fields[0]["field_id"]
                result["target_before_hex"] = baseline[int(page_fields[0]["offset"]):int(page_fields[0]["offset"]) + 18].hex().upper()
                result["target_after_hex"] = after[int(page_fields[0]["offset"]):int(page_fields[0]["offset"]) + 18].hex().upper()
            results.append(result)
            CASE_REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            log(f"saved {page} {kind} ({len(results)}/24)")
    return results


def cold_read(results: list[dict[str, object]], catalog: dict[str, object]) -> None:
    pages = list(catalog["pages"])
    driver = Win32LegacyDriver()
    try:
        driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        for index, result in enumerate(results):
            path = ROOT / str(result["after"])
            driver.open_rom(path)
            open_font(driver)
            page_index = pages.index(result["page"])
            select_page(driver, page_index)
            click_cell(driver)
            result["cold_grid_sha256"] = _control_pixel_sha256_hwnd(int(driver._control(110).handle))
            result["cold_grid_matches"] = result["cold_grid_sha256"] == result["warm_grid_sha256"]
            close_font(driver)
            log(f"cold read {index + 1}/24")
    finally:
        driver.stop()
    CASE_REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_field_evidence(results: list[dict[str, object]], catalog: dict[str, object]) -> None:
    by_page = {str(result["page"]): result for result in results if result["kind"] == "clear_page"}
    with PAGE_EVIDENCE.open("w", encoding="utf-8") as stream:
        for sequence, field in enumerate(catalog["fields"]):
            result = by_page[str(field["page"])]
            before = (ROOT / result["before"]).read_bytes()
            after = (ROOT / result["after"]).read_bytes()
            offset = int(field["offset"])
            stream.write(json.dumps({"sequence": sequence, "field_id": field["field_id"], "page": field["page"], "offset": offset, "length": 18, "before_hex": before[offset:offset + 18].hex().upper(), "after_hex": after[offset:offset + 18].hex().upper(), "page_save_case": f"{field['page']}-clear_page", "cold_page_readback": bool(result["cold_grid_matches"])}, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    for path in (PAGE_EVIDENCE, CASE_REPORT, SUMMARY, OUT / "error.log"):
        path.unlink(missing_ok=True)
    PROGRESS.write_text("start\n", encoding="utf-8")
    results = save_cases(catalog)
    cold_read(results, catalog)
    write_field_evidence(results, catalog)
    clear_cases = [item for item in results if item["kind"] == "clear_page"]
    single_cases = [item for item in results if item["kind"] == "single_glyph"]
    passed = all(item["allowed_only"] and item["reserved_unchanged"] and item["cold_grid_matches"] for item in results) and all(item["all_224_fields_blank"] for item in clear_cases)
    summary = {"passed": passed, "physical_fields": 2688, "page_save_cases": len(clear_cases), "isolated_single_glyph_cases": len(single_cases), "covered_fields": sum(224 for item in clear_cases if item["all_224_fields_blank"] and item["cold_grid_matches"]), "reserved_rows_verified": 12 * 16, "cold_process_cases_passed": sum(bool(item["cold_grid_matches"]) for item in results), "baseline_sha256": sha(BASELINE.read_bytes()), "evidence": PAGE_EVIDENCE.relative_to(ROOT).as_posix(), "case_report": CASE_REPORT.relative_to(ROOT).as_posix()}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not passed:
        raise RuntimeError("M11 page or single-glyph save verification failed")
    return 0


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    raise SystemExit(result)
