from __future__ import annotations

import unittest
from dataclasses import replace

from dc_modifier.battle_calculator import (
    BattleFormulaParameters,
    BattleSideState,
    calculate_battle_attack,
    defensive_effect,
    normalized_special_code,
    reference_firepower,
)


class BattleCalculatorFormulaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parameters = BattleFormulaParameters.from_project(None)

    def test_reference_firepower_matches_archived_c08_values(self) -> None:
        self.assertEqual(reference_firepower(36, 10), 368)
        self.assertEqual(reference_firepower(33, 10), 338)
        self.assertEqual(reference_firepower(30, 10), 308)

    def test_hit_distance_terrain_damage_and_defense_effect_are_composed(self) -> None:
        attacker = BattleSideState(
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
        defender = BattleSideState(
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

        result = calculate_battle_attack(attacker, defender, self.parameters)

        self.assertEqual(result.distance_percent, 90)
        self.assertEqual(result.hit_score, 72)
        self.assertTrue(result.can_hit)
        self.assertEqual(result.minimum_hit_speed, 98)
        self.assertEqual((result.terrain_name, result.firepower), ("海", 200))
        self.assertEqual(result.predicted_damage, 500)
        self.assertEqual(result.actual_damage, 250)
        self.assertEqual(result.remaining_hp, 750)
        self.assertEqual(result.hits_to_defeat, 4)
        self.assertEqual(result.defensive_effect.name, "盾防")

    def test_double_hit_uses_strict_greater_than_and_exact_flooring(self) -> None:
        defender = BattleSideState(0, 0, 100, 1, 0, 1, 0, 0, 0)
        boundary = BattleSideState(0, 0, 158, 1, 0, 1, 0, 0, 0)
        passing = BattleSideState(0, 0, 159, 1, 0, 1, 0, 0, 0)

        at_boundary = calculate_battle_attack(boundary, defender, self.parameters)
        over_boundary = calculate_battle_attack(passing, defender, self.parameters)

        self.assertEqual(at_boundary.minimum_double_speed, 159)
        self.assertFalse(at_boundary.can_double)
        self.assertTrue(over_boundary.can_double)

    def test_zero_distance_correction_is_an_explicit_unreachable_boundary(self) -> None:
        parameters = replace(
            self.parameters,
            distance_hit_corrections=((0,) * 16,) * 4,
        )
        attacker = BattleSideState(0, 0, 255, 1, 255, 1, 0, 0, 0)
        defender = BattleSideState(0, 0, 0, 1, 0, 1, 0, 0, 0)

        result = calculate_battle_attack(attacker, defender, parameters)

        self.assertFalse(result.can_hit)
        self.assertEqual(result.minimum_hit_speed, 99999)

    def test_expanded_special_codes_are_normalized_without_guessing_combinations(self) -> None:
        self.assertEqual(normalized_special_code(16), 2)
        self.assertEqual(defensive_effect(16).name, "相对转移装甲")
        self.assertEqual(normalized_special_code(135), 135)
        self.assertIsNone(defensive_effect(135))


if __name__ == "__main__":
    unittest.main()
