# M14 参考版逐字段保存覆盖

- 状态：`complete`
- 已完成：3217/3217；剩余 0
- 安全持久化候选：2674；当前已证实 2674
- 排除：参考运行时易失字段 543
- 已枚举但无字段编辑入口的事件/指令行：9920
- 最终冷进程目录字段：3217
- 已采集字段族：action_name=256；chapter_initial_victory=32；chapter_title=32；map_name=255；story_text=2295；surrender_ally=32；surrender_chapter=32；surrender_enemy=32；victory_text=251

| 检查 | 结果 |
|---|---|
| `catalog_passed` | 通过 |
| `all_3217_fields_recorded` | 通过 |
| `sequences_contiguous` | 通过 |
| `catalog_identities_match` | 通过 |
| `hash_links_contiguous` | 通过 |
| `byte_ranges_replay` | 通过 |
| `tail_matches_work_rom` | 通过 |
| `requested_value_observed_before_each_save` | 通过 |
| `persistent_and_volatile_family_classification_matches` | 通过 |
| `two_fresh_final_inventories_match` | 通过 |

未完成时本报告保持 collecting，不以部分链冒充全量覆盖。
