from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from dc_modifier.battle_calculator import (  # noqa: E402
    BattleFormulaParameters,
    BattleSideState,
    calculate_battle_attack,
    defensive_effect,
    normalized_special_code,
    reference_firepower,
)
from dc_modifier.legacy_tools import AttributeCalculatorDialog  # noqa: E402
from fc_rom_editor_core import RomProject  # noqa: E402


DEFAULT_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
DEFAULT_REPORT = ROOT / "output" / "verification" / "m15-attribute-calculator.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _combo_values(combo) -> tuple[int, ...]:
    return tuple(int(combo.itemData(index) or 0) for index in range(combo.count()))


def _result_payload(result) -> dict[str, object]:
    return {
        "hit_score": result.hit_score,
        "hit_threshold": result.hit_threshold,
        "can_hit": result.can_hit,
        "minimum_hit_speed": result.minimum_hit_speed,
        "can_double": result.can_double,
        "minimum_double_speed": result.minimum_double_speed,
        "terrain_name": result.terrain_name,
        "firepower": result.firepower,
        "predicted_damage": result.predicted_damage,
        "actual_damage": result.actual_damage,
        "remaining_hp": result.remaining_hp,
        "hits_to_defeat": result.hits_to_defeat,
        "defensive_effect": (
            result.defensive_effect.name if result.defensive_effect is not None else None
        ),
        "distance_percent": result.distance_percent,
    }


