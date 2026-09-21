"""Build the M10 logical-field catalog from the read-only reference probe."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "output/verification/legacy-m10-reference-catalog-20260920/catalog.json"
DEFAULT_JSON = ROOT / "output/reports/m10-reference-field-catalog.json"
DEFAULT_MD = ROOT / "output/reports/m10-reference-field-catalog.md"
DEFAULT_ROM = ROOT / "output/build/legacy-diff-audit/audit.nes"
DIALOGUE_EDIT_IDS = (1970, 1990, 2010, 2020, 2040, 2060, 2090)


def build(source: dict[str, object]) -> dict[str, object]:
    fields: list[dict[str, object]] = []
    for item in source["items"]:
        row = int(item["row"])
        for family, key, control_id in (
            ("item_name", "name", 1710),
            ("item_price", "price", 1730),
            ("item_description", "description", 1780),
        ):
            fields.append({
                "field_id": f"M10/{family}/{row + 1:02d}",
                "physical_id": f"M10/{family}/{row + 1:02d}",
                "family": family,
                "row": row,
                "control_id": control_id,
                "value": item[key],
                "product_safe": True,
            })
    for shop in source["shops"]:
        row = int(shop["row"])
        label = str(shop["label"])
        shop_id = int(label[-2:], 16) if len(label) >= 2 else -1
        for slot, (control_id, value) in enumerate(zip((1870, 1880, 1890, 1900), shop["item_indices"])):
            safe = shop_id < 0xF4 or (shop_id == 0xF4 and slot == 0)
            fields.append({
                "field_id": f"M10/shop/{shop_id:02X}/item/{slot + 1}",
                "physical_id": f"M10/shop/{shop_id:02X}/item/{slot + 1}",
                "family": "shop_item",
                "shop_row": row,
                "shop_id": shop_id,
                "slot": slot,
                "control_id": control_id,
                "value": int(value),
                "product_safe": safe,
            })
        for family, key, control_id in (("shop_clerk", "clerk_index", 1920), ("shop_dialogue_id", "dialogue_index", 1940)):
            fields.append({
                "field_id": f"M10/shop/{shop_id:02X}/{family.removeprefix('shop_')}",
                "physical_id": f"M10/shop/{shop_id:02X}/{family.removeprefix('shop_')}",
                "family": family,
                "shop_row": row,
                "shop_id": shop_id,
                "control_id": control_id,
                "value": int(shop[key]),
                "product_safe": shop_id <= 0xF4,
            })
        base = int(shop["dialogue_index"])
        for slot, (control_id, value) in enumerate(zip(DIALOGUE_EDIT_IDS, shop["dialogue_texts"])):
            fields.append({
                "field_id": f"M10/shop/{shop_id:02X}/dialogue/{slot + 1}",
                "physical_id": f"M09/system/{base + slot:03d}",
                "family": "shop_dialogue_text",
                "shop_row": row,
                "shop_id": shop_id,
                "slot": slot,
                "control_id": control_id,
                "value": value,
                "product_safe": shop_id <= 0xF4,
            })
    safe = sum(bool(field["product_safe"]) for field in fields)
    families = Counter(str(field["family"]) for field in fields)
    return {
        "module": "M10",
        "classification": "reference_controls_enumerated_save_probe_pending",
        "source_sha256": source["source_sha256"],
        "controls": source["controls"],
        "counts": {
            "logical_fields": len(fields),
            "product_safe_candidates": safe,
            "product_blocked_candidates": len(fields) - safe,
            "unique_initial_physical_ids": len({str(field["physical_id"]) for field in fields}),
            "families": dict(sorted(families.items())),
            "items": len(source["items"]),
            "reference_shop_rows": len(source["shops"]),
        },
        "reference_shop_labels": [shop["label"] for shop in source["shops"]],
        "notes": [
            "The reference ListBox exposes F0-FC and FE; FD is absent.",
            "F5-FC and FE remain visibly enabled in the reference but overlap map-event data in the supported product layout.",
            "F4 only has one supported item slot; its remaining three visible slots are treated as blocked candidates.",
            "Dialogue edits alias M09 system-text records by the selected base dialogue id.",
        ],
        "fields": fields,
    }


def markdown(report: dict[str, object]) -> str:
    counts = report["counts"]
    lines = [
        "# M10 参考版字段目录",
        "",
        f"- 逻辑字段：{counts['logical_fields']}",
        f"- 产品安全候选：{counts['product_safe_candidates']}",
        f"- 产品禁写候选：{counts['product_blocked_candidates']}",
        f"- 道具：{counts['items']} 项",
        f"- 参考版商店行：{counts['reference_shop_rows']} 行（无 FD）",
        "",
        "| 字段族 | 数量 |",
        "|---|---:|",
    ]
    lines.extend(f"| {family} | {count} |" for family, count in counts["families"].items())
    lines.extend(("", "说明：F5-FC、FE 和 F4 的第 2-4 商品槽虽然在参考版可编辑，但在当前受支持布局中属于地图事件重叠区，保存实验只用于取证，结果不会并入安全链。", ""))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()
    report = build(json.loads(args.source.read_text(encoding="utf-8")))
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
