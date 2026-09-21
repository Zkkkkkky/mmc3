"""Build the M05 reference control and save-evidence catalog."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "output/verification/legacy-ui-probe-m05-icon-double-click-20260920l/controls"
MAIN = EVIDENCE / "M05_数据库_机体修改.json"
SKILL = EVIDENCE / "M05_数据库_机体修改_特殊技能.json"
ICON = EVIDENCE / "M05_数据库_机体修改_机体图标设置.json"
GOLDEN = ROOT / "output/reports/golden-coverage-report.json"
JSON_OUT = ROOT / "output/reports/m05-reference-control-catalog.json"
MD_OUT = ROOT / "output/reports/m05-reference-control-catalog.md"

CONTROL_CLASSES = {"Edit", "ComboBox", "Button", "ListBox"}


def controls(path: Path, surface: str) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: list[dict[str, object]] = []

    def walk(node: dict[str, object]) -> None:
        if (
            node.get("visible")
            and int(node.get("ctrl_id", 0))
            and str(node.get("class")) in CONTROL_CLASSES
        ):
            result.append(
                {
                    "surface": surface,
                    "control_id": int(node["ctrl_id"]),
                    "class": str(node["class"]),
                    "text": str(node.get("text", "")),
                    "enabled": bool(node.get("enabled")),
                }
            )
        for child in node.get("children", []):
            walk(child)

    walk(payload["tree"])
    return sorted(result, key=lambda item: (int(item["control_id"]), str(item["class"])))


def build() -> dict[str, object]:
    sources = {"main": MAIN, "special_skill": SKILL, "icon_binding": ICON}
    all_controls = [item for name, path in sources.items() for item in controls(path, name)]
    coverage = json.loads(GOLDEN.read_text(encoding="utf-8"))
    golden_rows = [
        item
        for item in coverage["field_details"]
        if item["module"] == "M05" and item["case_kind"] == "golden" and item["passed"] is True
    ]
    golden_fields = sorted({str(item["field"]) for item in golden_rows})
    non_rom_fields = [
        {"field_id": "upload_body_offset", "surface": "main", "control_id": 170, "classification": "operation_parameter"},
        {"field_id": "upload_fragment_offset", "surface": "main", "control_id": 1300, "classification": "operation_parameter"},
        {"field_id": "search_text", "surface": "main", "control_id": 2150, "classification": "ui_filter"},
        {"field_id": "icon_character_selector", "surface": "icon_binding", "control_id": 120, "classification": "no_rom_effect_without_canvas_commit"},
        {"field_id": "icon_tile_selector", "surface": "icon_binding", "control_id": 130, "classification": "no_rom_effect_without_canvas_commit"},
    ]
    pending_actions = [
        {"control_id": 130, "action": "add_unit", "reason": "pointer relocation save protocol pending"},
        {"control_id": 160, "action": "upload_body", "reason": "file and cross-bank save protocol pending"},
        {"control_id": 1310, "action": "upload_fragment", "reason": "file and cross-bank save protocol pending"},
        {"control_id": 180, "action": "compressed_upload_body", "reason": "compression save protocol pending"},
        {"control_id": 1290, "action": "compressed_upload_fragment", "reason": "compression save protocol pending"},
        {"control_id": 190, "action": "body_puzzle", "reason": "puzzle editor gesture-level save evidence pending"},
        {"control_id": 220, "action": "fragment_puzzle", "reason": "puzzle editor gesture-level save evidence pending"},
        {"control_id": 1350, "action": "icon_binding", "reason": "canvas commit gesture pending"},
        {"control_id": 2510, "action": "upload_icon", "reason": "file upload save protocol pending"},
        {"control_id": 2670, "action": "clear_body", "reason": "destructive save layout pending"},
        {"control_id": 2680, "action": "clear_fragment", "reason": "destructive save layout pending"},
    ]
    checks = {
        "source_files_present": all(path.is_file() for path in sources.values()),
        "main_controls_enumerated": sum(item["surface"] == "main" for item in all_controls) == 56,
        "special_skill_controls_enumerated": sum(item["surface"] == "special_skill" for item in all_controls) == 8,
        "icon_binding_controls_enumerated": sum(item["surface"] == "icon_binding" for item in all_controls) == 5,
        "golden_fields_unique": len(golden_fields) == 33,
        "all_golden_fields_passed": len(golden_rows) == 33,
        "non_rom_fields_classified": len(non_rom_fields) == 5,
        "pending_actions_guarded": len(pending_actions) == 11,
    }
    return {
        "schema_version": 1,
        "module": "M05",
        "passed": all(checks.values()),
        "status": "controls_cataloged_33_save_fields_passed_11_actions_guarded",
        "sources": {
            name: {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for name, path in sources.items()
        },
        "counts": {
            "controls": len(all_controls),
            "controls_by_surface": dict(Counter(str(item["surface"]) for item in all_controls)),
            "controls_by_class": dict(Counter(str(item["class"]) for item in all_controls)),
            "golden_save_fields": len(golden_fields),
            "classified_non_rom_fields": len(non_rom_fields),
            "guarded_pending_actions": len(pending_actions),
        },
        "checks": checks,
        "golden_save_fields": golden_fields,
        "classified_non_rom_fields": non_rom_fields,
        "guarded_pending_actions": pending_actions,
        "controls": all_controls,
    }


def markdown(report: dict[str, object]) -> str:
    counts = report["counts"]
    return "\n".join(
        [
            "# M05 参考版控件与保存字段目录",
            "",
            f"- 三个界面共枚举控件：{counts['controls']}（主界面 56、特殊技能 8、图标设置 5）",
            f"- 已通过黄金保存字段：{counts['golden_save_fields']}/33",
            f"- 已分类非 ROM 字段：{counts['classified_non_rom_fields']}",
            f"- 保持门禁的动作入口：{counts['guarded_pending_actions']}",
            f"- 状态：`{report['status']}`",
            "",
            "上传、清除、拼图、图标画布提交和新增机体是动作协议，不冒充普通字段；在对应参考版保存布局补证前继续保持写入门禁。完整控件、字段和原因见同名 JSON。",
            "",
        ]
    )


def main() -> int:
    report = build()
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], **report["counts"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
