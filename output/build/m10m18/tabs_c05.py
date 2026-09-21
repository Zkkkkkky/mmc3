# -*- coding: utf-8 -*-
"""提取剧情事件 C05P 系列 JSON 中指定容器的子树控件清单。"""
import json
import os

VER = r"d:\LLM\项目\FC\扩容MMC3\output\verification\legacy-ui-probe\controls"


def dump_container(fname, container_id, max_depth=6):
    p = os.path.join(VER, fname)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    tree = data.get("tree") or {}

    def find(node, cid):
        if node.get("ctrl_id") == cid:
            return node
        for c in node.get("children") or []:
            r = find(c, cid)
            if r:
                return r
        return None

    target = find(tree, container_id)
    if not target:
        print(f"{fname}: 容器 {container_id} 未找到")
        return
    r = target.get("rect") or {}
    print(f"=== {fname} 容器{container_id} '{(target.get('text') or '')[:30]}' ({r.get('width')}x{r.get('height')}) ===")

    def walk(node, depth):
        if depth > max_depth:
            return
        cls = node.get("class") or ""
        cid = node.get("ctrl_id")
        txt = (node.get("text") or "").replace("\n", "\\n")[:36]
        rr = node.get("rect") or {}
        print(f"  {'  '*depth}[{cls}] id={cid} {txt!r} ({rr.get('width')}x{rr.get('height')})")
        for c in node.get("children") or []:
            walk(c, depth + 1)

    for c in target.get("children") or []:
        walk(c, 1)
    print()


# 标题拼图设置容器 180（关卡设置页内）
dump_container("C05P_剧情事件_标题拼图设置.json", 180)

# 事件编辑容器 250（行动事件页）
dump_container("C05P_剧情事件_容器250_事件编辑.json", 250)

# 事件编辑容器 170（关卡设置页内，含三子页签 130/140/150/160）
dump_container("C05P_剧情事件_事件编辑_初始页.json", 170)
