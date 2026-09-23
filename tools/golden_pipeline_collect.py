"""M00: collect one isolated legacy-ROM field with a real cold restart.

The orchestration is standard-library-only so it can be tested with a fake driver.
The Win32 adapter imports pywinauto only when a live case is requested.
"""

from __future__ import annotations

import json
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

try:
    from golden_pipeline_core import (
        AUDIT_DIR_RELATIVE,
        ONLINE_FIELD_BUDGET_SECONDS,
        classify_case,
        compact_live_result_items,
        diff_roms,
        resolve_live_result_items,
        sha256_bytes,
        write_json_atomic,
    )
except ImportError:
    from tools.golden_pipeline_core import (  # type: ignore
        AUDIT_DIR_RELATIVE,
        ONLINE_FIELD_BUDGET_SECONDS,
        classify_case,
        compact_live_result_items,
        diff_roms,
        resolve_live_result_items,
        sha256_bytes,
        write_json_atomic,
    )


LIVE_CASES_RELATIVE = AUDIT_DIR_RELATIVE / "cases" / "legacy_live"
LIVE_RESULTS_RELATIVE = AUDIT_DIR_RELATIVE / "legacy-live-results.json"
SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
EXTRA_ALLOWED_PROFILE_DIR = Path(__file__).resolve().parent / "golden_pipeline" / "profiles"
STEP_OPERATIONS = frozenset(
    {
        "menu",
        "window",
        "click_id",
        "click_id_message",
        "click_id_input",
        "set_check",
        "set_text",
        "set_text_notify",
        "type_text",
        "select_index",
        "select_index_keyboard",
        "select_index_message",
        "select_index_click",
        "list_select",
        "list_double_click",
        "click_coords",
        "click_control_coords",
        "assert_value",
    }
)
LEGACY_MENU_COMMANDS = {
    "文件->打开": 20001,
    "文件->保存": 20004,
    "数据->数据库": 20008,
    "数据->地图动画": 20011,
    "数据->其他": 20023,
}


class LegacyDriver(Protocol):
    """Narrow interface for a real Win32 process or an in-memory test double."""

    def launch(self, executable: Path, work_dir: Path) -> int: ...

    def open_rom(self, rom_path: Path) -> None: ...

    def perform(self, steps: tuple[dict[str, Any], ...], requested: int | str) -> None: ...

    def read(self, selector: dict[str, Any]) -> int | str: ...

    def save(self) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class CaseSpec:
    module: str
    field: str
    case_id: str
    case_kind: str
    expected_noop: bool
    requested_value: int | str
    expected_before: int | str | None
    expected_offsets: tuple[int, ...]
    required_offsets: tuple[int, ...]
    optional_offsets: tuple[int, ...]
    extra_allowed: tuple[int, ...]
    extra_allowed_profile: str | None
    navigation: tuple[dict[str, Any], ...]
    read_navigation: tuple[dict[str, Any], ...]
    edit_steps: tuple[dict[str, Any], ...]
    read_selector: dict[str, Any]
    capture_after_step: int | None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CaseSpec:
        for key in ("module", "field", "case_id"):
            if not SAFE_NAME.fullmatch(str(payload.get(key, ""))):
                raise ValueError(f"Unsafe or missing case name: {key}")
        module = str(payload["module"])
        if not re.fullmatch(r"M\d\d", module):
            raise ValueError("module must be an Mxx identifier")
        case_kind = str(payload.get("case_kind", "golden"))
        if case_kind not in {"golden", "discovery"}:
            raise ValueError("case_kind must be golden or discovery")
        expected_noop = payload.get("expected_noop", False)
        if not isinstance(expected_noop, bool):
            raise ValueError("expected_noop must be a boolean")
        expected = tuple(int(value) for value in payload["expected_offsets"])
        required = tuple(int(value) for value in payload["required_offsets"])
        optional = tuple(int(value) for value in payload.get("optional_offsets", []))
        extra_allowed = tuple(int(value) for value in payload.get("extra_allowed", []))
        extra_allowed_profile = payload.get("extra_allowed_profile")
        if extra_allowed_profile is not None:
            if not SAFE_NAME.fullmatch(str(extra_allowed_profile)):
                raise ValueError("Unsafe extra_allowed_profile name")
            profile_path = EXTRA_ALLOWED_PROFILE_DIR / f"{extra_allowed_profile}.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            expanded: list[int] = []
            ranges = profile.get("ranges")
            source_case = profile.get("source_case")
            if isinstance(ranges, list):
                previous_end = -1
                for pair in ranges:
                    if not (
                        isinstance(pair, list)
                        and len(pair) == 2
                        and all(isinstance(value, int) and not isinstance(value, bool) for value in pair)
                        and 0 <= pair[0] <= pair[1]
                        and pair[0] > previous_end
                    ):
                        raise ValueError("extra_allowed profile ranges must be sorted and disjoint")
                    expanded.extend(range(pair[0], pair[1] + 1))
                    previous_end = pair[1]
            elif isinstance(source_case, str):
                repo_root = Path(__file__).resolve().parent.parent
                relative_source = Path(source_case)
                source_path = (repo_root / relative_source).resolve()
                if relative_source.is_absolute() or not source_path.is_relative_to(repo_root):
                    raise ValueError("extra_allowed profile source_case must stay inside the repo")
                source_bytes = source_path.read_bytes()
                # Hash-pinned JSON evidence is stored in canonical LF form.
                # Windows core.autocrlf may materialize equivalent CRLF bytes.
                canonical_source = source_bytes.replace(b"\r\n", b"\n")
                actual_hash = hashlib.sha256(canonical_source).hexdigest()
                if actual_hash.lower() != str(profile.get("source_case_sha256", "")).lower():
                    raise ValueError("extra_allowed profile source_case SHA-256 mismatch")
                source_payload = json.loads(source_bytes.decode("utf-8"))
                excluded = {
                    int(value) for value in profile.get("exclude_offsets", [])
                }
                expanded.extend(
                    int(value)
                    for value in source_payload["changed_offsets"]
                    if int(value) not in excluded
                )
            else:
                raise ValueError("extra_allowed profile requires ranges or source_case")
            extra_allowed = tuple(dict.fromkeys((*extra_allowed, *expanded)))
        if len(set(expected)) != len(expected):
            raise ValueError("expected_offsets contain duplicates")
        if (
            (case_kind == "golden" and not required and not expected_noop)
            or set(required) & set(optional)
            or set(required) | set(optional) != set(expected)
            or (expected_noop and (case_kind != "golden" or bool(expected)))
        ):
            raise ValueError("required/optional offsets must partition expected offsets")
        if any(value < 0 for value in (*expected, *extra_allowed)):
            raise ValueError("ROM offsets must be nonnegative")
        navigation = _validate_steps(payload["navigation"])
        read_navigation = _validate_steps(payload.get("read_navigation", payload["navigation"]))
        edit_steps = _validate_steps(payload["edit_steps"])
        if not navigation or not read_navigation or not edit_steps:
            raise ValueError("navigation, read_navigation and edit_steps must be nonempty")
        selector = dict(payload["read_selector"])
        selector_class = selector.get("class")
        if selector_class not in {
            "Edit",
            "ComboBox",
            "Button",
            "Static",
            "ListBox",
            "_EL_PicBox",
        } and not (
            isinstance(selector_class, str)
            and (
                selector_class.startswith("Afx:")
                or selector_class.startswith("_EL_")
            )
        ):
            raise ValueError("Unsupported read selector class")
        if not isinstance(selector.get("control_id"), int):
            raise ValueError("read selector needs an integer control_id")
        if selector.get("value_type", "str") not in {
            "int",
            "str",
            "check",
            "combo_index",
            "combo_item_count",
            "list_item_count",
            "list_item_text",
            "control_pixel_sha256",
            "checkbox_pixel",
        }:
            raise ValueError(
                "value_type must be int, str, check, combo_index, combo_item_count, list_item_count, list_item_text, control_pixel_sha256 or checkbox_pixel"
            )
        if selector.get("value_type") == "list_item_text" and not (
            isinstance(selector.get("item_index"), int)
            and not isinstance(selector.get("item_index"), bool)
            and selector["item_index"] >= 0
        ):
            raise ValueError("list_item_text requires a nonnegative item_index")
        if selector.get("value_type") == "checkbox_pixel" and not (
            isinstance(selector.get("item_index"), int)
            and not isinstance(selector.get("item_index"), bool)
            and 0 <= selector["item_index"] < 24
        ):
            raise ValueError("checkbox_pixel requires item_index from 0 through 23")
        requested = payload["requested_value"]
        before = payload.get("expected_before")
        if not isinstance(requested, (int, str)) or isinstance(requested, bool):
            raise ValueError("requested_value must be an integer or string")
        capture_after = requested == "$capture_after"
        if capture_after and case_kind != "discovery":
            raise ValueError("$capture_after is restricted to discovery cases")
        if capture_after and selector.get("value_type") in {
            "int",
            "check",
            "combo_index",
            "combo_item_count",
            "list_item_count",
            "checkbox_pixel",
        }:
            raise ValueError("$capture_after requires a string-valued read selector")
        if capture_after and any(
            step.get("value") == "$requested"
            for step in (*navigation, *edit_steps, *read_navigation)
        ):
            raise ValueError("$capture_after cannot be written through a $requested step")
        capture_after_step = payload.get("capture_after_step")
        if capture_after_step is not None:
            if not capture_after:
                raise ValueError("capture_after_step requires $capture_after")
            if (
                not isinstance(capture_after_step, int)
                or isinstance(capture_after_step, bool)
                or not 1 <= capture_after_step < len(edit_steps)
            ):
                raise ValueError(
                    "capture_after_step must split the nonempty edit_steps sequence"
                )
        if before is not None and type(before) is not type(requested):
            raise ValueError("expected_before and requested_value must have the same type")
        if (
            selector.get("value_type")
            in {"int", "check", "combo_index", "combo_item_count", "list_item_count", "checkbox_pixel"}
        ) != (isinstance(requested, int) and not capture_after):
            raise ValueError("read selector value_type must match requested_value")
        return cls(
            module=module,
            field=str(payload["field"]),
            case_id=str(payload["case_id"]),
            case_kind=case_kind,
            expected_noop=expected_noop,
            requested_value=requested,
            expected_before=before,
            expected_offsets=expected,
            required_offsets=required,
            optional_offsets=optional,
            extra_allowed=extra_allowed,
            extra_allowed_profile=(
                str(extra_allowed_profile) if extra_allowed_profile is not None else None
            ),
            navigation=navigation,
            read_navigation=read_navigation,
            edit_steps=edit_steps,
            read_selector=selector,
            capture_after_step=capture_after_step,
        )


