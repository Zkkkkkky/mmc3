# M14 参考版直接字段目录

- 直接可编辑字段：3217
- 只读指令解释行：9920
- 状态：`reference_direct_fields_cataloged_save_evidence_pending`

| 字段族 | 数量 |
|---|---:|
| `chapter_title` | 32 |
| `chapter_initial_victory` | 32 |
| `action_name` | 256 |
| `surrender_chapter` | 32 |
| `surrender_ally` | 32 |
| `surrender_enemy` | 32 |
| `map_name` | 255 |
| `story_text` | 2295 |
| `victory_text` | 251 |

关卡三阶段、行动、劝降和地图四类大列表中的 9,920 条非空指令均为解释视图；六类代表行双击不产生编辑窗口。直接字段目录仅包含页面上的 Edit/ComboBox，并等待逐字段保存/冷读分类。
