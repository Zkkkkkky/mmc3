"""M00: collect one isolated legacy-ROM field with a real cold restart.

The orchestration is standard-library-only so it can be tested with a fake driver.
The Win32 adapter imports pywinauto only when a live case is requested.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

try:
    from golden_pipeline_core import (
        AUDIT_DIR_RELATIVE,
        classify_case,
        diff_roms,
        sha256_bytes,
        write_json_atomic,
    )
except ImportError:
    from tools.golden_pipeline_core import (  # type: ignore
        AUDIT_DIR_RELATIVE,
        classify_case,
        diff_roms,
        sha256_bytes,
        write_json_atomic,
    )


LIVE_CASES_RELATIVE = AUDIT_DIR_RELATIVE / "cases" / "legacy_live"
LIVE_RESULTS_RELATIVE = AUDIT_DIR_RELATIVE / "legacy-live-results.json"
SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
STEP_OPERATIONS = frozenset(
    {"menu", "window", "click_id", "set_text", "select_index", "list_double_click", "click_coords"}
)


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
    requested_value: int | str
    expected_before: int | str | None
    expected_offsets: tuple[int, ...]
    required_offsets: tuple[int, ...]
    optional_offsets: tuple[int, ...]
    extra_allowed: tuple[int, ...]
    navigation: tuple[dict[str, Any], ...]
    edit_steps: tuple[dict[str, Any], ...]
    read_selector: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CaseSpec:
        for key in ("module", "field", "case_id"):
            if not SAFE_NAME.fullmatch(str(payload.get(key, ""))):
                raise ValueError(f"Unsafe or missing case name: {key}")
        module = str(payload["module"])
        if not re.fullmatch(r"M\d\d", module):
            raise ValueError("module must be an Mxx identifier")
        expected = tuple(int(value) for value in payload["expected_offsets"])
        required = tuple(int(value) for value in payload["required_offsets"])
        optional = tuple(int(value) for value in payload.get("optional_offsets", []))
        extra_allowed = tuple(int(value) for value in payload.get("extra_allowed", []))
        if len(set(expected)) != len(expected):
            raise ValueError("expected_offsets contain duplicates")
        if not required or set(required) & set(optional) or set(required) | set(optional) != set(expected):
            raise ValueError("required/optional offsets must partition expected offsets")
        if any(value < 0 for value in (*expected, *extra_allowed)):
            raise ValueError("ROM offsets must be nonnegative")
        navigation = _validate_steps(payload["navigation"])
        edit_steps = _validate_steps(payload["edit_steps"])
        if not navigation or not edit_steps:
            raise ValueError("navigation and edit_steps must be nonempty")
        selector = dict(payload["read_selector"])
        if selector.get("class") not in {"Edit", "ComboBox", "Button", "Static"}:
            raise ValueError("Unsupported read selector class")
        if not isinstance(selector.get("control_id"), int):
            raise ValueError("read selector needs an integer control_id")
        if selector.get("value_type", "str") not in {"int", "str"}:
            raise ValueError("value_type must be int or str")
        requested = payload["requested_value"]
        before = payload.get("expected_before")
        if not isinstance(requested, (int, str)) or isinstance(requested, bool):
            raise ValueError("requested_value must be an integer or string")
        if before is not None and type(before) is not type(requested):
            raise ValueError("expected_before and requested_value must have the same type")
        if (selector.get("value_type") == "int") != isinstance(requested, int):
            raise ValueError("read selector value_type must match requested_value")
        return cls(
            module=module,
            field=str(payload["field"]),
            case_id=str(payload["case_id"]),
            requested_value=requested,
            expected_before=before,
            expected_offsets=expected,
            required_offsets=required,
            optional_offsets=optional,
            extra_allowed=extra_allowed,
            navigation=navigation,
            edit_steps=edit_steps,
            read_selector=selector,
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
        if op in {"click_id", "set_text", "select_index"} and not isinstance(item.get("control_id"), int):
            raise ValueError(f"{op} step requires control_id")
        if op in {"set_text", "select_index"} and "value" not in item:
            raise ValueError(f"{op} step requires value")
        if op == "list_double_click" and not all(
            isinstance(item.get(key), int) and not isinstance(item.get(key), bool)
            for key in ("control_id", "row", "column")
        ):
            raise ValueError("list_double_click requires integer control_id/row/column")
        if op == "list_double_click" and (item["row"] < 0 or item["column"] < 0):
            raise ValueError("list_double_click row/column must be nonnegative")
        if op == "click_coords" and not all(isinstance(item.get(key), int) for key in ("x", "y")):
            raise ValueError("click_coords requires integer x/y")
        steps.append(dict(item))
    return tuple(steps)


def _within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


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
    started = time.monotonic()
    before_path = run_dir / "before.nes"
    after_path = run_dir / "after.nes"
    before_bytes = baseline.read_bytes()
    before_path.write_bytes(before_bytes)
    after_path.write_bytes(before_bytes)
    first_pid: int | None = None
    second_pid: int | None = None
    original: int | str | None = None
    reopened: int | str | None = None

    try:
        first = driver_factory()
        try:
            first_pid = first.launch(executable, executable.parent)
            first.open_rom(after_path)
            first.perform(spec.navigation, spec.requested_value)
            original = first.read(spec.read_selector)
            if spec.expected_before is not None and original != spec.expected_before:
                raise RuntimeError(
                    f"Baseline display differs: expected {spec.expected_before!r}, got {original!r}"
                )
            first.perform(spec.edit_steps, spec.requested_value)
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
            second.perform(spec.navigation, spec.requested_value)
            reopened = second.read(spec.read_selector)
        finally:
            second.stop()
    except Exception as error:
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
    elapsed = time.monotonic() - started
    within_budget = elapsed <= budget_seconds
    passed = (
        not classification.unexplained
        and not required_missing
        and reopened == spec.requested_value
        and within_budget
    )
    reasons: list[str] = []
    if classification.unexplained:
        reasons.append(f"{len(classification.unexplained)} unexplained offsets")
    if required_missing:
        reasons.append(f"{len(required_missing)} required offsets unchanged")
    if reopened != spec.requested_value:
        reasons.append("cold reopen value differs from request")
    if not within_budget:
        reasons.append(f"{elapsed:.2f}s exceeds {budget_seconds:.2f}s budget")
    relative = run_dir.relative_to(repo).as_posix()
    report: dict[str, Any] = {
        "schema_version": 1,
        "module": spec.module,
        "field": spec.field,
        "case_id": spec.case_id,
        "case_kind": "golden",
        "requested_value": spec.requested_value,
        "original_value": original,
        "reopen_value": reopened,
        "reopen_matches_request": reopened == spec.requested_value,
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
        "expected_not_changed": required_missing,
        "diffs": [
            {"offset": entry.offset, "before": entry.before_value, "after": entry.after_value}
            for entry in diff
        ],
        "snapshots": {
            "before": {"path": f"{relative}/before.nes", "sha256": sha256_bytes(before_bytes)},
            "after": {"path": f"{relative}/after.nes", "sha256": sha256_bytes(after_bytes)},
        },
        "duration_seconds": round(elapsed, 3),
        "budget_seconds": budget_seconds,
        "within_budget": within_budget,
        "passed": passed,
        "pending_reason": "; ".join(reasons) or None,
    }
    write_json_atomic(run_dir / "case.json", report)
    results_path = repo / LIVE_RESULTS_RELATIVE
    results: list[dict[str, Any]] = (
        json.loads(results_path.read_text(encoding="utf-8")) if results_path.is_file() else []
    )
    results.append(report)
    results.sort(key=lambda item: (item["module"], item["field"], item["case_id"]))
    write_json_atomic(results_path, results)
    return run_dir, report


class Win32LegacyDriver:
    """Whitelist-based pywinauto driver for the isolated SRW2 reference EXE."""

    def __init__(self) -> None:
        self.app: Any = None
        self.pid: int | None = None
        self.current_window: Any = None
        self.current_rom: Path | None = None

    def _wait_window(self, predicate: Callable[[Any], bool], timeout: float = 12.0) -> Any:
        from pywinauto import Desktop

        deadline = time.monotonic() + timeout
        seen: list[str] = []
        while time.monotonic() < deadline:
            windows = Desktop(backend="win32").windows(visible_only=False)
            if self.app is not None:
                try:
                    windows.extend(self.app.windows(visible_only=False))
                except Exception:
                    pass
            for window in windows:
                try:
                    if window.process_id() != self.pid:
                        continue
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

    def _main(self) -> Any:
        return self._wait_window(
            lambda item: item.is_visible()
            and item.window_text().startswith("SRW2扩容版修改器")
        )

    def launch(self, executable: Path, work_dir: Path) -> int:
        from pywinauto.application import Application

        self.app = Application(backend="win32").start(
            str(executable), work_dir=str(work_dir), timeout=30
        )
        self.pid = int(self.app.process)
        landing = self._wait_window(
            lambda item: item.is_visible()
            and any(
                button.window_text() == "进入修改器"
                for button in item.descendants(class_name="Button")
            )
        )
        button = next(
            item for item in landing.descendants(class_name="Button")
            if item.window_text() == "进入修改器"
        )
        button.click_input()
        self.current_window = self._main()
        return self.pid

    def open_rom(self, rom_path: Path) -> None:
        import win32con
        import win32gui

        main = self._main()
        main.menu_select("文件->打开")
        dialog = self._wait_window(
            lambda item: item.class_name() == "#32770"
            and item.window_text().startswith("打开")
        )
        if not dialog.is_visible():
            win32gui.ShowWindow(dialog.handle, win32con.SW_SHOW)
        edits = [
            item for item in dialog.descendants(class_name="Edit")
            if item.is_visible() and item.is_enabled()
        ]
        if not edits:
            raise RuntimeError("ROM picker has no enabled filename Edit")
        edits[-1].set_edit_text(str(rom_path))
        dialog.type_keys("{ENTER}")
        self.current_rom = rom_path
        self.current_window = self._main()

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

    def perform(self, steps: tuple[dict[str, Any], ...], requested: int | str) -> None:
        for step in steps:
            op = step["op"]
            if op == "menu":
                self._main().menu_select(step["path"])
            elif op == "window":
                title = step["title"]
                self.current_window = self._wait_window(
                    lambda item: item.is_visible() and item.window_text() == title
                )
            elif op == "click_id":
                self._control(step["control_id"], step.get("class")).click_input()
            elif op == "set_text":
                value = requested if step["value"] == "$requested" else step["value"]
                self._control(step["control_id"], step.get("class", "Edit")).set_edit_text(str(value))
            elif op == "select_index":
                value = requested if step["value"] == "$requested" else step["value"]
                self._control(step["control_id"], step.get("class", "ComboBox")).select(int(value))
            elif op == "list_double_click":
                table = self._control(step["control_id"], step.get("class", "SysListView32"))
                table.get_item(step["row"], step["column"]).double_click_input()
            elif op == "click_coords":
                self.current_window.click_input(coords=(step["x"], step["y"]))
            else:
                raise ValueError(f"Unsupported operation: {op}")

    def read(self, selector: dict[str, Any]) -> int | str:
        value = self._control(selector["control_id"], selector["class"]).window_text()
        return int(value) if selector.get("value_type") == "int" else value

    def save(self) -> None:
        if self.current_rom is None:
            raise RuntimeError("No ROM is open for saving")
        previous_mtime = self.current_rom.stat().st_mtime_ns
        self._main().menu_select("文件->保存")
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
            if self.current_rom.stat().st_mtime_ns != previous_mtime:
                return
            time.sleep(0.1)
        raise RuntimeError("Legacy save did not update the isolated ROM before timeout")

    def stop(self) -> None:
        if self.app is not None:
            try:
                try:
                    self.app.kill(soft=False)
                except Exception:
                    # The process may already have exited after a legacy error dialog.
                    pass
                self.app.wait_for_process_exit(timeout=5)
            except Exception as error:
                raise RuntimeError(f"Legacy process {self.pid} did not exit") from error
            finally:
                self.app = None
                self.pid = None
                self.current_window = None
                self.current_rom = None