def _validate_steps(raw: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, list):
        raise ValueError("steps must be a list")
    steps: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or item.get("op") not in STEP_OPERATIONS:
            raise ValueError("Unsupported step operation")
        op = item["op"]
        if op == "menu" and not isinstance(item.get("path"), str):
            raise ValueError("menu step requires path")
        if op == "window" and not isinstance(item.get("title"), str):
            raise ValueError("window step requires title")
        if op == "window" and "settle_seconds" in item and not (
            isinstance(item["settle_seconds"], (int, float))
            and not isinstance(item["settle_seconds"], bool)
            and 0 <= float(item["settle_seconds"]) <= 2
        ):
            raise ValueError("window settle_seconds must be between 0 and 2")
        if op in {"click_id", "click_id_message", "click_id_input", "set_check", "set_text", "set_text_notify", "type_text", "select_index", "select_index_keyboard", "select_index_message", "select_index_click"} and not isinstance(item.get("control_id"), int):
            raise ValueError(f"{op} step requires control_id")
        if op in {"set_check", "set_text", "set_text_notify", "type_text", "select_index", "select_index_keyboard", "select_index_message", "select_index_click"} and "value" not in item:
            raise ValueError(f"{op} step requires value")
        if op == "set_check" and item["value"] not in {0, 1, "$requested"}:
            raise ValueError("set_check value must be 0, 1 or $requested")
        if op == "list_double_click" and not all(
            isinstance(item.get(key), int) and not isinstance(item.get(key), bool)
            for key in ("control_id", "row", "column")
        ):
            raise ValueError("list_double_click requires integer control_id/row/column")
        if op == "list_double_click" and (item["row"] < 0 or item["column"] < 0):
            raise ValueError("list_double_click row/column must be nonnegative")
        if op == "list_select" and not (
            isinstance(item.get("control_id"), int)
            and isinstance(item.get("row"), int)
            and not isinstance(item["row"], bool)
            and item["row"] >= 0
        ):
            raise ValueError("list_select requires a nonnegative row and integer control_id")
        if op == "click_coords" and not all(isinstance(item.get(key), int) for key in ("x", "y")):
            raise ValueError("click_coords requires integer x/y")
        if op == "click_control_coords" and not (
            isinstance(item.get("control_id"), int)
            and all(isinstance(item.get(key), int) for key in ("x", "y"))
        ):
            raise ValueError(
                "click_control_coords requires integer control_id/x/y"
            )
        if (
            op == "click_control_coords"
            and "wait_control_id" in item
            and not isinstance(item["wait_control_id"], int)
        ):
            raise ValueError("wait_control_id must be an integer")
        if (
            op == "click_control_coords"
            and "click_count" in item
            and (
                not isinstance(item["click_count"], int)
                or isinstance(item["click_count"], bool)
                or item["click_count"] not in {1, 2}
            )
        ):
            raise ValueError("click_count must be 1 or 2")
        if op == "assert_value" and not (
            isinstance(item.get("control_id"), int)
            and item.get("value_type", "str") in {"int", "str", "combo_index"}
            and "value" in item
        ):
            raise ValueError(
                "assert_value requires control_id, value and int/str/combo_index value_type"
            )
        steps.append(dict(item))
    return tuple(steps)


