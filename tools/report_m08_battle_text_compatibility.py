from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fc_editor.codecs.legacy_text import (  # noqa: E402
    BATTLE_GROUPS_BY_BANK,
    BATTLE_TEXT_ARENAS,
    LegacyTextCodec,
)


DEFAULT_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
DEFAULT_REPORT = (
    ROOT / "output" / "verification" / "m08-battle-text-compatibility.json"
)
EXPECTED_ROM_SHA256 = (
    "82C218275459D53C0F306F6BC036C4797316976E0FA7AD1D5A8247E338995B8E"
)


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _apply(data: bytes, patches) -> bytes:
    result = bytearray(data)
    for offset, before, after in patches:
        if bytes(result[offset : offset + len(before)]) != before:
            raise ValueError(f"补丁基线已变化：0x{offset:06X}")
        result[offset : offset + len(after)] = after
    return bytes(result)


def _records(codec: LegacyTextCodec, keys: tuple[str, ...]):
    return {
        (key, index, variant): codec.record(key, index, variant).raw
        for key in keys
        for index in range(codec.group_by_key[key].count)
        for variant in range(codec.variant_count(key, index))
    }


def _aliases(codec: LegacyTextCodec, keys: tuple[str, ...]):
    groups: dict[int, list[tuple[str, int, int]]] = {}
    for identity in _records(codec, keys):
        groups.setdefault(codec.record(*identity).pointer, []).append(identity)
    return tuple(sorted(tuple(values) for values in groups.values()))


def _patch_rows(patches) -> list[dict[str, object]]:
    return [
        {
            "offset": f"0x{offset:06X}",
            "bytes": len(before),
            "changed_bytes": sum(a != b for a, b in zip(before, after)),
        }
        for offset, before, after in patches
    ]


