# 黄金对照覆盖率报告（M00 / G1·G2）

- 数据源：`output/build/legacy-diff-audit/golden/index.json`、`tools/golden_pipeline/cases/field_registry.json`
- 归一化剔除：6 个偏移（参考版保存时 C9 02→D8 47 副作用，NEG-8）

## 汇总指标

| 指标 | 数值 | 目标 |
| --- | --- | --- |
| G1 黄金对照覆盖率 | 58/61 = 95.08% | >=95% |
| G2 逐字段差分通过率 | 59/59 = 100.00% | =100% |

> G1 分母口径 `denominator_scope=registered_fields`：当前分母为 field_registry.json 登记字段数；最终口径为参考版全部可编辑字段数（主文档第 4/5 章字段清单，M00 第 5 节统计职责），全量采集完成后需以全量字段数重算分母

## 用例计数

| 类别 | 数量 |
| --- | --- |
| 注册字段（登记用例） | 61 |
| 已归档字段 | 61 |
| golden 用例 | 59 |
| discovery 用例 | 3 |
| 通过 golden 用例 | 59 |
| 未通过 golden 用例 | 0 |
| 待解释用例 | 3 |

## 待解释用例清单

| 模块 | 字段 | 用例 | 类型 | 原因 |
| --- | --- | --- | --- | --- |
| M09 | experience_level_2 | write | discovery | 发现型用例：存量 expected_offset=0（写入偏移未知）且重开读取值不等于请求值，需在线采集补证 |
| M09 | experience_level_60 | write | discovery | 发现型用例：存量 expected_offset=0（写入偏移未知）且重开读取值不等于请求值，需在线采集补证 |
| M09 | level_cap | write | discovery | 发现型用例：等级上限 60→61 触发成长曲线等联动重写（3778 处偏移），无单一预期偏移集，待在线采集拆解（D5 决策） |

## 逐字段明细

