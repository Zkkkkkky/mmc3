from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fc_editor.codecs import LegacyGrowthCodec  # noqa: E402
from fc_rom_editor_core import RomProject  # noqa: E402


DEFAULT_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
DEFAULT_AUDIT_BEFORE = (
    ROOT / "output" / "build" / "legacy-diff-audit" / "audit.nes"
)
DEFAULT_AUDIT_AFTER = (
    ROOT
    / "output"
    / "build"
    / "legacy-diff-audit"
    / "cases"
    / "legacy_level_cap"
    / "after.nes"
)
DEFAULT_REPORT = (
    ROOT / "output" / "verification" / "m09-level-cap-compatibility.json"
)
NORMALIZATION_OFFSETS = frozenset(
    (0x4A101, 0x4A102, 0x4AE2A, 0x4AE2B, 0x79538, 0x79539)
)


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _runtime_cap(data: bytes) -> tuple[str, int | None]:
    offset = LegacyGrowthCodec.LEVEL_CAP_COMPARE_OFFSET
    instruction = data[offset : offset + 2]
    return instruction.hex(" ").upper(), instruction[1] + 1 if instruction[:1] == b"\xC9" else None


def _growth_offsets(data: bytes, count: int = 11) -> tuple[int, ...]:
    start = LegacyGrowthCodec.POINTER_TABLE
    return tuple(
        0x10 + int.from_bytes(data[start + 2 * index : start + 2 * index + 2], "little")
        for index in range(count)
    )


def _growth_widths(data: bytes) -> tuple[int, ...]:
    offsets = _growth_offsets(data)
    return tuple(right - left for left, right in zip(offsets, offsets[1:]))


def analyze(
    rom_path: Path,
    audit_before_path: Path,
    audit_after_path: Path,
) -> dict[str, object]:
    rom_data = rom_path.read_bytes()
    audit_before = audit_before_path.read_bytes()
    audit_after = audit_after_path.read_bytes()
    if len(audit_before) != len(audit_after):
        raise ValueError("旧版等级上限审计样本长度不一致。")

    project = RomProject.load(rom_path)
    current_instruction, current_runtime_cap = _runtime_cap(rom_data)
    before_instruction, before_runtime_cap = _runtime_cap(audit_before)
    after_instruction, after_runtime_cap = _runtime_cap(audit_after)
    differences = tuple(
        index
        for index, (before, after) in enumerate(zip(audit_before, audit_after))
        if before != after
    )
    bank_counts = Counter(
        (offset - 16) // 0x2000
        for offset in differences
        if 16 <= offset < 16 + 32 * 0x2000
    )

    audit_supported = True
    audit_rejection = ""
    try:
        RomProject.load(audit_before_path)
    except ValueError as error:
        audit_supported = False
        audit_rejection = str(error)

    current_widths = _growth_widths(rom_data)
    before_widths = _growth_widths(audit_before)
    after_widths = _growth_widths(audit_after)
    verified_level_cap = project.get_verified_level_cap()
    experience_count = len(project.get_experience_totals())
    passed = all(
        (
            verified_level_cap == 99,
            current_runtime_cap == 99,
            experience_count == 99,
            set(current_widths) == {LegacyGrowthCodec.RECORD_SIZE},
            before_runtime_cap == 60,
            after_runtime_cap == 61,
            set(before_widths) == {30},
            set(after_widths) == {31},
            len(differences) == 3778,
            not audit_supported,
        )
    )
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": passed,
        "conclusion": (
            "当前受支持 ROM 已是固定 99 级布局；旧版 audit.nes 的 60→61 "
            "3778 字节重排不兼容，不能应用到当前产品。"
        ),
        "supported_rom": {
            "path": _relative(rom_path),
            "sha256": _sha256(rom_data),
            "runtime_compare": current_instruction,
            "runtime_level_cap": current_runtime_cap,
            "verified_level_cap": verified_level_cap,
            "experience_entries": experience_count,
            "growth_record_bytes": LegacyGrowthCodec.RECORD_SIZE,
            "growth_capacity": LegacyGrowthCodec.LEVEL_CAPACITY,
            "first_growth_offsets": [f"0x{offset:X}" for offset in _growth_offsets(rom_data)],
            "first_growth_widths": list(current_widths),
        },
        "legacy_audit": {
            "before_path": _relative(audit_before_path),
            "before_sha256": _sha256(audit_before),
            "after_path": _relative(audit_after_path),
            "after_sha256": _sha256(audit_after),
            "before_runtime_compare": before_instruction,
            "before_runtime_level_cap": before_runtime_cap,
            "after_runtime_compare": after_instruction,
            "after_runtime_level_cap": after_runtime_cap,
            "before_growth_widths": list(before_widths),
            "after_growth_widths": list(after_widths),
            "changed_bytes": len(differences),
            "changed_prg_banks": {
                f"0x{bank:02X}": count for bank, count in sorted(bank_counts.items())
            },
            "normalization_changes": sum(
                offset in NORMALIZATION_OFFSETS for offset in differences
            ),
            "accepted_by_current_product": audit_supported,
            "rejection": audit_rejection,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="核对 M09 当前 99 级布局与旧版 60→61 审计样本的兼容性。"
    )
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--audit-before", type=Path, default=DEFAULT_AUDIT_BEFORE)
    parser.add_argument("--audit-after", type=Path, default=DEFAULT_AUDIT_AFTER)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    report = analyze(args.rom, args.audit_before, args.audit_after)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
