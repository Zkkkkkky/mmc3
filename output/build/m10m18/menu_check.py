# -*- coding: utf-8 -*-
"""临时脚本：从 B03_完整菜单树.json 提取 M13-M18 相关菜单项证据（任务 #10）。"""
import json
import re

P = r"output\verification\legacy-ui-probe\controls\B03_完整菜单树.json"
d = json.load(open(P, encoding="utf-8"))
s = json.dumps(d, ensure_ascii=False)

for kw in ("文字转换", "属性计算", "存档", "导出", "地图动画", "剧情事件", "其他"):
    hits = re.findall(r'[^",\[\]{}]*' + kw + r'[^",\[\]{}]*', s)
    print("==", kw, "==")
    for h in dict.fromkeys(hits):
        print("  ", h.strip())
