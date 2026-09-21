# -*- coding: utf-8 -*-
"""临时脚本：提取 M10/M11 相关菜单项证据（任务 #10）。"""
import json
import re

P = r"output\verification\legacy-ui-probe\controls\B03_完整菜单树.json"
s = json.dumps(json.load(open(P, encoding="utf-8")), ensure_ascii=False)
for kw in ("文字库", "数据库", "其他修改", "字库"):
    print("==", kw, "==")
    for h in dict.fromkeys(re.findall(r'[^",\[\]{}]*' + kw + r'[^",\[\]{}]*', s)):
        print("  ", h.strip())