def analyze(rom_path: Path) -> dict[str, object]:
    data = rom_path.read_bytes()
    project = RomProject.load(rom_path)
    application = QApplication.instance() or QApplication([])
    application.processEvents()
    dialog = AttributeCalculatorDialog(project=project)
    try:
        initial_working = bytes(project.working)
        formula = BattleFormulaParameters.from_project(project)
        default_side = dialog.enemy
        default_ui = {
            "window_title": dialog.windowTitle(),
            "character_count": default_side.character.count(),
            "unit_count": default_side.unit.count(),
            "level_count": default_side.level.count(),
            "character_id": int(default_side.character.currentData()),
            "unit_id": int(default_side.unit.currentData()),
            "weapon_ids": list(_combo_values(default_side.weapon)),
            "weapon_id": int(default_side.weapon.currentData()),
            "strength": default_side.strength.value(),
            "defense": default_side.defense.value(),
            "speed": default_side.speed.value(),
            "hp": default_side.hp.value(),
            "weapon_hit": default_side.weapon_hit.value(),
            "weapon_range": default_side.weapon_range.value(),
            "power_air": default_side.power_air.value(),
            "power_land": default_side.power_land.value(),
            "power_sea": default_side.power_sea.value(),
            "special": default_side.skill.value(),
        }

        unit_two = default_side.unit.findData(2)
        unit_nine = default_side.unit.findData(9)
        default_side.unit.setCurrentIndex(unit_two)
        unit_two_weapons = list(_combo_values(default_side.weapon))
        default_side.unit.setCurrentIndex(unit_nine)
        unit_nine_weapons = list(_combo_values(default_side.weapon))

        level_values: dict[str, dict[str, int]] = {}
        for level in (1, 30, 60):
            default_side.level.setCurrentIndex(level - 1)
            level_values[str(level)] = {
                "strength": default_side.strength.value(),
                "defense": default_side.defense.value(),
                "speed": default_side.speed.value(),
                "hp": default_side.hp.value(),
            }
        default_side.level.setCurrentIndex(0)

        dialog.calculate()
        default_result = dialog.last_results["我方"]
        result_lines = [
            dialog.results.item(row).text() for row in range(dialog.results.count())
        ]
        calculation_preserved_rom = bytes(project.working) == initial_working

        dialog.enemy.multiplier_edit.setText("2/1")
        dialog.calculate()
        doubled_damage = dialog.last_results["敌方"].predicted_damage
        dialog.enemy.multiplier_edit.setText("1/0")
        dialog.enemy.state()
        invalid_multiplier_fallback = dialog.enemy.multiplier_edit.text()
        dialog.enemy.multiplier_edit.setText("1/1")
        dialog.enemy.state()

        raw_land_power = dialog.enemy._raw_weapon_powers[1]
        changed_formula = list(project.get_damage_formula_values())
        changed_formula[1] += 1
        project.set_damage_formula_values(changed_formula)
        after_formula_change = bytes(project.working)
        dialog.calculate()
        live_firepower = dialog.enemy.power_land.value()
        calculation_preserved_changed_rom = bytes(project.working) == after_formula_change
        undo_description = project.undo()
        undo_restored = bytes(project.working) == initial_working

        buttons = [button.text() for button in dialog.findChildren(QPushButton)]
        buttons_are_disabled = all(
            not side.change_multiplier_button.isEnabled()
            and "参考版此功能损坏" in side.change_multiplier_button.toolTip()
            for side in (dialog.enemy, dialog.ally)
        )

        boundary_attacker = BattleSideState(
            strength=100,
            defense=40,
            speed=101,
            hp=500,
            weapon_hit=40,
            weapon_range=3,
            power_air=300,
            power_land=250,
            power_sea=200,
            distance_table=2,
            damage_numerator=2,
            damage_denominator=1,
        )
        boundary_defender = BattleSideState(
            strength=50,
            defense=80,
            speed=60,
            hp=1000,
            weapon_hit=0,
            weapon_range=1,
            power_air=0,
            power_land=0,
            power_sea=0,
            terrain=2,
            special=6,
        )
        composed_result = calculate_battle_attack(
            boundary_attacker, boundary_defender, BattleFormulaParameters.from_project(None)
        )
        strict_boundary = calculate_battle_attack(
            BattleSideState(0, 0, 158, 1, 0, 1, 0, 0, 0),
            BattleSideState(0, 0, 100, 1, 0, 1, 0, 0, 0),
            BattleFormulaParameters.from_project(None),
        )
        strict_passing = calculate_battle_attack(
            BattleSideState(0, 0, 159, 1, 0, 1, 0, 0, 0),
            BattleSideState(0, 0, 100, 1, 0, 1, 0, 0, 0),
            BattleFormulaParameters.from_project(None),
        )

        checks = {
            "reference_window_structure": (
                default_ui["window_title"] == "战斗属性计算器"
                and default_ui["character_count"] == 200
                and default_ui["unit_count"] == 255
                and default_ui["level_count"] == 60
                and buttons.count("开始计算") == 1
                and "确定" not in buttons
                and "取消" not in buttons
            ),
            "unit_weapon_binding": unit_two_weapons == [0] and unit_nine_weapons == [7, 11],
            "default_record_values": default_ui
            == {
                "window_title": "战斗属性计算器",
                "character_count": 200,
                "unit_count": 255,
                "level_count": 60,
                "character_id": 4,
                "unit_id": 9,
                "weapon_ids": [7, 11],
                "weapon_id": 7,
                "strength": 98,
                "defense": 42,
                "speed": 86,
                "hp": 140,
                "weapon_hit": 110,
                "weapon_range": 1,
                "power_air": 58,
                "power_land": 58,
                "power_sea": 58,
                "special": 2,
            },
            "level_growth_is_bounded": (
                len(level_values) == 3
                and all(
                    values["strength"] <= 255
                    and values["defense"] <= 255
                    and values["speed"] <= 255
                    and values["hp"] <= 9999
                    for values in level_values.values()
                )
            ),
            "default_calculation_matches_reference_values": _result_payload(default_result)
            == {
                "hit_score": 110,
                "hit_threshold": 70,
                "can_hit": True,
                "minimum_hit_speed": 46,
                "can_double": False,
                "minimum_double_speed": 140,
                "terrain_name": "空",
                "firepower": 58,
                "predicted_damage": 143,
                "actual_damage": 107,
                "remaining_hp": 33,
                "hits_to_defeat": 2,
                "defensive_effect": "相对转移装甲",
                "distance_percent": 100,
            },
            "result_list_is_two_way": (
                len(result_lines) == 18
                and result_lines[0].startswith("--------我方计算")
                and any(line.startswith("--------敌方计算") for line in result_lines)
            ),
            "calculator_never_writes_rom": (
                calculation_preserved_rom and calculation_preserved_changed_rom
            ),
            "damage_multiplier_and_invalid_input": (
                doubled_damage == 286 and invalid_multiplier_fallback == "2/1"
            ),
            "m17_live_parameter_link_and_undo": (
                live_firepower == raw_land_power * changed_formula[1] + 8
                and undo_description == "伤害公式"
                and undo_restored
            ),
            "broken_multiplier_buttons_are_safe": buttons_are_disabled,
            "archived_firepower_examples": (
                reference_firepower(36, 10) == 368
                and reference_firepower(33, 10) == 338
                and reference_firepower(30, 10) == 308
            ),
            "distance_terrain_damage_and_defense_compose": _result_payload(composed_result)
            == {
                "hit_score": 72,
                "hit_threshold": 70,
                "can_hit": True,
                "minimum_hit_speed": 98,
                "can_double": False,
                "minimum_double_speed": 108,
                "terrain_name": "海",
                "firepower": 200,
                "predicted_damage": 500,
                "actual_damage": 250,
                "remaining_hp": 750,
                "hits_to_defeat": 4,
                "defensive_effect": "盾防",
                "distance_percent": 90,
            },
            "double_hit_is_strictly_greater": (
                strict_boundary.minimum_double_speed == 159
                and not strict_boundary.can_double
                and strict_passing.can_double
            ),
            "expanded_special_codes_are_conservative": (
                normalized_special_code(16) == 2
                and defensive_effect(16) is not None
                and normalized_special_code(135) == 135
                and defensive_effect(135) is None
            ),
        }

        return {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "passed": all(checks.values()),
            "delivery_status": "implementation_complete_reference_and_user_pending",
            "conclusion": (
                "M15 机体/人物/武器/等级联动、完整命中/双击/伤害公式、"
                "M17 实时参数和 D6 禁用按钮均通过实现侧门禁；"
                "参考 EXE 逐行动态黄金与用户签收仍待完成。"
            ),
            "rom": {
                "path": rom_path.resolve().relative_to(ROOT).as_posix(),
                "size": len(data),
                "sha256": _sha256(data),
            },
            "formula_parameters": {
                "double_hit": [
                    formula.double_attack_percent,
                    formula.double_defense_percent,
                    formula.double_bonus,
                ],
                "damage": list(project.get_damage_formula_values()),
                "hit_threshold": formula.hit_threshold,
            },
            "ui": {
                "default": default_ui,
                "unit_02_weapon_ids": unit_two_weapons,
                "unit_09_weapon_ids": unit_nine_weapons,
                "visible_button_texts": buttons,
                "level_values": level_values,
            },
            "calculation": {
                "default": _result_payload(default_result),
                "result_lines": result_lines,
                "doubled_damage": doubled_damage,
                "invalid_multiplier_fallback": invalid_multiplier_fallback,
                "live_weapon_multiplier": changed_formula[1],
                "live_land_firepower": live_firepower,
            },
            "checks": checks,
            "pending_acceptance": [
                "在可与提权参考 EXE 同完整性交互的 Windows 会话中补采结果列表逐行动态黄金。",
                "由用户按 docs/M15验收清单.md 执行正式 EXE 现场验收并明确签收。",
            ],
        }
    finally:
        dialog.close()
        application.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser(description="复验 M15 属性计算器联动、公式与零 ROM 写入。")
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    arguments = parser.parse_args()
    report = analyze(arguments.rom)
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
