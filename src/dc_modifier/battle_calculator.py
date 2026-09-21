from __future__ import annotations

from dataclasses import dataclass


REFERENCE_FIREPOWER_BONUS = 8
DEFAULT_DISTANCE_HIT_CORRECTIONS = (
    (100,) * 16,
    tuple(range(100, 68, -2)),
    tuple(range(100, 20, -5)),
    (100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 9, 8, 7, 6, 5, 4),
)


@dataclass(frozen=True)
class BattleFormulaParameters:
    double_attack_percent: int
    double_defense_percent: int
    double_bonus: int
    strength_multiplier: int
    weapon_multiplier: int
    strength_divisor: int
    defense_multiplier: int
    defense_divisor: int
    hit_threshold: int
    distance_hit_corrections: tuple[tuple[int, ...], ...]

    @classmethod
    def from_project(cls, project) -> BattleFormulaParameters:
        if project is None:
            double_values = (70, 90, 20)
            damage_values = (13, 10, 10, 1, 1)
            hit_threshold = 70
            distance_rows = DEFAULT_DISTANCE_HIT_CORRECTIONS
        else:
            double_values = project.get_double_hit_values()
            damage_values = project.get_damage_formula_values()
            hit_threshold = project.get_hit_threshold()
            distance_rows = project.get_distance_hit_corrections()
        strength_multiplier, weapon_multiplier, strength_divisor, defense_multiplier, defense_divisor = damage_values
        if strength_divisor <= 0 or defense_divisor <= 0:
            raise ValueError("伤害公式除数必须大于 0。")
        if double_values[0] <= 0:
            raise ValueError("双击攻方百分比必须大于 0。")
        return cls(
            *double_values,
            strength_multiplier,
            weapon_multiplier,
            strength_divisor,
            defense_multiplier,
            defense_divisor,
            hit_threshold,
            tuple(tuple(row) for row in distance_rows),
        )


@dataclass(frozen=True)
class BattleSideState:
    strength: int
    defense: int
    speed: int
    hp: int
    weapon_hit: int
    weapon_range: int
    power_air: int
    power_land: int
    power_sea: int
    terrain: int = 1
    special: int = 0
    distance_table: int = 0
    damage_numerator: int = 1
    damage_denominator: int = 1


@dataclass(frozen=True)
class DefensiveEffect:
    name: str
    numerator: int
    denominator: int


@dataclass(frozen=True)
class BattleAttackResult:
    hit_score: int
    hit_threshold: int
    can_hit: bool
    minimum_hit_speed: int
    can_double: bool
    minimum_double_speed: int
    terrain_name: str
    firepower: int
    predicted_damage: int
    actual_damage: int
    remaining_hp: int
    hits_to_defeat: int
    defensive_effect: DefensiveEffect | None
    distance_percent: int


DEFENSIVE_EFFECTS = {
    1: DefensiveEffect("T防御系统", 3, 4),
    2: DefensiveEffect("相对转移装甲", 3, 4),
    4: DefensiveEffect("VPS防御系统", 2, 3),
    5: DefensiveEffect("能量偏移装置", 2, 3),
    6: DefensiveEffect("盾防", 1, 2),
}


def reference_firepower(raw_power: int, weapon_multiplier: int) -> int:
    """Return the value shown by the reference calculator.

    The archived C08 capture shows raw 36/33/30 as 368/338/308 when the
    project weapon multiplier is 10.  The fixed +8 is the reference tool's
    prediction value; the runtime game still uses its own battle state.
    """

    return max(0, raw_power) * max(0, weapon_multiplier) + REFERENCE_FIREPOWER_BONUS


def _ceil_div(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("除数必须大于 0。")
    return -(-numerator // denominator)


def _distance_percent(
    parameters: BattleFormulaParameters, state: BattleSideState
) -> int:
    rows = parameters.distance_hit_corrections
    if not rows:
        return 100
    row_index = max(0, min(len(rows) - 1, state.distance_table))
    row = rows[row_index]
    if not row:
        return 100
    distance_index = max(0, min(len(row) - 1, state.weapon_range - 1))
    return max(0, row[distance_index])


def _terrain_firepower(state: BattleSideState, target_terrain: int) -> tuple[str, int]:
    terrain = target_terrain & 0x03
    if terrain == 0:
        return "空", state.power_air
    if terrain == 2:
        return "海", state.power_sea
    if terrain == 3:
        return "保留地形3（按陆）", state.power_land
    return "陆", state.power_land


def normalized_special_code(raw_special: int) -> int:
    """Normalize the two encodings found in DC-family unit tables.

    Most records store the reference calculator's small code directly.  Some
    expanded records store that code in units of eight.  Preserve combined or
    otherwise unknown bit patterns instead of inventing an effect for them.
    """

    if raw_special >= 8 and raw_special % 8 == 0:
        shifted = raw_special // 8
        if shifted in DEFENSIVE_EFFECTS:
            return shifted
    return raw_special


def defensive_effect(raw_special: int) -> DefensiveEffect | None:
    return DEFENSIVE_EFFECTS.get(normalized_special_code(raw_special))


def calculate_battle_attack(
    attacker: BattleSideState,
    defender: BattleSideState,
    parameters: BattleFormulaParameters,
) -> BattleAttackResult:
    distance_percent = _distance_percent(parameters, attacker)
    base_hit = max(0, attacker.weapon_hit + attacker.speed - defender.speed)
    hit_score = base_hit * distance_percent // 100
    can_hit = hit_score >= parameters.hit_threshold
    if distance_percent:
        required_base_hit = _ceil_div(parameters.hit_threshold * 100, distance_percent)
        minimum_hit_speed = max(
            0, required_base_hit + defender.speed - attacker.weapon_hit
        )
    else:
        minimum_hit_speed = 99999

    defense_double_value = (
        defender.speed * parameters.double_defense_percent // 100
        + parameters.double_bonus
    )
    attacker_double_value = (
        attacker.speed * parameters.double_attack_percent // 100
    )
    can_double = attacker_double_value > defense_double_value
    minimum_double_speed = _ceil_div(
        (defense_double_value + 1) * 100,
        parameters.double_attack_percent,
    )

    terrain_name, firepower = _terrain_firepower(attacker, defender.terrain)
    strength_component = (
        attacker.strength * parameters.strength_multiplier
        // parameters.strength_divisor
    )
    defense_component = (
        defender.defense * parameters.defense_multiplier
        // parameters.defense_divisor
    )
    damage_denominator = max(1, attacker.damage_denominator)
    predicted_damage = max(
        0,
        (strength_component + firepower - defense_component)
        * max(0, attacker.damage_numerator)
        // damage_denominator,
    )
    effect = defensive_effect(defender.special)
    actual_damage = predicted_damage
    if effect is not None:
        actual_damage = (
            predicted_damage * effect.numerator // effect.denominator
        )
    remaining_hp = max(0, defender.hp - actual_damage)
    hits_to_defeat = (
        _ceil_div(defender.hp, actual_damage) if actual_damage > 0 else 99999
    )
    return BattleAttackResult(
        hit_score=hit_score,
        hit_threshold=parameters.hit_threshold,
        can_hit=can_hit,
        minimum_hit_speed=minimum_hit_speed,
        can_double=can_double,
        minimum_double_speed=minimum_double_speed,
        terrain_name=terrain_name,
        firepower=firepower,
        predicted_damage=predicted_damage,
        actual_damage=actual_damage,
        remaining_hp=remaining_hp,
        hits_to_defeat=hits_to_defeat,
        defensive_effect=effect,
        distance_percent=distance_percent,
    )
