from __future__ import annotations

"""Render and audit the editor's complete top-level UI surface.

Run this module in a fresh process for every scale factor.  It intentionally
uses real Qt layouts and fonts instead of estimating dimensions from .ui/code
constants, so Windows 100% and 125% regressions are reproducible in CI.
"""

import argparse
import json
import os
import sys
from pathlib import Path


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", choices=("1", "1.25"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


ARGS = _arguments()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = ARGS.scale

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QGroupBox,
    QLabel,
    QScrollArea,
    QTabWidget,
    QWidget,
)

from dc_modifier.app import DEFAULT_ROM, LauncherWindow, MainWindow, STYLE_SHEET
from dc_modifier.animation_editor import (
    AnimationInstructionDialog,
    AnimationPointerDialog,
    WeaponAnimationCommandDialog,
    WeaponAnimationCommandPaletteDialog,
)
from dc_modifier.beginner_guide import BeginnerGuideDialog
from dc_modifier.character_editor import (
    DialogueRuleDialog,
    DialogueRuleGroupDialog,
    DialogueBindingDialog,
    RuleConditionDialog,
    SpiritCostDialog,
    TransformDialogueDialog,
)
from dc_modifier.database_graphics import FragmentTile
from dc_modifier.database_memory import DatabaseMemoryDialog
from dc_modifier.event_instruction_dialog import (
    EventCodeDialog,
    EventInstructionDialog,
    EventParameterDialog,
)
from dc_modifier.legacy_text_pages import GrowthHexDialog
from dc_modifier.legacy_tools import (
    AttributeCalculatorDialog,
    DamageMultiplierDialog,
    DefeatExperienceCalculatorDialog,
    FontLibraryDialog,
    MapAnimationDialog,
    OtherSettingsDialog,
    SaveEditorDialog,
    TextConverterDialog,
)
from dc_modifier.legacy_windows import (
    ChapterTitleDialog,
    DatabaseDialog,
    ScenarioDialog,
    UnitSpecialEditorDialog,
)
from dc_modifier.map_page import NesPaletteDialog, TileAttributeDialog
from dc_modifier.production_credits_editor import ProductionCreditsDialog
from dc_modifier.rom_data_browser import RomDataBrowserDialog
from dc_modifier.unit_appearance_dialog import (
    ChrTileEditorDialog,
    FragmentPlacementDialog,
    UnitAppearanceDialog,
)
from dc_modifier.unit_icon_dialog import UnitIconBindingDialog, UnitIconDialog
from dc_modifier.weapon_rule_library import (
    WeaponMovementSimulatorDialog,
    WeaponRuleLibraryDialog,
)
from fc_editor.codecs.animation import AnimationInstruction
from fc_editor.codecs.character_dialogue import DialogueRule, TransformDialogueBinding


def _process(application: QApplication) -> None:
    for _ in range(8):
        application.processEvents()


def _configure_font(application: QApplication) -> None:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for candidate in ("msyh.ttc", "simhei.ttf", "simsun.ttc"):
        font_id = QFontDatabase.addApplicationFont(str(windows / "Fonts" / candidate))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            font = QFont(families[0], 10)
            application.setFont(font)
            return
    application.setFont(QFont("Microsoft YaHei UI", 10))


def _identity(widget: QWidget) -> str:
    name = widget.objectName() or "-"
    return f"{type(widget).__name__}#{name}"


def _text_width(widget: QWidget, text: str) -> int:
    return widget.fontMetrics().horizontalAdvance(text.replace("&", ""))


