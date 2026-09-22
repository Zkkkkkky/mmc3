"""Verify M03/M04 reference add/delete structure evidence."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fc_editor.codecs.scenario_layout import ScenarioLayoutCodec
from fc_editor.rom_image import RomImage


EVIDENCE = ROOT / "output/verification/legacy-m03-m04-structural-20260921"
REPORT = ROOT / "output/reports/m03-m04-structural-compatibility.json"
M04_BANK = 0x0A
M04_WINDOW = 0x8000
M04_TABLE = 0x987E
M04_POOL = 0x9946
SCENARIOS = 32


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def m04_offset(address: int) -> int:
    return 16 + M04_BANK * 0x2000 + address - M04_WINDOW


def ordered_unique(values: list[bytes]) -> list[bytes]:
    result: list[bytes] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def sequential_pointers(
    payloads: list[bytes],
    start: int,
    *,
    minimum_slot: int = 0,
) -> tuple[int, ...]:
    addresses: dict[bytes, int] = {}
    cursor = start
    result: list[int] = []
    for payload in payloads:
        if payload not in addresses:
            addresses[payload] = cursor
            cursor += max(len(payload), minimum_slot)
        result.append(addresses[payload])
    return tuple(result)


def m03_inventory(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    codec = ScenarioLayoutCodec(RomImage.load(path))
    payloads = [codec.encode(codec.decode(index)) for index in range(SCENARIOS)]
    pointers = struct.unpack(
        "<32H",
        data[codec.pointer_table_offset : codec.pointer_table_offset + 64],
    )
    expected = sequential_pointers(payloads, pointers[0])
    return {
        "map0": {
            "enemies": len(codec.decode(0).enemies),
            "guests": len(codec.decode(0).guests),
            "players": len(codec.decode(0).player_placements),
            "bytes": len(payloads[0]),
        },
        "unique_payloads": len(ordered_unique(payloads)),
        "used_bytes": sum(map(len, ordered_unique(payloads))),
        "pointers_are_reference_sequential_pack": tuple(pointers) == expected,
    }


def m04_inventory(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    table = m04_offset(M04_TABLE)
    pointers = struct.unpack("<32H", data[table : table + 64])
    payloads: list[bytes] = []
    counts: list[int] = []
    for pointer in pointers:
        cursor = m04_offset(pointer)
        start = cursor
        count = 0
        while data[cursor] != 0xFF:
            cursor += 4
            count += 1
        payloads.append(data[start : cursor + 1])
        counts.append(count)
    expected = sequential_pointers(payloads, M04_POOL, minimum_slot=5)
    return {
        "map0_records": counts[0],
        "total_records": sum(counts),
        "unique_payloads": len(ordered_unique(payloads)),
        "used_bytes": sum(map(len, ordered_unique(payloads))),
        "allocated_bytes": sum(
            max(len(payload), 5) for payload in ordered_unique(payloads)
        ),
        "empty_layout_slot_bytes": 5,
        "pointers_are_reference_sequential_pack": tuple(pointers) == expected,
    }


def analyze() -> dict[str, object]:
    capture = json.loads((EVIDENCE / "report.json").read_text(encoding="utf-8"))
    cases = {item["case"]: item for item in capture["cases"]}
    baseline_m03 = m03_inventory(EVIDENCE / "normalized-baseline.nes")
    add_m03 = m03_inventory(EVIDENCE / "m03-add-enemy.nes")
    delete_m03 = m03_inventory(EVIDENCE / "m03-delete-player.nes")
    baseline_m04 = m04_inventory(EVIDENCE / "normalized-baseline.nes")
    add_m04 = m04_inventory(EVIDENCE / "m04-add-event.nes")
    delete_m04 = m04_inventory(EVIDENCE / "m04-delete-event.nes")
    checks = {
        "capture_passed": capture["passed"] is True,
        "m03_add_enemy_count": add_m03["map0"]["enemies"] == baseline_m03["map0"]["enemies"] + 1,
        "m03_add_grows_six_bytes": add_m03["used_bytes"] == baseline_m03["used_bytes"] + 6,
        "m03_delete_player_count": delete_m03["map0"]["players"] == baseline_m03["map0"]["players"] - 1,
        "m03_delete_shrinks_four_bytes": delete_m03["used_bytes"] == baseline_m03["used_bytes"] - 4,
        "m03_all_cases_use_reference_sequential_pack": all(
            item["pointers_are_reference_sequential_pack"]
            for item in (baseline_m03, add_m03, delete_m03)
        ),
        "m04_add_record_count": add_m04["map0_records"] == baseline_m04["map0_records"] + 1,
        "m04_add_grows_four_bytes": add_m04["used_bytes"] == baseline_m04["used_bytes"] + 4,
        "m04_delete_record_count": delete_m04["map0_records"] == baseline_m04["map0_records"] - 1,
        "m04_delete_shrinks_five_bytes": delete_m04["used_bytes"] == baseline_m04["used_bytes"] - 5,
        "m04_all_cases_use_reference_sequential_pack": all(
            item["pointers_are_reference_sequential_pack"]
            for item in (baseline_m04, add_m04, delete_m04)
        ),
        "all_cases_changed_rom": all(item["changed_count"] > 0 for item in cases.values()),
    }
    return {
        "schema_version": 1,
        "modules": ["M03", "M04"],
        "passed": all(checks.values()),
        "checks": checks,
        "reference": {
            "baseline_m03": baseline_m03,
            "add_m03": add_m03,
            "delete_m03": delete_m03,
            "baseline_m04": baseline_m04,
            "add_m04": add_m04,
            "delete_m04": delete_m04,
        },
        "evidence": {
            "capture": EVIDENCE.relative_to(ROOT).as_posix() + "/report.json",
            "capture_sha256": sha(EVIDENCE / "report.json"),
        },
        "remaining_guard": (
            "Reference structure saves use a sequential shared-pool repack. "
            "The product enables verified field edits and structure actions while "
            "retaining fixed-layout capacity checks; arbitrary overflow still "
            "requires the expanded map capacity plan."
        ),
    }


def main() -> int:
    report = analyze()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
