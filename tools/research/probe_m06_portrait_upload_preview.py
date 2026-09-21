"""Upload known 32x32 BMPs in memory and hash the legacy preview without saving."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.golden_pipeline_collect import Win32LegacyDriver, _control_pixel_sha256_hwnd


AUDIT = REPO / "output" / "build" / "legacy-diff-audit"
ROOT = REPO / "output" / "verification" / "legacy-ui-probe-m06-portrait-upload-20260920"
OUTPUT = ROOT / "M06_头像上传预览哈希.json"
SAMPLES = {
    "front": REPO / "output" / "verification" / "avatar-preview-layer-order-corrected" / "4：琉妮" / "[正面].bmp",
    "back": REPO / "output" / "verification" / "avatar-preview-layer-order-corrected" / "4：琉妮" / "[背面].bmp",
}


def run(kind: str, button_id: int) -> dict[str, object]:
    driver = Win32LegacyDriver()
    started = time.perf_counter()
    try:
        pid = driver.launch(AUDIT / "SRW2_patched.exe", AUDIT)
        driver.open_rom(AUDIT / "m05-reference-baseline.nes")
        driver.perform(
            (
                {"op": "menu", "path": "数据->数据库"},
                {"op": "window", "title": "数据库"},
                {"op": "click_coords", "x": 130, "y": 73},
                {"op": "list_select", "class": "ListBox", "control_id": 630, "row": 5},
            ),
            0,
        )
        opened = time.perf_counter()
        preview = driver._control(1360, "_EL_PicBox")
        before_hash = _control_pixel_sha256_hwnd(int(preview.handle))
        before_read = time.perf_counter()
        upload_steps = (
            {"op": "click_id_message", "class": "Button", "control_id": button_id},
            {"op": "window", "title": "信息："},
            {"op": "click_id_message", "class": "Button", "control_id": 7},
            {"op": "window", "title": "打开图片"},
            {"op": "set_text", "class": "Edit", "control_id": 1148, "value": str(SAMPLES[kind])},
            {"op": "click_id_message", "class": "Button", "control_id": 1},
            {"op": "window", "title": "数据库", "settle_seconds": 0.5},
        )
        step_timings: list[dict[str, object]] = []
        for step in upload_steps:
            step_started = time.perf_counter()
            driver.perform((step,), 0)
            step_timings.append(
                {"op": step["op"], "id_or_title": step.get("control_id", step.get("title")), "seconds": round(time.perf_counter() - step_started, 3)}
            )
        uploaded = time.perf_counter()
        after = driver._control(1360, "_EL_PicBox")
        after_hash = _control_pixel_sha256_hwnd(int(after.handle))
        finished = time.perf_counter()
        return {
            "pid": pid,
            "sample": SAMPLES[kind].relative_to(REPO).as_posix(),
            "before_hash": before_hash,
            "after_hash": after_hash,
            "timings": {
                "launch_open_navigation": round(opened - started, 3),
                "before_hash": round(before_read - opened, 3),
                "upload": round(uploaded - before_read, 3),
                "after_hash": round(finished - uploaded, 3),
                "upload_steps": step_timings,
            },
        }
    finally:
        driver.stop()


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    payload = {"front": run("front", 790)}
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
