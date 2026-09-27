from __future__ import annotations

import hashlib
import struct
from collections.abc import Sequence
from dataclasses import dataclass

from ..constants import INES_HEADER_SIZE, PRG_BANK_SIZE
from ..errors import RomFormatError
from ..rom_image import RomImage


@dataclass(frozen=True)
class MapTrigger:
    """One four-byte battlefield trigger record.

    The original Bank $0A runtime reads the third byte at $95E0.  $FF branches
    directly to the action at $9604; every other value is compared with the
    active character ID before the fourth byte is dispatched as an event or
    shop.  ``matches_character`` deliberately mirrors that verified rule.
    """

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

    def matches_character(self, character_id: int) -> bool:
        """Mirror the verified runtime character gate for this trigger."""

        return self.character_id == 0xFF or self.character_id == character_id


@dataclass(frozen=True)
class MapTriggerLayout:
    map_id: int
    pointer: int
    entries: tuple[MapTrigger, ...]


class MapTriggerCodec:
    """Lossless editor for X/Y/character/event map triggers.

    The original ROM stores the table and a tiny shared pool in Bank $0A.  The
    expanded FamiStudio build has two safe, non-contiguous spans: the original
    ten bytes at $9946-$994F and the zero-filled tail at $9ED4-$9FFF.  The
    occupied bytes between them must never be treated as trigger storage.
    """

    TERMINATOR = 0xFF
    # The reference editor advances at least one full four-byte record plus the
    # FF terminator for an empty unique layout.  This physical allocation, not
    # the one-byte semantic payload, is what consumes the shared pool.
    MINIMUM_SLOT_SIZE = 5

    def __init__(
        self,
        rom: RomImage,
        data: bytes | bytearray | None = None,
        *,
        record_locations: Sequence[object] | None = None,
        expanded_capacity: int | None = None,
    ) -> None:
        spec = rom.profile.map_triggers
        if spec is None:
            raise ValueError("当前 ROM 配置没有地图触发器布局。")
        self.rom = rom
        self.spec = spec
        self._source = rom.data if data is None else bytes(data)
        self._layout_cache: tuple[MapTriggerLayout, ...] | None = None
        self.pointer_table_offset = self.cpu_to_file_offset(spec.pointer_table)
        raw = self._source[
            self.pointer_table_offset : self.pointer_table_offset
            + spec.scenario_count * 2
        ]
        self.original_pointers = tuple(
            struct.unpack(f"<{spec.scenario_count}H", raw)
        )
        self._locations = tuple(record_locations or ())
        self._expanded_capacity = expanded_capacity
        if self._locations and len(self._locations) != spec.scenario_count:
            raise RomFormatError("扩展地图事件位置表数量不正确。")
        for map_id in range(spec.scenario_count):
            self.decode(map_id, self._source)

    @property
    def is_expanded(self) -> bool:
        return bool(self._locations)

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
        """First storage span; callers needing coverage must use pool_segments."""

        if self.is_expanded:
            return min(int(item.file_offset) for item in self._locations)
        return self.cpu_to_file_offset(self.spec.original_data_start)

    @property
    def pool_segments(self) -> tuple[tuple[int, int, int], ...]:
        """Return ``(CPU pointer, file offset, capacity)`` storage spans."""

        if self.is_expanded:
            unique: dict[int, tuple[int, int, int]] = {}
            for item in self._locations:
                offset = int(item.file_offset)
                unique.setdefault(
                    offset,
                    (int(item.pointer), offset, int(item.capacity)),
                )
            return tuple(unique.values())
        return (
            (
                self.spec.original_data_start,
                self.cpu_to_file_offset(self.spec.original_data_start),
                self.spec.original_data_end - self.spec.original_data_start,
            ),
            (
                self.spec.managed_data_start,
                self.cpu_to_file_offset(self.spec.managed_data_start),
                self.spec.managed_data_end - self.spec.managed_data_start,
            ),
        )

    @property
    def pool_capacity(self) -> int:
        if self.is_expanded and self._expanded_capacity is not None:
            return self._expanded_capacity
        return sum(capacity for _pointer, _offset, capacity in self.pool_segments)

    def pointer(self, map_id: int, data: bytes | bytearray | None = None) -> int:
        if not 0 <= map_id < self.spec.scenario_count:
            raise IndexError("地图触发器关卡 ID 超出范围。")
        source = self._source if data is None else bytes(data)
        offset = self.pointer_table_offset + map_id * 2
        return int.from_bytes(source[offset : offset + 2], "little")

    def _pointer_is_readable(self, pointer: int) -> bool:
        if self.is_expanded:
            return 0xA000 <= pointer < 0xC000
        return (
            self.spec.original_data_start <= pointer < self.spec.original_data_end
            or self.spec.managed_data_start <= pointer < self.spec.managed_data_end
        )

    def decode(
        self,
        map_id: int,
        data: bytes | bytearray | None = None,
    ) -> MapTriggerLayout:
        source = self._source if data is None else bytes(data)
        pointer = self.pointer(map_id, source)
        if not self._pointer_is_readable(pointer):
            raise RomFormatError(
                f"关卡 ${map_id:02X} 的地图触发器指针 ${pointer:04X} 越界。"
            )
        if self.is_expanded:
            location = self._locations[map_id]
            if pointer != int(location.pointer):
                raise RomFormatError(
                    f"关卡 ${map_id:02X} 的地图事件指针与位置表不一致。"
                )
            cursor = int(location.file_offset)
            bank_end = cursor + int(location.capacity)
        else:
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
        source = self._source if data is None else bytes(data)
        if source is self._source or source == self._source:
            if self._layout_cache is None:
                self._layout_cache = tuple(
                    self.decode(map_id, self._source)
                    for map_id in range(self.spec.scenario_count)
                )
            return self._layout_cache
        return tuple(
            self.decode(map_id, source)
            for map_id in range(self.spec.scenario_count)
        )

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
        data: bytes | bytearray | None,
        map_id: int,
        entries: tuple[MapTrigger, ...],
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        source = bytes(data)
        if self.is_expanded:
            raise ValueError("扩展地图事件必须通过地图共享池统一重排。")
        if not 0 <= map_id < self.spec.scenario_count:
            raise IndexError("地图触发器关卡 ID 超出范围。")
        self.validate_entries(entries)
        encoded_by_map = [self.encode_entries(layout.entries) for layout in self.layouts(source)]
        encoded_by_map[map_id] = self.encode_entries(entries)

        pointers, packed_segments, _used = self._pack_unexpanded(encoded_by_map)

        pointer_after = struct.pack(f"<{len(pointers)}H", *pointers)
        pointer_before = source[
            self.pointer_table_offset : self.pointer_table_offset + len(pointer_after)
        ]
        patches: list[tuple[int, bytes, bytes]] = [
            (self.pointer_table_offset, pointer_before, pointer_after)
        ]
        for (_pointer, offset, capacity), packed in zip(
            self.pool_segments, packed_segments
        ):
            patches.append(
                (offset, source[offset : offset + capacity], packed)
            )
        return tuple(patches)

    def _pack_unexpanded(
        self,
        payloads_by_map: Sequence[bytes],
    ) -> tuple[tuple[int, ...], tuple[bytes, ...], int]:
        """Pack unique payloads into the safe 10 B + 300 B split pool."""

        if self.is_expanded:
            raise ValueError("扩展地图事件必须通过地图共享池统一重排。")
        unique = list(dict.fromkeys(bytes(payload) for payload in payloads_by_map))
        allocated = [max(len(payload), self.MINIMUM_SLOT_SIZE) for payload in unique]
        segments = self.pool_segments
        if len(segments) != 2:
            raise RomFormatError("地图事件分段池结构无效。")
        first_capacity = segments[0][2]
        tail_capacity = segments[1][2]

        # Choose a deterministic subset for the tiny original span.  Dynamic
        # programming avoids rejecting a valid 307/310 B layout merely because
        # its large first record cannot fit in the ten-byte span.
        choices: dict[int, tuple[int, ...]] = {0: ()}
        for index, size in enumerate(allocated):
            for used, indices in tuple(sorted(choices.items(), reverse=True)):
                candidate = used + size
                if candidate <= first_capacity and candidate not in choices:
                    choices[candidate] = (*indices, index)
        first_used = max(choices)
        first_indices = set(choices[first_used])
        tail_used = sum(
            size for index, size in enumerate(allocated) if index not in first_indices
        )
        used = sum(allocated)
        if tail_used > tail_capacity:
            raise ValueError(
                f"地图触发器重排后需要 {used} 字节，"
                f"分段共享池只有 {self.pool_capacity} 字节"
                f"（原始区 {first_capacity} B + 尾部区 {tail_capacity} B）。"
            )

        buffers = [bytearray(first_capacity), bytearray(tail_capacity)]
        cursors = [0, 0]
        address_by_payload: dict[bytes, int] = {}
        for index, payload in enumerate(unique):
            segment_index = 0 if index in first_indices else 1
            cursor = cursors[segment_index]
            size = allocated[index]
            pointer = segments[segment_index][0] + cursor
            buffers[segment_index][cursor : cursor + len(payload)] = payload
            cursors[segment_index] += size
            address_by_payload[payload] = pointer
        pointers = tuple(address_by_payload[bytes(payload)] for payload in payloads_by_map)
        return pointers, tuple(bytes(buffer) for buffer in buffers), used

    def semantic_digest(self, layout: MapTriggerLayout) -> str:
        return hashlib.sha256(self.encode_entries(layout.entries)).hexdigest().upper()

    def storage_used(self, data: bytes | bytearray | None = None) -> int:
        payloads = {
            self.encode_entries(layout.entries) for layout in self.layouts(data)
        }
        return sum(max(len(payload), self.MINIMUM_SLOT_SIZE) for payload in payloads)

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
        _pointers, _segments, used = self._pack_unexpanded(payloads)
        return used
