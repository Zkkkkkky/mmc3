from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fc_editor.codecs import LegacySaveCodec  # noqa: E402


DEFAULT_SAVE = ROOT / "references" / "emulator-state" / "fceux" / "sav" / "DC_kuorong.sav"
DEFAULT_BATTLE_SAVE = (
    ROOT / "references" / "emulator-state" / "fceux" / "sav" / "DC-fixed-test.sav"
)
DEFAULT_REPORT = ROOT / "output" / "verification" / "m16-save-compatibility.json"


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _slot_report(slot) -> dict[str, object]:
    return {
        "number": slot.number,
        "data_offset": f"0x{slot.data_offset:04X}",
        "checksum_offset": (
            f"0x{slot.checksum_offset:04X}"
            if slot.checksum_offset is not None
            else None
        ),
        "stored_checksum": (
            f"0x{slot.stored_checksum:04X}"
            if slot.stored_checksum is not None
            else None
        ),
        "calculated_checksum": f"0x{slot.calculated_checksum:04X}",
        "checksum_valid": slot.checksum_valid,
        "occupied": slot.occupied,
        "chapter": slot.chapter_number,
        "money": slot.money,
        "roster_count": len(slot.occupied_roster),
    }


def analyze(save_path: Path, battle_save_path: Path) -> dict[str, object]:
    save_data = save_path.read_bytes()
    battle_data = battle_save_path.read_bytes()
    document = LegacySaveCodec.decode(save_data)
    battle_document = LegacySaveCodec.decode(battle_data)

    first_slot = document.slots[0]
    no_op = LegacySaveCodec.replace_slot(
        save_data,
        1,
        chapter_number=first_slot.chapter_number or 1,
        roster=first_slot.roster,
        money=first_slot.money,
    )
    first_entry = first_slot.occupied_roster[0]
    next_experience = (first_entry.experience + 1) & 0xFFFF
    changed_entry = replace(first_entry, experience=next_experience)
    mutation = LegacySaveCodec.replace_slot(
        save_data,
        1,
        chapter_number=first_slot.chapter_number or 1,
        roster=(changed_entry,),
    )
    mutation_document = LegacySaveCodec.decode(mutation)
    differences = tuple(
        index
        for index, (before, after) in enumerate(zip(save_data, mutation, strict=True))
        if before != after
    )
    allowed = {
        first_slot.data_offset + LegacySaveCodec.EXP_LOW_OFFSET + first_entry.index,
        first_slot.data_offset + LegacySaveCodec.EXP_HIGH_OFFSET + first_entry.index,
        first_slot.checksum_offset,
        first_slot.checksum_offset + 1,
    }
    unexpected = tuple(index for index in differences if index not in allowed)
    passed = all(
        (
            len(save_data) == LegacySaveCodec.SAVE_SIZE,
            len(battle_data) == LegacySaveCodec.SAVE_SIZE,
            len(document.slots) == 3,
            all(slot.occupied and slot.checksum_valid for slot in document.slots),
            no_op == save_data,
            not unexpected,
            mutation_document.slots[0].checksum_valid,
            mutation_document.slots[0].roster[first_entry.index].experience
            == next_experience,
            len(battle_document.enemies) > 0,
        )
    )
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": passed,
        "conclusion": (
            "三个 0xFB 字节槽位及其 16 位小端累加校验均可复验；"
            "单字段内存修改仅影响目标字节和校验和，活动战场敌方数组可独立读取。"
        ),
        "layout": {
            "save_size": LegacySaveCodec.SAVE_SIZE,
            "active": {
                "offset": f"0x{LegacySaveCodec.ACTIVE_OFFSET:04X}",
                "length": f"0x{LegacySaveCodec.ACTIVE_LENGTH:04X}",
            },
            "backup": {
                "offset": f"0x{LegacySaveCodec.BACKUP_OFFSET:04X}",
                "checksum_offset": f"0x{LegacySaveCodec.BACKUP_CHECKSUM_OFFSET:04X}",
            },
            "slot_length": f"0x{LegacySaveCodec.SLOT_LENGTH:04X}",
            "slot_data_offsets": [
                f"0x{offset:04X}" for offset in LegacySaveCodec.SLOT_DATA_OFFSETS
            ],
            "slot_checksum_offsets": [
                f"0x{offset:04X}" for offset in LegacySaveCodec.SLOT_CHECKSUM_OFFSETS
            ],
        },
        "save": {
            "path": _relative(save_path),
            "sha256": _sha256(save_data),
            "size": len(save_data),
            "active_chapter": document.active.chapter_number,
            "active_roster_count": len(document.active.occupied_roster),
            "slots": [_slot_report(slot) for slot in document.slots],
        },
        "battle_save": {
            "path": _relative(battle_save_path),
            "sha256": _sha256(battle_data),
            "size": len(battle_data),
            "active_chapter": battle_document.active.chapter_number,
            "ally_battle_rows": len(battle_document.allies),
            "enemy_battle_rows": len(battle_document.enemies),
        },
        "round_trip": {
            "no_op_identical": no_op == save_data,
            "changed_experience": {
                "slot": 1,
                "roster_index": first_entry.index,
                "before": first_entry.experience,
                "after": next_experience,
            },
            "changed_offsets": [f"0x{offset:04X}" for offset in differences],
            "unexpected_offsets": [f"0x{offset:04X}" for offset in unexpected],
            "checksum_valid_after_mutation": mutation_document.slots[0].checksum_valid,
            "input_sha256_after_in_memory_checks": _sha256(save_path.read_bytes()),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="复验 M16 DC 8 KiB SRAM 槽位、校验和和活动战场读取协议。"
    )
    parser.add_argument("--save", type=Path, default=DEFAULT_SAVE)
    parser.add_argument("--battle-save", type=Path, default=DEFAULT_BATTLE_SAVE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = analyze(args.save, args.battle_save)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