| 模块 | 字段 | 类型 | passed | 变化偏移 | 剔除归一化 | 未知偏移 | 档案 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M09 | distance_first | golden | true | 7 | 6 | 0 | M09-distance_first-write.json |
| M09 | distance_last | golden | true | 7 | 6 | 0 | M09-distance_last-write.json |
| M09 | experience_level_2 | discovery | - | 6 | 6 | 0 | M09-experience_level_2-write.json |
| M09 | experience_level_60 | discovery | - | 6 | 6 | 0 | M09-experience_level_60-write.json |
| M09 | level_cap | discovery | - | 3778 | 6 | 3772 | M09-level_cap-write.json |
| M10 | item_price_01 | golden | true | 7 | 6 | 0 | M10-item_price_01-write.json |
| M10 | item_price_02 | golden | true | 7 | 6 | 0 | M10-item_price_02-write.json |
| M10 | item_price_03 | golden | true | 7 | 6 | 0 | M10-item_price_03-write.json |
| M10 | item_price_04 | golden | true | 7 | 6 | 0 | M10-item_price_04-write.json |
| M10 | item_price_05 | golden | true | 7 | 6 | 0 | M10-item_price_05-write.json |
| M10 | item_price_06 | golden | true | 7 | 6 | 0 | M10-item_price_06-write.json |
| M10 | item_price_07 | golden | true | 7 | 6 | 0 | M10-item_price_07-write.json |
| M10 | item_price_08 | golden | true | 7 | 6 | 0 | M10-item_price_08-write.json |
| M10 | item_price_09 | golden | true | 7 | 6 | 0 | M10-item_price_09-write.json |
| M10 | item_price_10 | golden | true | 7 | 6 | 0 | M10-item_price_10-write.json |
| M10 | item_price_11 | golden | true | 7 | 6 | 0 | M10-item_price_11-write.json |
| M10 | item_price_12 | golden | true | 7 | 6 | 0 | M10-item_price_12-write.json |
| M10 | item_price_13 | golden | true | 7 | 6 | 0 | M10-item_price_13-write.json |
| M10 | item_price_14 | golden | true | 7 | 6 | 0 | M10-item_price_14-write.json |
| M10 | item_price_15 | golden | true | 7 | 6 | 0 | M10-item_price_15-write.json |
| M10 | item_price_16 | golden | true | 7 | 6 | 0 | M10-item_price_16-write.json |
| M10 | item_price_17 | golden | true | 7 | 6 | 0 | M10-item_price_17-write.json |
| M10 | item_price_18 | golden | true | 7 | 6 | 0 | M10-item_price_18-write.json |
| M10 | item_price_19 | golden | true | 7 | 6 | 0 | M10-item_price_19-write.json |
| M10 | item_price_20 | golden | true | 7 | 6 | 0 | M10-item_price_20-write.json |
| M10 | item_price_21 | golden | true | 7 | 6 | 0 | M10-item_price_21-write.json |
| M10 | item_price_22 | golden | true | 7 | 6 | 0 | M10-item_price_22-write.json |
| M10 | item_price_23 | golden | true | 7 | 6 | 0 | M10-item_price_23-write.json |
| M10 | item_price_24 | golden | true | 7 | 6 | 0 | M10-item_price_24-write.json |
| M17 | damage_defense_divisor | golden | true | 7 | 6 | 0 | M17-damage_defense_divisor-write.json |
| M17 | damage_defense_multiplier | golden | true | 7 | 6 | 0 | M17-damage_defense_multiplier-write.json |
| M17 | damage_strength_divisor | golden | true | 7 | 6 | 0 | M17-damage_strength_divisor-write.json |
| M17 | damage_strength_multiplier | golden | true | 7 | 6 | 0 | M17-damage_strength_multiplier-write.json |
| M17 | damage_weapon_multiplier | golden | true | 7 | 6 | 0 | M17-damage_weapon_multiplier-write.json |
| M17 | double_hit_attack_percent | golden | true | 9 | 6 | 0 | M17-double_hit_attack_percent-write.json |
| M17 | double_hit_bonus | golden | true | 9 | 6 | 0 | M17-double_hit_bonus-write.json |
| M17 | double_hit_defense_percent | golden | true | 9 | 6 | 0 | M17-double_hit_defense_percent-write.json |
| M17 | hit_threshold | golden | true | 7 | 6 | 0 | M17-hit_threshold-cold_start_03.json |
| M17 | hit_threshold | golden | true | 7 | 6 | 0 | M17-hit_threshold-write.json |
| M17 | item_01 | golden | true | 7 | 6 | 0 | M17-item_01-write.json |
| M17 | item_02 | golden | true | 7 | 6 | 0 | M17-item_02-write.json |
| M17 | item_03 | golden | true | 7 | 6 | 0 | M17-item_03-write.json |
| M17 | item_04 | golden | true | 7 | 6 | 0 | M17-item_04-write.json |
| M17 | item_05 | golden | true | 7 | 6 | 0 | M17-item_05-write.json |
| M17 | item_06 | golden | true | 7 | 6 | 0 | M17-item_06-write.json |
| M17 | item_07 | golden | true | 7 | 6 | 0 | M17-item_07-write.json |
| M17 | item_08 | golden | true | 7 | 6 | 0 | M17-item_08-write.json |
| M17 | item_09 | golden | true | 7 | 6 | 0 | M17-item_09-write.json |
| M17 | item_10 | golden | true | 7 | 6 | 0 | M17-item_10-write.json |
| M17 | item_11 | golden | true | 7 | 6 | 0 | M17-item_11-write.json |
| M17 | slot_1_character | golden | true | 7 | 6 | 0 | M17-slot_1_character-write.json |
| M17 | slot_1_unit | golden | true | 7 | 6 | 0 | M17-slot_1_unit-write.json |
| M17 | slot_2_character | golden | true | 7 | 6 | 0 | M17-slot_2_character-write.json |
| M17 | slot_2_unit | golden | true | 7 | 6 | 0 | M17-slot_2_unit-write.json |
| M17 | slot_3_character | golden | true | 7 | 6 | 0 | M17-slot_3_character-write.json |
| M17 | slot_3_unit | golden | true | 7 | 6 | 0 | M17-slot_3_unit-write.json |
| M17 | slot_4_character | golden | true | 7 | 6 | 0 | M17-slot_4_character-write.json |
| M17 | slot_4_unit | golden | true | 7 | 6 | 0 | M17-slot_4_unit-write.json |
| M17 | slot_5_character | golden | true | 7 | 6 | 0 | M17-slot_5_character-write.json |
| M17 | slot_5_unit | golden | true | 7 | 6 | 0 | M17-slot_5_unit-write.json |
| M17 | slot_6_character | golden | true | 7 | 6 | 0 | M17-slot_6_character-write.json |
| M17 | slot_6_unit | golden | true | 7 | 6 | 0 | M17-slot_6_unit-write.json |
