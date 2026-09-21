"""Build the physical M08 text-field catalog from the reference-save ROM.

The reference editor rewrites its table locations into the first words of each
8 KiB bank.  Reading those headers is important: applying the product ROM's
fixed table addresses to a reference-saved ROM silently interprets text bytes
as pointers.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.fc_editor.codecs.legacy_text import decode_legacy_text

DEFAULT_ROM = ROOT / "output/build/legacy-diff-audit/m05-reference-baseline.nes"
DEFAULT_UI = ROOT / "output/verification/legacy-ui-probe-m08-battle-20260920/M08_战斗对话完整控件.json"
DEFAULT_JSON = ROOT / "output/reports/m08-reference-physical-catalog.json"
DEFAULT_MD = ROOT / "output/reports/m08-reference-physical-catalog.md"

GROUPS = (
    ("00", 0x2A, 0, 256),
    ("01", 0x2A, 2, 16),
    ("04", 0x0E, 0, 256),
    ("05", 0x0E, 2, 64),
    ("07", 0x0E, 6, 52),
)


def bank_base(bank: int) -> int:
    return 16 + bank * 0x2000


def word(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def raw_text(data: bytes, bank: int, pointer: int) -> bytes:
    start = bank_base(bank) + pointer - 0x8000
    cursor = start
    # The legacy save format addresses the full $8000-$BFFF CPU window even
    # though the file-bank selector itself advances in 8 KiB units.
    while cursor < bank_base(bank) + 0x4000:
        lead = data[cursor]
        size = 2 if 0xC8 <= lead <= 0xDB else {0xFC: 3, 0xF0: 2, 0xEE: 2}.get(lead, 1)
        cursor += size
        if lead == 0xFF:
            return data[start:cursor]
    raise ValueError(f"unterminated text at bank ${bank:02X}:${pointer:04X}")


def ui_body(value: str) -> str:
    if len(value) < 4 or not value[:3].isdigit() or value[3] not in {"：", ":"}:
        raise ValueError(f"unexpected reference list item: {value!r}")
    return value[4:].replace("\\\r\n", "\n").replace("\r\n", "\n").rstrip("\n")


def build_catalog(rom_path: Path, ui_path: Path) -> dict[str, object]:
    data = rom_path.read_bytes()
    ui = json.loads(ui_path.read_text(encoding="utf-8"))
    ui_groups = {
        str(item["segment_text"]).strip(): item for item in ui["variant_counts"]
    }
    fields: list[dict[str, object]] = []
    physical_refs: dict[tuple[int, int], list[str]] = defaultdict(list)
    group_summaries: list[dict[str, object]] = []

    for segment, bank, header_offset, row_count in GROUPS:
        table = word(data, bank_base(bank) + header_offset)
        if not 0x8000 <= table < 0xC000:
            raise ValueError(f"M08/{segment} table pointer is invalid: ${table:04X}")
        ui_group = ui_groups[segment]
        if len(ui_group["rows"]) != row_count:
            raise ValueError(f"M08/{segment} row count differs from UI evidence")
        variant_total = 0
        for row in range(row_count):
            root = word(data, bank_base(bank) + table - 0x8000 + row * 2)
            root_offset = bank_base(bank) + root - 0x8000
            if data[root_offset] == 0xF8:
                pointers = [
                    word(data, root_offset + 2 + variant * 2)
                    for variant in range(data[root_offset + 1])
                ]
            else:
                pointers = [root]
            ui_variants = ui_group["rows"][row]["variants"]
            if len(pointers) != len(ui_variants):
                raise ValueError(f"M08/{segment}/{row:03d} variant count differs")
            for variant, (pointer, ui_value) in enumerate(zip(pointers, ui_variants)):
                raw = raw_text(data, bank, pointer)
                decoded = decode_legacy_text(raw[:-1])
                expected = ui_body(ui_value)
                if decoded != expected:
                    raise ValueError(
                        f"M08/{segment}/{row:03d}/{variant:03d} text differs: "
                        f"ROM={decoded!r}, UI={expected!r}"
                    )
                field_id = f"M08/{segment}/{row:03d}/{variant:03d}"
                physical_id = f"bank-{bank:02X}-ptr-{pointer:04X}"
                physical_refs[(bank, pointer)].append(field_id)
                fields.append(
                    {
                        "field_id": field_id,
                        "segment": segment,
                        "row": row,
                        "variant": variant,
                        "bank": bank,
                        "table_pointer": table,
                        "root_pointer": root,
                        "text_pointer": pointer,
                        "file_offset": bank_base(bank) + pointer - 0x8000,
                        "byte_length": len(raw),
                        "raw_hex": raw.hex().upper(),
                        "text": decoded,
                        "physical_id": physical_id,
                    }
                )
                variant_total += 1
        group_summaries.append(
            {
                "segment": segment,
                "bank": bank,
                "header_offset": header_offset,
                "table_pointer": table,
                "row_count": row_count,
                "ui_fields": variant_total,
                "unique_physical_fields": len(
                    {
                        (item["bank"], item["text_pointer"])
                        for item in fields
                        if item["segment"] == segment
                    }
                ),
            }
        )

    aliases = [
        {
            "physical_id": f"bank-{bank:02X}-ptr-{pointer:04X}",
            "bank": bank,
            "text_pointer": pointer,
            "field_ids": refs,
        }
        for (bank, pointer), refs in sorted(physical_refs.items())
        if len(refs) > 1
    ]
    return {
        "schema_version": 1,
        "source_rom": rom_path.relative_to(ROOT).as_posix(),
        "source_ui_evidence": ui_path.relative_to(ROOT).as_posix(),
        "layout_rule": "Each reference-saved bank header stores the live table pointers; fixed product-ROM table offsets are not used.",
        "counts": {
            "groups": len(GROUPS),
            "rows": sum(group[3] for group in GROUPS),
            "ui_fields": len(fields),
            "unique_physical_fields": len(physical_refs),
            "aliased_physical_fields": len(aliases),
            "duplicate_ui_references": len(fields) - len(physical_refs),
        },
        "groups": group_summaries,
        "fields": fields,
        "aliases": aliases,
    }


def render_markdown(report: dict[str, object]) -> str:
    counts = report["counts"]
    lines = [
        "# M08 参考版物理字段目录",
        "",
        f"- 界面字段：{counts['ui_fields']}",
        f"- 独立物理正文：{counts['unique_physical_fields']}",
        f"- 重复界面引用：{counts['duplicate_ui_references']}",
        f"- 含别名的物理正文：{counts['aliased_physical_fields']}",
        "",
        "| 组 | Bank | 表指针 | 行 | 界面字段 | 独立物理字段 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for group in report["groups"]:
        lines.append(
            f"| {group['segment']} | ${group['bank']:02X} | ${group['table_pointer']:04X} | "
            f"{group['row_count']} | {group['ui_fields']} | {group['unique_physical_fields']} |"
        )
    lines += [
        "",
        "说明：物理字段按 `(Bank, 正文指针)` 去重；同一正文的多个界面入口保留在 `aliases` 中。",
        "本报告只证明目录、文本和别名拓扑，不把目录解析冒充逐字段保存黄金。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--ui", type=Path, default=DEFAULT_UI)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()
    report = build_catalog(args.rom.resolve(), args.ui.resolve())
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(report), encoding="utf-8")
    print(
        f"M08 physical catalog: {report['counts']['ui_fields']} UI fields -> "
        f"{report['counts']['unique_physical_fields']} physical fields"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
