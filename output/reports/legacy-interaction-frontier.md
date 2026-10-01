# 旧修改器递归交互探索前沿

- 输入窗口快照：1375
- 菜单快照：7
- 实跑交互发现文件：19
- 因状态验证不足被拒绝的发现文件：11
- 待探索动作总数：3376
- 状态：passed=3376
- 探索闭合：是

> 该表是递归探索队列，不是完成证明。只有动作具有执行证据、条件状态已触发且不再产生新窗口/新动作，分母才可闭合。

## 动作类型

| 动作 | 数量 |
|---|---:|
| `activate` | 14 |
| `activate_context_command` | 55 |
| `boundary_values` | 234 |
| `decrement` | 66 |
| `discover_state_triggers` | 538 |
| `double_click_each_item` | 43 |
| `double_click_grid` | 1 |
| `double_click_regions` | 23 |
| `drag_grid` | 1 |
| `drag_regions` | 23 |
| `drag_thumb` | 13 |
| `focus` | 168 |
| `increment` | 66 |
| `keyboard_activate` | 321 |
| `keyboard_cycle` | 107 |
| `keyboard_navigation` | 43 |
| `keyboard_shortcuts` | 168 |
| `keyboard_tab_cycle` | 11 |
| `left_click` | 321 |
| `left_click_grid` | 1 |
| `left_click_regions` | 23 |
| `line_step` | 13 |
| `open_dropdown` | 107 |
| `page_step` | 13 |
| `replace_value` | 168 |
| `right_click` | 596 |
| `right_click_each_item` | 43 |
| `right_click_grid` | 1 |
| `right_click_regions` | 23 |
| `right_click_tabs` | 11 |
| `select_each_item` | 150 |
| `select_each_tab` | 11 |

## 控件类型

| 控件类 | 动作数 |
|---|---:|
| `Afx:400000:b:10003:900015:0` | 130 |
| `Button` | 1099 |
| `CPageControl` | 40 |
| `ComboBox` | 468 |
| `ContextMenuItem` | 55 |
| `CtrlNotifySink` | 12 |
| `DirectUIHWND` | 2 |
| `Edit` | 928 |
| `ListBox` | 180 |
| `MenuItem` | 14 |
| `NamespaceTreeControl` | 2 |
| `SHELLDLL_DefView` | 2 |
| `ScrollBar` | 47 |
| `SoPY_Status` | 1 |
| `SysHeader32` | 4 |
| `SysListView32` | 28 |
| `SysTreeView32` | 2 |
| `WTWindow` | 4 |
| `_EL_DrawPanel` | 5 |
| `_EL_Label` | 14 |
| `_EL_PicBox` | 109 |
| `msctls_updown32` | 230 |

## 待执行动作（前 500 项）

