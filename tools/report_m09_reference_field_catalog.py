"""Build the M09 logical/physical field catalog from reference evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "output/build/legacy-diff-audit/audit.nes"
DEFAULT_CAPTURE = ROOT / "output/verification/legacy-m09-reference-catalog-20260920/catalog.json"
DEFAULT_JSON = ROOT / "output/reports/m09-reference-field-catalog.json"
DEFAULT_MD = ROOT / "output/reports/m09-reference-field-catalog.md"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(rom_path: Path, capture_path: Path) -> dict[str, object]:
    data = rom_path.read_bytes()
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    logical: list[dict[str, object]] = []

    distance_offset = data.find(bytes(
        int(row[1].rstrip("%"))
        for group in capture["distance"]
        for row in group["rows"]
    ))
    if distance_offset < 0:
        raise ValueError("reference distance table was not found in the ROM")
    for group in capture["distance"]:
        selector = int(group["selector_index"])
        for row, cells in enumerate(group["rows"]):
            offset = distance_offset + selector * 16 + row
            logical.append({
                "field_id": f"M09/distance/{selector:02d}/{row:02d}",
                "family": "distance",
                "selector_index": selector,
                "row": row,
                "value": int(cells[1].rstrip("%")),
                "physical_id": f"rom/{offset:06X}/u8",
                "file_offset": offset,
                "byte_width": 1,
            })

    experience_totals = [int(row[1]) for row in capture["experience"]]
    experience_needed = [int(row[2]) for row in capture["experience"]]
    experience_bytes = b"".join(value.to_bytes(2, "little") for value in experience_totals[1:])
    experience_offset = data.find(experience_bytes)
    if experience_offset < 0:
        raise ValueError("reference experience table was not found in the ROM")
    for row, value in enumerate(experience_needed):
        item: dict[str, object] = {
            "field_id": f"M09/experience/{row + 1:02d}",
            "family": "experience",
            "row": row,
            "level": row + 1,
            "value": value,
            "total_experience_read_only": experience_totals[row],
            "byte_width": 2,
        }
        if row == len(experience_needed) - 1:
            item.update({"physical_id": "constant/max-level-next-0", "file_offset": None, "classification": "ui_constant_candidate"})
        else:
            offset = experience_offset + row * 2
            item.update({"physical_id": f"rom/{offset:06X}/u16le", "file_offset": offset})
        logical.append(item)

    bank_base = 16 + 0x2A * 0x2000
    system_table_pointer = int.from_bytes(data[bank_base + 4:bank_base + 6], "little")
    system_table_offset = bank_base + system_table_pointer - 0x8000
    if not 0 <= system_table_offset <= len(data) - 442:
        raise ValueError("reference system-text pointer table is outside the ROM")
    system_pointers = [
        int.from_bytes(data[system_table_offset + row * 2:system_table_offset + row * 2 + 2], "little")
        for row in range(221)
    ]
    system_aliases: dict[int, list[int]] = defaultdict(list)
    for row, pointer in enumerate(system_pointers):
        system_aliases[pointer].append(row)
    for item, pointer in zip(capture["system"], system_pointers, strict=True):
        offset = bank_base + pointer - 0x8000
        logical.append({
            "field_id": f"M09/system/{int(item['row']):03d}",
            "family": "system",
            "row": int(item["row"]),
            "label": item["label"],
            "text": item["text"],
            "pointer": pointer,
            "physical_id": f"rom/{offset:06X}/system-text",
            "file_offset": offset,
            "aliases": system_aliases[pointer],
        })

    growth_table_offset = 0xA720
    growth_pointers = [
        int.from_bytes(data[growth_table_offset + index * 2:growth_table_offset + index * 2 + 2], "little")
        for index in range(53)
    ]
    growth_aliases: dict[int, list[int]] = defaultdict(list)
    for index, pointer in enumerate(growth_pointers):
        growth_aliases[pointer].append(201 + index)
    growth_bank_base = 16 + 4 * 0x2000
    for item, pointer in zip(capture["growth"], growth_pointers, strict=True):
        growth_id = int(item["selector"])
        values = [int(row[1]) for row in item["rows"]]
        offset = growth_bank_base + pointer - 0x8000
        raw = data[offset:offset + 30]
        decoded = [nibble for byte in raw for nibble in (byte >> 4, byte & 0x0F)]
        if decoded != values:
            raise ValueError(f"growth {growth_id} UI values do not match ROM bytes")
        logical.append({
            "field_id": f"M09/growth/{growth_id}",
            "family": "growth",
            "selector_index": growth_id - 201,
            "growth_id": growth_id,
            "values": values,
            "quick_hex": raw.hex().upper(),
            "pointer": pointer,
            "physical_id": f"rom/{offset:06X}/growth-30",
            "file_offset": offset,
            "byte_width": 30,
            "aliases": growth_aliases[pointer],
        })

    physical: dict[str, dict[str, object]] = {}
    for item in logical:
        physical_id = str(item["physical_id"])
        physical.setdefault(physical_id, item)
    family_logical = Counter(str(item["family"]) for item in logical)
    family_physical = Counter(str(item["family"]) for item in physical.values())
    return {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_rom": rom_path.resolve().relative_to(ROOT).as_posix(),
        "source_sha256": sha256(data),
        "reference_capture": capture_path.resolve().relative_to(ROOT).as_posix(),
        "counts": {
            "logical_fields": len(logical),
            "physical_fields_including_constant": len(physical),
            "persistent_physical_fields": len(physical) - 1,
            "duplicate_logical_references": len(logical) - len(physical),
            "logical_by_family": dict(family_logical),
            "physical_by_family": dict(family_physical),
        },
        "layout": {
            "distance_offset": distance_offset,
            "experience_offset": experience_offset,
            "experience_max_level_next_constant": True,
            "system_table_pointer": system_table_pointer,
            "system_table_offset": system_table_offset,
            "growth_pointer_table_offset": growth_table_offset,
        },
        "fields": logical,
    }


def markdown(report: dict[str, object]) -> str:
    counts = report["counts"]
    return "\n".join([
        "# M09 参考版字段目录",
        "",
        f"- 参考 ROM SHA-256：`{report['source_sha256']}`",
        f"- 逻辑字段：{counts['logical_fields']}",
        f"- 持久物理字段：{counts['persistent_physical_fields']}",
        f"- 重复逻辑引用：{counts['duplicate_logical_references']}",
        "- `总经验`控件带 ES_READONLY；可编辑字段是`升级还需`。最高等级的下一等级需求显示为常量 0，单列为待保存验证的非持久候选。",
        "",
        "| 字段族 | 逻辑字段 | 去重物理字段 |",
        "|---|---:|---:|",
        *[
            f"| {family} | {counts['logical_by_family'][family]} | {counts['physical_by_family'][family]} |"
            for family in ("distance", "experience", "system", "growth")
        ],
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()
    report = build(args.rom, args.capture)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
