from __future__ import annotations

import hashlib
import struct

from ..errors import RomFormatError
from ..models import StoryTextRecord, TextToken
from ..profiles import ORIGINAL_STORY_TEXT_GROUPS, StoryTextGroupSpec
from ..rom_image import RomImage

# Backwards-compatible export used by existing scripts and tests for the original ROM.
STORY_TEXT_GROUPS = ORIGINAL_STORY_TEXT_GROUPS
STORY_TEXT_GROUP_BY_SELECTOR = {group.selector: group for group in STORY_TEXT_GROUPS}


class StoryTextCodec:
    """Lossless view and exact-size writer for the localized story resources.

    The glyph/control encoding is not fully mapped to Unicode.  Entries are
    therefore split only at confirmed pointer boundaries and every unknown
    token is preserved verbatim.
    """

    PAIR_CPU_BASE = 0x8000
    # The localized font is arranged as twelve 256-glyph pages.  Only these
    # lead bytes form two-byte glyph tokens; treating every C9-ED byte as a
    # lead corrupts token boundaries after punctuation and control codes.
    GLYPH_LEADS = frozenset(
        (*range(0xB8, 0xBC), *range(0xC8, 0xCC), *range(0xD8, 0xDC))
    )

    def __init__(self, rom: RomImage) -> None:
        self.rom = rom
        self._pointers: dict[int, tuple[int, ...]] = {}
        self._ids_by_pointer: dict[int, dict[int, tuple[int, ...]]] = {}
        self._capacities: dict[int, dict[int, int]] = {}
        self.groups = rom.profile.story_text_groups
        self.group_by_selector = {group.selector: group for group in self.groups}
        for group in self.groups:
            pointers = self._read_pointers(group)
            self._pointers[group.selector] = pointers
            ids: dict[int, list[int]] = {}
            for index, pointer in enumerate(pointers):
                ids.setdefault(pointer, []).append(index)
            self._ids_by_pointer[group.selector] = {
                pointer: tuple(indices) for pointer, indices in ids.items()
            }
            usable = sorted(
                pointer
                for pointer in ids
                if group.data_start <= pointer < group.data_end
            )
            capacities: dict[int, int] = {}
            for position, pointer in enumerate(usable):
                if position + 1 < len(usable):
                    end = usable[position + 1]
                elif group.last_pointer_writable:
                    end = group.data_end
                else:
                    end = pointer
                capacities[pointer] = end - pointer
            for pointer in ids:
                capacities.setdefault(pointer, 0)
            self._capacities[group.selector] = capacities

    def _read_pointers(self, group: StoryTextGroupSpec) -> tuple[int, ...]:
        offset = self.cpu_to_file_offset(group.prg_bank, group.pointer_table)
        raw = self.rom.read(offset, group.count * 2)
        pointers = tuple(struct.unpack(f"<{group.count}H", raw))
        if pointers[0] != group.expected_first_pointer:
            raise RomFormatError(
                f"剧情文本组 ${group.selector:02X} 的起始指针不正确。"
            )
        if any(pointer and not 0x8000 <= pointer <= 0xBFFF for pointer in pointers):
            raise RomFormatError(
                f"剧情文本组 ${group.selector:02X} 含越界指针。"
            )
        return pointers

    @staticmethod
    def cpu_to_file_offset(prg_bank: int, cpu_address: int) -> int:
        if prg_bank % 2 or not 0x8000 <= cpu_address <= 0xBFFF:
            raise ValueError("剧情文本必须使用偶数 Bank 的 16 KiB $8000 窗口。")
        return 16 + prg_bank * 0x2000 + (cpu_address - 0x8000)

    @property
    def selectors(self) -> tuple[int, ...]:
        return tuple(group.selector for group in self.groups)

    def pointers(self, selector: int) -> tuple[int, ...]:
        return self._pointers[selector]

    def ids_by_pointer(self, selector: int) -> dict[int, tuple[int, ...]]:
        return self._ids_by_pointer[selector]

    def decode(
        self,
        selector: int,
        index: int,
        data: bytes | None = None,
    ) -> StoryTextRecord:
        group = self.group_by_selector[selector]
        if not 0 <= index < group.count:
            raise IndexError(f"剧情文本索引必须在 00—{group.count - 1:02X} 之间。")
        pointer = self._pointers[selector][index]
        capacity = self._capacities[selector][pointer]
        source = self.rom.data if data is None else data
        if capacity:
            offset = self.cpu_to_file_offset(group.prg_bank, pointer)
            raw = bytes(source[offset : offset + capacity])
        else:
            raw = b""
        return StoryTextRecord(
            selector,
            self._ids_by_pointer[selector][pointer],
            pointer,
            raw,
            capacity,
        )

    @staticmethod
    def tokenize(raw: bytes) -> tuple[TextToken, ...]:
        tokens: list[TextToken] = []
        offset = 0
        while offset < len(raw):
            lead = raw[offset]
            if lead in StoryTextCodec.GLYPH_LEADS and offset + 1 < len(raw):
                token = raw[offset : offset + 2]
                category = "中文字形码"
            elif lead in StoryTextCodec.GLYPH_LEADS:
                token = raw[offset : offset + 1]
                category = "尾随字形导字节"
            elif lead == 0xFF:
                token = raw[offset : offset + 1]
                category = "文本结束"
            elif lead >= 0xF0:
                token = raw[offset : offset + 1]
                category = "控制码"
            elif lead >= 0xEE:
                token = raw[offset : offset + 1]
                category = "扩展控制字节"
            else:
                token = raw[offset : offset + 1]
                category = "单字节字形/参数"
            tokens.append(TextToken(offset, token, category))
            offset += len(token)
        return tuple(tokens)

    @staticmethod
    def semantic_digest(record: StoryTextRecord) -> str:
        return hashlib.sha256(record.raw).hexdigest().upper()

    def replacement_patch(
        self,
        data: bytes,
        selector: int,
        index: int,
        replacement: bytes,
    ) -> tuple[int, bytes, bytes]:
        record = self.decode(selector, index, data)
        if not record.capacity:
            raise ValueError("该索引是空/哨兵记录，不能写入。")
        if len(replacement) != record.capacity:
            raise ValueError(
                f"剧情文本记录必须保持 {record.capacity} 字节；当前输入 "
                f"{len(replacement)} 字节。"
            )
        group = self.group_by_selector[selector]
        offset = self.cpu_to_file_offset(group.prg_bank, record.pointer)
        return offset, record.raw, replacement

    def round_trip(self, selector: int, index: int) -> bool:
        record = self.decode(selector, index)
        if not record.capacity:
            return True
        offset, before, after = self.replacement_patch(
            self.rom.data, selector, index, record.raw
        )
        group = self.group_by_selector[selector]
        return (
            offset == self.cpu_to_file_offset(group.prg_bank, record.pointer)
            and before == after == record.raw
        )
