# -*- coding: utf-8 -*-
"""任务 #10 自查脚本：9 文件 8 节齐全 / F 编号统计 / 行数 / D 标记 / M14 新口径 / 证据路径存在性"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

BASE = r"d:\LLM\项目\FC\扩容MMC3"
SPLIT_DIR = os.path.join(BASE, "docs", "需求拆分")
PROBE = os.path.join(BASE, "output", "verification", "legacy-ui-probe")

# 文件名 -> 第 11 章对应小表行数（预期 F 编号数）
FILES = {
    "M10_其他修改2.md": 6,
    "M11_字库编辑.md": 4,
    "M12_地图动画.md": 8,
    "M13_文字转换.md": 2,
    "M14_剧情事件.md": 12,
    "M15_属性计算器.md": 4,
    "M16_存档修改器.md": 3,
    "M17_其他窗口.md": 5,
    "M18_导出机体与头像.md": 2,
}
D_MARK = {
    "M14_剧情事件.md": None,  # 无 D 决策，但需检查新口径
    "M15_属性计算器.md": "D6",
    "M16_存档修改器.md": "D4",
    "M18_导出机体与头像.md": "D2",
}

ok_all = True
evidence_paths = []  # (来源文件, 相对路径)

for name, expected_f in FILES.items():
    path = os.path.join(SPLIT_DIR, name)
    print("=" * 70)
    print(f"文件: {name}")
    if not os.path.exists(path):
        print("  [FAIL] 文件不存在!")
        ok_all = False
        continue
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    n_lines = len(lines)
    # 1) 行数 120-260
    line_ok = 120 <= n_lines <= 260
    print(f"  行数: {n_lines} (要求 120-260) -> {'OK' if line_ok else 'FAIL'}")
    ok_all &= line_ok
    # 2) 8 节齐全
    secs = [l.strip() for l in lines if re.match(r"^## \d", l.strip())]
    sec_ok = len(secs) == 8
    print(f"  ## 节标题数: {len(secs)} -> {'OK' if sec_ok else 'FAIL: ' + str(secs)}")
    ok_all &= sec_ok
    # 3) F 编号（仅统计第 2 节功能点清单表内——任务书"逐表统计"口径；
    #    正文其他位置的跨模块交叉引用（如 M10 引 F-094 归属 M17）不计入）
    sec2 = "\n".join(lines[lines.index(next(l for l in lines if l.startswith("## 2."))):
                        lines.index(next(l for l in lines if l.startswith("## 3.")))])
    fids = sorted(set(re.findall(r"F-\d{3}", sec2)))
    xrefs = sorted(set(re.findall(r"F-\d{3}", "\n".join(lines))) - set(fids))
    fcnt_ok = len(fids) == expected_f
    print(f"  清单表 F 编号 ({len(fids)} 个, 预期 {expected_f}): {', '.join(fids)} -> {'OK' if fcnt_ok else 'FAIL'}")
    if xrefs:
        print(f"  （正文跨模块交叉引用不计入: {', '.join(xrefs)}）")
    ok_all &= fcnt_ok
    # 4) D 标记
    if D_MARK.get(name):
        d = D_MARK[name]
        has_d = any(f"> 决策依赖：**{d}" in l or f"决策依赖：**{d}（待决策" in l for l in lines[:8])
        print(f"  决策依赖 {d}（待决策）: {'OK' if has_d else 'FAIL'}")
        ok_all &= has_d
    if name == "M14_剧情事件.md":
        text = "\n".join(lines)
        has_new = ("用户 2026-09-14" in text) and ("六类事件" in text or "界面事件和回合事件" in text)
        print(f"  按钮 690 新口径+待补证据标注: {'OK' if has_new else 'FAIL'}")
        ok_all &= has_new
    # 5) 归一化偏移剔除说明
    text = "\n".join(lines)
    has_norm = "0x4A101" in text and "0x79539" in text
    print(f"  归一化偏移剔除说明: {'OK' if has_norm else 'FAIL'}")
    ok_all &= has_norm
    # 收集证据路径（探针产物引用）
    for m in re.findall(r"(?:screenshots|controls)/[^\s\)\|、；，]+?\.(?:png|json)", text):
        evidence_paths.append((name, m))
    if "summary.md" in text:
        pass  # summary.md 引用单独处理

print("=" * 70)
print(f"证据路径抽查（全部引用共 {len(evidence_paths)} 条，逐条核验存在性）：")
miss = 0
for src, rel in evidence_paths:
    full = os.path.join(PROBE, rel.replace("/", os.sep))
    exists = os.path.exists(full)
    if not exists:
        miss += 1
        print(f"  [MISS] {src} -> {rel}")
checked = len(evidence_paths)
print(f"  核验 {checked} 条, 缺失 {miss} 条 -> {'OK' if miss == 0 and checked >= 10 else 'FAIL'}")
ok_all &= (miss == 0 and checked >= 10)

print("=" * 70)
print("总体结果:", "PASS" if ok_all else "FAIL")
