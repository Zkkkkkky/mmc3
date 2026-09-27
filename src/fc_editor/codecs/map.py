from __future__ import annotations

import hashlib
import struct
from collections.abc import Sequence

from ..constants import (
    MAP_MAX_HEIGHT,
    MAP_MAX_WIDTH,
)
from ..errors import RomFormatError
from ..models import MapRecord
from ..profiles import MapStorageRange
from ..rom_image import RomImage


class MapCodec:
    """Decoder and capacity-bounded encoder for the 4-bit terrain RLE maps."""

    def __init__(
        self,
        rom: RomImage,
        data: bytes | bytearray | None = None,
        *,
        bank_table_offset: int | None = None,
        record_locations: Sequence[object] | None = None,
    ) -> None:
        self.rom = rom
        self._source = rom.data if data is None else bytes(data)
        # Capacity previews and legacy repacks repeatedly need the same raw
        # records.  The codec is rebound whenever map bytes change, so this
        # lazy snapshot is both safe and substantially cheaper than decoding
        # all 100 maps for every selected chapter.
        self._raw_payload_cache: tuple[bytes, ...] | None = None
        self.bank_table_offset = bank_table_offset
        if record_locations is not None:
            self.storage_ranges = rom.profile.map_storage_ranges
            locations = tuple(record_locations)
            if len(locations) != rom.profile.map_count:
                raise RomFormatError("扩展地图位置表数量不正确。")
            self.pointers = tuple(int(item.pointer) for item in locations)
            self.banks = tuple(int(item.bank) for item in locations)
            self.offsets = tuple(int(item.file_offset) for item in locations)
            self.capacities = tuple(int(item.capacity) for item in locations)
            return
        self.storage_ranges = self._read_storage_ranges()
        self.pointers = self._read_pointers()
        self.banks = self._read_banks()
        offsets = [
            self.pointer_to_file_offset(map_id, pointer)
            for map_id, pointer in enumerate(self.pointers)
        ]
        self.offsets = tuple(offsets)
        capacities = self._build_capacities()
        self.capacities = tuple(capacities)

    def _read_storage_ranges(self) -> tuple[MapStorageRange, ...]:
        templates = self.rom.profile.map_storage_ranges
        offsets = self.rom.profile.map_storage_boundary_offsets
        if not offsets:
            return templates
        if len(offsets) != len(templates) - 1:
            raise RomFormatError("地图动态分界数量与存储区数量不一致。")
        try:
            boundaries = tuple(self._source[offset] for offset in offsets)
        except IndexError as error:
            raise RomFormatError("地图动态分界超出 ROM。") from error
        ids = (templates[0].first_id, *boundaries, templates[-1].end_id)
        if any(left >= right for left, right in zip(ids, ids[1:])):
            raise RomFormatError("地图动态分界没有严格递增。")
        if ids[0] != 0 or ids[-1] != self.rom.profile.map_count:
            raise RomFormatError("地图动态分界没有覆盖完整地图编号。")
        return tuple(
            MapStorageRange(
                ids[index],
                ids[index + 1],
                template.prg_bank,
                template.window_base,
                template.data_end_pointer,
            )
            for index, template in enumerate(templates)
        )

    def map_storage(self, map_id: int) -> MapStorageRange:
        for storage in self.storage_ranges:
            if storage.contains(map_id):
                return storage
        raise IndexError(f"地图 ID {map_id:02X} 没有对应的存储区。")

    def _read_pointers(self) -> tuple[int, ...]:
        profile = self.rom.profile
        start = profile.map_pointer_table_offset
        raw = self._source[start : start + profile.map_count * 2]
        if len(raw) != profile.map_count * 2:
            raise RomFormatError("地图指针表不完整。")
        pointers = struct.unpack(f"<{profile.map_count}H", raw)
        if self.bank_table_offset is None and pointers[0] != profile.map_first_pointer:
            raise RomFormatError("地图指针表起始标记不正确。")
        if self.bank_table_offset is not None:
            if any(not 0xA000 <= pointer < 0xC000 for pointer in pointers):
                raise RomFormatError("扩展地图指针必须位于 $A000—$BFFF。")
            return tuple(pointers)
        for storage in self.storage_ranges:
            segment = pointers[storage.first_id : storage.end_id]
            if any(
                not storage.window_base <= pointer < storage.data_end_pointer
                for pointer in segment
            ):
                raise RomFormatError("地图指针超出当前 ROM 的地图存储区。")
            if any(left >= right for left, right in zip(segment, segment[1:])):
                raise RomFormatError("同一存储区内的地图指针没有严格递增。")
        return tuple(pointers)

    def _read_banks(self) -> tuple[int, ...]:
        if self.bank_table_offset is not None:
            end = self.bank_table_offset + self.rom.profile.map_count
            raw = self._source[self.bank_table_offset:end]
            if len(raw) != self.rom.profile.map_count:
                raise RomFormatError("地图 Bank 目录不完整。")
            return tuple(raw)
        return tuple(
            self.map_storage(map_id).prg_bank
            for map_id in range(self.rom.profile.map_count)
        )

    def _build_capacities(self) -> list[int]:
        if self.bank_table_offset is None:
            capacities: list[int] = []
            for map_id, pointer in enumerate(self.pointers):
                storage = self.map_storage(map_id)
                if map_id + 1 < storage.end_id:
                    capacity = self.pointers[map_id + 1] - pointer
                else:
                    capacity = storage.data_end_pointer - pointer
                if capacity <= 0:
                    raise RomFormatError(f"地图 {map_id:02X} 数据容量无效。")
                capacities.append(capacity)
            return capacities

        next_pointer: dict[tuple[int, int], int] = {}
        by_bank: dict[int, list[int]] = {}
        for bank, pointer in zip(self.banks, self.pointers):
            by_bank.setdefault(bank, []).append(pointer)
        for bank, pointers in by_bank.items():
            ordered = sorted(pointers)
            if len(ordered) != len(set(ordered)):
                raise RomFormatError(f"扩展地图 Bank ${bank:02X} 含重复指针。")
            for index, pointer in enumerate(ordered):
                next_pointer[(bank, pointer)] = (
                    ordered[index + 1] if index + 1 < len(ordered) else 0xC000
                )
        capacities = [
            next_pointer[(bank, pointer)] - pointer
            for bank, pointer in zip(self.banks, self.pointers)
        ]
        if any(capacity <= 0 for capacity in capacities):
            raise RomFormatError("扩展地图记录容量无效。")
        return capacities

    def pointer_to_file_offset(self, map_id: int, pointer: int) -> int:
        if self.bank_table_offset is not None:
            if not 0xA000 <= pointer < 0xC000:
                raise ValueError(f"地图 CPU 指针 ${pointer:04X} 无效。")
            return 16 + self.banks[map_id] * 0x2000 + pointer - 0xA000
        storage = self.map_storage(map_id)
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
        source = self._source if data is None else data
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

    def _replacement_payloads(
        self,
        source: bytes,
        map_id: int,
        replacement: bytes,
    ) -> tuple[bytes, ...]:
        if source is self._source or source == self._source:
            if self._raw_payload_cache is None:
                self._raw_payload_cache = tuple(
                    self.decode(current_id, self._source).raw
                    for current_id in range(self.rom.profile.map_count)
                )
            payloads = self._raw_payload_cache
        else:
            payloads = tuple(
                self.decode(current_id, source).raw
                for current_id in range(self.rom.profile.map_count)
            )
        return tuple(
            replacement if current_id == map_id else payload
            for current_id, payload in enumerate(payloads)
        )

    def _dynamic_partition_plan(
        self,
        payloads: Sequence[bytes],
    ) -> tuple[tuple[MapStorageRange, tuple[bytes, ...]], ...]:
        """Assign sequential maps to legacy Banks like the reference editor."""

        if not self.rom.profile.map_storage_boundary_offsets:
            raise ValueError("当前地图布局没有动态 Bank 分界。")
        if len(payloads) != self.rom.profile.map_count:
            raise ValueError("地图正文数量与 Profile 不一致。")
        starts = tuple(
            self.pointers[storage.first_id] for storage in self.storage_ranges
        )
        cursor = 0
        planned: list[tuple[MapStorageRange, tuple[bytes, ...]]] = []
        for index, (template, start_pointer) in enumerate(
            zip(self.storage_ranges, starts)
        ):
            first_id = cursor
            used = 0
            remaining_banks = len(self.storage_ranges) - index - 1
            maximum_end = len(payloads) - remaining_banks
            capacity = template.data_end_pointer - start_pointer
            while cursor < maximum_end:
                payload = payloads[cursor]
                if used + len(payload) > capacity:
                    break
                used += len(payload)
                cursor += 1
            if cursor == first_id:
                raise ValueError(
                    f"地图 ${cursor:02X} 的 {len(payloads[cursor])} 字节正文"
                    f"无法放入 Bank ${template.prg_bank:02X}。"
                )
            storage = MapStorageRange(
                first_id,
                cursor,
                template.prg_bank,
                template.window_base,
                template.data_end_pointer,
            )
            planned.append((storage, tuple(payloads[first_id:cursor])))
        if cursor != len(payloads):
            used = sum(len(payload) for payload in payloads[cursor:])
            raise ValueError(
                f"地图动态分区后仍有 {len(payloads) - cursor} 张地图、"
                f"共 {used} 字节无法放入三个 Bank。"
            )
        return tuple(planned)

    def _dynamic_repack_patches(
        self,
        source: bytes,
        map_id: int,
        replacement: bytes,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        payloads = self._replacement_payloads(source, map_id, replacement)
        plan = self._dynamic_partition_plan(payloads)
        patches: list[tuple[int, bytes, bytes]] = []

        boundary_offsets = self.rom.profile.map_storage_boundary_offsets
        for offset, (storage, _partition_payloads) in zip(
            boundary_offsets, plan[:-1]
        ):
            patches.append((offset, source[offset : offset + 1], bytes((storage.end_id,))))

        pointers: list[int] = []
        for index, (_storage, partition_payloads) in enumerate(plan):
            current_storage = self.storage_ranges[index]
            cursor = self.pointers[current_storage.first_id]
            for payload in partition_payloads:
                pointers.append(cursor)
                cursor += len(payload)
        if len(pointers) != self.rom.profile.map_count:
            raise ValueError("地图动态重排没有生成完整指针表。")
        pointer_offset = self.rom.profile.map_pointer_table_offset
        pointer_after = struct.pack(f"<{len(pointers)}H", *pointers)
        pointer_before = source[pointer_offset : pointer_offset + len(pointer_after)]
        patches.append((pointer_offset, pointer_before, pointer_after))

        for index, (_storage, partition_payloads) in enumerate(plan):
            current_storage = self.storage_ranges[index]
            first_pointer = self.pointers[current_storage.first_id]
            total = current_storage.data_end_pointer - first_pointer
            pool_offset = (
                16
                + current_storage.prg_bank * 0x2000
                + first_pointer
                - current_storage.window_base
            )
            pool_before = source[pool_offset : pool_offset + total]
            packed = b"".join(partition_payloads)
            pool_after = packed + pool_before[len(packed) :]
            patches.append((pool_offset, pool_before, pool_after))
        return tuple(patches)

    def storage_usage(
        self,
        map_id: int,
        data: bytes | bytearray | None = None,
        *,
        replacement: bytes | None = None,
    ) -> tuple[int, int]:
        """Return used and total bytes for the map's legacy Bank partition."""

        if self.bank_table_offset is not None:
            raise ValueError("扩展地图容量由地图共享池统一计算。")
        source = self._source if data is None else bytes(data)
        if replacement is not None and self.rom.profile.map_storage_boundary_offsets:
            payloads = self._replacement_payloads(source, map_id, replacement)
            plan = self._dynamic_partition_plan(payloads)
            for index, (storage, partition_payloads) in enumerate(plan):
                if storage.contains(map_id):
                    current_storage = self.storage_ranges[index]
                    first_pointer = self.pointers[current_storage.first_id]
                    return (
                        sum(len(payload) for payload in partition_payloads),
                        storage.data_end_pointer - first_pointer,
                    )
            raise IndexError(f"地图 ID {map_id:02X} 没有动态存储区。")
        storage = self.map_storage(map_id)
        first_pointer = self.pointers[storage.first_id]
        total = storage.data_end_pointer - first_pointer
        used = 0
        for current_id in range(storage.first_id, storage.end_id):
            payload = (
                replacement
                if current_id == map_id and replacement is not None
                else self.decode(current_id, source).raw
            )
            used += len(payload)
        return used, total

    def total_storage_usage(
        self,
        data: bytes | bytearray | None = None,
        *,
        replacement_map_id: int | None = None,
        replacement: bytes | None = None,
    ) -> tuple[int, int]:
        """Return used and total terrain bytes across all legacy partitions."""

        if self.bank_table_offset is not None:
            raise ValueError("扩展地图容量由地图共享池统一计算。")
        if (replacement_map_id is None) != (replacement is None):
            raise ValueError("地图替换编号和正文必须同时提供。")
        if (
            replacement_map_id is not None
            and self.rom.profile.map_storage_boundary_offsets
        ):
            source = self._source if data is None else bytes(data)
            assert replacement is not None
            payloads = self._replacement_payloads(
                source, replacement_map_id, replacement
            )
            self._dynamic_partition_plan(payloads)
            total = sum(
                storage.data_end_pointer - self.pointers[storage.first_id]
                for storage in self.storage_ranges
            )
            return sum(len(payload) for payload in payloads), total
        used = 0
        total = 0
        for storage in self.storage_ranges:
            target_id = storage.first_id
            target_replacement = None
            if (
                replacement_map_id is not None
                and storage.contains(replacement_map_id)
            ):
                target_id = replacement_map_id
                target_replacement = replacement
            partition_used, partition_total = self.storage_usage(
                target_id,
                data,
                replacement=target_replacement,
            )
            used += partition_used
            total += partition_total
        return used, total

    def repack_patches(
        self,
        data: bytes | bytearray,
        map_id: int,
        width: int,
        height: int,
        tiles: tuple[int, ...],
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        """Repack legacy terrain and update boundaries plus affected pointers."""

        if self.bank_table_offset is not None:
            raise ValueError("扩展地图必须通过地图共享池统一重排。")
        source = bytes(data)
        encoded = self.encode(width, height, tiles)
        if self.rom.profile.map_storage_boundary_offsets:
            return self._dynamic_repack_patches(source, map_id, encoded)
        storage = self.map_storage(map_id)
        payloads = [
            encoded if current_id == map_id else self.decode(current_id, source).raw
            for current_id in range(storage.first_id, storage.end_id)
        ]
        first_pointer = self.pointers[storage.first_id]
        used = sum(len(payload) for payload in payloads)
        total = storage.data_end_pointer - first_pointer
        if used > total:
            raise ValueError(
                f"地图分区重排后需要 {used} 字节，分区总容量只有 {total} 字节。"
            )

        pointers: list[int] = []
        cursor = first_pointer
        for payload in payloads:
            pointers.append(cursor)
            cursor += len(payload)
        pointer_offset = (
            self.rom.profile.map_pointer_table_offset + storage.first_id * 2
        )
        pointer_after = struct.pack(f"<{len(pointers)}H", *pointers)
        pointer_before = source[pointer_offset : pointer_offset + len(pointer_after)]

        pool_offset = (
            16
            + storage.prg_bank * 0x2000
            + first_pointer
            - storage.window_base
        )
        pool_before = source[pool_offset : pool_offset + total]
        packed = b"".join(payloads)
        pool_after = packed + pool_before[len(packed) :]
        return (
            (pointer_offset, pointer_before, pointer_after),
            (pool_offset, pool_before, pool_after),
        )

    def round_trip(self, map_id: int) -> bool:
        record = self.decode(map_id)
        return self.encode(record.width, record.height, record.tiles) == record.raw
