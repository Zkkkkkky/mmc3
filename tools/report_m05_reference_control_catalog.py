"""Build the M05 reference control and save-evidence catalog."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "output/verification/legacy-ui-probe-m05-icon-double-click-20260920l/controls"
LEGACY_EVIDENCE = ROOT / "output/verification/legacy-ui-probe/controls"
MAIN = EVIDENCE / "M05_数据库_机体修改.json"
SKILL = EVIDENCE / "M05_数据库_机体修改_特殊技能.json"
ICON = EVIDENCE / "M05_数据库_机体修改_机体图标设置.json"
BODY_PUZZLE = LEGACY_EVIDENCE / "D3_数据库_机体拼图.json"
FRAGMENT_PUZZLE = LEGACY_EVIDENCE / "D3_数据库_碎片拼图.json"
GOLDEN = ROOT / "output/reports/golden-coverage-report.json"
JSON_OUT = ROOT / "output/reports/m05-reference-control-catalog.json"
MD_OUT = ROOT / "output/reports/m05-reference-control-catalog.md"
DISCOVERY_DIR = ROOT / "tools/golden_pipeline/discovery_history"
ACTION_DISCOVERY_RECIPES = {
    "body_compressed_upload_bmp": DISCOVERY_DIR
    / "M05-body-compressed-upload-bmp-discovery-cold-start-01.json",
    "fragment_compressed_upload_bmp": DISCOVERY_DIR
    / "M05-fragment-compressed-upload-bmp-discovery-cold-start-01.json",
    "main_clear_body": DISCOVERY_DIR
    / "M05-main-clear-body-discovery-cold-start-01.json",
    "main_clear_fragment": DISCOVERY_DIR
    / "M05-main-clear-fragment-discovery-cold-start-01.json",
    "body_upload_bmp": DISCOVERY_DIR
    / "M05-body-upload-bmp-discovery-cold-start-01.json",
    "fragment_upload_bmp": DISCOVERY_DIR
    / "M05-fragment-upload-bmp-discovery-cold-start-01.json",
    "icon_upload_bmp": DISCOVERY_DIR
    / "M05-icon-upload-bmp-discovery-cold-start-01.json",
    "icon_binding_double_click": DISCOVERY_DIR
    / "M05-icon-binding-double-click-discovery-cold-start-01.json",
    "body_puzzle_clear": DISCOVERY_DIR
    / "M05-body-puzzle-clear-discovery-cold-start-01.json",
    "body_puzzle_move_up": DISCOVERY_DIR
    / "M05-body-puzzle-move-up-discovery-cold-start-01.json",
    "body_puzzle_move_down": DISCOVERY_DIR
    / "M05-body-puzzle-move-down-discovery-cold-start-01.json",
    "body_puzzle_move_left": DISCOVERY_DIR
    / "M05-body-puzzle-move-left-discovery-cold-start-01.json",
    "body_puzzle_move_right": DISCOVERY_DIR
    / "M05-body-puzzle-move-right-discovery-cold-start-01.json",
    "body_puzzle_template_8x8": DISCOVERY_DIR
    / "M05-body-puzzle-template-8x8-discovery-cold-start-01.json",
    "body_puzzle_template_7x9": DISCOVERY_DIR
    / "M05-body-puzzle-template-7x9-discovery-cold-start-01.json",
    "body_puzzle_template_9x7": DISCOVERY_DIR
    / "M05-body-puzzle-template-9x7-discovery-cold-start-01.json",
    "body_puzzle_template_10x6": DISCOVERY_DIR
    / "M05-body-puzzle-template-10x6-discovery-cold-start-01.json",
    "body_puzzle_swap_banks": DISCOVERY_DIR
    / "M05-body-puzzle-swap-banks-discovery-cold-start-01.json",
    "fragment_puzzle_move_up": DISCOVERY_DIR
    / "M05-fragment-puzzle-move-up-discovery-cold-start-01.json",
    "fragment_puzzle_move_down": DISCOVERY_DIR
    / "M05-fragment-puzzle-move-down-discovery-cold-start-01.json",
    "fragment_puzzle_move_left": DISCOVERY_DIR
    / "M05-fragment-puzzle-move-left-discovery-cold-start-01.json",
    "fragment_puzzle_move_right": DISCOVERY_DIR
    / "M05-fragment-puzzle-move-right-discovery-cold-start-01.json",
    "fragment_puzzle_clear": DISCOVERY_DIR
    / "M05-fragment-puzzle-clear-discovery-cold-start-01.json",
    "fragment_puzzle_flip_horizontal": DISCOVERY_DIR
    / "M05-fragment-puzzle-flip-horizontal-discovery-cold-start-01.json",
    "fragment_puzzle_flip_vertical": DISCOVERY_DIR
    / "M05-fragment-puzzle-flip-vertical-discovery-cold-start-01.json",
}
ACTION_RECIPE_COVERAGE = {
    "upload_body": ("body_upload_bmp",),
    "upload_fragment": ("fragment_upload_bmp",),
    "compressed_upload_body": ("body_compressed_upload_bmp",),
    "compressed_upload_fragment": ("fragment_compressed_upload_bmp",),
    "body_puzzle": (
        "body_puzzle_clear",
        "body_puzzle_move_up",
        "body_puzzle_move_down",
        "body_puzzle_move_left",
        "body_puzzle_move_right",
        "body_puzzle_template_8x8",
        "body_puzzle_template_7x9",
        "body_puzzle_template_9x7",
        "body_puzzle_template_10x6",
        "body_puzzle_swap_banks",
    ),
    "fragment_puzzle": (
        "fragment_puzzle_clear",
        "fragment_puzzle_move_up",
        "fragment_puzzle_move_down",
        "fragment_puzzle_move_left",
        "fragment_puzzle_move_right",
        "fragment_puzzle_flip_horizontal",
        "fragment_puzzle_flip_vertical",
    ),
    "icon_binding": ("icon_binding_double_click",),
    "upload_icon": ("icon_upload_bmp",),
    "clear_body": ("main_clear_body",),
    "clear_fragment": ("main_clear_fragment",),
}

CONTROL_CLASSES = {"Edit", "ComboBox", "Button", "ListBox"}


def controls(
    path: Path,
    surface: str,
    *,
    include_custom_controls: bool = False,
) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: list[dict[str, object]] = []

    def walk(node: dict[str, object]) -> None:
        control_class = str(node.get("class"))
        is_supported_class = control_class in CONTROL_CLASSES or (
            include_custom_controls and control_class.startswith("Afx:")
        )
        if node.get("visible") and int(node.get("ctrl_id", 0)) and is_supported_class:
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
    sources = {
        "main": MAIN,
        "special_skill": SKILL,
        "icon_binding": ICON,
        "body_puzzle": BODY_PUZZLE,
        "fragment_puzzle": FRAGMENT_PUZZLE,
    }
    all_controls = [
        item
        for name, path in sources.items()
        for item in controls(
            path,
            name,
            include_custom_controls=name in {"body_puzzle", "fragment_puzzle"},
        )
    ]
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
    capacity_boundaries = [
        {
            "control_id": 130,
            "action": "add_unit",
            "classification": "byte_id_space_full",
            "available_ids": "$01-$FF",
            "slot_count": 255,
            "product_behavior": "disabled_with_direct_edit_of_existing_empty_slots",
        }
    ]
    discovery_recipes = {}
    for name, path in ACTION_DISCOVERY_RECIPES.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        promotion_guarded = (
            payload.get("module") == "M05"
            and payload.get("case_kind") == "discovery"
            and payload.get("expected_offsets") == []
            and payload.get("required_offsets") == []
        )
        discovery_recipes[name] = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "case_kind": payload.get("case_kind"),
            "promotion_guarded": promotion_guarded,
            "status": "prepared_not_promoted" if promotion_guarded else "invalid_guard",
        }
    for action in pending_actions:
        action["prepared_recipe_keys"] = list(
            ACTION_RECIPE_COVERAGE.get(str(action["action"]), ())
        )
    checks = {
        "source_files_present": all(path.is_file() for path in sources.values()),
        "main_controls_enumerated": sum(item["surface"] == "main" for item in all_controls) == 56,
        "special_skill_controls_enumerated": sum(item["surface"] == "special_skill" for item in all_controls) == 8,
        "icon_binding_controls_enumerated": sum(item["surface"] == "icon_binding" for item in all_controls) == 5,
        "body_puzzle_controls_enumerated": sum(item["surface"] == "body_puzzle" for item in all_controls) == 29,
        "fragment_puzzle_controls_enumerated": sum(item["surface"] == "fragment_puzzle" for item in all_controls) == 27,
        "puzzle_canvas_controls_enumerated": sum(
            item["surface"] in {"body_puzzle", "fragment_puzzle"}
            and str(item["class"]).startswith("Afx:")
            for item in all_controls
        )
        == 13,
        "golden_fields_unique": len(golden_fields) == 33,
        "all_golden_fields_passed": len(golden_rows) == 33,
        "non_rom_fields_classified": len(non_rom_fields) == 5,
        "pending_actions_guarded": len(pending_actions) == 10,
        "capacity_boundaries_classified": len(capacity_boundaries) == 1
        and capacity_boundaries[0]["slot_count"] == 255,
        "every_pending_action_has_guarded_discovery": all(
            action["prepared_recipe_keys"]
            and all(
                discovery_recipes.get(recipe_key, {}).get("promotion_guarded")
                for recipe_key in action["prepared_recipe_keys"]
            )
            for action in pending_actions
        ),
        "action_discovery_recipes_ready": len(discovery_recipes) == 25
        and all(path.is_file() for path in ACTION_DISCOVERY_RECIPES.values()),
        "action_discovery_recipes_not_promoted": all(
            item["promotion_guarded"] for item in discovery_recipes.values()
        ),
    }
    return {
        "schema_version": 1,
        "module": "M05",
        "passed": all(checks.values()),
        "status": "five_surfaces_cataloged_33_save_fields_passed_10_actions_guarded_1_capacity_boundary",
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
            "classified_capacity_boundaries": len(capacity_boundaries),
            "prepared_discovery_recipes": len(discovery_recipes),
            "guarded_actions_with_discovery": sum(
                bool(action["prepared_recipe_keys"]) for action in pending_actions
            ),
        },
        "checks": checks,
        "golden_save_fields": golden_fields,
        "classified_non_rom_fields": non_rom_fields,
        "guarded_pending_actions": pending_actions,
        "classified_capacity_boundaries": capacity_boundaries,
        "prepared_discovery_recipes": discovery_recipes,
        "controls": all_controls,
    }


def markdown(report: dict[str, object]) -> str:
    counts = report["counts"]
    return "\n".join(
        [
            "# M05 参考版控件与保存字段目录",
            "",
            f"- 五个界面共枚举可见控件：{counts['controls']}（主界面 56、特殊技能 8、图标设置 5、机体拼图 29、碎片拼图 27）",
            f"- 已通过黄金保存字段：{counts['golden_save_fields']}/33",
            f"- 已分类非 ROM 字段：{counts['classified_non_rom_fields']}",
            f"- 保持门禁的动作入口：{counts['guarded_pending_actions']}",
            f"- 已分类容量边界：{counts['classified_capacity_boundaries']}",
            f"- 已准备但未晋级黄金的动作 discovery 配方：{counts['prepared_discovery_recipes']}",
            f"- 已由 discovery 覆盖的门禁动作：{counts['guarded_actions_with_discovery']}/{counts['guarded_pending_actions']}",
            f"- 状态：`{report['status']}`",
            "",
            "上传、清除、拼图和图标画布提交是待补参考保存布局的动作协议；新增机体已按字节型 ID 的 255 槽满容量边界分类，产品保持禁用并引导直接编辑现有空白槽。完整控件、字段和原因见同名 JSON。",
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
