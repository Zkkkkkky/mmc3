from __future__ import annotations

import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget  # noqa: E402

from dc_modifier.app import DEFAULT_ROM, MainWindow  # noqa: E402
from dc_modifier.legacy_tools import (  # noqa: E402
    AttributeCalculatorDialog,
    FontLibraryDialog,
    MapAnimationDialog,
    OtherSettingsDialog,
    SaveEditorDialog,
    TextConverterDialog,
)
from dc_modifier.legacy_windows import DatabaseDialog, ScenarioDialog  # noqa: E402
from dc_modifier.production_credits_editor import ProductionCreditsDialog  # noqa: E402
from dc_modifier.rom_data_browser import RomDataBrowserDialog  # noqa: E402
from fc_rom_editor_core import RomProject  # noqa: E402


def main() -> int:
    app = QApplication.instance() or QApplication([])
    measurements: dict[str, float] = {}

    def timed(label: str, callback):
        started = time.perf_counter()
        result = callback()
        app.processEvents()
        measurements[label] = time.perf_counter() - started
        return result

    project = timed("rom_load", lambda: RomProject.load(DEFAULT_ROM))
    timed("validate", project.validate)
    window = timed("window_construct_no_rom", lambda: MainWindow(open_default=False))
    timed("project_activate", lambda: window._activate_project(project))

    for key in window.page_index:
        timed(f"main.{key}.first", lambda key=key: window.show_page(key))
    for key in window.page_index:
        timed(f"main.{key}.again", lambda key=key: window.show_page(key))

    dialogs: list[QWidget] = []
    factories = (
        ("database", lambda: DatabaseDialog(project, window, lazy=True)),
        ("scenario", lambda: ScenarioDialog(project, window, lazy=True)),
        ("font", lambda: FontLibraryDialog(parent=window, project=project)),
        ("animation", lambda: MapAnimationDialog(parent=window, project=project)),
        ("converter", lambda: TextConverterDialog(parent=window, project=project)),
        ("calculator", lambda: AttributeCalculatorDialog(parent=window, project=project)),
        ("other", lambda: OtherSettingsDialog(parent=window, project=project)),
        ("save", lambda: SaveEditorDialog(parent=window, project=project)),
        ("rom_data", lambda: RomDataBrowserDialog(project, window)),
        ("credits", lambda: ProductionCreditsDialog(window, project)),
    )
    for label, factory in factories:
        dialog = timed(f"dialog.{label}.construct", factory)
        dialogs.append(dialog)
        ensure_current = getattr(dialog, "_ensure_tab_loaded", None)
        if callable(ensure_current):
            timed(
                f"dialog.{label}.default.first",
                lambda: ensure_current(dialog.tabs.currentIndex()),
            )
        visited: set[int] = set()
        pending = list(dialog.findChildren(QTabWidget))
        while pending:
            tabs = pending.pop(0)
            identity = id(tabs)
            if identity in visited:
                continue
            visited.add(identity)
            tab_name = tabs.objectName() or "tabs"
            for index in range(tabs.count()):
                timed(
                    f"dialog.{label}.{tab_name}.{index}.first",
                    lambda tabs=tabs, index=index: tabs.setCurrentIndex(index),
                )
            for index in range(tabs.count()):
                timed(
                    f"dialog.{label}.{tab_name}.{index}.again",
                    lambda tabs=tabs, index=index: tabs.setCurrentIndex(index),
                )
            pending.extend(
                child
                for child in dialog.findChildren(QTabWidget)
                if id(child) not in visited
            )

    for dialog in dialogs:
        dialog.deleteLater()
    window.close()
    app.processEvents()
    for label, seconds in measurements.items():
        print(f"{label}={seconds:.4f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
