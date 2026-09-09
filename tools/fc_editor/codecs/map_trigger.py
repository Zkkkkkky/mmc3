from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from ..constants import INES_HEADER_SIZE, PRG_BANK_SIZE
from ..errors import RomFormatError
from ..rom_image import RomImage


@dataclass(frozen=True)
class MapTrigger:
    x: int
    y: int
    character_id: int
    event_id: int

    @property
    def is_shop(self) -> bool:
        return self.event_id >= 0xF0

    @property
    def shop_id(self) -> int | None:
        return self.event_id & 0x0F if self.is_shop else None

    def to_bytes(self) -> bytes:
        return bytes((self.x, self.y, self.character_id, self.event_id))


@dataclass(frozen=True)
class MapTriggerLayout:
    map_id: int
    pointer: int
    entries: tuple[MapTrigger, ...]


class MapTriggerCodec:
    """Lossless editor for X/Y/character/event map triggers.

    The original ROM stores the table and a tiny shared pool in Bank $0A. On
    first edit all 32 layouts are deterministically repacked into the verified
    zero-filled tail at $9ED4-$9FFF, leaving the old data untouched.
    """

    TERMINATOR = 0xFF

    def __init__(self, rom: RomImage) -> None:
        spec = rom.profile.map_triggers
        if spec is None:
            raise ValueError("当前 ROM 配置没有地图触发器布局。")
        self.rom = rom
        self.spec = spec
        self.pointer_table_offset = self.cpu_to_file_offset(spec.pointer_table)
        raw = rom.read(self.pointer_table_offset, spec.scenario_count * 2)
        self.original_pointers = tuple(
            struct.unpack(f"<{spec.scenario_count}H", raw)
        )
        for map_id in range(spec.scenario_count):
            self.decode(map_id, rom.data)

    def cpu_to_file_offset(self, address: int) -> int:
        if not self.spec.window_base <= address < self.spec.window_base + PRG_BANK_SIZE:
            raise ValueError(f"地图触发器 CPU 地址 ${address:04X} 无效。")
        return (
            INES_HEADER_SIZE
            + self.spec.prg_bank * PRG_BANK_SIZE
            + address
            - self.spec.window_base
        )

    @property
    def pool_offset(self) -> int:
        return self.cpu_to_file_offset(self.spec.managed_data_start)

    @property
    def pool_capacity(self) -> int:
        return self.spec.managed_data_end - self.spec.managed_data_start

    def pointer(self, map_id: int, data: bytes | bytearray | None = None) -> int:
        if not 0 <= map_id < self.spec.scenario_count:
            raise IndexError("地图触发器关卡 ID 超出范围。")
        source = self.rom.data if data is None else bytes(data)
        offset = self.pointer_table_offset + map_id * 2
        return int.from_bytes(source[offset : offset + 2], "little")

    def _pointer_is_readable(self, pointer: int) -> bool:
        return (
            self.spec.original_data_start <= pointer < self.spec.original_data_end
            or self.spec.managed_data_start <= pointer < self.spec.managed_data_end
        )

    def decode(
        self,
        map_id: int,
        data: bytes | bytearray | None = None,
    ) -> MapTriggerLayout:
        source = self.rom.data if data is None else bytes(data)
        pointer = self.pointer(map_id, source)
        if not self._pointer_is_readable(pointer):
            raise RomFormatError(
                f"关卡 ${map_id:02X} 的地图触发器指针 ${pointer:04X} 越界。"
            )
        cursor = self.cpu_to_file_offset(pointer)
        bank_end = INES_HEADER_SIZE + (self.spec.prg_bank + 1) * PRG_BANK_SIZE
        entries: list[MapTrigger] = []
        while cursor < bank_end:
            if source[cursor] == self.TERMINATOR:
                layout = MapTriggerLayout(map_id, pointer, tuple(entries))
                self.validate_entries(layout.entries)
                return layout
            if cursor + 4 > bank_end:
                break
            entries.append(MapTrigger(*source[cursor : cursor + 4]))
            cursor += 4
        raise RomFormatError(f"关卡 ${map_id:02X} 的地图触发器缺少 FF 结束码。")

    def layouts(self, data: bytes | bytearray | None = None) -> tuple[MapTriggerLayout, ...]:
        return tuple(self.decode(map_id, data) for map_id in range(self.spec.scenario_count))

    @classmethod
    def validate_entries(
        cls,
        entries: tuple[MapTrigger, ...],
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        occupied: set[tuple[int, int, int]] = set()
        for index, entry in enumerate(entries, 1):
            if not 0 <= entry.x < cls.TERMINATOR or not 0 <= entry.y <= 0xFF:
                raise ValueError(f"第 {index} 条地图触发器的坐标字节越界。")
            if entry.character_id != 0xFF and not 0 <= entry.character_id < 0xC8:
                raise ValueError(f"第 {index} 条地图触发器的限定人物越界。")
            if not 0 <= entry.event_id <= 0xFF:
                raise ValueError(f"第 {index} 条地图触发器的事件编号越界。")
            if width is not None and height is not None:
                if not 0 <= entry.x < width or not 0 <= entry.y < height:
                    raise ValueError(
                        f"第 {index} 条地图触发器坐标 "
                        f"({entry.x}, {entry.y}) 超出 {width}×{height} 地图。"
                    )
            identity = (entry.x, entry.y, entry.character_id)
            if identity in occupied:
                raise ValueError(
                    f"地图触发器坐标/限定人物 {identity} 重复。"
                )
            occupied.add(identity)

    @classmethod
    def encode_entries(cls, entries: tuple[MapTrigger, ...]) -> bytes:
        cls.validate_entries(entries)
        return b"".join(entry.to_bytes() for entry in entries) + bytes((cls.TERMINATOR,))

    def repack_patches(
        self,
        data: bytes | bytearray,
        map_id: int,
        entries: tuple[MapTrigger, ...],
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        source = bytes(data)
        if not 0 <= map_id < self.spec.scenario_count:
            raise IndexError("地图触发器关卡 ID 超出范围。")
        self.validate_entries(entries)
        encoded_by_map = [self.encode_entries(layout.entries) for layout in self.layouts(source)]
        encoded_by_map[map_id] = self.encode_entries(entries)

        pool = bytearray(self.pool_capacity)
        address_by_payload: dict[bytes, int] = {}
        cursor = 0
        pointers: list[int] = []
        for payload in encoded_by_map:
            address = address_by_payload.get(payload)
            if address is None:
                if cursor + len(payload) > len(pool):
                    raise ValueError(
                        f"地图触发器压缩后需要 {cursor + len(payload)} 字节，"
                        f"托管池只有 {len(pool)} 字节。"
                    )
                address = self.spec.managed_data_start + cursor
                pool[cursor : cursor + len(payload)] = payload
                address_by_payload[payload] = address
                cursor += len(payload)
            pointers.append(address)

        pointer_after = struct.pack(f"<{len(pointers)}H", *pointers)
        pointer_before = source[
            self.pointer_table_offset : self.pointer_table_offset + len(pointer_after)
        ]
        pool_before = source[self.pool_offset : self.pool_offset + self.pool_capacity]
        return (
            (self.pointer_table_offset, pointer_before, pointer_after),
            (self.pool_offset, pool_before, bytes(pool)),
        )

    def semantic_digest(self, layout: MapTriggerLayout) -> str:
        return hashlib.sha256(self.encode_entries(layout.entries)).hexdigest().upper()

    def storage_used(self, data: bytes | bytearray | None = None) -> int:
        payloads = {
            self.encode_entries(layout.entries) for layout in self.layouts(data)
        }
        return sum(len(payload) for payload in payloads)

    def storage_used_after(
        self,
        data: bytes | bytearray,
        map_id: int,
        entries: tuple[MapTrigger, ...],
    ) -> int:
        if not 0 <= map_id < self.spec.scenario_count:
            raise IndexError("地图触发器关卡 ID 超出范围。")
        self.validate_entries(entries)
        payloads = [self.encode_entries(layout.entries) for layout in self.layouts(data)]
        payloads[map_id] = self.encode_entries(entries)
        used = sum(len(payload) for payload in set(payloads))
        if used > self.pool_capacity:
            raise ValueError(
                f"地图触发器压缩后需要 {used} 字节，"
                f"托管池只有 {self.pool_capacity} 字节。"
            )
        return used
