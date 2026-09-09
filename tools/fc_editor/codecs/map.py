from __future__ import annotations

import hashlib
import struct

from ..constants import (
    MAP_MAX_HEIGHT,
    MAP_MAX_WIDTH,
)
from ..errors import RomFormatError
from ..models import MapRecord
from ..rom_image import RomImage


class MapCodec:
    """Decoder and capacity-bounded encoder for the 4-bit terrain RLE maps."""

    def __init__(self, rom: RomImage) -> None:
        self.rom = rom
        self.pointers = self._read_pointers()
        offsets = [
            self.pointer_to_file_offset(map_id, pointer)
            for map_id, pointer in enumerate(self.pointers)
        ]
        self.offsets = tuple(offsets)
        capacities: list[int] = []
        for map_id, pointer in enumerate(self.pointers):
            storage = self.rom.profile.map_storage(map_id)
            if map_id + 1 < storage.end_id:
                capacity = self.pointers[map_id + 1] - pointer
            else:
                capacity = storage.data_end_pointer - pointer
            if capacity <= 0:
                raise RomFormatError(f"地图 {map_id:02X} 数据容量无效。")
            capacities.append(capacity)
        self.capacities = tuple(capacities)

    def _read_pointers(self) -> tuple[int, ...]:
        profile = self.rom.profile
        raw = self.rom.read(profile.map_pointer_table_offset, profile.map_count * 2)
        pointers = struct.unpack(f"<{profile.map_count}H", raw)
        if pointers[0] != profile.map_first_pointer:
            raise RomFormatError("地图指针表起始标记不正确。")
        for storage in profile.map_storage_ranges:
            segment = pointers[storage.first_id : storage.end_id]
            if any(
                not storage.window_base <= pointer < storage.data_end_pointer
                for pointer in segment
            ):
                raise RomFormatError("地图指针超出当前 ROM 的地图存储区。")
            if any(left >= right for left, right in zip(segment, segment[1:])):
                raise RomFormatError("同一存储区内的地图指针没有严格递增。")
        return tuple(pointers)

    def pointer_to_file_offset(self, map_id: int, pointer: int) -> int:
        storage = self.rom.profile.map_storage(map_id)
        if not storage.window_base <= pointer < storage.data_end_pointer:
            raise ValueError(f"地图 CPU 指针 ${pointer:04X} 无效。")
        return 16 + storage.prg_bank * 0x2000 + pointer - storage.window_base

    def record_offset(self, map_id: int) -> int:
        if not 0 <= map_id < self.rom.profile.map_count:
            raise IndexError(
                f"Map ID must be between 00 and {self.rom.profile.map_count - 1:02X}"
            )
        return self.offsets[map_id]

    def decode(self, map_id: int, data: bytes | None = None) -> MapRecord:
        if not 0 <= map_id < self.rom.profile.map_count:
            raise IndexError(
                f"Map ID must be between 00 and {self.rom.profile.map_count - 1:02X}"
            )
        source = self.rom.data if data is None else data
        offset = self.offsets[map_id]
        capacity = self.capacities[map_id]
        block = bytes(source[offset : offset + capacity])
        if len(block) != capacity or capacity < 3:
            raise RomFormatError(f"地图 {map_id:02X} 数据块不完整。")
        width, height = block[0], block[1]
        if not 1 <= width <= MAP_MAX_WIDTH or not 1 <= height <= MAP_MAX_HEIGHT:
            raise RomFormatError(
                f"地图 {map_id:02X} 尺寸 {width}×{height} 超出 1—32。"
            )
        expected_count = width * height
        tiles: list[int] = []
        cursor = 2
        while len(tiles) < expected_count:
            if cursor >= capacity:
                raise RomFormatError(f"地图 {map_id:02X} 的 RLE 数据提前结束。")
            token = block[cursor]
            cursor += 1
            run_length = (token >> 4) + 1
            tile = token & 0x0F
            if len(tiles) + run_length > expected_count:
                raise RomFormatError(f"地图 {map_id:02X} 的 RLE 游程越过地图末尾。")
            tiles.extend((tile,) * run_length)
        return MapRecord(
            map_id,
            self.pointers[map_id],
            width,
            height,
            tuple(tiles),
            block[:cursor],
            capacity,
        )

    @staticmethod
    def encode(width: int, height: int, tiles: tuple[int, ...]) -> bytes:
        if not 1 <= width <= MAP_MAX_WIDTH or not 1 <= height <= MAP_MAX_HEIGHT:
            raise ValueError("地图宽高必须在 1—32 之间。")
        if len(tiles) != width * height:
            raise ValueError("地图图块数量与宽高不一致。")
        if any(not 0 <= tile <= 0x0F for tile in tiles):
            raise ValueError("逻辑地形编号必须在 0—15 之间。")
        encoded = bytearray((width, height))
        cursor = 0
        while cursor < len(tiles):
            tile = tiles[cursor]
            run_length = 1
            while (
                cursor + run_length < len(tiles)
                and tiles[cursor + run_length] == tile
                and run_length < 16
            ):
                run_length += 1
            encoded.append(((run_length - 1) << 4) | tile)
            cursor += run_length
        return bytes(encoded)

    @staticmethod
    def semantic_digest(record: MapRecord) -> str:
        payload = bytes((record.width, record.height, *record.tiles))
        return hashlib.sha256(payload).hexdigest().upper()

    def replacement_patch(
        self,
        data: bytes,
        map_id: int,
        width: int,
        height: int,
        tiles: tuple[int, ...],
    ) -> tuple[int, bytes, bytes]:
        offset = self.record_offset(map_id)
        capacity = self.capacities[map_id]
        encoded = self.encode(width, height, tiles)
        if len(encoded) > capacity:
            raise ValueError(
                f"地图 {map_id:02X} 编码需要 {len(encoded)} 字节，"
                f"原数据块只有 {capacity} 字节。"
            )
        before = bytes(data[offset : offset + capacity])
        if len(before) != capacity:
            raise RomFormatError(f"地图 {map_id:02X} 数据块不完整。")
        after = encoded + before[len(encoded) :]
        return offset, before, after

    def round_trip(self, map_id: int) -> bool:
        record = self.decode(map_id)
        return self.encode(record.width, record.height, record.tiles) == record.raw
