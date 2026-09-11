from __future__ import annotations

from dataclasses import dataclass

from ..errors import RomFormatError


@dataclass(frozen=True)
class LegacyGrowthRecord:
    growth_id: int
    file_offset: int
    values: tuple[int, ...]
    raw: bytes
    shared_ids: tuple[int, ...]


class LegacyGrowthCodec:
    POINTER_TABLE = 0xA720
    COUNT = 53
    FIRST_ID = 201
    RECORD_SIZE = 50
    POOL_START = 0xA78A
    POOL_END = 0xAA46
    READER = bytes.fromhex("C9 C9 B0 05 85 BA 4C 23 98 E9 C9 85 19 A9 73 85 18 20 0B C1")

    def __init__(self, data: bytes | bytearray) -> None:
        self.data = bytes(data)
        if self.data[0x801A:0x801C] != bytes.fromhex("10 A7") or self.data[0xA4C0:0xA4C0 + len(self.READER)] != self.READER:
            raise RomFormatError("成长表入口或成长读取程序不匹配。")
        self.offsets = tuple(0x10 + int.from_bytes(self.data[self.POINTER_TABLE + 2 * index:self.POINTER_TABLE + 2 * index + 2], "little") for index in range(self.COUNT))
        if any(not self.POOL_START <= offset <= self.POOL_END - self.RECORD_SIZE for offset in self.offsets):
            raise RomFormatError("成长方式指针超出已验证数据区。")

    def record(self, growth_id: int) -> LegacyGrowthRecord:
        if not self.FIRST_ID <= growth_id < self.FIRST_ID + self.COUNT:
            raise ValueError("成长方式编号须在 201—253 之间。")
        offset = self.offsets[growth_id - self.FIRST_ID]
        raw = self.data[offset:offset + self.RECORD_SIZE]
        values = tuple(value for byte in raw for value in (byte >> 4, byte & 15))[:99]
        return LegacyGrowthRecord(growth_id, offset, values, raw, tuple(self.FIRST_ID + i for i, other in enumerate(self.offsets) if other == offset))

    def replacement_patch(self, growth_id: int, values) -> tuple[int, bytes, bytes]:
        record = self.record(growth_id)
        values = tuple(values)
        if len(values) != 99 or any(not isinstance(value, int) or not 0 <= value <= 15 for value in values):
            raise ValueError("成长方式需要 99 个 0—15 的整数。")
        complete = values + (record.raw[-1] & 15,)
        after = bytes((complete[index] << 4) | complete[index + 1] for index in range(0, 100, 2))
        return record.file_offset, record.raw, after