def _within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _resolve_repo_step_paths(
    steps: tuple[dict[str, Any], ...], repo_root: Path
) -> tuple[dict[str, Any], ...]:
    """Expand guarded ``$repo_path:`` values used by native file dialogs."""

    resolved_steps: list[dict[str, Any]] = []
    repo = repo_root.resolve()
    for source in steps:
        item = dict(source)
        value = item.get("value")
        if isinstance(value, str) and value.startswith("$repo_path:"):
            relative = value.removeprefix("$repo_path:")
            candidate = (repo / relative).resolve()
            if not relative or not _within(candidate, repo) or not candidate.is_file():
                raise ValueError(f"Invalid or missing repository file: {relative!r}")
            item["value"] = str(candidate)
        resolved_steps.append(item)
    return tuple(resolved_steps)


def _owner_drawn_spirit_checkbox_state(image: Any, item_index: int) -> int:
    """Read one of the legacy 3-column x 8-row spirit checkboxes from pixels."""

    if not 0 <= item_index < 24 or image.width <= 0 or image.height <= 0:
        raise ValueError("invalid spirit checkbox image or item index")
    column, row = divmod(item_index, 8)
    column_width = image.width / 3.0
    # The control keeps a small bottom remainder outside its eight fixed rows.
    # Use the integral owner-drawn row height so that lower rows do not drift.
    row_height = float(max(1, image.height // 8))
    left = int(round(column * column_width + row_height * 0.19))
    top = int(round(row * row_height + row_height * 0.24))
    right = max(left + 1, int(round(column * column_width + row_height * 0.61)))
    bottom = max(top + 1, int(round(row * row_height + row_height * 0.62)))
    pixels = image.crop((left, top, right, bottom)).get_flattened_data()
    dark_pixels = sum(1 for pixel in pixels if max(pixel[:3]) < 100)
    return int(dark_pixels >= 5)


def _owner_drawn_spirit_checkbox_state_hwnd(hwnd: int, item_index: int) -> int:
    """Fast GDI readback for one checkbox without capturing the whole control."""

    import ctypes
    from ctypes import wintypes
    import win32gui

    if not 0 <= item_index < 24:
        raise ValueError("invalid spirit checkbox item index")
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    dc = user32.GetDC(hwnd)
    if not dc:
        raise RuntimeError("could not acquire spirit ListBox device context")
    try:
        # Window/client rectangles can both be DPI-virtualized across the
        # elevated 32-bit reference process boundary.  The DC clip box is in
        # the exact device coordinate space consumed by GetPixel.
        clip = wintypes.RECT()
        if gdi32.GetClipBox(dc, ctypes.byref(clip)) == 0:
            raise RuntimeError("could not query spirit ListBox device clip box")
        clip_left, clip_top = int(clip.left), int(clip.top)
        clip_right, clip_bottom = int(clip.right), int(clip.bottom)
        width = clip_right - clip_left
        height = clip_bottom - clip_top
        if width <= 0 or height <= 0:
            raise RuntimeError("spirit ListBox has an empty device clip box")
        column, row = divmod(item_index, 8)
        column_width = width / 3.0
        row_height = float(max(1, height // 8))
        left = clip_left + int(round(column * column_width + row_height * 0.19))
        top = clip_top + int(round(row * row_height + row_height * 0.24))
        right = max(
            left + 1,
            clip_left + int(round(column * column_width + row_height * 0.61)),
        )
        bottom = max(
            top + 1,
            clip_top + int(round(row * row_height + row_height * 0.62)),
        )
        dark_pixels = 0
        for y in range(top, bottom):
            for x in range(left, right):
                color = int(gdi32.GetPixel(dc, x, y))
                if color == -1:
                    continue
                red = color & 0xFF
                green = (color >> 8) & 0xFF
                blue = (color >> 16) & 0xFF
                dark_pixels += int(max(red, green, blue) < 100)
        return int(dark_pixels >= 5)
    finally:
        user32.ReleaseDC(hwnd, dc)


def _control_pixel_sha256_hwnd(hwnd: int) -> str:
    """Hash one foreground screen capture of an elevated legacy picture control."""

    import ctypes
    import win32gui
    from PIL import ImageGrab

    root = ctypes.windll.user32.GetAncestor(hwnd, 2) or hwnd
    ctypes.windll.user32.ShowWindow(root, 5)
    ctypes.windll.user32.SetForegroundWindow(root)
    ctypes.windll.user32.UpdateWindow(root)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    if right <= left or bottom <= top:
        raise RuntimeError("control has an empty screen rectangle")
    image = ImageGrab.grab(bbox=(left, top, right, bottom)).convert("RGB")
    payload = (
        image.width.to_bytes(4, "little")
        + image.height.to_bytes(4, "little")
        + image.tobytes()
    )
    return hashlib.sha256(payload).hexdigest()


def collect_case(
    repo_root: Path,
    spec: CaseSpec,
    baseline_path: Path,
    executable_path: Path,
    driver_factory: Callable[[], LegacyDriver],
    *,
    budget_seconds: float = 30.0,
) -> tuple[Path, dict[str, Any]]:
    """Run exactly one write, diff and new-process reopen without overwriting a case."""
    repo = repo_root.resolve()
    baseline = baseline_path.resolve()
    executable = executable_path.resolve()
    audit_root = (repo / AUDIT_DIR_RELATIVE).resolve()
    if not baseline.is_file() or not executable.is_file():
        raise FileNotFoundError("Baseline ROM or isolated legacy executable is missing")
    if not _within(executable, audit_root):
        raise ValueError("Legacy executable must be an isolated copy under output/build/legacy-diff-audit")
    if baseline.suffix.lower() != ".nes":
        raise ValueError("Baseline must be a NES ROM")
    if budget_seconds <= 0:
        raise ValueError("budget_seconds must be positive")
    run_dir = (repo / LIVE_CASES_RELATIVE / spec.module / spec.field / spec.case_id).resolve()
    if not _within(run_dir, (repo / LIVE_CASES_RELATIVE).resolve()):
        raise ValueError("Live case path escaped the audit root")
    run_dir.mkdir(parents=True, exist_ok=False)
    # perf_counter has the resolution required by the strict budget test on
    # Windows; monotonic can return the same tick for an in-memory fake run.
    started = time.perf_counter()
    before_path = run_dir / "before.nes"
    after_path = run_dir / "after.nes"
    before_bytes = baseline.read_bytes()
    before_path.write_bytes(before_bytes)
    after_path.write_bytes(before_bytes)
    cdl_source = executable.parent / "默认配置文件" / "测试.cdl"
    cdl_path = after_path.with_suffix(".cdl")
    cdl_bytes: bytes | None = None
    if cdl_source.is_file():
        # The reference editor requires a same-stem CDL beside each opened ROM.
        # It is an input sidecar only; keep its tracked source/hash in the report
        # and remove the per-case copy after both legacy processes exit.
        cdl_bytes = cdl_source.read_bytes()
        cdl_path.write_bytes(cdl_bytes)
    first_pid: int | None = None
    second_pid: int | None = None
    original: int | str | None = None
    reopened: int | str | None = None
    effective_requested: int | str = spec.requested_value
    navigation = _resolve_repo_step_paths(spec.navigation, repo)
    edit_steps = _resolve_repo_step_paths(spec.edit_steps, repo)
    read_navigation = _resolve_repo_step_paths(spec.read_navigation, repo)

    try:
        first = driver_factory()
        try:
            first_pid = first.launch(executable, executable.parent)
            first.open_rom(after_path)
            first.perform(navigation, spec.requested_value)
            original = first.read(spec.read_selector)
            if spec.expected_before is not None and original != spec.expected_before:
                raise RuntimeError(
                    f"Baseline display differs: expected {spec.expected_before!r}, got {original!r}"
                )
            if spec.capture_after_step is None:
                first.perform(edit_steps, spec.requested_value)
            else:
                first.perform(
                    edit_steps[: spec.capture_after_step], spec.requested_value
                )
            if spec.requested_value == "$capture_after":
                effective_requested = first.read(spec.read_selector)
                if effective_requested == original:
                    raise RuntimeError("Captured post-action value did not change")
            if spec.capture_after_step is not None:
                first.perform(
                    edit_steps[spec.capture_after_step :], effective_requested
                )
            first.save()
        finally:
            first.stop()

        # A new driver starts a genuinely different process; the old process is dead.
        second = driver_factory()
        try:
            second_pid = second.launch(executable, executable.parent)
            if second_pid == first_pid:
                raise RuntimeError("Cold reopen reused the first process ID")
            second.open_rom(after_path)
            second.perform(read_navigation, effective_requested)
            reopened = second.read(spec.read_selector)
        finally:
            second.stop()
    except Exception as error:
        cdl_path.unlink(missing_ok=True)
        write_json_atomic(
            run_dir / "error.json",
            {"module": spec.module, "field": spec.field, "case_id": spec.case_id,
             "error": f"{type(error).__name__}: {error}", "first_pid": first_pid,
             "second_pid": second_pid},
        )
        raise

    try:
        after_bytes = after_path.read_bytes()
        diff = diff_roms(before_bytes, after_bytes)
    except (OSError, ValueError) as error:
        cdl_path.unlink(missing_ok=True)
        write_json_atomic(
            run_dir / "error.json",
            {"module": spec.module, "field": spec.field, "case_id": spec.case_id,
             "error": f"{type(error).__name__}: {error}", "first_pid": first_pid,
             "second_pid": second_pid},
        )
        raise
    changed = tuple(entry.offset for entry in diff)
    classification = classify_case(changed, spec.expected_offsets, spec.extra_allowed)
    required_missing = sorted(set(spec.required_offsets) - set(changed))
    elapsed = time.perf_counter() - started
    effective_budget = min(budget_seconds, ONLINE_FIELD_BUDGET_SECONDS)
    within_budget = elapsed <= effective_budget
    passed = (
        spec.case_kind == "golden"
        and (bool(spec.required_offsets) or spec.expected_noop)
        and not classification.unexplained
        and not required_missing
        and reopened == effective_requested
        and within_budget
    )
    reasons: list[str] = []
    if spec.case_kind == "discovery":
        reasons.append("discovery case requires reviewed offset promotion")
    if classification.unexplained:
        reasons.append(f"{len(classification.unexplained)} unexplained offsets")
    if required_missing:
        reasons.append(f"{len(required_missing)} required offsets unchanged")
    if reopened != effective_requested:
        reasons.append("cold reopen value differs from request")
    if not within_budget:
        reasons.append(f"{elapsed:.2f}s exceeds {effective_budget:.2f}s budget")
    relative = run_dir.relative_to(repo).as_posix()
    report: dict[str, Any] = {
        "schema_version": 1,
        "module": spec.module,
        "field": spec.field,
        "case_id": spec.case_id,
        "case_kind": spec.case_kind,
        "expected_noop": spec.expected_noop,
        "requested_value": effective_requested,
        "requested_value_mode": (
            "captured_mid_action"
            if spec.capture_after_step is not None
            else "captured_after_action"
            if spec.requested_value == "$capture_after"
            else "declared"
        ),
        "original_value": original,
        "reopen_value": reopened,
        "reopen_matches_request": reopened == effective_requested,
        "reopen_mode": "new_process",
        "first_pid": first_pid,
        "second_pid": second_pid,
        "changed_offsets": list(changed),
        "removed_normalization": list(classification.removed_normalization),
        "unexpected_offsets": list(classification.unexplained),
        "expected_offsets": list(spec.expected_offsets),
        "required_offsets": list(spec.required_offsets),
        "optional_offsets": list(spec.optional_offsets),
        "extra_allowed": list(spec.extra_allowed),
        "extra_allowed_profile": spec.extra_allowed_profile,
        "expected_not_changed": required_missing,
        "diffs": [
            {"offset": entry.offset, "before": entry.before_value, "after": entry.after_value}
            for entry in diff
        ],
        "snapshots": {
            "before": {"path": f"{relative}/before.nes", "sha256": sha256_bytes(before_bytes)},
            "after": {"path": f"{relative}/after.nes", "sha256": sha256_bytes(after_bytes)},
        },
        "supporting_cdl": (
            {
                "source": cdl_source.relative_to(repo).as_posix(),
                "sha256": sha256_bytes(cdl_bytes),
            }
            if cdl_bytes is not None
            else None
        ),
        "duration_seconds": round(elapsed, 3),
        "budget_seconds": effective_budget,
        "requested_budget_seconds": budget_seconds,
        "within_budget": within_budget,
        "passed": passed,
        "pending_reason": "; ".join(reasons) or None,
    }
    write_json_atomic(run_dir / "case.json", report)
    results_path = repo / LIVE_RESULTS_RELATIVE
    indexed_results: list[dict[str, Any]] = (
        json.loads(results_path.read_text(encoding="utf-8")) if results_path.is_file() else []
    )
    results = resolve_live_result_items(indexed_results, repo)
    results.append(report)
    results.sort(key=lambda item: (item["module"], item["field"], item["case_id"]))
    write_json_atomic(results_path, compact_live_result_items(results))
    cdl_path.unlink(missing_ok=True)
    return run_dir, report


class Win32LegacyDriver:
    """Whitelist-based pywinauto driver for the isolated SRW2 reference EXE."""

    def __init__(self) -> None:
        self.app: Any = None
        self.pid: int | None = None
        self.launcher_pid: int | None = None
        self.current_window: Any = None
        self.current_rom: Path | None = None
        self.repo_root: Path | None = None

    def _wait_window(self, predicate: Callable[[Any], bool], timeout: float = 12.0) -> Any:
        from pywinauto import Desktop
        import win32gui
        import win32process

        desktop = Desktop(backend="win32")
        deadline = time.monotonic() + timeout
        seen: list[str] = []
        while time.monotonic() < deadline:
            handles: list[int] = []

            def visit(hwnd: int, _extra: object) -> bool:
                try:
                    _thread, process_id = win32process.GetWindowThreadProcessId(hwnd)
                    if process_id == self.pid:
                        handles.append(hwnd)
                except Exception:
                    pass
                return True

            win32gui.EnumWindows(visit, None)
            for hwnd in handles:
                try:
                    window = desktop.window(handle=hwnd).wrapper_object()
                    summary = f"{window.class_name()}:{window.window_text()}"
                    if summary not in seen:
                        seen.append(summary)
                    if predicate(window):
                        return window
                except Exception:
                    continue
            time.sleep(0.1)
        raise RuntimeError(
            f"Legacy window did not appear before timeout (pid={self.pid}; seen={seen[:12]})"
        )

    def _main(self, timeout: float = 25.0) -> Any:
        def is_main_window(item: Any) -> bool:
            if not item.is_visible():
                return False
            # A clean launch can keep an empty title, while the 786 KiB audit
            # baseline changes it to "SRW2修改器V1.5" after opening.  Identify
            # both states by the real main menu instead of a versioned title.
            # The launcher and modal WTWindows do not expose both menu groups.
            if item.class_name() != "WTWindow":
                return False
            try:
                import win32gui

                menu_handle = win32gui.GetMenu(item.handle)
                return bool(menu_handle and win32gui.GetMenuItemCount(menu_handle) >= 2)
            except Exception:
                return False

        # The legacy launcher can create the WTWindow several seconds before
        # attaching its menu.  Wait through that intermediate state instead of
        # mistaking the visible shell for a failed launch.
        return self._wait_window(is_main_window, timeout=timeout)

    def launch(self, executable: Path, work_dir: Path) -> int:
        from pywinauto import Desktop
        from pywinauto.application import Application
        import win32gui
        import win32process

        resolved_work_dir = work_dir.resolve()
        self.repo_root = resolved_work_dir.parents[2]
        preexisting_pids = set(int(pid) for pid in win32process.EnumProcesses())
        self.app = Application(backend="win32").start(
            str(executable), work_dir=str(resolved_work_dir), timeout=30
        )
        self.pid = int(self.app.process)
        self.launcher_pid = self.pid
        def has_main_menu(item: Any) -> bool:
            try:
                menu_handle = win32gui.GetMenu(item.handle)
                return (
                    item.is_visible()
                    and item.class_name() == "WTWindow"
                    and bool(menu_handle)
                    and win32gui.GetMenuItemCount(menu_handle) >= 2
                )
            except Exception:
                return False

        def visible_launch_button(item: Any) -> Any | None:
            try:
                return next(
                    (
                        button
                        for button in item.descendants(class_name="Button")
                        if button.control_id() == 110 and button.is_visible()
                    ),
                    None,
                )
            except Exception:
                return None

        def wait_owned_main(timeout: float = 9.0) -> Any:
            """Accept a main window retained by the launcher or its new child."""

            deadline = time.monotonic() + timeout
            seen: list[str] = []
            while time.monotonic() < deadline:
                for item in Desktop(backend="win32").windows():
                    try:
                        _thread, process_id = win32process.GetWindowThreadProcessId(
                            item.handle
                        )
                        summary = f"{process_id}:{item.class_name()}:{item.window_text()}"
                        if summary not in seen:
                            seen.append(summary)
                        if (
                            process_id == self.pid
                            or process_id not in preexisting_pids
                        ) and has_main_menu(item):
                            self.pid = int(process_id)
                            return item
                    except Exception:
                        continue
                time.sleep(0.1)
            raise RuntimeError(
                "Legacy main window did not appear for launcher or new child "
                f"(launcher_pid={self.launcher_pid}; seen={seen[:12]})"
            )

        # Depending on the saved legacy configuration, a fresh process can
        # either show its launcher or enter the real main WTWindow directly.
        # Accept both states and only click control 110 when it is truly the
        # visible launcher button (the main window also owns a hidden ID 110).
        landing = self._wait_window(
            lambda item: has_main_menu(item) or visible_launch_button(item) is not None
        )
        if has_main_menu(landing):
            self.current_window = landing
            time.sleep(0.2)
            return self.pid
        button = next(
            item for item in landing.descendants(class_name="Button")
            if item.control_id() == 110 and item.is_visible()
        )
        # The launcher intermittently ignores synthesized mouse input but
        # consistently handles the same BM_CLICK used by the probe tool.
        last_error: RuntimeError | None = None
        for attempt in range(3):
            # The launcher occasionally ignores one synthesized click after a
            # prior legacy process has just exited.  BM_CLICK is the primary
            # path; a real click is used only for the retry while the same
            # verified launcher button remains visible.
            if button.is_visible():
                if attempt == 0:
                    button.click()
                else:
                    try:
                        button.click_input()
                    except Exception:
                        button.click()
            try:
                self.current_window = wait_owned_main(timeout=9.0)
                break
            except RuntimeError as error:
                last_error = error
                time.sleep(0.3)
        else:
            assert last_error is not None
            raise last_error
        # The main WTWindow becomes visible before the launcher finishes
        # closing.  Menu commands posted during that overlap are swallowed.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if not win32gui.IsWindow(landing.handle) or not win32gui.IsWindowVisible(
                landing.handle
            ):
                break
            time.sleep(0.1)
        time.sleep(0.2)
        return self.pid

    def open_rom(self, rom_path: Path) -> None:
        import win32con
        import win32gui
        import win32process

        main = self._main()
        known_dialogs: set[int] = set()
        seen_top_windows: list[str] = []

        def process_dialogs() -> list[int]:
            matches: list[int] = []

            def visit(hwnd: int, _extra: object) -> bool:
                try:
                    _thread, process_id = win32process.GetWindowThreadProcessId(hwnd)
                    if process_id == self.pid:
                        summary = (
                            f"{hwnd}:{win32gui.GetClassName(hwnd)}:"
                            f"{win32gui.GetWindowText(hwnd)!r}:"
                            f"visible={bool(win32gui.IsWindowVisible(hwnd))}"
                        )
                        if summary not in seen_top_windows:
                            seen_top_windows.append(summary)
                    if (
                        process_id == self.pid
                        and win32gui.GetClassName(hwnd) == "#32770"
                        and win32gui.IsWindowVisible(hwnd)
                    ):
                        matches.append(hwnd)
                except Exception:
                    pass
                return True

            win32gui.EnumWindows(visit, None)
            return matches

        known_dialogs.update(process_dialogs())
        dialog_hwnd = 0
        deadline = time.monotonic() + 12.0
        next_command_at = 0.0
        commands_sent = 0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if commands_sent < 3 and now >= next_command_at:
                self._menu_command(main, "文件->打开")
                commands_sent += 1
                next_command_at = now + 3.0
            dialogs = [
                hwnd for hwnd in process_dialogs()
                if hwnd not in known_dialogs and win32gui.IsWindow(hwnd)
            ]
            if dialogs:
                dialog_hwnd = dialogs[-1]
                break
            time.sleep(0.1)
        if not dialog_hwnd:
            raise RuntimeError(
                "ROM picker did not appear; process windows="
                + repr(seen_top_windows[:12])
            )
        if not win32gui.IsWindowVisible(dialog_hwnd):
            win32gui.ShowWindow(dialog_hwnd, win32con.SW_SHOW)
        edits: list[int] = []

        def visit_child(hwnd: int, _extra: object) -> bool:
            try:
                if (
                    win32gui.GetClassName(hwnd) == "Edit"
                    and win32gui.IsWindowVisible(hwnd)
                    and win32gui.IsWindowEnabled(hwnd)
                ):
                    edits.append(hwnd)
            except Exception:
                pass
            return True

        win32gui.EnumChildWindows(dialog_hwnd, visit_child, None)
        if not edits:
            raise RuntimeError("ROM picker has no enabled filename Edit")
        win32gui.SendMessage(edits[-1], win32con.WM_SETTEXT, 0, str(rom_path))
        ok_button = win32gui.GetDlgItem(dialog_hwnd, 1)  # IDOK
        if not ok_button:
            raise RuntimeError("ROM picker has no IDOK button")
        win32gui.PostMessage(ok_button, 0x00F5, 0, 0)  # BM_CLICK
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and win32gui.IsWindow(dialog_hwnd):
            time.sleep(0.1)
        if win32gui.IsWindow(dialog_hwnd):
            raise RuntimeError("ROM picker did not close after IDOK")
        deadline = time.monotonic() + 15.0
        loaded_main = None
        while time.monotonic() < deadline:
            loaded_main = self._main()
            menu_handle = win32gui.GetMenu(loaded_main.handle)
            if menu_handle and win32gui.GetMenuItemCount(menu_handle) >= 3:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Legacy main menu did not expose Data after ROM load")
        self.current_rom = rom_path
        self.current_window = loaded_main

    def _control(self, control_id: int, class_name: str | None = None) -> Any:
        if self.current_window is None:
            raise RuntimeError("No current legacy window")
        descendants = self.current_window.descendants(
            class_name=class_name
        ) if class_name else self.current_window.descendants()
        matches = [
            item for item in descendants
            if item.control_id() == control_id and item.is_visible() and item.is_enabled()
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Control ID {control_id} matched {len(matches)} descendants")
        return matches[0]

    @staticmethod
    def _menu_command(window: Any, path: str) -> None:
        """Dispatch verified legacy menu IDs without cross-bitness menu wrappers."""

        import ctypes
        import win32con

        try:
            command_id = LEGACY_MENU_COMMANDS[path]
        except KeyError as error:
            raise ValueError(f"Unsupported legacy menu path: {path}") from error
        posted = ctypes.windll.user32.PostMessageW(
            int(window.handle), win32con.WM_COMMAND, command_id, 0
        )
        if not posted:
            raise RuntimeError(f"Legacy menu command was rejected: {path}")

    def perform(self, steps: tuple[dict[str, Any], ...], requested: int | str) -> None:
        for step in steps:
            op = step["op"]
            if op == "menu":
                self._menu_command(self._main(), step["path"])
            elif op == "window":
                title = step["title"]
                if title == "数据库":
                    self.current_window = self._wait_window(
                        lambda item: item.class_name() == "WTWindow"
                        and any(
                            control.control_id() == 590
                            for control in item.descendants(class_name="Button")
                        )
                    )
                else:
                    self.current_window = self._wait_window(
                        lambda item: item.window_text() == title
                    )
                if not self.current_window.is_visible():
                    import win32con
                    import win32gui

                    win32gui.ShowWindow(self.current_window.handle, win32con.SW_SHOW)
                time.sleep(float(step.get("settle_seconds", 0)))
            elif op == "click_id":
                self._control(step["control_id"], step.get("class")).click()
            elif op == "click_id_message":
                import ctypes

                control = self._control(step["control_id"], step.get("class"))
                if not ctypes.windll.user32.PostMessageW(
                    int(control.handle), 0x00F5, 0, 0
                ):
                    raise RuntimeError(
                        f"Control ID {step['control_id']} rejected BM_CLICK"
                    )
                time.sleep(0.1)
            elif op == "click_id_input":
                import ctypes
                import time as _time

                control = self._control(step["control_id"], step.get("class"))
                rect = control.rectangle()
                root = ctypes.windll.user32.GetAncestor(int(control.handle), 2) or int(
                    control.handle
                )
                ctypes.windll.user32.ShowWindow(root, 5)  # SW_SHOW
                ctypes.windll.user32.SetForegroundWindow(root)
                x = (int(rect.left) + int(rect.right)) // 2
                y = (int(rect.top) + int(rect.bottom)) // 2
                ctypes.windll.user32.SetCursorPos(x, y)
                _time.sleep(0.12)
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                _time.sleep(0.04)
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                _time.sleep(0.2)
            elif op == "set_check":
                value = requested if step["value"] == "$requested" else step["value"]
                target = int(value)
                if target not in {0, 1}:
                    raise ValueError("set_check target must be 0 or 1")
                control = self._control(step["control_id"], step.get("class", "Button"))
                if int(control.get_check_state()) != target:
                    control.click()
                    time.sleep(0.2)
                actual = int(control.get_check_state())
                if actual != target:
                    raise RuntimeError(
                        f"Control ID {step['control_id']} check state did not change: "
                        f"expected {target}, got {actual}"
                    )
            elif op == "set_text":
                value = requested if step["value"] == "$requested" else step["value"]
                if isinstance(value, str) and value.startswith("$repo/"):
                    if self.repo_root is None:
                        raise RuntimeError("Legacy repository root is unavailable")
                    relative = Path(value[len("$repo/"):])
                    resolved = (self.repo_root / relative).resolve()
                    if relative.is_absolute() or not resolved.is_relative_to(self.repo_root):
                        raise ValueError("set_text $repo path escaped the repository")
                    value = str(resolved)
                self._control(step["control_id"], step.get("class", "Edit")).set_edit_text(str(value))
            elif op == "set_text_notify":
                import win32con
                import win32gui

                value = requested if step["value"] == "$requested" else step["value"]
                control = self._control(step["control_id"], step.get("class", "Edit"))
                control.set_edit_text(str(value))
                parent = win32gui.GetParent(control.handle)
                wparam = int(step["control_id"]) | (0x0300 << 16)  # EN_CHANGE
                win32gui.SendMessage(parent, win32con.WM_COMMAND, wparam, control.handle)
                time.sleep(0.2)
            elif op == "type_text":
                value = requested if step["value"] == "$requested" else step["value"]
                control = self._control(step["control_id"], step.get("class", "Edit"))
                control.click_input()
                control.type_keys(
                    "^a{BACKSPACE}" + str(value),
                    set_foreground=False,
                    with_spaces=True,
                )
                time.sleep(0.2)
            elif op == "select_index":
                value = requested if step["value"] == "$requested" else step["value"]
                self._control(step["control_id"], step.get("class", "ComboBox")).select(int(value))
            elif op == "select_index_keyboard":
                value = requested if step["value"] == "$requested" else step["value"]
                index = int(value)
                if index < 0:
                    raise ValueError("ComboBox keyboard index must be nonnegative")
                control = self._control(
                    step["control_id"], step.get("class", "ComboBox")
                )
                # Some legacy owner-drawn combos only commit on the real
                # CBN_SELENDOK sequence produced by keyboard navigation.
                control.click_input()
                control.set_focus()
                control.type_keys(
                    "{HOME}" + "{DOWN}" * index + "{ENTER}",
                    set_foreground=True,
                )
                actual = int(control.selected_index())
                if actual != index:
                    raise RuntimeError(
                        f"ComboBox {step['control_id']} keyboard selection "
                        f"remained at index {actual}, expected {index}"
                    )
                time.sleep(0.2)
            elif op == "select_index_message":
                import win32con
                import win32gui

                value = requested if step["value"] == "$requested" else step["value"]
                index = int(value)
                control_id = int(step["control_id"])
                control = self._control(
                    control_id, step.get("class", "ComboBox")
                )
                selected = int(
                    win32gui.SendMessage(control.handle, 0x014E, index, 0)
                )  # CB_SETCURSEL
                if selected != index:
                    raise RuntimeError(
                        f"ComboBox {control_id} rejected index {index}"
                    )
                parent = win32gui.GetParent(control.handle)
                # The reference editor commits this owner-drawn combo only
                # after the selection/change, selection/end and close-up
                # notifications that a real drop-down interaction produces.
                for notification in (1, 9, 8):  # CBN_SELCHANGE/SELENDOK/CLOSEUP
                    wparam = control_id | (notification << 16)
                    win32gui.SendMessage(
                        parent, win32con.WM_COMMAND, wparam, control.handle
                    )
                actual = int(
                    win32gui.SendMessage(control.handle, 0x0147, 0, 0)
                )  # CB_GETCURSEL
                if actual != index:
                    raise RuntimeError(
                        f"ComboBox {control_id} remained at index {actual}"
                    )
                time.sleep(0.2)
            elif op == "select_index_click":
                import win32gui
                import win32process
                from pywinauto import mouse

                value = requested if step["value"] == "$requested" else step["value"]
                index = int(value)
                if index < 0:
                    raise ValueError("ComboBox click index must be nonnegative")
                control = self._control(
                    step["control_id"], step.get("class", "ComboBox")
                )
                rectangle = control.rectangle()
                control.click_input(
                    coords=(max(1, rectangle.width() - 8), rectangle.height() // 2)
                )
                combo_list = 0
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline and not combo_list:
                    candidates: list[int] = []

                    def visit(hwnd: int, _extra: object) -> bool:
                        _thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
                        if (
                            process_id == self.pid
                            and win32gui.GetClassName(hwnd) == "ComboLBox"
                            and win32gui.IsWindowVisible(hwnd)
                        ):
                            candidates.append(hwnd)
                        return True

                    win32gui.EnumWindows(visit, None)
                    if candidates:
                        combo_list = candidates[-1]
                        break
                    time.sleep(0.05)
                if not combo_list:
                    raise RuntimeError("ComboBox drop-down list did not open")
                left, top, right, _bottom = win32gui.GetWindowRect(combo_list)
                item_height = int(
                    win32gui.SendMessage(control.handle, 0x0154, 0, 0)
                )  # CB_GETITEMHEIGHT
                if item_height <= 0:
                    raise RuntimeError("ComboBox returned an invalid item height")
                mouse.click(
                    button="left",
                    coords=((left + right) // 2, top + item_height * index + item_height // 2),
                )
                actual = int(control.selected_index())
                if actual != index:
                    raise RuntimeError(
                        f"ComboBox {step['control_id']} click selection "
                        f"remained at index {actual}, expected {index}"
                    )
                time.sleep(0.2)
            elif op == "list_select":
                import win32con
                import win32gui

                listbox = self._control(step["control_id"], step.get("class", "ListBox"))
                row = int(step["row"])
                result = win32gui.SendMessage(listbox.handle, 0x0186, row, 0)  # LB_SETCURSEL
                if result == -1:
                    raise RuntimeError(f"ListBox row {row} is out of range")
                parent = win32gui.GetParent(listbox.handle)
                wparam = int(step["control_id"]) | (1 << 16)  # LBN_SELCHANGE
                win32gui.SendMessage(parent, win32con.WM_COMMAND, wparam, listbox.handle)
                time.sleep(0.2)
            elif op == "list_double_click":
                table = self._control(step["control_id"], step.get("class", "SysListView32"))
                table.get_item(step["row"], step["column"]).double_click_input()
            elif op == "click_coords":
                self.current_window.click_input(coords=(step["x"], step["y"]))
                # Owner-drawn CPageControl pages rebuild their child controls
                # asynchronously after the real click.  Do not query the next
                # page immediately or pywinauto can still see the old page.
                time.sleep(0.6)
            elif op == "click_control_coords":
                import ctypes
                import win32con
                import win32gui
                import win32process

                control = self._control(step["control_id"], step.get("class"))
                target = int(self.current_window.handle)
                foreground = int(win32gui.GetForegroundWindow())
                foreground_tid, _foreground_pid = (
                    win32process.GetWindowThreadProcessId(foreground)
                )
                target_tid, _target_pid = win32process.GetWindowThreadProcessId(
                    target
                )
                current_tid = int(ctypes.windll.kernel32.GetCurrentThreadId())
                attached_foreground = False
                attached_target = False
                try:
                    if foreground_tid and foreground_tid != current_tid:
                        attached_foreground = bool(
                            ctypes.windll.user32.AttachThreadInput(
                                current_tid, foreground_tid, True
                            )
                        )
                    if target_tid and target_tid != current_tid:
                        attached_target = bool(
                            ctypes.windll.user32.AttachThreadInput(
                                current_tid, target_tid, True
                            )
                        )
                    win32gui.ShowWindow(target, win32con.SW_RESTORE)
                    win32gui.BringWindowToTop(target)
                    win32gui.SetForegroundWindow(target)
                finally:
                    if attached_target:
                        ctypes.windll.user32.AttachThreadInput(
                            current_tid, target_tid, False
                        )
                    if attached_foreground:
                        ctypes.windll.user32.AttachThreadInput(
                            current_tid, foreground_tid, False
                        )
                time.sleep(0.2)
                left, top, _right, _bottom = win32gui.GetWindowRect(control.handle)
                point = (left + int(step["x"]), top + int(step["y"]))
                hit = int(win32gui.WindowFromPoint(point))
                root = int(win32gui.GetAncestor(hit, win32con.GA_ROOT)) if hit else 0
                if root != target:
                    raise RuntimeError(
                        "Control-relative click is covered by another window: "
                        f"point={point}, hit={hit}, root={root}, target={target}, "
                        f"foreground={int(win32gui.GetForegroundWindow())}"
                    )
                ctypes.windll.user32.SetCursorPos(*point)
                for click_index in range(int(step.get("click_count", 1))):
                    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                    time.sleep(0.05)
                    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                    if click_index == 0 and int(step.get("click_count", 1)) == 2:
                        time.sleep(0.08)
                wait_control_id = step.get("wait_control_id")
                deadline = time.monotonic() + 3.0
                while wait_control_id is not None and time.monotonic() < deadline:
                    if any(
                        item.control_id() == wait_control_id
                        and item.is_visible()
                        and item.is_enabled()
                        for item in self.current_window.descendants()
                    ):
                        break
                    time.sleep(0.1)
                else:
                    if wait_control_id is not None:
                        visible_ids = sorted(
                            {
                                int(item.control_id())
                                for item in self.current_window.descendants()
                                if item.is_visible() and item.is_enabled()
                            }
                        )
                        raise RuntimeError(
                            f"Control-relative click did not expose {wait_control_id}; "
                            f"visible_ids={visible_ids}"
                        )
                time.sleep(0.2)
            elif op == "assert_value":
                expected = (
                    requested if step["value"] == "$requested" else step["value"]
                )
                control = self._control(step["control_id"], step.get("class"))
                actual: int | str
                if step.get("value_type") == "combo_index":
                    actual = int(control.selected_index())
                    expected = int(expected)
                else:
                    actual = control.window_text()
                if step.get("value_type", "str") == "int":
                    actual = int(actual)
                    expected = int(expected)
                if actual != expected:
                    raise RuntimeError(
                        f"Control ID {step['control_id']} value did not change: "
                        f"expected {expected!r}, got {actual!r}"
                    )
            else:
                raise ValueError(f"Unsupported operation: {op}")

    def read(self, selector: dict[str, Any]) -> int | str:
        control = self._control(selector["control_id"], selector["class"])
        if selector.get("value_type") == "check":
            return int(control.get_check_state())
        if selector.get("value_type") == "combo_index":
            return int(control.selected_index())
        if selector.get("value_type") == "combo_item_count":
            return len(control.item_texts())
        if selector.get("value_type") == "list_item_count":
            return len(control.item_texts())
        if selector.get("value_type") == "list_item_text":
            items = list(control.item_texts())
            item_index = int(selector["item_index"])
            if item_index >= len(items):
                raise RuntimeError(
                    f"ListBox item {item_index} is unavailable; count={len(items)}"
                )
            return items[item_index]
        if selector.get("value_type") == "control_pixel_sha256":
            return _control_pixel_sha256_hwnd(int(control.handle))
        if selector.get("value_type") == "checkbox_pixel":
            return _owner_drawn_spirit_checkbox_state_hwnd(
                int(control.handle), int(selector["item_index"])
            )
        value = control.window_text()
        return int(value) if selector.get("value_type") == "int" else value

    def save(self) -> None:
        if self.current_rom is None:
            raise RuntimeError("No ROM is open for saving")
        previous_stat = self.current_rom.stat()
        previous_bytes = self.current_rom.read_bytes()
        self._menu_command(self._main(), "文件->保存")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            for window in self.app.windows(visible_only=True):
                if window.class_name() != "#32770":
                    continue
                for label in ("是", "确定", "保存"):
                    buttons = [
                        button for button in window.descendants(class_name="Button")
                        if button.window_text().replace("&", "") == label
                    ]
                    if buttons:
                        buttons[0].click()
                        break
            try:
                current_stat = self.current_rom.stat()
                current_bytes = self.current_rom.read_bytes()
            except OSError:
                time.sleep(0.1)
                continue
            if current_stat.st_size == previous_stat.st_size and (
                current_stat.st_mtime_ns != previous_stat.st_mtime_ns
                or current_bytes != previous_bytes
            ):
                time.sleep(0.1)
                if self.current_rom.read_bytes() == current_bytes:
                    return
            time.sleep(0.1)
        raise RuntimeError("Legacy save did not update the isolated ROM before timeout")

    def stop(self) -> None:
        if self.app is not None:
            try:
                import win32api
                import win32con
                import win32event
                import win32gui

                owned_pids = {
                    int(pid)
                    for pid in (self.pid, self.launcher_pid)
                    if pid is not None
                }
                for owned_pid in owned_pids:
                    try:
                        handle = win32api.OpenProcess(
                            win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE,
                            False,
                            owned_pid,
                        )
                    except win32gui.error:
                        handle = None  # The process already exited after a legacy dialog.
                    if handle is not None:
                        try:
                            win32api.TerminateProcess(handle, 0)
                            result = win32event.WaitForSingleObject(handle, 5000)
                            if result != win32con.WAIT_OBJECT_0:
                                raise RuntimeError("process handle did not signal exit")
                        finally:
                            win32api.CloseHandle(handle)
            except Exception as error:
                raise RuntimeError(f"Legacy process {self.pid} did not exit") from error
            finally:
                self.app = None
                self.pid = None
                self.launcher_pid = None
                self.current_window = None
                self.current_rom = None