def _text_issues(root: QWidget, state: str) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    candidates = root.findChildren(QWidget)
    if isinstance(root, QWidget):
        candidates.insert(0, root)
    for widget in candidates:
        if not widget.isVisibleTo(root) or widget.width() <= 0:
            continue
        text = ""
        allowance = 12
        if isinstance(widget, QLabel):
            if widget.wordWrap() or widget.textFormat() == Qt.TextFormat.RichText:
                continue
            text = widget.text().splitlines()[0] if widget.text() else ""
            allowance = 2
        elif isinstance(widget, QAbstractButton):
            text = widget.text()
            allowance = 20 if widget.isCheckable() else 12
        elif isinstance(widget, QGroupBox):
            text = widget.title()
            allowance = 22
        elif isinstance(widget, QComboBox):
            text = widget.currentText()
            allowance = 30
        if not text:
            continue
        required = max(_text_width(widget, line) for line in text.splitlines()) + allowance
        available = widget.contentsRect().width()
        # One-pixel rounding differences are normal under fractional DPI.
        if required > available + 2:
            issues.append(
                {
                    "state": state,
                    "kind": "text-clipped",
                    "widget": _identity(widget),
                    "text": text[:120],
                    "required": required,
                    "available": available,
                    "severity": "error" if isinstance(widget, QAbstractButton) else "warning",
                }
            )
    return issues


def _scroll_issues(root: QWidget, state: str) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for area in root.findChildren(QScrollArea):
        if not area.isVisibleTo(root):
            continue
        horizontal = area.horizontalScrollBar()
        vertical = area.verticalScrollBar()
        if horizontal.maximum() > 0:
            issues.append(
                {
                    "state": state,
                    "kind": "horizontal-scrollbar",
                    "widget": _identity(area),
                    "maximum": horizontal.maximum(),
                    "severity": "error",
                }
            )
        if vertical.maximum() > 0 and area.objectName() in {
            "pageScrollArea",
            "dialogScrollArea",
            "databasePageScrollArea",
        }:
            issues.append(
                {
                    "state": state,
                    "kind": "page-vertical-scrollbar",
                    "widget": _identity(area),
                    "maximum": vertical.maximum(),
                    "severity": "error",
                }
            )
    return issues


def _audit_state(
    application: QApplication,
    widget: QWidget,
    state: str,
    output: Path,
) -> list[dict[str, object]]:
    _process(application)
    safe = "".join(character if character.isalnum() or character in "-_" else "_" for character in state)
    destination = output / f"{safe}.png"
    if not widget.grab().save(str(destination), "PNG"):
        raise RuntimeError(f"无法写入截图：{destination}")
    return _text_issues(widget, state) + _scroll_issues(widget, state)