def analyze(rom_path: Path) -> dict[str, object]:
    data = rom_path.read_bytes()
    codec = LegacyTextCodec(data)
    rom_sha256 = _sha256(data)
    usage = {
        f"{bank:02X}": codec.battle_usage(bank)
        for bank in BATTLE_GROUPS_BY_BANK
    }

    keys_2a = BATTLE_GROUPS_BY_BANK[0x2A]
    before_2a = _records(codec, keys_2a)
    aliases_2a = _aliases(codec, keys_2a)
    shorter_2a_id = ("battle_00", 0, 0)
    longer_2a_id = ("battle_00", 0, 1)
    shorter_2a = codec.record(*shorter_2a_id).text.replace("小毛贼", "贼")
    longer_2a = codec.record(*longer_2a_id).text.replace(
        "你们", "你们你们", 1
    )
    edits_2a = {shorter_2a_id: shorter_2a, longer_2a_id: longer_2a}
    patches_2a = codec.battle_repack_patches(edits_2a)
    data_2a = _apply(data, patches_2a)
    codec_2a = LegacyTextCodec(data_2a)
    other_2a_preserved = all(
        codec_2a.record(*identity).raw == raw
        for identity, raw in before_2a.items()
        if identity not in edits_2a
    )
    system_start = LegacyTextCodec.offset(0x2A, 0x9768)
    system_end = LegacyTextCodec.offset(0x2A, 0xA000)

    shorter_0e_id = ("battle_04", 0, 0)
    longer_0e_id = ("battle_04", 0, 1)
    shorter_0e = codec.record(*shorter_0e_id).text.replace("小毛贼", "贼")
    first_0e_patches = codec.battle_repack_patches(
        {shorter_0e_id: shorter_0e}
    )
    first_0e = _apply(data, first_0e_patches)
    reopened_0e = LegacyTextCodec(first_0e)
    longer_0e = reopened_0e.record(*longer_0e_id).text.replace(
        "敌人", "敌人敌人", 1
    )
    second_0e_patches = reopened_0e.battle_repack_patches(
        {longer_0e_id: longer_0e}
    )
    data_0e = _apply(first_0e, second_0e_patches)
    codec_0e = LegacyTextCodec(data_0e)
    gap_rows = []
    gaps_unchanged = True
    for start, end in ((0x97E4, 0x97FB), (0x9B3D, 0x9E28)):
        offset = LegacyTextCodec.offset(0x0E, start)
        before = data[offset : offset + end - start]
        after = data_0e[offset : offset + end - start]
        unchanged = before == after
        gaps_unchanged &= unchanged
        gap_rows.append(
            {
                "cpu_range": f"${start:04X}-${end - 1:04X}",
                "bytes": end - start,
                "sha256_before": _sha256(before),
                "sha256_after": _sha256(after),
                "unchanged": unchanged,
            }
        )

    overflow_id = ("battle_00", 0, 0)
    overflow_text = codec.record(*overflow_id).text.replace(
        "嘿嘿", "嘿嘿嘿", 1
    )
    overflow_rejected = False
    overflow_error = ""
    try:
        codec.battle_repack_patches({overflow_id: overflow_text})
    except ValueError as error:
        overflow_error = str(error)
        overflow_rejected = "超出 2 字节" in overflow_error

    checks = {
        "supported_rom_hash": rom_sha256 == EXPECTED_ROM_SHA256,
        "baseline_arenas_exactly_full": all(item.free == 0 for item in usage.values()),
        "2a_shorter_and_longer_roundtrip": (
            codec_2a.record(*shorter_2a_id).text == shorter_2a
            and codec_2a.record(*longer_2a_id).text == longer_2a
        ),
        "2a_other_records_preserved": other_2a_preserved,
        "2a_alias_topology_preserved": _aliases(codec_2a, keys_2a) == aliases_2a,
        "2a_system_table_and_pool_unchanged": (
            data_2a[system_start:system_end] == data[system_start:system_end]
        ),
        "2a_reopened_no_op": codec_2a.battle_repack_patches(edits_2a) == (),
        "0e_shorter_then_reopen_then_longer": (
            codec_0e.record(*shorter_0e_id).text == shorter_0e
            and codec_0e.record(*longer_0e_id).text == longer_0e
            and codec_0e.battle_usage(0x0E).free == 0
        ),
        "0e_non_text_gaps_unchanged": gaps_unchanged,
        "capacity_overflow_rejected": overflow_rejected,
    }
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": all(checks.values()),
        "rom": {
            "path": _relative(rom_path),
            "size": len(data),
            "sha256": rom_sha256,
        },
        "arenas": {
            f"{bank:02X}": {
                "groups": list(BATTLE_GROUPS_BY_BANK[bank]),
                "ranges": [
                    f"${start:04X}-${end - 1:04X}"
                    for start, end in BATTLE_TEXT_ARENAS[bank]
                ],
                "capacity": item.capacity,
                "used": item.used,
                "free": item.free,
                "text_records": item.text_records,
                "random_directories": item.random_directories,
            }
            for bank, item in (
                (int(key, 16), value) for key, value in usage.items()
            )
        },
        "repack_2a": {
            "shortened": list(shorter_2a_id),
            "grown": list(longer_2a_id),
            "pointer_before": f"${codec.record(*longer_2a_id).pointer:04X}",
            "pointer_after": f"${codec_2a.record(*longer_2a_id).pointer:04X}",
            "patches": _patch_rows(patches_2a),
        },
        "repack_0e": {
            "free_after_shorten": reopened_0e.battle_usage(0x0E).free,
            "free_after_grow": codec_0e.battle_usage(0x0E).free,
            "first_patches": _patch_rows(first_0e_patches),
            "second_patches": _patch_rows(second_0e_patches),
            "protected_non_text_gaps": gap_rows,
        },
        "overflow": {
            "rejected": overflow_rejected,
            "message": overflow_error,
        },
        "checks": checks,
        "limitations": [
            "搬移只在同一运行时 Bank 的已验证正文/随机目录段内进行，不跨 Bank，也不占用扩展 PRG。",
            "Bank $0E 的 $97E4-$97FA 与 $9B3D-$9E27 含非文字数据，始终排除在重排补丁之外。",
            "若同 Bank 总字节超容，整个事务拒绝；必须先缩短其他对话或还原草稿。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="验证 M08 战斗文字池内重排、随机目录与非文字隔离。"
    )
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = analyze(args.rom)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
