from __future__ import annotations

from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fc_editor.codecs.legacy_text import LegacyTextCodec  # noqa: E402
from fc_editor.codecs.legacy_text_shop import LegacyShopCodec  # noqa: E402
from fc_rom_editor_core import RomProject  # noqa: E402


DEFAULT_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
DEFAULT_REPORT = ROOT / "output" / "verification" / "m10-other2-compatibility.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _changed_offsets(before: bytes, after: bytes) -> list[int]:
    return [
        index
        for index, (left, right) in enumerate(zip(before, after))
        if left != right
    ]


def _apply_patches(data: bytes, patches) -> bytes:
    result = bytearray(data)
    for offset, before, after in patches:
        if len(before) != len(after):
            raise AssertionError("报告只允许等长补丁。")
        if bytes(result[offset : offset + len(before)]) != before:
            raise AssertionError("报告补丁原值冲突。")
    for offset, _before, after in patches:
        result[offset : offset + len(after)] = after
    return bytes(result)


def _rejected(action) -> str:
    try:
        action()
    except ValueError as error:
        return str(error)
    raise AssertionError("预期门禁拒绝操作，但调用成功。")


def analyze(rom_path: Path) -> dict[str, object]:
    data = rom_path.read_bytes()
    original_hash = _sha256(data)
    project = RomProject.load(rom_path)
    global_codec = project.legacy_global_data_codec
    if global_codec is None:
        raise ValueError("当前 ROM 未启用已验证的全局数据协议。")
    text_codec = LegacyTextCodec(data)
    shop_codec = LegacyShopCodec(data)

    names = list(global_codec.item_name_records(data))
    name_pool_capacity = (
        global_codec.spec.item_name_pool_end_offset
        - global_codec.spec.item_name_pool_start_offset
    )
    name_bytes_used = sum(len(record) + 1 for record in names)
    shortened_names = list(names)
    shortened_names[0] = shortened_names[0][:-2]
    name_patches = global_codec.item_name_record_patches(data, shortened_names)
    renamed_data = _apply_patches(data, name_patches)
    renamed_records = global_codec.item_name_records(renamed_data)
    name_diff = _changed_offsets(data, renamed_data)
    name_allowed = set(
        range(
            global_codec.spec.item_name_pointer_table_offset,
            global_codec.spec.item_name_pointer_table_offset + 24 * 2,
        )
    ) | set(
        range(
            global_codec.spec.item_name_pool_start_offset,
            global_codec.spec.item_name_pool_end_offset,
        )
    )
    oversized_names = list(names)
    oversized_names[0] += bytes((1,)) * (name_pool_capacity + 1)
    name_capacity_rejection = _rejected(
        lambda: global_codec.item_name_record_patches(data, oversized_names)
    )

    prices = global_codec.item_prices(data)
    changed_prices = list(prices)
    changed_prices[0] += 1
    price_patch = global_codec.item_price_patches(data, changed_prices)[0]
    price_diff = _changed_offsets(price_patch[1], price_patch[2])

    description_roundtrips = []
    for index in range(24):
        for variant in range(text_codec.variant_count("item_description", index)):
            record = text_codec.record("item_description", index, variant)
            patch = text_codec.replacement_patch(
                "item_description", index, variant, record.text
            )
            description_roundtrips.append(patch[1] == patch[2])
    description = text_codec.record("item_description", 0)
    changed_description_text = description.text.replace("1点", "2点", 1)
    description_patch = text_codec.replacement_patch(
        "item_description", 0, 0, changed_description_text
    )
    description_diff = _changed_offsets(
        description_patch[1], description_patch[2]
    )

    shops = [shop_codec.record(shop_id) for shop_id in range(0xF0, 0xF5)]
    shop_roundtrips = [
        shop_codec.replacement_patch(
            record.shop_id,
            record.clerk_id,
            record.dialogue_id,
            record.items,
        )[1:]
        for record in shops
    ]
    shop_item_patch = shop_codec.replacement_patch(
        0xF0, shops[0].clerk_id, shops[0].dialogue_id, (12, *shops[0].items[1:])
    )
    shop_clerk_patch = shop_codec.replacement_patch(
        0xF0, shops[0].clerk_id + 1, shops[0].dialogue_id, shops[0].items
    )
    shop_dialogue_patch = shop_codec.replacement_patch(
        0xF0, shops[0].clerk_id, shops[0].dialogue_id + 1, shops[0].items
    )
    invalid_shop_rejections = {
        f"${shop_id:02X}": _rejected(lambda value=shop_id: shop_codec.record(value))
        for shop_id in range(0xF5, 0xFF)
    }
    f4_capacity_rejection = _rejected(
        lambda: shop_codec.replacement_patch(0xF4, 2, 48, (1, 2, 3, 4))
    )

    dialogue_roundtrips = []
    for shop in shops:
        for dialogue_index in range(7):
            text_id = shop.dialogue_id + dialogue_index
            record = text_codec.record("system", text_id)
            patch = text_codec.replacement_patch("system", text_id, 0, record.text)
            dialogue_roundtrips.append(patch[1] == patch[2])
    first_dialogue = text_codec.record("system", shops[0].dialogue_id)
    dialogue_patch = text_codec.replacement_patch(
        "system",
        shops[0].dialogue_id,
        0,
        first_dialogue.text.replace("欢迎", "感谢", 1),
    )
    dialogue_diff = _changed_offsets(dialogue_patch[1], dialogue_patch[2])

    single_field_shop_patches = {
        "item": shop_item_patch,
        "clerk": shop_clerk_patch,
        "dialogue": shop_dialogue_patch,
    }
    checks = {
        "item_names_24_and_pool_exact": (
            len(names) == 24
            and name_pool_capacity == 184
            and name_bytes_used <= name_pool_capacity
        ),
        "item_name_repack_roundtrip_and_confined": (
            renamed_records == tuple(shortened_names)
            and bool(name_diff)
            and set(name_diff) <= name_allowed
            and "超过文本池" in name_capacity_rejection
        ),
        "item_prices_24_single_field": (
            len(prices) == 24
            and price_patch[0] == 0x15723
            and price_diff == [0]
        ),
        "item_descriptions_roundtrip_and_single_field": (
            len(description_roundtrips) == 24
            and all(description_roundtrips)
            and bool(description_diff)
            and description_patch[0] == description.file_offset
        ),
        "shops_f0_f4_roundtrip_and_capacities": (
            [len(record.items) for record in shops] == [4, 4, 4, 4, 1]
            and all(before == after for before, after in shop_roundtrips)
        ),
        "shop_single_fields_are_isolated": all(
            len(_changed_offsets(patch[1], patch[2])) == 1
            for patch in single_field_shop_patches.values()
        ),
        "invalid_shops_and_f4_overflow_rejected": (
            len(invalid_shop_rejections) == 10
            and all("地图事件" in reason for reason in invalid_shop_rejections.values())
            and "须保持 1 件商品" in f4_capacity_rejection
        ),
        "seven_dialogues_roundtrip_and_edit_is_confined": (
            len(dialogue_roundtrips) == 35
            and all(dialogue_roundtrips)
            and bool(dialogue_diff)
            and dialogue_patch[0] == first_dialogue.file_offset
        ),
        "source_rom_unchanged": _sha256(data) == original_hash,
    }

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": all(checks.values()),
        "delivery_status": "implementation_complete_reference_and_user_pending",
        "conclusion": (
            "M10 六项实现范围已具备离线可重复证据；参考 EXE 单字段保存黄金和用户签收仍未完成。"
        ),
        "rom": {
            "path": rom_path.resolve().relative_to(ROOT).as_posix(),
            "size": len(data),
            "sha256": original_hash,
            "unchanged_after_analysis": _sha256(data) == original_hash,
        },
        "evidence": {
            "item_names": {
                "records": len(names),
                "pointer_table": "0x00CD5A-0x00CD89",
                "pool": "0x00CD8A-0x00CE41",
                "pool_capacity": name_pool_capacity,
                "bytes_used": name_bytes_used,
                "sample_repack_changed_offsets": [
                    f"0x{offset:06X}" for offset in name_diff
                ],
                "overflow_rejection": name_capacity_rejection,
            },
            "item_prices": {
                "records": len(prices),
                "table": "0x015723-0x015752",
                "sample_patch_offset": f"0x{price_patch[0]:06X}",
                "sample_changed_indices": price_diff,
                "ui_scale": 10,
            },
            "item_descriptions": {
                "records": 24,
                "no_op_roundtrips": sum(description_roundtrips),
                "sample_patch_offset": f"0x{description_patch[0]:06X}",
                "sample_changed_indices": description_diff,
            },
            "shops": {
                "valid_ids": [f"${record.shop_id:02X}" for record in shops],
                "item_counts": [len(record.items) for record in shops],
                "sample_single_field_patches": {
                    key: {
                        "offset": f"0x{patch[0]:06X}",
                        "changed_indices": _changed_offsets(patch[1], patch[2]),
                    }
                    for key, patch in single_field_shop_patches.items()
                },
                "invalid_ids": invalid_shop_rejections,
                "f4_overflow_rejection": f4_capacity_rejection,
            },
            "shop_dialogues": {
                "labels": list(LegacyShopCodec.LABELS),
                "no_op_roundtrips": sum(dialogue_roundtrips),
                "sample_patch_offset": f"0x{dialogue_patch[0]:06X}",
                "sample_changed_indices": dialogue_diff,
            },
        },
        "checks": checks,
        "pending_acceptance": [
            "参考 EXE：道具名称、说明、商店三字段及七段对话的单字段保存/重开黄金。",
            "正式 EXE 人工执行 M10 验收清单并由用户签收。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="复验 M10 道具名称/价格/说明、商店目录和七段对话。"
    )
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    arguments = parser.parse_args()
    report = analyze(arguments.rom)
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
