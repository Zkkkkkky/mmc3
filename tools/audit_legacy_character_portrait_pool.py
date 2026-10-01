from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path


INES_HEADER = 16
BANK = 0x04
PAIR_FILE_BASE = INES_HEADER + BANK * 0x2000
WINDOW_BASE = 0x8000
DIRECTORY_OFFSET = PAIR_FILE_BASE
PORTRAIT_DIRECTORY_INDEX = 2
CONFIGURATION_DIRECTORY_INDEX = 6
PORTRAIT_POINTER_COUNT = 201
CONFIGURATION_POINTER_COUNT = 256
FIXED_TAIL_START = 0xB5E6


@dataclass(frozen=True)
class PortraitTailData:
    portraits: tuple[bytes, ...]
    configurations: tuple[bytes, ...]


def _file_offset(pointer: int) -> int:
    if not WINDOW_BASE <= pointer < 0xC000:
        raise ValueError(f"CPU 指针 ${pointer:04X} 不在 $8000—$BFFF。")
    return PAIR_FILE_BASE + pointer - WINDOW_BASE


def _root(data: bytes, index: int) -> int:
    return struct.unpack_from("<H", data, DIRECTORY_OFFSET + index * 2)[0]


def _pointers(data: bytes, pointer: int, count: int) -> tuple[int, ...]:
    return tuple(struct.unpack_from(f"<{count}H", data, _file_offset(pointer)))


def _configuration_size(data: bytes, pointer: int) -> int:
    # The stock game reads a tenth byte only when the high flag bit is set.
    # This is why the physical pool contains a mixture of 9- and 10-byte
    # records even though the relocation layer preserves ten observable bytes.
    return 10 if data[_file_offset(pointer)] & 0x80 else 9


def parse_portrait_tail(data: bytes) -> tuple[int, PortraitTailData]:
    portrait_root = _root(data, PORTRAIT_DIRECTORY_INDEX)
    configuration_root = _root(data, CONFIGURATION_DIRECTORY_INDEX)
    if not WINDOW_BASE <= portrait_root < configuration_root < FIXED_TAIL_START:
        raise ValueError("Bank $04 的头像/战斗外观目录无效。")
    portrait_pointers = _pointers(data, portrait_root, PORTRAIT_POINTER_COUNT)
    configuration_pointers = _pointers(
        data, configuration_root, CONFIGURATION_POINTER_COUNT
    )
    if portrait_pointers[0] or configuration_pointers[0]:
        raise ValueError("头像或战斗外观的保留 ID $00 指针已变化。")
    portraits = tuple(
        data[_file_offset(pointer) : _file_offset(pointer) + 7]
        for pointer in portrait_pointers[1:]
    )
    configurations = tuple(
        data[
            _file_offset(pointer) :
            _file_offset(pointer) + _configuration_size(data, pointer)
        ]
        for pointer in configuration_pointers[1:]
    )
    return portrait_root, PortraitTailData(portraits, configurations)


def pack_portrait_tail(
    portrait_root: int, logical: PortraitTailData
) -> tuple[bytes, int, int]:
    if len(logical.portraits) != 200 or len(logical.configurations) != 255:
        raise ValueError("头像必须为 200 项，机体战斗外观必须为 255 项。")
    image = bytearray(FIXED_TAIL_START - portrait_root)
    cursor = portrait_root

    def write(pointer: int, raw: bytes) -> None:
        start = pointer - portrait_root
        image[start : start + len(raw)] = raw

    def pack(records: tuple[bytes, ...], pointer_count: int) -> int:
        nonlocal cursor
        table = cursor
        cursor += pointer_count * 2
        addresses: dict[bytes, int] = {}
        pointers = [0]
        for raw in records:
            pointer = addresses.get(raw)
            if pointer is None:
                pointer = cursor
                addresses[raw] = pointer
                write(pointer, raw)
                cursor += len(raw)
            pointers.append(pointer)
        write(table, struct.pack(f"<{pointer_count}H", *pointers))
        return table

    packed_portrait_root = pack(logical.portraits, PORTRAIT_POINTER_COUNT)
    configuration_root = pack(
        logical.configurations, CONFIGURATION_POINTER_COUNT
    )
    if cursor > FIXED_TAIL_START:
        raise ValueError(
            f"头像与机体战斗外观需要 {cursor - portrait_root} 字节，"
            f"当前尾区只有 {FIXED_TAIL_START - portrait_root} 字节。"
        )
    if packed_portrait_root != portrait_root:
        raise AssertionError("头像根地址发生意外变化。")
    return bytes(image[: cursor - portrait_root]), configuration_root, cursor


def audit(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    portrait_root, logical = parse_portrait_tail(data)
    packed, configuration_root, used_end = pack_portrait_tail(
        portrait_root, logical
    )
    original = data[_file_offset(portrait_root) : _file_offset(used_end)]
    mismatches = [
        portrait_root + index
        for index, (before, after) in enumerate(zip(original, packed))
        if before != after
    ]
    actual_configuration_root = _root(data, CONFIGURATION_DIRECTORY_INDEX)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "portrait_root": f"${portrait_root:04X}",
        "configuration_root": f"${configuration_root:04X}",
        "used_end": f"${used_end:04X}",
        "capacity": FIXED_TAIL_START - portrait_root,
        "used": used_end - portrait_root,
        "remaining": FIXED_TAIL_START - used_end,
        "unique_portraits": len(set(logical.portraits)),
        "unique_configurations": len(set(logical.configurations)),
        "configuration_record_lengths": {
            "9": sum(len(item) == 9 for item in set(logical.configurations)),
            "10": sum(len(item) == 10 for item in set(logical.configurations)),
        },
        "exact_rebuild": (
            not mismatches and configuration_root == actual_configuration_root
        ),
        "mismatch_count": len(mismatches),
        "first_mismatches": [f"${item:04X}" for item in mismatches[:16]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="复核旧修改器 Bank $04 头像与机体战斗外观的连续重排。"
    )
    parser.add_argument("rom", nargs="+", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    reports = [audit(path) for path in args.rom]
    text = json.dumps(reports, ensure_ascii=False, indent=2)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
