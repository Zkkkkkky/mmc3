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
    {
        "menu",
        "window",
        "click_id",
        "set_text",
        "select_index",
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
        if op == "assert_value" and not (
            isinstance(item.get("control_id"), int)
            and item.get("value_type", "str") in {"int", "str"}
            and "value" in item
        ):
            raise ValueError(
                "assert_value requires control_id, value and int/str value_type"
            )
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
        "supporting_cdl": (
            {
                "source": cdl_source.relative_to(repo).as_posix(),
                "sha256": sha256_bytes(cdl_bytes),
            }
            if cdl_bytes is not None
            else None
        ),
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
    cdl_path.unlink(missing_ok=True)
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
        from pywinauto.application import Application

        self.app = Application(backend="win32").start(
            str(executable), work_dir=str(work_dir), timeout=30
        )
        self.pid = int(self.app.process)
        landing = self._wait_window(
            lambda item: item.is_visible()
            and any(
                button.control_id() == 110
                for button in item.descendants(class_name="Button")
            )
        )
        button = next(
            item for item in landing.descendants(class_name="Button")
            if item.control_id() == 110
        )
        # The launcher intermittently ignores synthesized mouse input but
        # consistently handles the same BM_CLICK used by the probe tool.
        last_error: RuntimeError | None = None
        for attempt in range(3):
            # The launcher occasionally ignores one synthesized click after a
            # prior legacy process has just exited.  BM_CLICK is the primary
            # path; a real click is used only for the retry while the same
            # verified launcher button remains visible.
            if attempt == 0:
                button.click()
            else:
                try:
                    button.click_input()
                except Exception:
                    button.click()
            try:
                self.current_window = self._main(timeout=9.0)
                break
            except RuntimeError as error:
                last_error = error
                time.sleep(0.3)
        else:
            assert last_error is not None
            raise last_error
        # The main WTWindow becomes visible before the launcher finishes
        # closing.  Menu commands posted during that overlap are swallowed.
        import win32gui

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
            elif op == "click_id":
                self._control(step["control_id"], step.get("class")).click()
            elif op == "set_text":
                value = requested if step["value"] == "$requested" else step["value"]
                self._control(step["control_id"], step.get("class", "Edit")).set_edit_text(str(value))
            elif op == "select_index":
                value = requested if step["value"] == "$requested" else step["value"]
                self._control(step["control_id"], step.get("class", "ComboBox")).select(int(value))
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
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                time.sleep(0.05)
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
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
                actual: int | str = self._control(
                    step["control_id"], step.get("class")
                ).window_text()
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
        value = self._control(selector["control_id"], selector["class"]).window_text()
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
