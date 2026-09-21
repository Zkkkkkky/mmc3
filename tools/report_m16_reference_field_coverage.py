from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLS = ROOT / "output/verification/legacy-m16-reference-controls-20260920/catalog.json"
CANDIDATES = ROOT / "output/verification/legacy-m16-reference-save-candidates-20260920/candidates.json"
SINGLE_SAVE = ROOT / "output/verification/legacy-m16-reference-single-save-20260920/result.json"
IMPLEMENTATION = ROOT / "output/verification/m16-save-compatibility.json"
DEFAULT_JSON = ROOT / "output/reports/m16-reference-field-coverage.json"
DEFAULT_MD = ROOT / "output/reports/m16-reference-field-coverage.md"


UPPER_MUTABLE = ("人物", "机体", "等级", "机动", "强度", "防御", "速度", "HP", "EXP")
LOWER_MUTABLE = ("人物", "等级", "机动", "强度", "防御", "速度", "HP")


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def build() -> dict[str, object]:
    controls = load(CONTROLS)
    candidates = load(CANDIDATES)
    single = load(SINGLE_SAVE)
    implementation = load(IMPLEMENTATION)
    upper_headers = tuple(str(value) for value in controls["upper"]["headers"])
    lower_headers = ("序号", "人物", "机体", "等级", "机动", "强度", "防御", "速度", "HP", "金钱", "双击速度")
    candidate_rows = list(candidates["candidates"])
    error_texts = [" ".join(str(value) for value in item.get("dialogs", [])) for item in candidate_rows]
    write_texts = " ".join(
        text
        for window in single["windows_after_write"]
        for text in window.get("texts", [])
    )
    fields = [
        {
            "field_id": "save_slot_selector",
            "family": "navigation",
            "classification": "navigation_only",
            "reason": "三项存档槽下拉仅选择读取目标，不是持久字段。",
        },
        {
            "field_id": "chapter_selector",
            "family": "chapter",
            "classification": "reference_runtime_error_blocked",
            "reason": "关卡下拉可选择 32 项，但所有现有 8 KiB 样本读取后均触发参考版运行时错误，无法形成保存证据。",
        },
    ]
    for header in UPPER_MUTABLE:
        fields.append(
            {
                "field_id": f"upper.{header}",
                "family": "upper_table",
                "classification": "reference_runtime_error_blocked",
                "reason": "参考表格可显示该列，但逐列双击无编辑控件，强制改单元格后写入触发运行时错误且磁盘零差分。",
            }
        )
    for header in LOWER_MUTABLE:
        fields.append(
            {
                "field_id": f"lower.{header}",
                "family": "lower_table",
                "classification": "reference_runtime_error_blocked",
                "reason": "15 份现有样本在参考版下表均为 0 行，读取即报错，无法生成合法字段实例。",
            }
        )
    checks = {
        "control_probe_passed": bool(controls["passed"]),
        "rom_and_save_unchanged": bool(controls["rom_unchanged"] and controls["save_unchanged"]),
        "physical_controls_enumerated": len(controls["visible_controls"]) == 12,
        "upper_headers_complete": upper_headers == lower_headers[:9] + ("EXP", "双击速度"),
        "all_upper_columns_probed": len(controls["upper_column_probes"]) == 11,
        "no_inplace_editor_exposed": all(
            not item["new_controls"] and not item["new_edit_or_combo"]
            for item in controls["upper_column_probes"]
        ),
        "all_preserved_saves_scanned": bool(candidates["passed"]) and int(candidates["count"]) == 15,
        "all_slots_rejected_by_reference": all(item.get("slot_selected") == "1：没有数据" for item in candidate_rows),
        "all_lower_tables_empty": all(int(item.get("lower_rows", -1)) == 0 for item in candidate_rows),
        "all_reads_raise_runtime_error_4": all("错误代码：4" in text for text in error_texts),
        "forced_exp_write_rejected": "错误代码：4" in write_texts,
        "forced_exp_disk_zero_diff": not single["disk_changed_after_set"] and not single["disk_changed_after_write"] and not single["disk_changed_after_save"] and not single["ranges_after_save"],
        "product_safe_codec_still_passes": bool(implementation["passed"]),
    }
    blocked = sum(item["classification"] == "reference_runtime_error_blocked" for item in fields)
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "module": "M16",
        "passed": all(checks.values()),
        "delivery_status": "reference_control_scope_complete_runtime_blocked_user_pending",
        "physical_controls": 13,
        "logical_field_families": len(fields),
        "safe_denominator_fields": 0,
        "classification_counts": {
            "navigation_only": 1,
            "reference_runtime_error_blocked": blocked,
        },
        "checks": checks,
        "evidence": {
            "controls": CONTROLS.relative_to(ROOT).as_posix(),
            "save_candidates": CANDIDATES.relative_to(ROOT).as_posix(),
            "single_save": SINGLE_SAVE.relative_to(ROOT).as_posix(),
            "implementation": IMPLEMENTATION.relative_to(ROOT).as_posix(),
        },
        "limitations": [
            "仓库保存的 15 份 8 KiB SAV 均被参考版显示为“1：没有数据”，读取后统一报运行时错误 4。",
            "参考版上表 11 列均未暴露双击编辑器；下表在全部样本中均为 0 行。",
            "强制将首行 EXP 3884 改为 3885 后，写入按钮仍报错误 4，隔离 SAV 保持逐字节不变。",
            "产品 8 KiB/三槽/校验和实现继续由独立安全协议证据守护，但不冒充参考版保存黄金。",
        ],
        "fields": fields,
    }


def markdown(report: dict[str, object]) -> str:
    return "\n".join(
        [
            "# M16 参考版控件与保存覆盖",
            "",
            f"- 物理控件：{report['physical_controls']}",
            f"- 逻辑字段族：{report['logical_field_families']}",
            f"- 安全分母：{report['safe_denominator_fields']}",
            f"- 参考运行时错误排除：{report['classification_counts']['reference_runtime_error_blocked']}",
            f"- 状态：`{report['delivery_status']}`",
            "",
            "15 份现有 8 KiB 存档均被参考版判为无有效槽并在读取后报错误 4；逐列双击无编辑控件，强制 EXP 写入亦为磁盘零差分。因此 M16 的参考控件范围已封口，但没有可进入 G1 的参考安全持久字段。产品存档协议按独立证据继续开放，用户验收仍单独保留。",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()
    report = build()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "logical_field_families": report["logical_field_families"], "safe_denominator_fields": report["safe_denominator_fields"], "classification_counts": report["classification_counts"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
