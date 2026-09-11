"""Exercise database transactions and deletion in an actual Qt event loop.

Only the JSON report is written; the input ROM is never saved or overwritten.
Run with the project's Python environment from any working directory.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import faulthandler
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import PySide6
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QSpinBox
import shiboken6

from dc_modifier.legacy_windows import DatabaseDialog
from dc_modifier.workspace import DEFAULT_ROM, writable_output_path
from fc_rom_editor_core import RomProject


def changed_value(field: QSpinBox) -> int:
    value = field.value()
    updated = value + 1 if value < field.maximum() else value - 1
    assert field.minimum() <= updated <= field.maximum() and updated != value
    return updated


class LifecycleProbe:
    def __init__(self, app: QApplication, rounds: int, report_path: Path) -> None:
        self.app = app
        self.rounds = rounds
        self.report_path = report_path
        self.dialog: DatabaseDialog | None = None
        self.project: RomProject | None = None
        self.baseline = b""
        self.round_index = 0
        self.destroyed_count = 0
        self.started = time.monotonic()
        self.failed = False
        self.finished = False
        self.source_hash = hashlib.sha256(DEFAULT_ROM.read_bytes()).hexdigest()
        self.report: dict[str, object] = {
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(),
            "pyside6": PySide6.__version__,
            "platform": os.environ.get("QT_QPA_PLATFORM", ""),
            "event_loop": "QApplication.exec with QTimer callbacks",
            "automatic_gc_enabled": gc.isenabled(),
            "explicit_gc_collection": False,
            "explicit_deferred_delete_flush": False,
            "requested_rounds": rounds,
            "input_rom": str(DEFAULT_ROM.relative_to(ROOT)),
            "input_sha256_before": self.source_hash,
            "rounds": [],
        }

    def schedule(self, callback: Callable[[], None], delay_ms: int = 0) -> None:
        def guarded() -> None:
            if self.finished:
                return
            try:
                callback()
            except BaseException:
                self.failed = True
                self.report["error"] = traceback.format_exc()
                print(self.report["error"], flush=True)
                self.finish()

        QTimer.singleShot(delay_ms, guarded)

    def open_dialog(self) -> None:
        assert not self.app.topLevelWidgets(), "A prior round left Qt windows alive"
        self.round_index += 1
        self.project = RomProject.load(DEFAULT_ROM)
        self.baseline = bytes(self.project.working)
        self.dialog = DatabaseDialog(self.project)
        self.dialog.destroyed.connect(self.dialog_destroyed)
        self.dialog.show()
        self.schedule(self.edit_and_navigate)

    def dialog_destroyed(self) -> None:
        self.destroyed_count += 1

    def edit_and_navigate(self) -> None:
        assert self.dialog is not None and self.project is not None
        unit = self.dialog.unit_page
        unit_id = unit.current_id
        hp = changed_value(unit.fields["hp"])
        unit.fields["hp"].setValue(hp)
        unit.weapon_slots[0].setCurrentIndex(unit.weapon_slots[0].findData(1))
        unit._request_weapon(0)
        assert self.project.get_value(unit_id, "hp") == hp

        weapon = self.dialog.weapon_page
        assert weapon.current_id == 1
        selected = weapon.usage_list.currentItem()
        assert selected is not None, "Edited weapon must have at least one user"
        target_id = int(selected.data(Qt.ItemDataRole.UserRole))
        hit = changed_value(weapon.fields["hit"])
        weapon.fields["hit"].setValue(hit)
        weapon.usage_list.itemDoubleClicked.emit(selected)
        assert shiboken6.isValid(selected), "Signal argument was deleted during navigation"
        assert self.dialog.unit_page.current_id == target_id
        assert self.project.get_weapon_value(1, "hit") == hit
        assert bytes(self.project.working) != self.baseline
        self.schedule(self.close_dialog)

    def close_dialog(self) -> None:
        assert self.dialog is not None and self.project is not None
        accepted = self.round_index % 2 == 0
        undo_steps = 0
        if accepted:
            self.dialog.accept()
            assert bytes(self.project.working) != self.baseline
            while self.project._undo_stack:
                self.project.undo()
                undo_steps += 1
            assert undo_steps >= 2, "Unit and weapon edits should both be undoable"
        else:
            self.dialog.reject()
            assert not self.project._undo_stack
            assert not self.project._redo_stack
        assert bytes(self.project.working) == self.baseline
        self.report["rounds"].append({
            "round": self.round_index,
            "action": "accept_then_undo" if accepted else "reject",
            "undo_steps": undo_steps,
            "rom_restored": True,
        })
        self.dialog.deleteLater()
        # Return to the real event loop so Qt, not a manual event flush,
        # processes DeferredDelete before the following observation.
        self.schedule(self.check_deleted, delay_ms=10)

    def check_deleted(self) -> None:
        assert self.dialog is not None
        assert not shiboken6.isValid(self.dialog), "Dialog was not deleted by event loop"
        assert self.destroyed_count == self.round_index
        remaining = self.app.topLevelWidgets()
        assert not remaining, f"Remaining Qt windows: {[type(w).__name__ for w in remaining]}"
        self.report["rounds"][-1]["top_level_widgets_after_delete"] = len(remaining)
        self.report["rounds"][-1]["destroyed_signal_observed"] = True
        self.dialog = None
        self.project = None
        print(f"round {self.round_index}/{self.rounds}: transaction and lifecycle OK", flush=True)
        if self.round_index == self.rounds:
            self.finish()
        else:
            self.schedule(self.open_dialog)

    def timeout(self) -> None:
        self.failed = True
        self.report["error"] = "Qt lifecycle verification exceeded the timeout"
        self.finish()

    def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        current_hash = hashlib.sha256(DEFAULT_ROM.read_bytes()).hexdigest()
        self.report["input_sha256_after"] = current_hash
        self.report["input_unchanged"] = current_hash == self.source_hash
        self.failed = self.failed or current_hash != self.source_hash
        self.report["destroyed_dialogs"] = self.destroyed_count
        self.report["elapsed_seconds"] = round(time.monotonic() - self.started, 3)
        self.report["status"] = "failed" if self.failed else "passed"
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{self.report['status']}: {self.report_path}", flush=True)
        self.app.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--report", type=Path, default=ROOT / "output/verification/dialog-lifecycle.json")
    arguments = parser.parse_args()
    if arguments.rounds < 2 or arguments.timeout_seconds < 1:
        parser.error("rounds must be at least 2 and timeout-seconds positive")
    try:
        report_path = writable_output_path(arguments.report)
        if report_path == DEFAULT_ROM.resolve() or (
            report_path.exists() and report_path.samefile(DEFAULT_ROM)
        ):
            raise ValueError("The report cannot overwrite the input ROM")
        if report_path.suffix.lower() != ".json":
            raise ValueError("The report path must have a .json suffix")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    faulthandler.enable()
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    probe = LifecycleProbe(app, arguments.rounds, report_path)
    probe.schedule(probe.open_dialog)
    probe.schedule(probe.timeout, delay_ms=arguments.timeout_seconds * 1000)
    app.exec()
    return int(probe.failed)


if __name__ == "__main__":
    raise SystemExit(main())