def _audit_tabs(
    application: QApplication,
    widget: QWidget,
    prefix: str,
    output: Path,
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    tabs = [tab for tab in widget.findChildren(QTabWidget) if tab.isVisibleTo(widget)]
    if not tabs:
        return _audit_state(application, widget, prefix, output)
    primary = max(tabs, key=lambda tab: tab.width() * tab.height())
    original = primary.currentIndex()
    for index in range(primary.count()):
        primary.setCurrentIndex(index)
        _process(application)
        label = primary.tabText(index).replace("&", "") or str(index)
        issues.extend(_audit_state(application, widget, f"{prefix}-{index:02d}-{label}", output))
    primary.setCurrentIndex(original)
    return issues


def main() -> int:
    output = ARGS.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Every run is a complete snapshot.  Remove only this tool's previous PNG
    # captures so repeated audits report the real number of rendered states
    # instead of treating overwritten filenames as zero new states.
    for previous_capture in output.glob("*.png"):
        previous_capture.unlink()
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    _configure_font(application)
    application.setStyleSheet(STYLE_SHEET)

    launcher = LauncherWindow()
    launcher.show()
    issues = _audit_state(application, launcher, "00-launcher", output)
    if not DEFAULT_ROM.is_file():
        raise RuntimeError(f"默认 ROM 不存在：{DEFAULT_ROM}")
    window = MainWindow(open_default=True)
    if window.project is None:
        raise RuntimeError("无法载入默认 ROM")
    project = window.project
    window.resize(1180, 760)
    window.show()
    issues.extend(_audit_tabs(application, window, "01-main", output))

    factories = (
        ("02-database", lambda: DatabaseDialog(project, window)),
        ("03-scenario", lambda: ScenarioDialog(project, window)),
        ("04-font", lambda: FontLibraryDialog(parent=window, project=project)),
        ("05-animation", lambda: MapAnimationDialog(parent=window, project=project)),
        ("06-text", lambda: TextConverterDialog(parent=window, project=project)),
        ("07-calculator", lambda: AttributeCalculatorDialog(parent=window, project=project)),
        ("08-save", lambda: SaveEditorDialog(parent=window, project=project)),
        ("09-other", lambda: OtherSettingsDialog(parent=window, project=project)),
        ("10-rom-browser", lambda: RomDataBrowserDialog(project, window)),
        ("11-unit-composition", lambda: UnitAppearanceDialog(project, 12, window)),
        ("12-memory", lambda: DatabaseMemoryDialog(project, window)),
        ("13-weapon-rules", lambda: WeaponRuleLibraryDialog(project, window)),
        ("14-guide", lambda: BeginnerGuideDialog(window, has_project=True)),
        ("15-credits", lambda: ProductionCreditsDialog(parent=window, project=project)),
        # Frequently opened nested editors.  These were historically the most
        # likely surfaces to retain fixed pixel sizes after a parent redesign.
        ("20-unit-special", lambda: UnitSpecialEditorDialog(0x10, window)),
        ("21-unit-icon-binding", lambda: UnitIconBindingDialog(project, 0, (0x0F, 0x01, 0x11, 0x21), window)),
        ("22-unit-icon-pixels", lambda: UnitIconDialog(project, 0, 0, (0x0F, 0x01, 0x11, 0x21), window)),
        ("23-chr-tile", lambda: ChrTileEditorDialog((0,) * 64, "编辑图块", window)),
        ("24-spirit-cost", lambda: SpiritCostDialog("热血", 40, window)),
        ("25-dialogue-binding", lambda: DialogueBindingDialog(project, 0, 0, window)),
        ("26-rule-condition", lambda: RuleConditionDialog(project, 0, 0, window)),
        ("27-animation-pointer", lambda: AnimationPointerDialog(window)),
        ("28-animation-command", lambda: WeaponAnimationCommandDialog(window)),
        ("29-animation-palette", lambda: WeaponAnimationCommandPaletteDialog(window)),
        ("30-event-code", lambda: EventCodeDialog(b"\x00", 1, window)),
        ("31-event-parameter", lambda: EventParameterDialog(b"\x00\x01", window, project=project)),
        ("32-event-instruction", lambda: EventInstructionDialog(b"\x00\x01", window, project=project)),
        ("33-growth", lambda: GrowthHexDialog((0,) * 60, window)),
        ("34-damage", lambda: DamageMultiplierDialog(1, 1, window)),
        ("35-defeat-exp", lambda: DefeatExperienceCalculatorDialog(window, project)),
        ("36-palette", lambda: NesPaletteDialog(0, window)),
        # Recursive second/third-level editors evidenced by the reference UI
        # probe.  Keeping these in the same render gate prevents a polished
        # parent page from hiding clipped or untranslated nested workflows.
        ("37-animation-instruction", lambda: AnimationInstructionDialog(
            window,
            instruction=AnimationInstruction(
                0x12345,
                bytes.fromhex("F0 11 03 0F 16 20"),
                "设置动画颜色",
                ((1, 0, 0x3F), (2, 0, 0x3F), (3, 0, 0x3F)),
            ),
            values=(0x11, 0x03, 0x0F),
        )),
        ("38-dialogue-rule", lambda: DialogueRuleDialog(
            project, 0, DialogueRule(0x07, 0x08, 0x00, 0x52), window
        )),
        ("39-dialogue-rule-group", lambda: DialogueRuleGroupDialog(
            project,
            0,
            [
                DialogueRule(0x07, 0x08, 0x00, 0x52),
                DialogueRule(0x09, 0x0A, 0x00, 0x53),
                DialogueRule(0x00, 0xFF, 0x00, 0x51),
            ],
            window,
        )),
        ("40-transform-dialogue", lambda: TransformDialogueDialog(
            project, TransformDialogueBinding(6, 0, 0x10, 0), window
        )),
        ("41-chapter-title", lambda: ChapterTitleDialog(project, 0, window)),
        ("42-tile-attribute", lambda: TileAttributeDialog(
            project, "D", tuple(window.map_page.canvas.tile_images), window
        )),
        ("43-fragment-placement", lambda: FragmentPlacementDialog(
            FragmentTile(0x10, 40, 64), window
        )),
        ("44-weapon-movement", lambda: WeaponMovementSimulatorDialog(
            bytes.fromhex("01 02 FF"), bytes.fromhex("01 01 FF"), window
        )),
    )
    audited_states = 1
    for prefix, factory in factories:
        dialog = factory()
        dialog.show()
        _process(application)
        before = len(list(output.glob("*.png")))
        issues.extend(_audit_tabs(application, dialog, prefix, output))
        audited_states += len(list(output.glob("*.png"))) - before
        dialog.reject()
        dialog.deleteLater()
        _process(application)

    # Stateful right-click surfaces are separate native popup windows and are
    # therefore invisible in ordinary parent grabs.  Render both disabled and
    # enabled paste states for every reference record menu.
    database = DatabaseDialog(project, window)
    database.show()
    _process(application)
    menu_specs = (
        (
            "50-context-unit-disabled",
            lambda: database.unit_page._create_unit_context_menu()[0],
        ),
        (
            "51-context-character-disabled",
            lambda: database._build_reference_record_menu(
                database.character_page,
                copy_label="复制人物",
                paste_label="粘贴人物",
                export_label="导出人物",
            )[0],
        ),
        (
            "52-context-weapon-disabled",
            lambda: database._build_reference_record_menu(
                database.weapon_page,
                copy_label="复制武器",
                paste_label="粘贴武器",
            )[0],
        ),
    )
    for prefix, menu_factory in menu_specs:
        menu = menu_factory()
        menu.show()
        _process(application)
        issues.extend(_audit_state(application, menu, prefix, output))
        audited_states += 1
        menu.close()
        menu.deleteLater()
    database.unit_page.controller._copied_record_id = 1
    database.character_page._copied_record_id = 1
    database.weapon_page._copied_record_id = 1
    enabled_specs = (
        ("53-context-unit-enabled", lambda: database.unit_page._create_unit_context_menu()[0]),
        (
            "54-context-character-enabled",
            lambda: database._build_reference_record_menu(
                database.character_page,
                copy_label="复制人物",
                paste_label="粘贴人物",
                export_label="导出人物",
            )[0],
        ),
        (
            "55-context-weapon-enabled",
            lambda: database._build_reference_record_menu(
                database.weapon_page,
                copy_label="复制武器",
                paste_label="粘贴武器",
            )[0],
        ),
    )
    for prefix, menu_factory in enabled_specs:
        menu = menu_factory()
        menu.show()
        _process(application)
        issues.extend(_audit_state(application, menu, prefix, output))
        audited_states += 1
        menu.close()
        menu.deleteLater()
    database.reject()
    database.deleteLater()
    _process(application)

    window._saved_snapshot = bytes(project.working)
    window.close()
    launcher.close()
    errors = [issue for issue in issues if issue["severity"] == "error"]
    warnings = [issue for issue in issues if issue["severity"] == "warning"]
    report = {
        "scale": ARGS.scale,
        "audited_states": audited_states,
        "errors": errors,
        "warnings": warnings,
        "passed": not errors,
    }
    (output / "audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"scale": ARGS.scale, "states": audited_states, "errors": len(errors), "warnings": len(warnings)}, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
