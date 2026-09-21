# 参考 EXE 静态对话框资源枚举

- 对话框资源：17
- 已声明控件：184
- 解析失败：0
- EXE SHA-256：`FF1C1C5799FDB8F34DF355D761B382C6946CDADC6810772862947E892E8B4C27`

> 只读解析参考 EXE 的 RT_DIALOG；动态创建窗口仍以运行时控件树为准。

| 资源 | 标题 | 控件数 | 模板 |
|---|---|---:|---|
| `1037` | 请输入： | 6 | DIALOG |
| ↳ 65535 |  |  | `Static` |
| ↳ 1128 |  |  | `Static` |
| ↳ 1001 |  |  | `Edit` |
| ↳ 1002 |  |  | `Edit` |
| ↳ 1 | 确认输入(&O) |  | `Button` |
| ↳ 2 | 取消(&C) |  | `Button` |
| `1084` | 打印设置对话框 | 54 | DIALOG |
| ↳ 65535 | 打印机: |  | `Static` |
| ↳ 1087 |  |  | `ComboBox` |
| ↳ 1088 | 设置(&S) |  | `Button` |
| ↳ 1089 | 打印到文件: |  | `Button` |
| ↳ 1090 |  |  | `Edit` |
| ↳ 1092 | ... |  | `Button` |
| ↳ 65535 | 页边距(单位:毫米) |  | `Button` |
| ↳ 65535 | 上: |  | `Static` |
| ↳ 1001 |  |  | `Edit` |
| ↳ 1095 | Spin1 |  | `msctls_updown32` |
| ↳ 65535 | 下: |  | `Static` |
| ↳ 1002 |  |  | `Edit` |
| ↳ 1096 | Spin1 |  | `msctls_updown32` |
| ↳ 65535 | 左: |  | `Static` |
| ↳ 1097 |  |  | `Edit` |
| ↳ 1098 | Spin1 |  | `msctls_updown32` |
| ↳ 65535 | 右: |  | `Static` |
| ↳ 1099 |  |  | `Edit` |
| ↳ 1100 | Spin1 |  | `msctls_updown32` |
| ↳ 65535 | 缩放 |  | `Button` |
| ↳ 1117 | 缩放到纸宽 |  | `Button` |
| ↳ 1118 | 如超宽则压缩到纸宽 |  | `Button` |
| ↳ 1121 | 自定义: |  | `Button` |
| ↳ 1115 | 缩放百分比: |  | `Static` |
| ↳ 1119 |  |  | `Edit` |
| ↳ 1120 | Spin1 |  | `msctls_updown32` |
| ↳ 65535 | 打印范围 |  | `Button` |
| ↳ 65535 | 奇偶页方式: |  | `Static` |
| ↳ 1101 |  |  | `ComboBox` |
| ↳ 1102 | 打印所有页 |  | `Button` |
| ↳ 1103 | 打印页范围 |  | `Button` |
| ↳ 1104 | 打印行范围 |  | `Button` |
| ↳ 1085 | 起始页号: |  | `Static` |
| ↳ 1105 |  |  | `Edit` |
| ↳ 1106 | Spin1 |  | `msctls_updown32` |
| ↳ 1086 | 结束页号: |  | `Static` |
| ↳ 1107 |  |  | `Edit` |
| ↳ 1108 | Spin1 |  | `msctls_updown32` |
| ↳ 1109 | 打印到结尾 |  | `Button` |
| ↳ 65535 | 打印份数: |  | `Static` |
| ↳ 1091 |  |  | `Edit` |
| ↳ 1093 | Spin1 |  | `msctls_updown32` |
| ↳ 65535 | 页号位置: |  | `Static` |
| ↳ 1110 |  |  | `ComboBox` |
| ↳ 65535 | 首页打印页号: |  | `Static` |
| ↳ 1111 |  |  | `Edit` |
| ↳ 1112 | Spin1 |  | `msctls_updown32` |
| ↳ 1012 | 自动重复尾行填充尾页空白 |  | `Button` |
| ↳ 1094 | 自动添加表格线 |  | `Button` |
| ↳ 65535 | 每页打印行数(为0自动判断): |  | `Static` |
| ↳ 1113 |  |  | `Edit` |
| ↳ 1114 | Spin1 |  | `msctls_updown32` |
| ↳ 1 | 确认(&O) |  | `Button` |
| ↳ 2 | 取消(&C) |  | `Button` |
| `1124` | 页面跳转: | 4 | DIALOG |
| ↳ 1128 | # |  | `Static` |
| ↳ 1001 |  |  | `Edit` |
| ↳ 1 | 确定(&O) |  | `Button` |
| ↳ 2 | 取消(&C) |  | `Button` |
| `1134` | 正在打印，请稍候... | 3 | DIALOG |
| ↳ 2 | 中止打印(&C) |  | `Button` |
| ↳ 1135 | Progress1 |  | `msctls_progress32` |
| ↳ 1128 | # |  | `Static` |
| `1150` | 请输入： | 4 | DIALOG |
| ↳ 1001 |  |  | `Edit` |
| ↳ 1002 |  |  | `Edit` |
| ↳ 1 | 确认输入(&O) |  | `Button` |
| ↳ 2 | 取消(&C) |  | `Button` |
| `150` |  | 4 | DIALOG |
| ↳ 1078 |  |  | `Static` |
| ↳ 1001 |  |  | `Edit` |
| ↳ 1012 |  |  | `Button` |
| ↳ 1013 | ... |  | `Button` |
| `286` |  | 9 | DIALOG |
| ↳ 1002 |  |  | `Edit` |
| ↳ 1001 |  |  | `Edit` |
| ↳ 5 | 演播(&P) |  | `Button` |
| ↳ 7 | 停止演播(&T) |  | `Button` |
| ↳ 6 | 清空(&E) |  | `Button` |
| ↳ 3 | 导入(&I) |  | `Button` |
| ↳ 4 | 导出(&O) |  | `Button` |
| ↳ 1 | 保存退出(&S) |  | `Button` |
| ↳ 2 | 取消退出(&C) |  | `Button` |
| `30721` | 新建 | 5 | DIALOG |
| ↳ 65535 | 新建(&N) |  | `Static` |
| ↳ 100 |  |  | `ListBox` |
| ↳ 1 | 确定 |  | `Button` |
| ↳ 2 | 取消 |  | `Button` |
| ↳ 57670 | 帮助(&H) |  | `Button` |
| `30722` | 正在进行打印，请稍候 ...... | 10 | DIALOG |
| ↳ 65535 | 打印作业名： |  | `Static` |
| ↳ 2 | 中止打印 |  | `Button` |
| ↳ 65535 | 打印目的： |  | `Static` |
| ↳ 65535 | 已打印份数： |  | `Static` |
| ↳ 65535 | 当前页号： |  | `Static` |
| ↳ 1008 | # |  | `Static` |
| ↳ 65535 |  |  | `Static` |
| ↳ 1009 | # |  | `Static` |
| ↳ 1010 | # |  | `Static` |
| ↳ 1011 | # |  | `Static` |
| `554` | 密码输入 | 6 | DIALOG |
| ↳ 65535 | 请输入数据库访问密码： |  | `Static` |
| ↳ 65535 | 1151 |  | `Static` |
| ↳ 1017 |  |  | `Static` |
| ↳ 1001 |  |  | `Edit` |
| ↳ 1 | 确认(&O) |  | `Button` |
| ↳ 2 | 取消(&C) |  | `Button` |
| `FIGURES_IDD_ABOUTBOX` | 关于递归视图制作工具 | 3 | DIALOG |
| ↳ 65535 | 递归视图制作工具 1.0 版 |  | `Static` |
| ↳ 65535 | 大连大有吴涛易语言软件开发有限公司 版权所有 (C) 2004 |  | `Static` |
| ↳ 1 | 确定 |  | `Button` |
| `FIGURES_IDD_DLG_VGC_DESIGN` | 设置“图形窗口.文档内容” | 5 | DIALOG |
| ↳ 1007 | Static |  | `Static` |
| ↳ 1008 | Static |  | `Static` |
| ↳ 1009 | 视图管理... |  | `Button` |
| ↳ 1 | 确定(&O) |  | `Button` |
| ↳ 2 | 取消 |  | `Button` |
| `FIGURES_IDD_OBJ_DIALOG` |  | 54 | DIALOG |
| ↳ 1010 | 欲跳转到的视图名称： |  | `Static` |
| ↳ 1003 |  |  | `ComboBox` |
| ↳ 127 | 水平位置: |  | `Static` |
| ↳ 128 |  |  | `Edit` |
| ↳ 129 | Spin1 |  | `msctls_updown32` |
| ↳ 130 | 垂直位置: |  | `Static` |
| ↳ 131 |  |  | `Edit` |
| ↳ 132 | Spin1 |  | `msctls_updown32` |
| ↳ 133 | 宽度: |  | `Static` |
| ↳ 134 |  |  | `Edit` |
| ↳ 135 | Spin1 |  | `msctls_updown32` |
| ↳ 136 | 高度: |  | `Static` |
| ↳ 137 |  |  | `Edit` |
| ↳ 138 | Spin1 |  | `msctls_updown32` |
| ↳ 139 | 旋转角度: |  | `Static` |
| ↳ 140 |  |  | `Edit` |
| ↳ 141 | Spin1 |  | `msctls_updown32` |
| ↳ 142 | 文本: |  | `Static` |
| ↳ 143 | 字体...(&T) |  | `Button` |
| ↳ 144 | 水平对齐: |  | `Static` |
| ↳ 145 |  |  | `ComboBox` |
| ↳ 146 | 垂直对齐: |  | `Static` |
| ↳ 147 |  |  | `ComboBox` |
| ↳ 101 | 阴影方向: |  | `Static` |
| ↳ 102 |  |  | `ComboBox` |
| ↳ 103 | 颜色: |  | `Static` |
| ↳ 104 |  |  | `Button` |
| ↳ 105 | 宽度: |  | `Static` |
| ↳ 106 |  |  | `Edit` |
| ↳ 107 | Spin1 |  | `msctls_updown32` |
| ↳ 108 | 线条颜色: |  | `Static` |
| ↳ 109 |  |  | `Button` |
| ↳ 110 | 类型: |  | `Static` |
| ↳ 111 |  |  | `ComboBox` |
| ↳ 112 | 宽度: |  | `Static` |
| ↳ 113 |  |  | `Edit` |
| ↳ 114 | Spin1 |  | `msctls_updown32` |
| ↳ 115 | 填充风格: |  | `Static` |
| ↳ 116 |  |  | `ComboBox` |
| ↳ 123 | 颜色: |  | `Static` |
| ↳ 124 |  |  | `Button` |
| ↳ 125 | 图像设置(&P) |  | `Button` |
| ↳ 117 | 前景: |  | `Static` |
| ↳ 118 |  |  | `Button` |
| ↳ 119 | 背景: |  | `Static` |
| ↳ 120 |  |  | `Button` |
| ↳ 121 | 类型: |  | `Static` |
| ↳ 122 |  |  | `ComboBox` |
| ↳ 65535 | 位置、文本 |  | `Button` |
| ↳ 65535 | 阴影、线条、填充 |  | `Button` |
| ↳ 148 | 放置方法: |  | `Static` |
| ↳ 149 |  |  | `ComboBox` |
| ↳ 1 | 确定(&O) |  | `Button` |
| ↳ 2 | 取消(&C) |  | `Button` |
| `FIGURES_IDD_RICHLINE_DIALOG` | 线条端点设定: | 6 | DIALOGEX |
| ↳ 4294967295 | 端点类型: |  | `Static` |
| ↳ 143 |  |  | `ComboBox` |
| ↳ 4294967295 | 端点尺寸: |  | `Static` |
| ↳ 142 |  |  | `ComboBox` |
| ↳ 1 | 确定(&O) |  | `Button` |
| ↳ 2 | 取消(&C) |  | `Button` |
| `FIGURES_IDD_TEXTBOXDIALOG` | 请输入文本(Esc键退出): | 1 | DIALOGEX |
| ↳ 141 |  |  | `Edit` |
| `FIGURES_IDD_VIEW_DLG` | 文档管理 | 7 | DIALOG |
| ↳ 65535 | 文档名称： |  | `Static` |
| ↳ 141 |  |  | `Edit` |
| ↳ 1000 |  |  | `ListBox` |
| ↳ 3 | 添加(&A) |  | `Button` |
| ↳ 4 | 删除(&D) |  | `Button` |
| ↳ 1 | 跳转(&G) |  | `Button` |
| ↳ 2 | 关闭(&C) |  | `Button` |
| `FIGURES_IDD_WORK` |  | 3 | DIALOG |
| ↳ 1000 |  |  | `ListBox` |
| ↳ 1001 |  |  | `ComboBox` |
| ↳ 1002 | # |  | `Static` |
