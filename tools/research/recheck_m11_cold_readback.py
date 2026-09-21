"""Recheck saved M11 cases with focus-independent cell captures in two processes."""

from __future__ import annotations

import hashlib
import json
import sys
import time
import traceback
from pathlib import Path

from PIL import ImageGrab


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.golden_pipeline_collect import Win32LegacyDriver
from tools.report_m11_reference_field_catalog import DEFAULT_JSON as CATALOG_PATH
from tools.research.collect_m11_all_glyph_fields import AUDIT, CASE_REPORT, OUT, PAGE_EVIDENCE, PROGRESS, SUMMARY, click_cell, close_font, open_font, select_page


def cell_hash(driver: Win32LegacyDriver) -> str:
    grid = driver._control(110)
    rect = grid.rectangle()
    width, height = int(rect.width()), int(rect.height())
    left, top = int(rect.left), int(rect.top)
    # Exclude the selected-cell border and neighboring grid lines.
    image = ImageGrab.grab(bbox=(left + 4, top + 4, left + width // 16 - 4, top + height // 16 - 4)).convert("RGB")
    return hashlib.sha256(image.width.to_bytes(2, "little") + image.height.to_bytes(2, "little") + image.tobytes()).hexdigest()


def inventory(results: list[dict[str, object]], pages: list[str], key: str) -> None:
    driver = Win32LegacyDriver()
    try:
        driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        for index, result in enumerate(results):
            driver.open_rom(ROOT / str(result["after"]))
            open_font(driver)
            select_page(driver, pages.index(str(result["page"])))
            click_cell(driver)
            result[key] = cell_hash(driver)
            close_font(driver)
            with PROGRESS.open("a", encoding="utf-8") as stream:
                stream.write(f"{key} {index + 1}/24\n")
    finally:
        driver.stop()


def main() -> int:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    results = json.loads(CASE_REPORT.read_text(encoding="utf-8"))
    pages = list(catalog["pages"])
    inventory(results, pages, "cold_cell_sha256_1")
    inventory(results, pages, "cold_cell_sha256_2")
    for result in results:
        result["cold_cell_matches"] = result["cold_cell_sha256_1"] == result["cold_cell_sha256_2"]
        changed = set(int(value) for value in result["changed_offsets"])
        page_fields = [field for field in catalog["fields"] if field["page"] == result["page"]]
        allowed = {offset for field in page_fields for offset in range(int(field["offset"]), int(field["offset"]) + 18)}
        target = set(range(int(page_fields[0]["offset"]), int(page_fields[0]["offset"]) + 18))
        expected = allowed if result["kind"] == "clear_page" else target
        target_changed = bool(changed & target)
        if not changed:
            status = "no_effect"
        elif changed <= expected:
            status = "saved_confined"
        elif target_changed:
            status = "unsafe_extra_write"
        else:
            status = "unexpected_non_target_write"
        result["classification"] = status
    CASE_REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    clear_by_page = {str(item["page"]): item for item in results if item["kind"] == "clear_page"}
    with PAGE_EVIDENCE.open("w", encoding="utf-8") as stream:
        for sequence, field in enumerate(catalog["fields"]):
            case = clear_by_page[str(field["page"])]
            before = (ROOT / str(case["before"])).read_bytes()
            after = (ROOT / str(case["after"])).read_bytes()
            offset = int(field["offset"])
            stream.write(json.dumps({"sequence": sequence, "field_id": field["field_id"], "page": field["page"], "offset": offset, "length": 18, "before_hex": before[offset:offset + 18].hex().upper(), "after_hex": after[offset:offset + 18].hex().upper(), "page_save_case": f"{field['page']}-clear_page", "page_case_classification": case["classification"], "two_cold_process_cell_match": case["cold_cell_matches"]}, ensure_ascii=False, separators=(",", ":")) + "\n")

    clear_cases = [item for item in results if item["kind"] == "clear_page"]
    single_cases = [item for item in results if item["kind"] == "single_glyph"]
    safe_pages = [item["page"] for item in clear_cases if item["classification"] == "saved_confined"]
    no_effect_pages = [item["page"] for item in clear_cases if item["classification"] == "no_effect"]
    unsafe_pages = [item["page"] for item in clear_cases if item["classification"] == "unsafe_extra_write"]
    passed = all(item["cold_cell_matches"] and item["reserved_unchanged"] for item in results) and all(item["all_224_fields_blank"] for item in clear_cases) and all(item["classification"] == "unsafe_extra_write" for item in single_cases)
    summary = {"passed": passed, "physical_fields": 2688, "covered_fields": 2688, "safe_page_save_fields": len(safe_pages) * 224, "unsafe_or_no_effect_fields": 2688 - len(safe_pages) * 224, "safe_pages": safe_pages, "no_effect_pages": no_effect_pages, "unsafe_extra_write_pages": unsafe_pages, "page_save_cases": 12, "isolated_single_glyph_cases": 12, "single_glyph_unsafe_extra_write_cases": sum(item["classification"] == "unsafe_extra_write" for item in single_cases), "reserved_rows_verified": 192, "two_cold_process_cases_passed": sum(bool(item["cold_cell_matches"]) for item in results), "evidence": PAGE_EVIDENCE.relative_to(ROOT).as_posix(), "case_report": CASE_REPORT.relative_to(ROOT).as_posix()}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not passed:
        raise RuntimeError("M11 normalized cold readback or classification failed")
    return 0


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "recheck-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    raise SystemExit(result)
