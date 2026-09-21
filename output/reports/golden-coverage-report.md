# 黄金对照覆盖率报告（M00 / G1·G2）

- 数据源：`output/build/legacy-diff-audit/golden/index.json`、`tools/golden_pipeline/cases/field_registry.json`
- 归一化剔除：6 个偏移（参考版保存时 C9 02→D8 47 副作用，NEG-8）

## 汇总指标

| 指标 | 数值 | 目标 |
| --- | --- | --- |
| G1 黄金对照覆盖率 | 211/216 = 97.69% | >=95% |
| G2 逐字段差分通过率 | 212/212 = 100.00% | =100% |

> G1 分母口径 `denominator_scope=registered_fields`：当前分母为 field_registry.json 登记字段数；最终口径为参考版全部可编辑字段数（主文档第 4/5 章字段清单，M00 第 5 节统计职责），全量采集完成后需以全量字段数重算分母

## 用例计数

| 类别 | 数量 |
| --- | --- |
| 注册字段（登记用例） | 216 |
| 已归档字段 | 216 |
| golden 用例 | 212 |
| discovery 用例 | 7 |
| 通过 golden 用例 | 212 |
| 未通过 golden 用例 | 0 |
| 待解释用例 | 7 |

## 待解释用例清单

| 模块 | 字段 | 用例 | 类型 | 原因 |
| --- | --- | --- | --- | --- |
| M06 | character_add_overflow | cold_start_01 | discovery | 在线单字段采集：保存后关闭进程，再以不同 PID 冷启动重开 |
| M06 | character_add_overflow | cold_start_02 | discovery | 在线单字段采集：保存后关闭进程，再以不同 PID 冷启动重开 |
| M09 | experience_level_2 | write | discovery | 发现型用例：存量 expected_offset=0（写入偏移未知）且重开读取值不等于请求值，需在线采集补证 |
| M09 | experience_level_60 | write | discovery | 发现型用例：存量 expected_offset=0（写入偏移未知）且重开读取值不等于请求值，需在线采集补证 |
| M09 | level_cap | write | discovery | 发现型用例：等级上限 60→61 触发成长曲线等联动重写（3778 处偏移），无单一预期偏移集，待在线采集拆解（D5 决策） |
| M12 | sprite_anchor_x | cold_start_07 | discovery | 在线单字段采集：保存后关闭进程，再以不同 PID 冷启动重开 |
| M12 | sprite_code_first_tile | cold_start_01 | discovery | 在线单字段采集：保存后关闭进程，再以不同 PID 冷启动重开 |

## 逐字段明细