| ID | 窗口 | 控件 | 文本 | 动作 | 状态 |
|---|---|---|---|---|---|
| `849e1685ccb3ef674961` |  | `SoPY_Status#0` |  | `discover_state_triggers` | passed |
| `32b6e908f8104717d853` | SRW2修改器V1.5 | `Button#110` | 进入修改器 | `keyboard_activate` | passed |
| `2d3fa29c7a826cc038b8` | SRW2修改器V1.5 | `Button#110` | 进入修改器 | `left_click` | passed |
| `c01d62fbeff633d4b295` | SRW2修改器V1.5 | `Button#110` | 进入修改器 | `right_click` | passed |
| `11850958b0f1a30535ee` | SRW2修改器V1.5 | `Button#120` | 第二次机器人大战资料集 | `keyboard_activate` | passed |
| `37adf4c56e0619061ebf` | SRW2修改器V1.5 | `Button#120` | 第二次机器人大战资料集 | `left_click` | passed |
| `19cc2d8d3327b8c31bc7` | SRW2修改器V1.5 | `Button#120` | 第二次机器人大战资料集 | `right_click` | passed |
| `7c881bcf8ca633f04f6e` | SRW2修改器V1.5 | `Button#140` | 第二次机器人大战百度贴吧 | `keyboard_activate` | passed |
| `c228e619ef6c0cef7ae7` | SRW2修改器V1.5 | `Button#140` | 第二次机器人大战百度贴吧 | `left_click` | passed |
| `eb69acb23055bef4dd96` | SRW2修改器V1.5 | `Button#140` | 第二次机器人大战百度贴吧 | `right_click` | passed |
| `cc72776a5f46058be78a` | SRW2修改器V1.5 | `Button#150` | 第二次机器人大战公共网盘 | `keyboard_activate` | passed |
| `ab45529f33ba34782b16` | SRW2修改器V1.5 | `Button#150` | 第二次机器人大战公共网盘 | `left_click` | passed |
| `c12b10c87ccf4c7718b8` | SRW2修改器V1.5 | `Button#150` | 第二次机器人大战公共网盘 | `right_click` | passed |
| `3509178e707156946dfd` | SRW2修改器V1.5 | `Button#160` | 修改器更新查看  (百度网盘：提取码6553) | `keyboard_activate` | passed |
| `e8ed6c0270853cdfdcd2` | SRW2修改器V1.5 | `Button#160` | 修改器更新查看  (百度网盘：提取码6553) | `left_click` | passed |
| `d258676c26b05128271e` | SRW2修改器V1.5 | `Button#160` | 修改器更新查看  (百度网盘：提取码6553) | `right_click` | passed |
| `2e66d1240a700b0cf885` | SRW2扩容版修改器V1.0：<ROM> | `Afx:400000:b:10003:900015:0#130` |  | `discover_state_triggers` | passed |
| `16fd8931472b74790aaa` | SRW2扩容版修改器V1.0：<ROM> | `Afx:400000:b:10003:900015:0#150` |  | `discover_state_triggers` | passed |
| `6fcb8c8870458ae07906` | SRW2扩容版修改器V1.0：<ROM> | `Afx:400000:b:10003:900015:0#170` |  | `discover_state_triggers` | passed |
| `b6c233527897e8e89cd9` | SRW2扩容版修改器V1.0：<ROM> | `Afx:400000:b:10003:900015:0#400` | 位图选择： | `discover_state_triggers` | passed |
| `b01e970406e5165c003e` | SRW2扩容版修改器V1.0：<ROM> | `Afx:400000:b:10003:900015:0#410` | 左键 | `discover_state_triggers` | passed |
| `b1ac760968038e241bb9` | SRW2扩容版修改器V1.0：<ROM> | `Afx:400000:b:10003:900015:0#420` | 右键 | `discover_state_triggers` | passed |
| `10a06d4e2eca11f3fefd` | SRW2扩容版修改器V1.0：<ROM> | `Afx:400000:b:10003:900015:0#450` | 地图宽度： | `discover_state_triggers` | passed |
| `cad755d9bd2e3a89dab4` | SRW2扩容版修改器V1.0：<ROM> | `Afx:400000:b:10003:900015:0#470` | 地图高度： | `discover_state_triggers` | passed |
| `e07f7e6fe45ee1847536` | SRW2扩容版修改器V1.0：<ROM> | `Afx:400000:b:10003:900015:0#610` | 图标地址1： | `discover_state_triggers` | passed |
| `5cee1fbcae4a6fd172f2` | SRW2扩容版修改器V1.0：<ROM> | `Afx:400000:b:10003:900015:0#620` | 图标地址2： | `discover_state_triggers` | passed |
| `53b6c362b5fa10dfd758` | SRW2扩容版修改器V1.0：<ROM> | `Afx:400000:b:10003:900015:0#630` | 图标地址3： | `discover_state_triggers` | passed |
| `829df67e817ef589ee81` | SRW2扩容版修改器V1.0：<ROM> | `Afx:400000:b:10003:900015:0#670` | 图库选择： | `discover_state_triggers` | passed |
| `9dac26e39887c7a48305` | SRW2扩容版修改器V1.0：<ROM> | `Button#110` | 关卡选择 | `keyboard_activate` | passed |
| `72106bc764b5097cdd18` | SRW2扩容版修改器V1.0：<ROM> | `Button#110` | 关卡选择 | `left_click` | passed |
| `67ca2bb52082205d4590` | SRW2扩容版修改器V1.0：<ROM> | `Button#110` | 关卡选择 | `right_click` | passed |
| `7c63073724b440e8b224` | SRW2扩容版修改器V1.0：<ROM> | `Button#200` | 机体图标 | `discover_state_triggers` | passed |
| `34735c44688e9b9d30a1` | SRW2扩容版修改器V1.0：<ROM> | `Button#200` | 机体图标 | `keyboard_activate` | passed |
| `daf8e32ecf5a554c8415` | SRW2扩容版修改器V1.0：<ROM> | `Button#200` | 机体图标 | `left_click` | passed |
| `4ba222aa8467d913372a` | SRW2扩容版修改器V1.0：<ROM> | `Button#200` | 机体图标 | `right_click` | passed |
| `905871f2fb2286127c7e` | SRW2扩容版修改器V1.0：<ROM> | `Button#430` | 地图图块设置 | `discover_state_triggers` | passed |
| `5cc83b2aa56d63707039` | SRW2扩容版修改器V1.0：<ROM> | `Button#430` | 地图图块设置 | `keyboard_activate` | passed |
| `e1f262f283d12cdc7a9b` | SRW2扩容版修改器V1.0：<ROM> | `Button#430` | 地图图块设置 | `left_click` | passed |
| `e2bc4afc9268ba784bf0` | SRW2扩容版修改器V1.0：<ROM> | `Button#430` | 地图图块设置 | `right_click` | passed |
| `e5276199363269ede7c7` | SRW2扩容版修改器V1.0：<ROM> | `Button#660` | 编辑图块属性 | `discover_state_triggers` | passed |
| `64d88e477d309cb8f223` | SRW2扩容版修改器V1.0：<ROM> | `Button#660` | 编辑图块属性 | `keyboard_activate` | passed |
| `b2a12aa49195f9bbd50f` | SRW2扩容版修改器V1.0：<ROM> | `Button#660` | 编辑图块属性 | `left_click` | passed |
| `c9d65df0137648348374` | SRW2扩容版修改器V1.0：<ROM> | `Button#660` | 编辑图块属性 | `right_click` | passed |
| `a1fe256f16d6f0d8f9f9` | SRW2扩容版修改器V1.0：<ROM> | `CPageControl#120` |  | `keyboard_tab_cycle` | passed |
| `99196faa52ea4ab51fcd` | SRW2扩容版修改器V1.0：<ROM> | `CPageControl#120` |  | `right_click_tabs` | passed |
| `61713053c678b86b6302` | SRW2扩容版修改器V1.0：<ROM> | `CPageControl#120` |  | `select_each_tab` | passed |
| `397eb15870bcfd2b8ad3` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#140` | [34]052：8D010 | `discover_state_triggers` | passed |
| `a0f40bbc0708aab4cf09` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#140` | [34]052：8D010 | `keyboard_cycle` | passed |
| `23dc248c7cabf6ac1b84` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#140` | [34]052：8D010 | `open_dropdown` | passed |
| `22ddb029819edfac0394` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#140` | [34]052：8D010 | `right_click` | passed |
| `ad89c9b55cb027b42796` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#140` | [34]052：8D010 | `select_each_item` | passed |
| `282500ee7fa060cac1cc` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#160` | [35]053：8D410 | `discover_state_triggers` | passed |
| `9392cdf022a40ed7d936` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#160` | [35]053：8D410 | `keyboard_cycle` | passed |
| `9960724d5cf8e10cdcdf` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#160` | [35]053：8D410 | `open_dropdown` | passed |
| `44e2ba2c29a73aae8e64` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#160` | [35]053：8D410 | `right_click` | passed |
| `1cfeb43b95041bcb1f16` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#160` | [35]053：8D410 | `select_each_item` | passed |
| `b0bf7a7a53002d96aeb5` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#180` | [36]054：8D810 / [3A]058：8E810 / [3E]062：8F810 | `discover_state_triggers` | passed |
| `0ecdba0868d201410ea6` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#180` | [3E]062：8F810 | `keyboard_cycle` | passed |
| `7ac4dc924157017847cd` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#180` | [3E]062：8F810 | `open_dropdown` | passed |
| `4f16ec3ebbd304990ea1` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#180` | [3E]062：8F810 | `right_click` | passed |
| `cef2c76e5dd1e49d5357` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#180` | [3E]062：8F810 | `select_each_item` | passed |
| `7635ba7e953a3512fd3c` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#210` | 位图B / 位图C / 位图D | `discover_state_triggers` | passed |
| `f54a50b789bc5078fdc4` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#210` | 位图C | `keyboard_cycle` | passed |
| `7cd022e586dfab74b77e` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#210` | 位图C | `open_dropdown` | passed |
| `c915290fdcf4d266d4f7` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#210` | 位图C | `right_click` | passed |
| `6f7d72adefab85b0cc44` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#210` | 位图C | `select_each_item` | passed |
| `2f4ee0d746764cf833eb` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#680` | [05]005：81410 / [06]006：81810 / [3D]061：8F410 | `discover_state_triggers` | passed |
| `1fe67c47958c5500da94` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#680` | [06]006：81810 | `keyboard_cycle` | passed |
| `6ee125edb1d2644fa81b` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#680` | [06]006：81810 | `open_dropdown` | passed |
| `fad1db384a9c81f4ca3b` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#680` | [06]006：81810 | `right_click` | passed |
| `fe0c1ff643f5b2581beb` | SRW2扩容版修改器V1.0：<ROM> | `ComboBox#680` | [06]006：81810 | `select_each_item` | passed |
| `ba822dd63ef63ad93905` | SRW2扩容版修改器V1.0：<ROM> | `Edit#440` | 23 / 25 / 27 | `discover_state_triggers` | passed |
| `d6a23ffdb13c69b1e63f` | SRW2扩容版修改器V1.0：<ROM> | `Edit#460` | 21 / 25 / 26 | `discover_state_triggers` | passed |
| `bcd82bd0f95067f94d7f` | SRW2扩容版修改器V1.0：<ROM> | `ListBox#100` |  | `double_click_each_item` | passed |
| `3b9642bec9e3046772a6` | SRW2扩容版修改器V1.0：<ROM> | `ListBox#100` |  | `keyboard_navigation` | passed |
| `3aa5c3b234a9920161cc` | SRW2扩容版修改器V1.0：<ROM> | `ListBox#100` |  | `right_click_each_item` | passed |
| `465b5ce2086587aa78d3` | SRW2扩容版修改器V1.0：<ROM> | `ListBox#100` |  | `select_each_item` | passed |
| `e8e00091e168148f104a` | SRW2扩容版修改器V1.0：<ROM> | `ListBox#550` |  | `discover_state_triggers` | passed |
| `153689117bc495e6735c` | SRW2扩容版修改器V1.0：<ROM> | `ListBox#550` |  | `double_click_each_item` | passed |
| `5ee18804408e3d312374` | SRW2扩容版修改器V1.0：<ROM> | `ListBox#550` |  | `keyboard_navigation` | passed |
| `091bded36e8c4805ef97` | SRW2扩容版修改器V1.0：<ROM> | `ListBox#550` |  | `right_click_each_item` | passed |
| `99c60317b080a4fe81f6` | SRW2扩容版修改器V1.0：<ROM> | `ListBox#550` |  | `select_each_item` | passed |
| `ac1139d7770b8540d4cf` | SRW2扩容版修改器V1.0：<ROM> | `WTWindow#0` | SRW2扩容版修改器V1.0：C:\Users\hu\Desktop\新DC上\新DC上原始文件.nes / SRW2扩容版修改器V1.0：D:\GIT\mmc3\output\build\legacy-diff-audit\probe-m05-special\after.nes / SRW2扩容版修改器V1.0：D:\GIT\mmc3\output\build\legacy-ui-probe\calculator-controls.nes | `discover_state_triggers` | passed |
| `bd3cd9ffc9d91dbfe4d0` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#220` |  | `discover_state_triggers` | passed |
| `8760c6dadd8b645f658b` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#220` |  | `double_click_regions` | passed |
| `d751bd4d10edb1eb081b` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#220` |  | `drag_regions` | passed |
| `fa0b1243709c63108840` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#220` |  | `left_click_regions` | passed |
| `1327d47b33e7bd7948dc` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#220` |  | `right_click_regions` | passed |
| `7acb8c28bfd3d1f45adf` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#230` |  | `discover_state_triggers` | passed |
| `8ed745c778d80b166e9d` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#230` |  | `double_click_regions` | passed |
| `74b5527106b5a27e320a` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#230` |  | `drag_regions` | passed |
| `e9d8b9ad7a1d89bf36ed` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#230` |  | `left_click_regions` | passed |
| `75296ed22919b94f9238` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#230` |  | `right_click_regions` | passed |
| `5b46855a93816a224de8` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#240` |  | `discover_state_triggers` | passed |
| `00f5eda9ee6ea819a90b` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#240` |  | `double_click_regions` | passed |
| `bdaf03ba45553990a58f` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#240` |  | `drag_regions` | passed |
| `c6a81b39794cfca71e51` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#240` |  | `left_click_regions` | passed |
| `59f07bebd8b9149d3992` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#240` |  | `right_click_regions` | passed |
| `19a83fabed09d6191bc2` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#250` |  | `discover_state_triggers` | passed |
| `72c5bdff75ef8b458a3e` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#250` |  | `double_click_regions` | passed |
| `3d7fe44e4998d1430506` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#250` |  | `drag_regions` | passed |
| `e2b8550e41012819e578` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#250` |  | `left_click_regions` | passed |
| `6b60a2b07edef4ed54c7` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#250` |  | `right_click_regions` | passed |
| `fbe5bdf6fe83a63b1ae0` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#260` |  | `discover_state_triggers` | passed |
| `8ffaf09a5663fd48ca5c` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#260` |  | `double_click_regions` | passed |
| `5191d4dab2e4b36ab59d` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#260` |  | `drag_regions` | passed |
| `40174fe6ec6db3329b9f` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#260` |  | `left_click_regions` | passed |
| `bde925b2711548c80cf3` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#260` |  | `right_click_regions` | passed |
| `091c084ed0aec9acddd6` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#270` |  | `discover_state_triggers` | passed |
| `c7af200c010454e55c8e` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#270` |  | `double_click_regions` | passed |
| `71792365ea95247ddad4` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#270` |  | `drag_regions` | passed |
| `81bc295ed2895ac2bc10` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#270` |  | `left_click_regions` | passed |
| `774ab4e0104701671d9d` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#270` |  | `right_click_regions` | passed |
| `0712725aaf668598318e` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#280` |  | `discover_state_triggers` | passed |
| `99a08e7b5bfc0449414c` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#280` |  | `double_click_regions` | passed |
| `fb009764bba33be89c96` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#280` |  | `drag_regions` | passed |
| `dd1267e7950b3d4679b7` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#280` |  | `left_click_regions` | passed |
| `f9fd0f8b4ff2f57d55fd` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#280` |  | `right_click_regions` | passed |
| `163da477a2cd61116ed4` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#290` |  | `discover_state_triggers` | passed |
| `873bc9ac29972efdbae4` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#290` |  | `double_click_regions` | passed |
| `666a34c3c90e0e7dbba0` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#290` |  | `drag_regions` | passed |
| `dd65e96b8859275ed61a` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#290` |  | `left_click_regions` | passed |
| `e84ce61be5ac23bcd7e8` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#290` |  | `right_click_regions` | passed |
| `a01a56bc88cd7765f13c` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#300` |  | `discover_state_triggers` | passed |
| `742f843febe8068b50e0` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#300` |  | `double_click_regions` | passed |
| `288c198c6c4166c5073f` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#300` |  | `drag_regions` | passed |
| `9450fa128702f6f3b9ac` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#300` |  | `left_click_regions` | passed |
| `0b3ea6b575f5d42f12d9` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#300` |  | `right_click_regions` | passed |
| `e49bdf86924d1e75972a` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#310` |  | `discover_state_triggers` | passed |
| `17b89ecc1bedff6df382` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#310` |  | `double_click_regions` | passed |
| `66bb61e3684841429430` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#310` |  | `drag_regions` | passed |
| `bc2dc3a879daf76cfd01` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#310` |  | `left_click_regions` | passed |
| `d1bcb1ac9eb9b18a7dad` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#310` |  | `right_click_regions` | passed |
| `48ecb06483036c269fb8` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#320` |  | `discover_state_triggers` | passed |
| `8b9fe995beec2999140c` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#320` |  | `double_click_regions` | passed |
| `90401905d26963b91274` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#320` |  | `drag_regions` | passed |
| `34b4a27dc2fbf7a5347d` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#320` |  | `left_click_regions` | passed |
| `8eb376a7fed6d6a09c51` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#320` |  | `right_click_regions` | passed |
| `fa349022711c654f623f` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#330` |  | `discover_state_triggers` | passed |
| `632839dec11fc179bb8f` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#330` |  | `double_click_regions` | passed |
| `da70fe8486af2fc3f732` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#330` |  | `drag_regions` | passed |
| `302e87764187daf49174` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#330` |  | `left_click_regions` | passed |
| `b49b8c4bd594a19d56eb` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#330` |  | `right_click_regions` | passed |
| `94226f66aed4423fb617` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#340` |  | `discover_state_triggers` | passed |
| `842933f6b53f07ad9ff2` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#340` |  | `double_click_regions` | passed |
| `e0ce3311507d8ecd00dd` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#340` |  | `drag_regions` | passed |
| `9c7ce19b15c7f0709d1f` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#340` |  | `left_click_regions` | passed |
| `e249f3da4e046984b8c0` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#340` |  | `right_click_regions` | passed |
| `3688329d198c3ee64de3` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#350` |  | `discover_state_triggers` | passed |
| `f952a08c5c5ba35fd6ef` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#350` |  | `double_click_regions` | passed |
| `24cc1479e6b9567458cc` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#350` |  | `drag_regions` | passed |
| `63016d3858ef8f3f36d1` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#350` |  | `left_click_regions` | passed |
| `5bbf72b6c843febb7e51` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#350` |  | `right_click_regions` | passed |
| `da88d51766aebe14ad2e` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#360` |  | `discover_state_triggers` | passed |
| `130e3f47b61f04069fa4` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#360` |  | `double_click_regions` | passed |
| `c1aee50417e5a614e295` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#360` |  | `drag_regions` | passed |
| `7ea9d2091b3657ae249d` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#360` |  | `left_click_regions` | passed |
| `4d36437afdd6d9fe08d2` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#360` |  | `right_click_regions` | passed |
| `eb1ef9816d8b9b644e0b` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#370` |  | `discover_state_triggers` | passed |
| `f2f49d4f482834978c71` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#370` |  | `double_click_regions` | passed |
| `30430f1b857840c6e390` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#370` |  | `drag_regions` | passed |
| `a5539140784b79ba1e23` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#370` |  | `left_click_regions` | passed |
| `c20e481053092395decd` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#370` |  | `right_click_regions` | passed |
| `9c2d4c48d01829abf08e` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#380` |  | `discover_state_triggers` | passed |
| `7c346a333f418e243a91` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#380` |  | `double_click_regions` | passed |
| `f4a035d5838942091945` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#380` |  | `drag_regions` | passed |
| `39c945dd163b5078089b` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#380` |  | `left_click_regions` | passed |
| `33098911d43a0c1bb029` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#380` |  | `right_click_regions` | passed |
| `d7c1d3e3e1360b743eae` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#390` |  | `discover_state_triggers` | passed |
| `2178d110b224741d073e` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#390` |  | `double_click_regions` | passed |
| `2d150938203d0e21fe28` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#390` |  | `drag_regions` | passed |
| `d0c2a0329ea18e395ed6` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#390` |  | `left_click_regions` | passed |
| `9791b88f117ea92d58a7` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#390` |  | `right_click_regions` | passed |
| `9a905c0601690182fb5b` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#530` |  | `discover_state_triggers` | passed |
| `68f2bc63e1f30fdaa2f4` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#530` |  | `double_click_regions` | passed |
| `7f43003766531e979bb4` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#530` |  | `drag_regions` | passed |
| `10ddf59ebaedf2a0e814` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#530` |  | `left_click_regions` | passed |
| `ccfd21c5f28a667c5ba1` | SRW2扩容版修改器V1.0：<ROM> | `_EL_PicBox#530` |  | `right_click_regions` | passed |
| `5c39aef24c1bdac3ea5b` | SRW2扩容版修改器V1.0：<ROM> | `msctls_updown32#480` |  | `boundary_values` | passed |
| `add8dc4879b95d8f521e` | SRW2扩容版修改器V1.0：<ROM> | `msctls_updown32#480` |  | `decrement` | passed |
| `f2f5069411da4176b981` | SRW2扩容版修改器V1.0：<ROM> | `msctls_updown32#480` |  | `discover_state_triggers` | passed |
| `5cb17d371d11412cde82` | SRW2扩容版修改器V1.0：<ROM> | `msctls_updown32#480` |  | `increment` | passed |
| `cd1f7f107a196461f76b` | SRW2扩容版修改器V1.0：<ROM> | `msctls_updown32#490` |  | `boundary_values` | passed |
| `c61f7f98b713354a47cf` | SRW2扩容版修改器V1.0：<ROM> | `msctls_updown32#490` |  | `decrement` | passed |
| `90aa14ede7f6500ad107` | SRW2扩容版修改器V1.0：<ROM> | `msctls_updown32#490` |  | `discover_state_triggers` | passed |
| `ef157b8d3d9e0ec1b475` | SRW2扩容版修改器V1.0：<ROM> | `msctls_updown32#490` |  | `increment` | passed |
| `4605ad404ec4fd63d54f` | menu | `MenuItem#20001` | 打开&(O)	Ctrl+O | `activate` | passed |
| `a2756b7cec63bad6f94d` | menu | `MenuItem#20004` | 保存&(S)	Ctrl+S | `activate` | passed |
| `e8f223d10baa77764860` | menu | `MenuItem#20006` | 退出&(X)	Ctrl+X | `activate` | passed |
| `df6162447fc4aa5c8847` | menu | `MenuItem#20008` | 数据库&(D)	Ctrl+D | `activate` | passed |
| `4eb42e9e1fa2a6c37ba1` | menu | `MenuItem#20009` | 文字库&(W)	Ctrl+W | `activate` | passed |
| `d577fd4af9530d6cf274` | menu | `MenuItem#20011` | 地图动画&(M)	Ctrl+M | `activate` | passed |
| `6012b1393b446b24c3fe` | menu | `MenuItem#20013` | 文字转换&(Z)	Ctrl+Z | `activate` | passed |
| `4bf65d65d018b9629b23` | menu | `MenuItem#20015` | 剧情事件&(J)	Ctrl+J | `activate` | passed |
| `deebf9d008515c345f4a` | menu | `MenuItem#20017` | 导出机体&(P)	Ctrl+F | `activate` | passed |
| `b5bc945999459094d8ef` | menu | `MenuItem#20018` | 导出头像&(L)	Ctrl+L | `activate` | passed |
| `818036306dbd3dc185a8` | menu | `MenuItem#20020` | 属性计算器 | `activate` | passed |
| `7c7f54dbf8b58894c9eb` | menu | `MenuItem#20021` | 存档修改器 | `activate` | passed |
| `9a8961035064c5c200d6` | menu | `MenuItem#20023` | 其他&(T)	Ctrl+T | `activate` | passed |
| `8bf79e79acc0fe280902` | menu | `MenuItem#20025` | 关于 | `activate` | passed |
| `6f6c9bef3ac1f48bce91` | 事件编辑 | `Afx:400000:b:10003:900015:0#380` | 名称： | `discover_state_triggers` | passed |
| `cbcc53e82c2744e2cc09` | 事件编辑 | `Afx:400000:b:10003:900015:0#420` | 关卡： | `discover_state_triggers` | passed |
| `fad368b788d25e10e9c0` | 事件编辑 | `Afx:400000:b:10003:900015:0#450` | 我方： | `discover_state_triggers` | passed |
| `6231fe4c1a8c21f7070d` | 事件编辑 | `Afx:400000:b:10003:900015:0#470` | 被劝降敌方： | `discover_state_triggers` | passed |
| `3d20394ae8cd07f303e6` | 事件编辑 | `Afx:400000:b:10003:900015:0#480` | 名称： | `discover_state_triggers` | passed |
| `3ef70595575e88e4a8ab` | 事件编辑 | `Afx:400000:b:10003:900015:0#510` | 初始胜利文字： | `discover_state_triggers` | passed |
| `9263a418189c0f0d2a03` | 事件编辑 | `Afx:400000:b:10003:900015:0#590` | 标题： | `discover_state_triggers` | passed |
| `954db16101fb2935925c` | 事件编辑 | `Button#100` | 确定 | `keyboard_activate` | passed |
| `36f9a51bd6f0b6e729b7` | 事件编辑 | `Button#100` | 确定 | `left_click` | passed |
| `2f0d5fc6eda7e0c23bcb` | 事件编辑 | `Button#100` | 确定 | `right_click` | passed |
| `4c9b72e144fd24c2e525` | 事件编辑 | `Button#110` | 取消 | `keyboard_activate` | passed |
| `58c94e6c8f3f609c9e0d` | 事件编辑 | `Button#110` | 取消 | `left_click` | passed |
| `aca5e799130bbb0ca795` | 事件编辑 | `Button#110` | 取消 | `right_click` | passed |
| `19722d9c954621603fa0` | 事件编辑 | `Button#170` | 事件编辑 | `discover_state_triggers` | passed |
| `3eac88a1749cede042a1` | 事件编辑 | `Button#170` | 事件编辑 | `keyboard_activate` | passed |
| `2306a2f8314429ffa3df` | 事件编辑 | `Button#170` | 事件编辑 | `left_click` | passed |
| `93abd9c31bbacee728a0` | 事件编辑 | `Button#170` | 事件编辑 | `right_click` | passed |
| `5f3d5b63f8da7b4bb19e` | 事件编辑 | `Button#180` | 标题拼图设置 | `discover_state_triggers` | passed |
| `bfca3e9945bb38657c9b` | 事件编辑 | `Button#180` | 标题拼图设置 | `keyboard_activate` | passed |
| `68b4ad8f07fcce4c6cbd` | 事件编辑 | `Button#180` | 标题拼图设置 | `left_click` | passed |
| `3255779cd91389e31dc5` | 事件编辑 | `Button#180` | 标题拼图设置 | `right_click` | passed |
| `fd30529e200e46a40adb` | 事件编辑 | `Button#200` | 基本设置 | `discover_state_triggers` | passed |
| `62e336daedd6f4de333c` | 事件编辑 | `Button#200` | 基本设置 | `keyboard_activate` | passed |
| `be97967b2fc896840fe3` | 事件编辑 | `Button#200` | 基本设置 | `left_click` | passed |
| `4aa00a9aa28ece71101b` | 事件编辑 | `Button#200` | 基本设置 | `right_click` | passed |
| `f9920954ad7c852fbd51` | 事件编辑 | `Button#210` | 关卡选择 | `discover_state_triggers` | passed |
| `78e4ef4791dafdb72710` | 事件编辑 | `Button#210` | 关卡选择 | `keyboard_activate` | passed |
| `0751be14a4c5c48c40b4` | 事件编辑 | `Button#210` | 关卡选择 | `left_click` | passed |
| `e2c49c23845e3ca820d3` | 事件编辑 | `Button#210` | 关卡选择 | `right_click` | passed |
| `7702df32ef558726e9f7` | 事件编辑 | `Button#250` | 事件编辑 | `discover_state_triggers` | passed |
| `4fca0466328f739f40bf` | 事件编辑 | `Button#250` | 事件编辑 | `keyboard_activate` | passed |
| `db4a9e2542f37b0c77b8` | 事件编辑 | `Button#250` | 事件编辑 | `left_click` | passed |
| `3d23d8c66a781f44f761` | 事件编辑 | `Button#250` | 事件编辑 | `right_click` | passed |
| `e3aa4b86d50b309a4301` | 事件编辑 | `Button#270` | 行动事件 | `discover_state_triggers` | passed |
| `9f85bd806b18e7f8423a` | 事件编辑 | `Button#270` | 行动事件 | `keyboard_activate` | passed |
| `545804ac692f43638f64` | 事件编辑 | `Button#270` | 行动事件 | `left_click` | passed |
| `08c2e8977b6b7a243691` | 事件编辑 | `Button#270` | 行动事件 | `right_click` | passed |
| `c2ecb5bd031a4375952b` | 事件编辑 | `Button#300` | 事件编辑 | `discover_state_triggers` | passed |
| `642b19559e63ed60da0b` | 事件编辑 | `Button#300` | 事件编辑 | `keyboard_activate` | passed |
| `01a0d4ba1b1b6eae7784` | 事件编辑 | `Button#300` | 事件编辑 | `left_click` | passed |
| `88b4fc977275b36fbd31` | 事件编辑 | `Button#300` | 事件编辑 | `right_click` | passed |
| `e9a425a5a6a710304849` | 事件编辑 | `Button#320` | 劝降选择 | `discover_state_triggers` | passed |
| `169b6a33df1f300c2f83` | 事件编辑 | `Button#320` | 劝降选择 | `keyboard_activate` | passed |
| `02d66bd662eac0ceaa22` | 事件编辑 | `Button#320` | 劝降选择 | `left_click` | passed |
| `820bc3b5821ec4a74adb` | 事件编辑 | `Button#320` | 劝降选择 | `right_click` | passed |
| `f53306bae36737def41f` | 事件编辑 | `Button#350` | 事件编辑 | `discover_state_triggers` | passed |
| `f9d95bc07c41287363ed` | 事件编辑 | `Button#350` | 事件编辑 | `keyboard_activate` | passed |
| `e9c914dd0a5909ec096f` | 事件编辑 | `Button#350` | 事件编辑 | `left_click` | passed |
| `d94d547342c879a959ea` | 事件编辑 | `Button#350` | 事件编辑 | `right_click` | passed |
| `9973cde789f7730cd704` | 事件编辑 | `Button#370` | 地图事件 | `discover_state_triggers` | passed |
| `2dbe4d0982e2485a8e74` | 事件编辑 | `Button#370` | 地图事件 | `keyboard_activate` | passed |
| `70cd7bf15dd189901ac8` | 事件编辑 | `Button#370` | 地图事件 | `left_click` | passed |
| `c8b0a3e7f6ea8c431918` | 事件编辑 | `Button#370` | 地图事件 | `right_click` | passed |
| `3c8b8696d0ea40abe094` | 事件编辑 | `Button#400` | 基本设置 | `discover_state_triggers` | passed |
| `a1cf9281276f7e760aa9` | 事件编辑 | `Button#400` | 基本设置 | `keyboard_activate` | passed |
| `126e2162b4cb902483bc` | 事件编辑 | `Button#400` | 基本设置 | `left_click` | passed |
| `cd4330fddcd54cf4f7a4` | 事件编辑 | `Button#400` | 基本设置 | `right_click` | passed |
| `b905960b9e3189a1c5e2` | 事件编辑 | `Button#410` | 基本设置 | `discover_state_triggers` | passed |
| `9e447ac6c276d1cff2ee` | 事件编辑 | `Button#410` | 基本设置 | `keyboard_activate` | passed |
| `e76dbf8c12f36dcf5e7e` | 事件编辑 | `Button#410` | 基本设置 | `left_click` | passed |
| `243ac07162665af89789` | 事件编辑 | `Button#410` | 基本设置 | `right_click` | passed |
| `69de918f3bd63a89a79d` | 事件编辑 | `Button#500` | 基本设置 | `discover_state_triggers` | passed |
| `f14b885037aabca3c8fa` | 事件编辑 | `Button#500` | 基本设置 | `keyboard_activate` | passed |
| `13d5bef60f3292424c97` | 事件编辑 | `Button#500` | 基本设置 | `left_click` | passed |
| `8af6282bd50ed88977ef` | 事件编辑 | `Button#500` | 基本设置 | `right_click` | passed |
| `833d10df994eb52f1b97` | 事件编辑 | `Button#530` | 文字编辑 | `discover_state_triggers` | passed |
| `ac37607cca2cdeb700dc` | 事件编辑 | `Button#530` | 文字编辑 | `keyboard_activate` | passed |
| `1ef9ba937cec89d7e32a` | 事件编辑 | `Button#530` | 文字编辑 | `left_click` | passed |
| `6fdc16cecfcb9364a62e` | 事件编辑 | `Button#530` | 文字编辑 | `right_click` | passed |
| `956a48d6f1af17a912de` | 事件编辑 | `Button#550` | 文字编辑提示 | `discover_state_triggers` | passed |
| `c1bde171a4a16aad93bb` | 事件编辑 | `Button#550` | 文字编辑提示 | `keyboard_activate` | passed |
| `e4afe30bbd26545b8638` | 事件编辑 | `Button#550` | 文字编辑提示 | `left_click` | passed |
| `ce89edb8e6c6b85b8021` | 事件编辑 | `Button#550` | 文字编辑提示 | `right_click` | passed |
| `9c5dbe758225320fff2e` | 事件编辑 | `Button#580` | 对话段选择 | `discover_state_triggers` | passed |
| `9b79b99d73fe33c5a1a3` | 事件编辑 | `Button#580` | 对话段选择 | `keyboard_activate` | passed |
| `89d4e7ea04b480521b87` | 事件编辑 | `Button#580` | 对话段选择 | `left_click` | passed |
| `5129223b384f6d3aaa33` | 事件编辑 | `Button#580` | 对话段选择 | `right_click` | passed |
| `8b438c0a12d89f13bd74` | 事件编辑 | `Button#610` | 代码编辑 | `discover_state_triggers` | passed |
| `36a5988ea6d755cce394` | 事件编辑 | `Button#610` | 代码编辑 | `keyboard_activate` | passed |
| `ecdb99a619cf6c8f4500` | 事件编辑 | `Button#610` | 代码编辑 | `left_click` | passed |
| `869c4e523eb213c0a384` | 事件编辑 | `Button#610` | 代码编辑 | `right_click` | passed |
| `3b89f13ca3464fdc3232` | 事件编辑 | `Button#640` | 对话段选择 | `discover_state_triggers` | passed |
| `0fadca5df94f8dd8fc55` | 事件编辑 | `Button#640` | 对话段选择 | `keyboard_activate` | passed |
| `f526282464dc2cbc618a` | 事件编辑 | `Button#640` | 对话段选择 | `left_click` | passed |
| `7ac7d27317d00bb22fd2` | 事件编辑 | `Button#640` | 对话段选择 | `right_click` | passed |
| `51154be96e3016fb0e69` | 事件编辑 | `Button#660` | 文字编辑 | `discover_state_triggers` | passed |
| `f76997ff48da1b397ab4` | 事件编辑 | `Button#660` | 文字编辑 | `keyboard_activate` | passed |
| `e5ce59b0fb4d91b37c85` | 事件编辑 | `Button#660` | 文字编辑 | `left_click` | passed |
| `5c15a392934c3f2db965` | 事件编辑 | `Button#660` | 文字编辑 | `right_click` | passed |
| `1128095a7e8eaef7e91a` | 事件编辑 | `Button#680` | 文字编辑提示 | `discover_state_triggers` | passed |
| `72c435745871807dc058` | 事件编辑 | `Button#680` | 文字编辑提示 | `keyboard_activate` | passed |
| `4bb9a243dffca670f217` | 事件编辑 | `Button#680` | 文字编辑提示 | `left_click` | passed |
| `58274a7fe74cf427538f` | 事件编辑 | `Button#680` | 文字编辑提示 | `right_click` | passed |
| `76ee1b91ea560faae952` | 事件编辑 | `Button#690` | 检查剧情剩余空间 | `keyboard_activate` | passed |
| `02746f0fbc659ce36d10` | 事件编辑 | `Button#690` | 检查剧情剩余空间 | `left_click` | passed |
| `cf7b38a7cfde3f4424e6` | 事件编辑 | `Button#690` | 检查剧情剩余空间 | `right_click` | passed |
| `b9eaf2b09be530f480ed` | 事件编辑 | `Button#700` | 清空本页 | `discover_state_triggers` | passed |
| `8c18c5775d92de257362` | 事件编辑 | `Button#700` | 清空本页 | `keyboard_activate` | passed |
| `e159a073c29c182c722d` | 事件编辑 | `Button#700` | 清空本页 | `left_click` | passed |
| `372ec2480b78ab1f4a42` | 事件编辑 | `Button#700` | 清空本页 | `right_click` | passed |
| `98746706e7a22400f716` | 事件编辑 | `CPageControl#120` |  | `keyboard_tab_cycle` | passed |
| `00c64ff35b604fe39184` | 事件编辑 | `CPageControl#120` |  | `right_click_tabs` | passed |
| `16ec2cb7949a365f6dcb` | 事件编辑 | `CPageControl#120` |  | `select_each_tab` | passed |
| `e9f91f2d1cabec445fc4` | 事件编辑 | `CPageControl#130` |  | `discover_state_triggers` | passed |
| `3e5305fd81bc235c2856` | 事件编辑 | `CPageControl#130` |  | `keyboard_tab_cycle` | passed |
| `b0740ec3c45b88210093` | 事件编辑 | `CPageControl#130` |  | `right_click_tabs` | passed |
| `18adaefaf66d4f824f6f` | 事件编辑 | `CPageControl#130` |  | `select_each_tab` | passed |
| `2bdd7a7ae275d8f6fed2` | 事件编辑 | `CPageControl#230` |  | `discover_state_triggers` | passed |
| `e8f9b923ed04b3214ce8` | 事件编辑 | `CPageControl#230` |  | `keyboard_tab_cycle` | passed |
| `28d82f48d10acc41220f` | 事件编辑 | `CPageControl#230` |  | `right_click_tabs` | passed |
| `98cec1b8b1d67aec0b07` | 事件编辑 | `CPageControl#230` |  | `select_each_tab` | passed |
| `3fa20ec4b09f38b33937` | 事件编辑 | `CPageControl#280` |  | `discover_state_triggers` | passed |
| `e9319d67ba333f1b4e57` | 事件编辑 | `CPageControl#280` |  | `keyboard_tab_cycle` | passed |
| `c1626ee08cf991008029` | 事件编辑 | `CPageControl#280` |  | `right_click_tabs` | passed |
| `ab86bb28ce76fa6229e4` | 事件编辑 | `CPageControl#280` |  | `select_each_tab` | passed |
| `2692c2d2cc41a36a1ca9` | 事件编辑 | `CPageControl#330` |  | `discover_state_triggers` | passed |
| `843c3721072fb3c153d1` | 事件编辑 | `CPageControl#330` |  | `keyboard_tab_cycle` | passed |
| `0b170a9cf2d45bd24026` | 事件编辑 | `CPageControl#330` |  | `right_click_tabs` | passed |
| `628ba0bf04f20ce7ec23` | 事件编辑 | `CPageControl#330` |  | `select_each_tab` | passed |
| `43054ef3785aa7050f02` | 事件编辑 | `ComboBox#430` | 002：街上追击战 / 008：荒野谋略 | `discover_state_triggers` | passed |
| `e533d20d05363b66b7e1` | 事件编辑 | `ComboBox#430` | 008：荒野谋略 | `keyboard_cycle` | passed |
| `acdd403a49d0d4aecca6` | 事件编辑 | `ComboBox#430` | 008：荒野谋略 | `open_dropdown` | passed |
| `e3a10fc0347ce18c8e66` | 事件编辑 | `ComboBox#430` | 008：荒野谋略 | `right_click` | passed |
| `5cc1f4a0971fb157abce` | 事件编辑 | `ComboBox#430` | 008：荒野谋略 | `select_each_item` | passed |
| `f4370e3cbe37f874eda1` | 事件编辑 | `ComboBox#440` | 006：夏亚 / 011：拉米娅 | `discover_state_triggers` | passed |
| `6839bb5cbc30c1f3dfa4` | 事件编辑 | `ComboBox#440` | 011：拉米娅 | `keyboard_cycle` | passed |
| `db518936f3f41b9e8e04` | 事件编辑 | `ComboBox#440` | 011：拉米娅 | `open_dropdown` | passed |
| `ea42aa129c700a452ddf` | 事件编辑 | `ComboBox#440` | 011：拉米娅 | `right_click` | passed |
| `e8dd3caafef4fc903ea5` | 事件编辑 | `ComboBox#440` | 011：拉米娅 | `select_each_item` | passed |
| `04f34f11a21e07d083ce` | 事件编辑 | `ComboBox#460` | 012：蕾蒙 / 069：拉拉 | `discover_state_triggers` | passed |
| `c85412ed9e85bb6bdd06` | 事件编辑 | `ComboBox#460` | 012：蕾蒙 | `keyboard_cycle` | passed |
| `9ab56a6529e17c65041a` | 事件编辑 | `ComboBox#460` | 012：蕾蒙 | `open_dropdown` | passed |
| `d1bd7134eddbbe4232c5` | 事件编辑 | `ComboBox#460` | 012：蕾蒙 | `right_click` | passed |
| `778735d6a6be78626db6` | 事件编辑 | `ComboBox#460` | 012：蕾蒙 | `select_each_item` | passed |
| `2038825301eebea7909c` | 事件编辑 | `ComboBox#570` | 02 | `discover_state_triggers` | passed |
| `d2af8c57789e68a13bc8` | 事件编辑 | `ComboBox#570` | 02 | `keyboard_cycle` | passed |
| `e693ec61ccaf9abda2af` | 事件编辑 | `ComboBox#570` | 02 | `open_dropdown` | passed |
| `a8a10fcb80d3d31b96f6` | 事件编辑 | `ComboBox#570` | 02 | `right_click` | passed |
| `00e4842b9d0eeb5c48b2` | 事件编辑 | `ComboBox#570` | 02 | `select_each_item` | passed |
| `5138a18f5449e8f8cfb8` | 事件编辑 | `Edit#190` | 阻挡敌方进攻等待我方大部队增援 @基拉或阿斯兰被击落则失败。 | `boundary_values` | passed |
| `1848d9ad9a19f1b3ecc8` | 事件编辑 | `Edit#190` | 琉妮给击落则失败，全歼敌方即胜利！ / 阻挡敌方进攻等待我方大部队增援 @基拉或阿斯兰被击落则失败。 | `discover_state_triggers` | passed |
| `f8640f6a4c9249c081d7` | 事件编辑 | `Edit#190` | 阻挡敌方进攻等待我方大部队增援 @基拉或阿斯兰被击落则失败。 | `focus` | passed |
| `afdcf9f9b96418a99825` | 事件编辑 | `Edit#190` | 阻挡敌方进攻等待我方大部队增援 @基拉或阿斯兰被击落则失败。 | `keyboard_shortcuts` | passed |
| `bd24a03b30f451193d50` | 事件编辑 | `Edit#190` | 阻挡敌方进攻等待我方大部队增援 @基拉或阿斯兰被击落则失败。 | `replace_value` | passed |
| `2d538ca93bad17942e1e` | 事件编辑 | `Edit#190` | 阻挡敌方进攻等待我方大部队增援 @基拉或阿斯兰被击落则失败。 | `right_click` | passed |
| `307a12df5ff99527fed4` | 事件编辑 | `Edit#390` | 不动 | `boundary_values` | passed |
| `1b061db6ca28bc7624ee` | 事件编辑 | `Edit#390` | 不动 | `discover_state_triggers` | passed |
| `42b4a6208f78ade8a83c` | 事件编辑 | `Edit#390` | 不动 | `focus` | passed |
| `5ad57985344824c0bf27` | 事件编辑 | `Edit#390` | 不动 | `keyboard_shortcuts` | passed |
| `169af8d3aa438a92d4dd` | 事件编辑 | `Edit#390` | 不动 | `replace_value` | passed |
| `2e4479e1ec2f1205ea7a` | 事件编辑 | `Edit#390` | 不动 | `right_click` | passed |
| `7e80daa46c3eec6b4965` | 事件编辑 | `Edit#490` | 商店 | `boundary_values` | passed |
| `d14259c2f48e44e2f316` | 事件编辑 | `Edit#490` | 商店 | `discover_state_triggers` | passed |
| `aedef1c574edc105f095` | 事件编辑 | `Edit#490` | 商店 | `focus` | passed |
| `6ce04d29be3276a572c2` | 事件编辑 | `Edit#490` | 商店 | `keyboard_shortcuts` | passed |
| `b4941ade3309fc052608` | 事件编辑 | `Edit#490` | 商店 | `replace_value` | passed |
| `49f9bea2e1b6fe022950` | 事件编辑 | `Edit#490` | 商店 | `right_click` | passed |
| `726f811b8028d238d82a` | 事件编辑 | `Edit#520` | 克鲁泽：\ 这是根据雅金多维的追击数据测\ 算出的，那些家伙的预测航线！】  【047？？？？：\ L4殖民地层内，殖民地门德尔\ 吗？果然…】  【045克鲁泽：\ 那也是个令人伤脑筋的地方，\ 被奇怪的人作为根据地。】  【045克鲁泽：\ 确实是个便利的地方，这次\ 也要…干出点什么吧！】  【045克鲁泽：\ 不管怎样，深藏在人类心中的想\ 法，并非那么容易从表面看出…】  【045克鲁泽：\ 卡纳德！你的对手基拉.大和\ 终于要出现了！】  【044卡纳德：\ 卡纳德：……】  | `boundary_values` | passed |
| `501f96365f030ee0ec89` | 事件编辑 | `Edit#520` | 克鲁泽：\ 这是根据雅金多维的追击数据测\ 算出的，那些家伙的预测航线！】  【047？？？？：\ L4殖民地层内，殖民地门德尔\ 吗？果然…】  【045克鲁泽：\ 那也是个令人伤脑筋的地方，\ 被奇怪的人作为根据地。】  【045克鲁泽：\ 确实是个便利的地方，这次\ 也要…干出点什么吧！】  【045克鲁泽：\ 不管怎样，深藏在人类心中的想\ 法，并非那么容易从表面看出…】  【045克鲁泽：\ 卡纳德！你的对手基拉.大和\ 终于要出现了！】  【044卡纳德：\ 卡纳德：……】  / 请你选择琉妮驾驶的机体！】  | `discover_state_triggers` | passed |
| `5534a0464104f854fbb6` | 事件编辑 | `Edit#520` | 克鲁泽：\ 这是根据雅金多维的追击数据测\ 算出的，那些家伙的预测航线！】  【047？？？？：\ L4殖民地层内，殖民地门德尔\ 吗？果然…】  【045克鲁泽：\ 那也是个令人伤脑筋的地方，\ 被奇怪的人作为根据地。】  【045克鲁泽：\ 确实是个便利的地方，这次\ 也要…干出点什么吧！】  【045克鲁泽：\ 不管怎样，深藏在人类心中的想\ 法，并非那么容易从表面看出…】  【045克鲁泽：\ 卡纳德！你的对手基拉.大和\ 终于要出现了！】  【044卡纳德：\ 卡纳德：……】  | `focus` | passed |
| `bc82f7d0775fb72804db` | 事件编辑 | `Edit#520` | 克鲁泽：\ 这是根据雅金多维的追击数据测\ 算出的，那些家伙的预测航线！】  【047？？？？：\ L4殖民地层内，殖民地门德尔\ 吗？果然…】  【045克鲁泽：\ 那也是个令人伤脑筋的地方，\ 被奇怪的人作为根据地。】  【045克鲁泽：\ 确实是个便利的地方，这次\ 也要…干出点什么吧！】  【045克鲁泽：\ 不管怎样，深藏在人类心中的想\ 法，并非那么容易从表面看出…】  【045克鲁泽：\ 卡纳德！你的对手基拉.大和\ 终于要出现了！】  【044卡纳德：\ 卡纳德：……】  | `keyboard_shortcuts` | passed |
| `a29fc7758c6ff06f255d` | 事件编辑 | `Edit#520` | 克鲁泽：\ 这是根据雅金多维的追击数据测\ 算出的，那些家伙的预测航线！】  【047？？？？：\ L4殖民地层内，殖民地门德尔\ 吗？果然…】  【045克鲁泽：\ 那也是个令人伤脑筋的地方，\ 被奇怪的人作为根据地。】  【045克鲁泽：\ 确实是个便利的地方，这次\ 也要…干出点什么吧！】  【045克鲁泽：\ 不管怎样，深藏在人类心中的想\ 法，并非那么容易从表面看出…】  【045克鲁泽：\ 卡纳德！你的对手基拉.大和\ 终于要出现了！】  【044卡纳德：\ 卡纳德：……】  | `replace_value` | passed |
| `7977486a47fcbd91c4aa` | 事件编辑 | `Edit#520` | 克鲁泽：\ 这是根据雅金多维的追击数据测\ 算出的，那些家伙的预测航线！】  【047？？？？：\ L4殖民地层内，殖民地门德尔\ 吗？果然…】  【045克鲁泽：\ 那也是个令人伤脑筋的地方，\ 被奇怪的人作为根据地。】  【045克鲁泽：\ 确实是个便利的地方，这次\ 也要…干出点什么吧！】  【045克鲁泽：\ 不管怎样，深藏在人类心中的想\ 法，并非那么容易从表面看出…】  【045克鲁泽：\ 卡纳德！你的对手基拉.大和\ 终于要出现了！】  【044卡纳德：\ 卡纳德：……】  | `right_click` | passed |
| `d76f017e5397edfd53f1` | 事件编辑 | `Edit#600` | 伏击之战 | `boundary_values` | passed |
| `438225f966966057fe93` | 事件编辑 | `Edit#600` | 伏击之战 | `discover_state_triggers` | passed |
| `9dc349ae8208dd73765d` | 事件编辑 | `Edit#600` | 伏击之战 | `focus` | passed |
| `cdec57dede9945b07731` | 事件编辑 | `Edit#600` | 伏击之战 | `keyboard_shortcuts` | passed |
| `4e1ee6af76e4a2f136e8` | 事件编辑 | `Edit#600` | 伏击之战 | `replace_value` | passed |
| `640889a20db27ba1dba3` | 事件编辑 | `Edit#600` | 伏击之战 | `right_click` | passed |
| `5a09873ed6707666651e` | 事件编辑 | `Edit#650` |  | `boundary_values` | passed |
| `f470d0f5f7451798ec40` | 事件编辑 | `Edit#650` |  | `discover_state_triggers` | passed |
| `5f107ed117ff72773145` | 事件编辑 | `Edit#650` |  | `focus` | passed |
| `6b76af92f9c6c711fb81` | 事件编辑 | `Edit#650` |  | `keyboard_shortcuts` | passed |
| `17dfdd9d4067249b0588` | 事件编辑 | `Edit#650` |  | `replace_value` | passed |
| `f9101e3f2794e1fbe77e` | 事件编辑 | `Edit#650` |  | `right_click` | passed |
| `4f25645ad609a5a8cde4` | 事件编辑 | `ListBox#160` |  | `discover_state_triggers` | passed |
| `1f77d6b2ff75aebb1131` | 事件编辑 | `ListBox#160` |  | `double_click_each_item` | passed |
| `973aebc03d03e777dc4f` | 事件编辑 | `ListBox#160` |  | `keyboard_navigation` | passed |
| `dd00c62a8bffa446a0f9` | 事件编辑 | `ListBox#160` |  | `right_click_each_item` | passed |
| `36b338321cc42486698c` | 事件编辑 | `ListBox#160` |  | `select_each_item` | passed |
| `ac570b0c6a70d61d2913` | 事件编辑 | `ListBox#220` |  | `discover_state_triggers` | passed |
| `54c4b0aa22a2e111d494` | 事件编辑 | `ListBox#220` |  | `double_click_each_item` | passed |
| `63324d2bd73c4447b641` | 事件编辑 | `ListBox#220` |  | `keyboard_navigation` | passed |
| `f53ef2608120c3e37dee` | 事件编辑 | `ListBox#220` |  | `right_click_each_item` | passed |
| `522386c0010a94b82cf0` | 事件编辑 | `ListBox#220` |  | `select_each_item` | passed |
| `13052c897e727026e2a5` | 事件编辑 | `ListBox#240` |  | `discover_state_triggers` | passed |
| `5cb29b1954bc4d8944db` | 事件编辑 | `ListBox#240` |  | `double_click_each_item` | passed |
| `def9f402d4c5969e1a22` | 事件编辑 | `ListBox#240` |  | `keyboard_navigation` | passed |
| `0dbe93f41a94b1e8452f` | 事件编辑 | `ListBox#240` |  | `right_click_each_item` | passed |
| `246eb591d4cf96bced4f` | 事件编辑 | `ListBox#240` |  | `select_each_item` | passed |
| `a7906151e1589c3cad39` | 事件编辑 | `ListBox#260` |  | `discover_state_triggers` | passed |
| `3c00a5fc2d7fee371802` | 事件编辑 | `ListBox#260` |  | `double_click_each_item` | passed |
| `8d2d5f85f954550f2f04` | 事件编辑 | `ListBox#260` |  | `keyboard_navigation` | passed |
| `3aeaef3fa32c9eced5f2` | 事件编辑 | `ListBox#260` |  | `right_click_each_item` | passed |
| `733589724d6311950fdc` | 事件编辑 | `ListBox#260` |  | `select_each_item` | passed |
| `de347313f7cb3fba8a95` | 事件编辑 | `ListBox#290` |  | `discover_state_triggers` | passed |
| `9bf306119b7bf86d7007` | 事件编辑 | `ListBox#290` |  | `double_click_each_item` | passed |
| `7a8d445dc8bbac02f646` | 事件编辑 | `ListBox#290` |  | `keyboard_navigation` | passed |
| `dc6d48472c37a03f5e99` | 事件编辑 | `ListBox#290` |  | `right_click_each_item` | passed |
| `6805e1716717bf5dd5eb` | 事件编辑 | `ListBox#290` |  | `select_each_item` | passed |
| `26b4db0dde648be54d89` | 事件编辑 | `ListBox#310` |  | `discover_state_triggers` | passed |
| `6f4b46b0f791f8450a13` | 事件编辑 | `ListBox#310` |  | `double_click_each_item` | passed |
| `fbf405c697aa49de433e` | 事件编辑 | `ListBox#310` |  | `keyboard_navigation` | passed |
| `6f711c04ccc6fc8e24d3` | 事件编辑 | `ListBox#310` |  | `right_click_each_item` | passed |
| `bd59668c66acf9cdd9f8` | 事件编辑 | `ListBox#310` |  | `select_each_item` | passed |
| `60b3aad6de66eda1a29a` | 事件编辑 | `ListBox#340` |  | `discover_state_triggers` | passed |
| `c80e1515cb2901115d89` | 事件编辑 | `ListBox#340` |  | `double_click_each_item` | passed |
| `9e0b2ec26172b842b0c7` | 事件编辑 | `ListBox#340` |  | `keyboard_navigation` | passed |
| `eebe11cb4e0e7ff87c9a` | 事件编辑 | `ListBox#340` |  | `right_click_each_item` | passed |
| `931f1680503ce9067a5e` | 事件编辑 | `ListBox#340` |  | `select_each_item` | passed |
| `7496ea05efdb6b80c220` | 事件编辑 | `ListBox#360` |  | `discover_state_triggers` | passed |
| `5218548443da050d2514` | 事件编辑 | `ListBox#360` |  | `double_click_each_item` | passed |
| `43d73460513dd8175cff` | 事件编辑 | `ListBox#360` |  | `keyboard_navigation` | passed |
| `c560108bb768d11bba3c` | 事件编辑 | `ListBox#360` |  | `right_click_each_item` | passed |
| `c1b3d5f8c54fe75d352b` | 事件编辑 | `ListBox#360` |  | `select_each_item` | passed |
| `ac0ffb6bc9dc86e000ed` | 事件编辑 | `ListBox#560` |  | `discover_state_triggers` | passed |
| `aa27872115d33f717d39` | 事件编辑 | `ListBox#560` |  | `double_click_each_item` | passed |
| `5abb0ab47b07b2f99e76` | 事件编辑 | `ListBox#560` |  | `keyboard_navigation` | passed |
| `890dbad76611ad92b52c` | 事件编辑 | `ListBox#560` |  | `right_click_each_item` | passed |
| `4e55d354e9cacf23c80c` | 事件编辑 | `ListBox#560` |  | `select_each_item` | passed |
| `2544f269c57797bdc2fb` | 事件编辑 | `ListBox#630` |  | `discover_state_triggers` | passed |
| `bc5f190661b72fdc1982` | 事件编辑 | `ListBox#630` |  | `double_click_each_item` | passed |
| `bb1cb72425166c8e50d9` | 事件编辑 | `ListBox#630` |  | `keyboard_navigation` | passed |
| `862b688fbb6452283d86` | 事件编辑 | `ListBox#630` |  | `right_click_each_item` | passed |
| `55791e2d032020652c1f` | 事件编辑 | `ListBox#630` |  | `select_each_item` | passed |
| `2d8f31e957c1ab1b74a0` | 事件编辑 | `WTWindow#0` | 事件编辑 | `discover_state_triggers` | passed |
| `7165b67b3faa48642fcf` | 事件编辑 | `_EL_Label#540` | 提示：   “_”=空格        “\”=换行        “@”=头像不换  “【”加三位数人物序号=换头像       “】”=对话结束  “*”加三位数字=延迟      | `discover_state_triggers` | passed |
| `40a2345f3a807e5c3add` | 事件编辑 | `_EL_Label#670` | 提示：   “_”=空格        “\”=换行        “@”=头像不换  “【”加三位数人物序号=换头像       “】”=对话结束  “*”加三位数字=延迟      | `discover_state_triggers` | passed |
| `184db882c090f87a7a43` | 事件编辑 | `_EL_PicBox#620` |  | `discover_state_triggers` | passed |
| `c3b0bd87f260794c59c1` | 事件编辑 | `_EL_PicBox#620` |  | `double_click_regions` | passed |
| `248a01e048bbf28f7a5d` | 事件编辑 | `_EL_PicBox#620` |  | `drag_regions` | passed |
| `67b439bf87e4e0e41b20` | 事件编辑 | `_EL_PicBox#620` |  | `left_click_regions` | passed |
| `54ad124747390f24164e` | 事件编辑 | `_EL_PicBox#620` |  | `right_click_regions` | passed |
| `dc86254148e977f99119` | 人物修改 | `ContextMenuItem#20007` | 复制人物 | `activate_context_command` | passed |
| `f09794863bd4f9af4798` | 人物修改 | `ContextMenuItem#20007` | 复制人物 | `activate_context_command` | passed |
| `e79bde2f477f8e6a91a7` | 人物修改 | `ContextMenuItem#20008` | 粘贴人物 | `activate_context_command` | passed |
| `b09d0618b73892574525` | 人物修改 | `ContextMenuItem#20008` | 粘贴人物 | `activate_context_command` | passed |
| `c4030b804f1b54f8c563` | 人物修改 | `ContextMenuItem#20009` | 导出人物 | `activate_context_command` | passed |
| `27a96414a83d5a340d27` | 人物修改 | `ContextMenuItem#20009` | 导出人物 | `activate_context_command` | passed |
| `194a4543e7d8e34834c9` | 人物修改 | `ContextMenuItem#20029` | 复制对话 | `activate_context_command` | passed |
| `5ec91a965016201c5b25` | 人物修改 | `ContextMenuItem#20029` | 复制对话 | `activate_context_command` | passed |
| `dc439ca8ec99aba6c670` | 人物修改 | `ContextMenuItem#20029` | 复制对话 | `activate_context_command` | passed |
| `ee0c7a7de564ba256eb7` | 人物修改 | `ContextMenuItem#20029` | 复制对话 | `activate_context_command` | passed |
| `35d2a446be88e21908bb` | 人物修改 | `ContextMenuItem#20030` | 粘贴对话 | `activate_context_command` | passed |
| `f656ce09d89f87b5b5d8` | 人物修改 | `ContextMenuItem#20030` | 粘贴对话 | `activate_context_command` | passed |
| `6b3570f98aefdfa717d6` | 人物修改 | `ContextMenuItem#20030` | 粘贴对话 | `activate_context_command` | passed |
| `5c80c2967867142bdbae` | 人物修改 | `ContextMenuItem#20030` | 粘贴对话 | `activate_context_command` | passed |
| `5aefb68af7cb62ece9c9` | 信息： | `Button#2` | 确定 | `keyboard_activate` | passed |
| `a474a9f3375b0311fca1` | 信息： | `Button#2` | 确定 | `left_click` | passed |
| `dd9bdf4711b1637d2b41` | 信息： | `Button#2` | 确定 | `right_click` | passed |
| `c7d6db6310d357d5bcba` | 信息： | `Button#6` | 是(&Y) | `keyboard_activate` | passed |
| `9b2b4b55b112b46e6bf7` | 信息： | `Button#6` | 是(&Y) | `left_click` | passed |
| `0ffa69ac4ec21dbfc780` | 信息： | `Button#6` | 是(&Y) | `right_click` | passed |
| `f9de160be48135a32ed5` | 信息： | `Button#7` | 否(&N) | `keyboard_activate` | passed |
| `afd5c1ee23258721397c` | 信息： | `Button#7` | 否(&N) | `left_click` | passed |
| `df0f75ec68b0441884ec` | 信息： | `Button#7` | 否(&N) | `right_click` | passed |
| `363b31f6593f2d548728` | 光束拼图 | `Button#100` | 参考设置 | `keyboard_activate` | passed |
| `bf2d56baf6c4f0314131` | 光束拼图 | `Button#100` | 参考设置 | `left_click` | passed |
| `0c0497c9d4f42cc1bda3` | 光束拼图 | `Button#100` | 参考设置 | `right_click` | passed |
| `61308ddcb40d35250b5c` | 光束拼图 | `Button#130` | 图库（提示：左键选择图块） | `keyboard_activate` | passed |
| `c128a736b4cc0aab79e7` | 光束拼图 | `Button#130` | 图库（提示：左键选择图块） | `left_click` | passed |
| `24712141655f1270b705` | 光束拼图 | `Button#130` | 图库（提示：左键选择图块） | `right_click` | passed |
| `1e31b94203f4da30bb37` | 光束拼图 | `Button#150` | 效果图片(提示：左键编辑图块 右键删除图块) | `keyboard_activate` | passed |
| `a26554bf43e1bc56047a` | 光束拼图 | `Button#150` | 效果图片(提示：左键编辑图块 右键删除图块) | `left_click` | passed |
| `508a3c21103ed6c0b922` | 光束拼图 | `Button#150` | 效果图片(提示：左键编辑图块 右键删除图块) | `right_click` | passed |
| `bd692c498f4f0ec3c6c6` | 光束拼图 | `Button#190` | 确定 | `keyboard_activate` | passed |
| `73c801f9badb78cd04e3` | 光束拼图 | `Button#190` | 确定 | `left_click` | passed |
| `f90c04e1ab100e06cd4d` | 光束拼图 | `Button#190` | 确定 | `right_click` | passed |
| `dbb38986893fbb2b7790` | 光束拼图 | `Button#200` | 取消 | `keyboard_activate` | passed |
| `a0e0792f20ccab43d48c` | 光束拼图 | `Button#200` | 取消 | `left_click` | passed |
| `2851ddb946f80574eec5` | 光束拼图 | `Button#200` | 取消 | `right_click` | passed |
| `5f229f3707ed65f80d39` | 光束拼图 | `Button#210` | 显示图块编号 | `keyboard_activate` | passed |
| `f5adfd9c9d573bed0bf0` | 光束拼图 | `Button#210` | 显示图块编号 | `left_click` | passed |
| `9806ec6a02068dabf02f` | 光束拼图 | `Button#210` | 显示图块编号 | `right_click` | passed |
| `2b9b73db4fecfc0b0105` | 光束拼图 | `Button#270` | 40开始 | `keyboard_activate` | passed |
| `281cba90ea445e454ed0` | 光束拼图 | `Button#270` | 40开始 | `left_click` | passed |
| `73dfcdd34b6601ecd1cc` | 光束拼图 | `Button#270` | 40开始 | `right_click` | passed |
| `fd5afd2d9f326a598112` | 光束拼图 | `Button#280` | 80开始 | `keyboard_activate` | passed |
| `9113a9869b034127d884` | 光束拼图 | `Button#280` | 80开始 | `left_click` | passed |
| `634d348613ad59b31451` | 光束拼图 | `Button#280` | 80开始 | `right_click` | passed |
| `57b11037c3fbc7efa832` | 光束拼图 | `ComboBox#120` | [00]000：80010 | `keyboard_cycle` | passed |
| `7ada72870ab079b5e7f5` | 光束拼图 | `ComboBox#120` | [00]000：80010 | `open_dropdown` | passed |
| `5d49144e56b92cd83a6a` | 光束拼图 | `ComboBox#120` | [00]000：80010 | `right_click` | passed |
| `eb18e9a250f4ac3983a1` | 光束拼图 | `ComboBox#120` | [00]000：80010 | `select_each_item` | passed |
| `af9b4ab48e0bd6f1332b` | 其他 | `Button#100` | 双击公式 | `keyboard_activate` | passed |
| `e3bd29164fae06bf55b0` | 其他 | `Button#100` | 双击公式 | `left_click` | passed |
| `9c015349c35443f5ab7e` | 其他 | `Button#100` | 双击公式 | `right_click` | passed |
| `ec144d550422e58da7c2` | 其他 | `Button#130` | 道具相关修改 | `keyboard_activate` | passed |
| `85d751eac239358b2042` | 其他 | `Button#130` | 道具相关修改 | `left_click` | passed |
| `f3f9b1aa3a1d838b33c9` | 其他 | `Button#130` | 道具相关修改 | `right_click` | passed |
| `0fc3b75026652049b33f` | 其他 | `Button#320` | 确定 | `keyboard_activate` | passed |
| `d3daa61380d23e0c710a` | 其他 | `Button#320` | 确定 | `left_click` | passed |
| `7c391b878ab1e84d939a` | 其他 | `Button#320` | 确定 | `right_click` | passed |
| `b9d734b4cde21480fe38` | 其他 | `Button#330` | 取消 | `keyboard_activate` | passed |
| `433a758efcc4f2ae0a3d` | 其他 | `Button#330` | 取消 | `left_click` | passed |
| `bf9e51dcf830d9a92e16` | 其他 | `Button#330` | 取消 | `right_click` | passed |
| `8e6b05d49168c9612301` | 其他 | `Button#370` | 初始机体 | `keyboard_activate` | passed |
| `e2873d2884017586f13d` | 其他 | `Button#370` | 初始机体 | `left_click` | passed |
| `8d8c1ffbd4362ef86094` | 其他 | `Button#370` | 初始机体 | `right_click` | passed |
| `fb9dfdb781f65c38b59f` | 其他 | `Button#740` | 伤害计算公式 | `keyboard_activate` | passed |