| 模块 | 字段 | 类型 | passed | 变化偏移 | 剔除归一化 | 未知偏移 | 档案 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M05 | body_bank_1 | golden | true | 1585 | 0 | 0 | M05-body_bank_1-cold_start_01.json |
| M05 | body_bank_2 | golden | true | 1706 | 0 | 0 | M05-body_bank_2-cold_start_01.json |
| M05 | body_color_1 | golden | true | 1585 | 0 | 0 | M05-body_color_1-cold_start_01.json |
| M05 | body_color_2 | golden | true | 1585 | 0 | 0 | M05-body_color_2-cold_start_01.json |
| M05 | body_color_3 | golden | true | 1585 | 0 | 0 | M05-body_color_3-cold_start_01.json |
| M05 | captain | golden | true | 1706 | 0 | 0 | M05-captain-cold_start_01.json |
| M05 | defense | golden | true | 1 | 0 | 0 | M05-defense-cold_start_01.json |
| M05 | defense_growth | golden | true | 1 | 0 | 0 | M05-defense_growth-cold_start_01.json |
| M05 | experience | golden | true | 1 | 0 | 0 | M05-experience-cold_start_01.json |
| M05 | fragment_bank | golden | true | 1585 | 0 | 0 | M05-fragment_bank-cold_start_01.json |
| M05 | fragment_color_1 | golden | true | 1585 | 0 | 0 | M05-fragment_color_1-cold_start_01.json |
| M05 | fragment_color_2 | golden | true | 1585 | 0 | 0 | M05-fragment_color_2-cold_start_01.json |
| M05 | fragment_color_3 | golden | true | 1585 | 0 | 0 | M05-fragment_color_3-cold_start_01.json |
| M05 | hp | golden | true | 1 | 0 | 0 | M05-hp-cold_start_01.json |
| M05 | hp_growth | golden | true | 1 | 0 | 0 | M05-hp_growth-cold_start_01.json |
| M05 | money | golden | true | 1 | 0 | 0 | M05-money-cold_start_01.json |
| M05 | movement | golden | true | 1 | 0 | 0 | M05-movement-cold_start_01.json |
| M05 | name | golden | true | 3897 | 2 | 0 | M05-name-cold_start_01.json |
| M05 | special_skill_base | golden | true | 1 | 0 | 0 | M05-special_skill_base-cold_start_01.json |
| M05 | special_skill_dimension | golden | true | 1 | 0 | 0 | M05-special_skill_dimension-cold_start_01.json |
| M05 | special_skill_first_strike | golden | true | 1 | 0 | 0 | M05-special_skill_first_strike-cold_start_01.json |
| M05 | special_skill_hit_and_away | golden | true | 1 | 0 | 0 | M05-special_skill_hit_and_away-cold_start_01.json |
| M05 | special_skill_reflect | golden | true | 1 | 0 | 0 | M05-special_skill_reflect-cold_start_01.json |
| M05 | special_skill_twist | golden | true | 1 | 0 | 0 | M05-special_skill_twist-cold_start_01.json |
| M05 | speed | golden | true | 1 | 0 | 0 | M05-speed-cold_start_01.json |
| M05 | speed_growth | golden | true | 1 | 0 | 0 | M05-speed_growth-cold_start_01.json |
| M05 | strength | golden | true | 1 | 0 | 0 | M05-strength-cold_start_01.json |
| M05 | strength_growth | golden | true | 1 | 0 | 0 | M05-strength_growth-cold_start_01.json |
| M05 | terrain | golden | true | 1 | 0 | 0 | M05-terrain-cold_start_01.json |
| M05 | transform | golden | true | 1 | 0 | 0 | M05-transform-cold_start_01.json |
| M05 | unit_type | golden | true | 14066 | 0 | 0 | M05-unit_type-cold_start_01.json |
| M05 | weapon_1 | golden | true | 1 | 0 | 0 | M05-weapon_1-cold_start_01.json |
| M05 | weapon_2 | golden | true | 1 | 0 | 0 | M05-weapon_2-cold_start_01.json |
| M06 | ally_music | golden | true | 1 | 0 | 0 | M06-ally_music-cold_start_01.json |
| M06 | battle_name | golden | true | 3922 | 2 | 0 | M06-battle_name-cold_start_01.json |
| M06 | character_add_overflow | discovery | - | 16479 | 4 | 16475 | M06-character_add_overflow-cold_start_01.json |
| M06 | character_add_overflow | discovery | - | 16479 | 4 | 16475 | M06-character_add_overflow-cold_start_02.json |
| M06 | defeat_persist | golden | true | 12155 | 4 | 0 | M06-defeat_persist-cold_start_01.json |
| M06 | defense_bonus | golden | true | 12155 | 4 | 0 | M06-defense_bonus-cold_start_01.json |
| M06 | dialogue_attack_blocked_number | golden | true | 1864 | 0 | 0 | M06-dialogue_attack_blocked_number-cold_start_01.json |
| M06 | dialogue_attack_blocked_segment | golden | true | 1864 | 0 | 0 | M06-dialogue_attack_blocked_segment-cold_start_01.json |
| M06 | dialogue_attack_hit_number | golden | true | 1864 | 0 | 0 | M06-dialogue_attack_hit_number-cold_start_01.json |
| M06 | dialogue_attack_hit_segment | golden | true | 1864 | 0 | 0 | M06-dialogue_attack_hit_segment-cold_start_01.json |
| M06 | dialogue_defense_destroyed_number | golden | true | 1864 | 0 | 0 | M06-dialogue_defense_destroyed_number-cold_start_01.json |
| M06 | dialogue_defense_destroyed_segment | golden | true | 1864 | 0 | 0 | M06-dialogue_defense_destroyed_segment-cold_start_01.json |
| M06 | dialogue_defense_heavy_damage_number | golden | true | 1864 | 0 | 0 | M06-dialogue_defense_heavy_damage_number-cold_start_01.json |
| M06 | dialogue_defense_heavy_damage_segment | golden | true | 1864 | 0 | 0 | M06-dialogue_defense_heavy_damage_segment-cold_start_01.json |
| M06 | dialogue_defense_light_damage_number | golden | true | 1864 | 0 | 0 | M06-dialogue_defense_light_damage_number-cold_start_01.json |
| M06 | dialogue_defense_light_damage_segment | golden | true | 1864 | 0 | 0 | M06-dialogue_defense_light_damage_segment-cold_start_01.json |
| M06 | dialogue_defense_medium_damage_number | golden | true | 1864 | 0 | 0 | M06-dialogue_defense_medium_damage_number-cold_start_01.json |
| M06 | dialogue_defense_medium_damage_segment | golden | true | 1864 | 0 | 0 | M06-dialogue_defense_medium_damage_segment-cold_start_01.json |
| M06 | dialogue_defense_no_damage_number | golden | true | 1864 | 0 | 0 | M06-dialogue_defense_no_damage_number-cold_start_01.json |
| M06 | dialogue_defense_no_damage_segment | golden | true | 1864 | 0 | 0 | M06-dialogue_defense_no_damage_segment-cold_start_01.json |
| M06 | dialogue_defense_success_number | golden | true | 1864 | 0 | 0 | M06-dialogue_defense_success_number-cold_start_01.json |
| M06 | dialogue_defense_success_segment | golden | true | 1864 | 0 | 0 | M06-dialogue_defense_success_segment-cold_start_01.json |
| M06 | dialogue_special_attack_1_end | golden | true | 1864 | 0 | 0 | M06-dialogue_special_attack_1_end-cold_start_01.json |
| M06 | dialogue_special_attack_1_number | golden | true | 1864 | 0 | 0 | M06-dialogue_special_attack_1_number-cold_start_01.json |
| M06 | dialogue_special_attack_1_segment | golden | true | 1864 | 0 | 0 | M06-dialogue_special_attack_1_segment-cold_start_01.json |
| M06 | dialogue_special_attack_1_start | golden | true | 1864 | 0 | 0 | M06-dialogue_special_attack_1_start-cold_start_01.json |
| M06 | dialogue_special_attack_2_end | golden | true | 1864 | 0 | 0 | M06-dialogue_special_attack_2_end-cold_start_01.json |
| M06 | dialogue_special_attack_2_number | golden | true | 1864 | 0 | 0 | M06-dialogue_special_attack_2_number-cold_start_01.json |
| M06 | dialogue_special_attack_2_segment | golden | true | 1864 | 0 | 0 | M06-dialogue_special_attack_2_segment-cold_start_01.json |
| M06 | dialogue_special_attack_2_start | golden | true | 1864 | 0 | 0 | M06-dialogue_special_attack_2_start-cold_start_01.json |
| M06 | dialogue_special_attack_3_end | golden | true | 1864 | 0 | 0 | M06-dialogue_special_attack_3_end-cold_start_01.json |
| M06 | dialogue_special_attack_3_number | golden | true | 1864 | 0 | 0 | M06-dialogue_special_attack_3_number-cold_start_01.json |
| M06 | dialogue_special_attack_3_segment | golden | true | 1864 | 0 | 0 | M06-dialogue_special_attack_3_segment-cold_start_01.json |
| M06 | dialogue_special_attack_3_start | golden | true | 1864 | 0 | 0 | M06-dialogue_special_attack_3_start-cold_start_01.json |
| M06 | enemy_music | golden | true | 1 | 0 | 0 | M06-enemy_music-cold_start_01.json |
| M06 | growth_curve | golden | true | 10188 | 4 | 0 | M06-growth_curve-cold_start_01.json |
| M06 | growth_fixed | golden | true | 10188 | 4 | 0 | M06-growth_fixed-cold_start_01.json |
| M06 | hp_bonus | golden | true | 12155 | 4 | 0 | M06-hp_bonus-cold_start_01.json |
| M06 | mobility_bonus | golden | true | 12155 | 4 | 0 | M06-mobility_bonus-cold_start_01.json |
| M06 | name | golden | true | 3923 | 2 | 0 | M06-name-cold_start_01.json |
| M06 | portrait_back_bank | golden | true | 1 | 0 | 0 | M06-portrait_back_bank-cold_start_01.json |
| M06 | portrait_back_slot | golden | true | 1 | 0 | 0 | M06-portrait_back_slot-cold_start_01.json |
| M06 | portrait_back_upload | golden | true | 74 | 0 | 0 | M06-portrait_back_upload-cold_start_01.json |
| M06 | portrait_color_1 | golden | true | 1 | 0 | 0 | M06-portrait_color_1-cold_start_01.json |
| M06 | portrait_color_2 | golden | true | 1 | 0 | 0 | M06-portrait_color_2-cold_start_01.json |
| M06 | portrait_color_3 | golden | true | 1 | 0 | 0 | M06-portrait_color_3-cold_start_01.json |
| M06 | portrait_front_bank | golden | true | 2 | 0 | 0 | M06-portrait_front_bank-cold_start_01.json |
| M06 | portrait_front_slot | golden | true | 1 | 0 | 0 | M06-portrait_front_slot-cold_start_01.json |
| M06 | portrait_front_upload | golden | true | 223 | 0 | 0 | M06-portrait_front_upload-cold_start_01.json |
| M06 | sp | golden | true | 10188 | 4 | 0 | M06-sp-cold_start_01.json |
| M06 | speed_bonus | golden | true | 12155 | 4 | 0 | M06-speed_bonus-cold_start_01.json |
| M06 | spirit_01 | golden | true | 10188 | 4 | 0 | M06-spirit_01-cold_start_01.json |
| M06 | spirit_02 | golden | true | 10188 | 4 | 0 | M06-spirit_02-cold_start_01.json |
| M06 | spirit_03 | golden | true | 10188 | 4 | 0 | M06-spirit_03-cold_start_01.json |
| M06 | spirit_04 | golden | true | 10188 | 4 | 0 | M06-spirit_04-cold_start_01.json |
| M06 | spirit_05 | golden | true | 10188 | 4 | 0 | M06-spirit_05-cold_start_01.json |
| M06 | spirit_06 | golden | true | 10188 | 4 | 0 | M06-spirit_06-cold_start_01.json |
| M06 | spirit_07 | golden | true | 10188 | 4 | 0 | M06-spirit_07-cold_start_01.json |
| M06 | spirit_08 | golden | true | 10188 | 4 | 0 | M06-spirit_08-cold_start_01.json |
| M06 | spirit_09 | golden | true | 10188 | 4 | 0 | M06-spirit_09-cold_start_01.json |
| M06 | spirit_10 | golden | true | 10188 | 4 | 0 | M06-spirit_10-cold_start_01.json |
| M06 | spirit_11 | golden | true | 10188 | 4 | 0 | M06-spirit_11-cold_start_01.json |
| M06 | spirit_12 | golden | true | 10188 | 4 | 0 | M06-spirit_12-cold_start_01.json |
| M06 | spirit_13 | golden | true | 10188 | 4 | 0 | M06-spirit_13-cold_start_01.json |
| M06 | spirit_14 | golden | true | 10188 | 4 | 0 | M06-spirit_14-cold_start_01.json |
| M06 | spirit_15 | golden | true | 10188 | 4 | 0 | M06-spirit_15-cold_start_01.json |
| M06 | spirit_16 | golden | true | 10188 | 4 | 0 | M06-spirit_16-cold_start_01.json |
| M06 | spirit_17 | golden | true | 10188 | 4 | 0 | M06-spirit_17-cold_start_01.json |
| M06 | spirit_18 | golden | true | 10188 | 4 | 0 | M06-spirit_18-cold_start_01.json |
| M06 | spirit_19 | golden | true | 10188 | 4 | 0 | M06-spirit_19-cold_start_01.json |
| M06 | spirit_20 | golden | true | 10188 | 4 | 0 | M06-spirit_20-cold_start_01.json |
| M06 | spirit_21 | golden | true | 10188 | 4 | 0 | M06-spirit_21-cold_start_01.json |
| M06 | spirit_22 | golden | true | 10188 | 4 | 0 | M06-spirit_22-cold_start_01.json |
| M06 | spirit_23 | golden | true | 10188 | 4 | 0 | M06-spirit_23-cold_start_01.json |
| M06 | spirit_24 | golden | true | 10188 | 4 | 0 | M06-spirit_24-cold_start_01.json |
| M06 | spirit_cost_01 | golden | true | 1 | 0 | 0 | M06-spirit_cost_01-cold_start_01.json |
| M06 | spirit_cost_02 | golden | true | 1 | 0 | 0 | M06-spirit_cost_02-cold_start_01.json |
| M06 | spirit_cost_03 | golden | true | 1 | 0 | 0 | M06-spirit_cost_03-cold_start_01.json |
| M06 | spirit_cost_04 | golden | true | 1 | 0 | 0 | M06-spirit_cost_04-cold_start_01.json |
| M06 | spirit_cost_05 | golden | true | 1 | 0 | 0 | M06-spirit_cost_05-cold_start_01.json |
| M06 | spirit_cost_06 | golden | true | 1 | 0 | 0 | M06-spirit_cost_06-cold_start_01.json |
| M06 | spirit_cost_07 | golden | true | 1 | 0 | 0 | M06-spirit_cost_07-cold_start_01.json |
| M06 | spirit_cost_08 | golden | true | 1 | 0 | 0 | M06-spirit_cost_08-cold_start_01.json |
| M06 | spirit_cost_09 | golden | true | 1 | 0 | 0 | M06-spirit_cost_09-cold_start_01.json |
| M06 | spirit_cost_10 | golden | true | 1 | 0 | 0 | M06-spirit_cost_10-cold_start_01.json |
| M06 | spirit_cost_11 | golden | true | 1 | 0 | 0 | M06-spirit_cost_11-cold_start_01.json |
| M06 | spirit_cost_12 | golden | true | 1 | 0 | 0 | M06-spirit_cost_12-cold_start_01.json |
| M06 | spirit_cost_13 | golden | true | 1 | 0 | 0 | M06-spirit_cost_13-cold_start_01.json |
| M06 | spirit_cost_14 | golden | true | 1 | 0 | 0 | M06-spirit_cost_14-cold_start_01.json |
| M06 | spirit_cost_15 | golden | true | 1 | 0 | 0 | M06-spirit_cost_15-cold_start_01.json |
| M06 | spirit_cost_16 | golden | true | 1 | 0 | 0 | M06-spirit_cost_16-cold_start_01.json |
| M06 | spirit_cost_17 | golden | true | 1 | 0 | 0 | M06-spirit_cost_17-cold_start_01.json |
| M06 | spirit_cost_18 | golden | true | 1 | 0 | 0 | M06-spirit_cost_18-cold_start_01.json |
| M06 | spirit_cost_19 | golden | true | 1 | 0 | 0 | M06-spirit_cost_19-cold_start_01.json |
| M06 | spirit_cost_20 | golden | true | 1 | 0 | 0 | M06-spirit_cost_20-cold_start_01.json |
| M06 | spirit_cost_21 | golden | true | 1 | 0 | 0 | M06-spirit_cost_21-cold_start_01.json |
| M06 | spirit_cost_22 | golden | true | 1 | 0 | 0 | M06-spirit_cost_22-cold_start_01.json |
| M06 | spirit_cost_23 | golden | true | 1 | 0 | 0 | M06-spirit_cost_23-cold_start_01.json |
| M06 | spirit_cost_24 | golden | true | 1 | 0 | 0 | M06-spirit_cost_24-cold_start_01.json |
| M06 | strength_bonus | golden | true | 12155 | 4 | 0 | M06-strength_bonus-cold_start_01.json |
| M06 | transform_dialogue_2_end | golden | true | 1 | 0 | 0 | M06-transform_dialogue_2_end-cold_start_01.json |
| M06 | transform_dialogue_2_number | golden | true | 1 | 0 | 0 | M06-transform_dialogue_2_number-cold_start_01.json |
| M06 | transform_dialogue_2_start | golden | true | 1 | 0 | 0 | M06-transform_dialogue_2_start-cold_start_01.json |
| M06 | transform_dialogue_add | golden | true | 429 | 0 | 0 | M06-transform_dialogue_add-cold_start_01.json |
| M06 | transform_dialogue_clear | golden | true | 435 | 0 | 0 | M06-transform_dialogue_clear-cold_start_01.json |
| M06 | transform_dialogue_end | golden | true | 1 | 0 | 0 | M06-transform_dialogue_end-cold_start_01.json |
| M06 | transform_dialogue_number | golden | true | 1 | 0 | 0 | M06-transform_dialogue_number-cold_start_01.json |
| M06 | transform_dialogue_start | golden | true | 1 | 0 | 0 | M06-transform_dialogue_start-cold_start_01.json |
| M07 | distance_correction | golden | true | 1 | 0 | 0 | M07-distance_correction-cold_start_01.json |
| M07 | hit | golden | true | 1 | 0 | 0 | M07-hit-cold_start_01.json |
| M07 | max_range | golden | true | 1 | 0 | 0 | M07-max_range-cold_start_01.json |
| M07 | name_token | golden | true | 2487 | 2 | 0 | M07-name_token-cold_start_01.json |
| M07 | power_air | golden | true | 1 | 0 | 0 | M07-power_air-cold_start_01.json |
| M07 | power_land | golden | true | 1 | 0 | 0 | M07-power_land-cold_start_01.json |
| M07 | power_sea | golden | true | 1 | 0 | 0 | M07-power_sea-cold_start_01.json |
| M07 | weapon_skill | golden | true | 1 | 0 | 0 | M07-weapon_skill-cold_start_01.json |
| M08 | battle_00_row000_variant000 | golden | true | 1 | 0 | 0 | M08-battle_00_row000_variant000-cold_start_01.json |
| M08 | battle_01_row000_variant000 | golden | true | 2 | 0 | 0 | M08-battle_01_row000_variant000-cold_start_01.json |
| M08 | battle_04_row000_variant001 | golden | true | 10866 | 0 | 0 | M08-battle_04_row000_variant001-cold_start_01.json |
| M08 | battle_05_row001_variant000 | golden | true | 2 | 0 | 0 | M08-battle_05_row001_variant000-cold_start_01.json |
| M08 | battle_07_alias_row000_variant000 | golden | true | 2 | 0 | 0 | M08-battle_07_alias_row000_variant000-cold_start_01.json |
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
| M12 | sprite_anchor_x | discovery | - | 0 | 0 | 0 | M12-sprite_anchor_x-cold_start_07.json |
| M12 | sprite_code_first_tile | discovery | - | 7 | 0 | 6 | M12-sprite_code_first_tile-cold_start_01.json |
| M12 | sprite_code_first_tile | golden | true | 7 | 0 | 0 | M12-sprite_code_first_tile-cold_start_02.json |
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
