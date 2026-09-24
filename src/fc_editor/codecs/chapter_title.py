from __future__ import annotations

from dataclasses import dataclass
import struct

from ..errors import RomFormatError
from ..rom_image import RomImage


CHAPTER_TITLE_COUNT = 32
CHAPTER_TITLE_CHR_TABLE_OFFSET = 0x159AE
CHAPTER_TITLE_POINTER_TABLE_OFFSET = 0x16111
CHAPTER_TITLE_PRG_BANK = 0x0B
CHAPTER_TITLE_CPU_BASE = 0xA000
CHAPTER_TITLE_FILE_BASE = 0x16010
CHAPTER_TITLE_POOL_START = 0xAB7A
CHAPTER_TITLE_POOL_END = 0xB0DE


@dataclass(frozen=True)
class ChapterTitleSegment:
    x: int
    y: int
    width: int
    tiles: bytes


@dataclass(frozen=True)
class ChapterTitleRecord:
    scenario_id: int
    pointer: int
    file_offset: int
    raw: bytes
    chr_banks: tuple[int, int, int]
    segments: tuple[ChapterTitleSegment, ...]

    @property
    def capacity(self) -> int:
        return len(self.raw)

    @property
    def title_segment(self) -> ChapterTitleSegment:
        return self.segments[-1]


class ChapterTitleCodec:
    """Access to the 32 chapter-title tile scripts and their shared pool.

    The active DC layout extends the original title pointer table to 32
    entries.  Each record consists of one or more ``FE X Y WIDTH`` commands,
    followed by two tile rows (``WIDTH * 2`` bytes), and a final ``FF``.
    Tile numbers ``40-FE`` address the chapter's three 64-tile CHR pages;
    ``00-3F`` uses the shared episode-number page selected by the runtime.
    """

    def __init__(
        self,
        rom: RomImage,
        data: bytes | bytearray | None = None,
    ) -> None:
        self.rom = rom
        self._source = rom.data if data is None else bytes(data)
        baseline = self._scan_layouts(bytes(rom.data))
        self.pool_file_start = self.pointer_to_file_offset(CHAPTER_TITLE_POOL_START)
        self.pool_file_end = self.pointer_to_file_offset(CHAPTER_TITLE_POOL_END)
        ordered = sorted((offset, size) for _pointer, offset, size in baseline)
        if any(
            offset + size != ordered[index + 1][0]
            for index, (offset, size) in enumerate(ordered[:-1])
        ) or ordered[0][0] != self.pool_file_start:
            raise RomFormatError("关卡标题基准脚本不是连续的独立数据池。")
        used_end = ordered[-1][0] + ordered[-1][1]
        if used_end > self.pool_file_end or any(
            value != 0xFF for value in bytes(rom.data)[used_end:self.pool_file_end]
        ):
            raise RomFormatError("关卡标题数据越过安全池或尾部不是空闲填充。")
        self._layouts = self._scan_layouts(self._source)

    @staticmethod
    def pointer_to_file_offset(pointer: int) -> int:
        if not CHAPTER_TITLE_CPU_BASE <= pointer < CHAPTER_TITLE_CPU_BASE + 0x2000:
            raise RomFormatError(
                f"关卡标题指针 ${pointer:04X} 不在 Bank $0B 的 $A000—$BFFF 窗口。"
            )
        return CHAPTER_TITLE_FILE_BASE + pointer - CHAPTER_TITLE_CPU_BASE

    @staticmethod
    def parse_segments(raw: bytes) -> tuple[ChapterTitleSegment, ...]:
        if not raw or raw[-1:] != b"\xFF":
            raise RomFormatError("关卡标题脚本缺少 FF 结束码。")
        cursor = 0
        segments: list[ChapterTitleSegment] = []
        while cursor < len(raw) - 1:
            if raw[cursor] != 0xFE:
                raise RomFormatError(
                    f"关卡标题指令 0x{cursor:02X} 必须以 FE 开始。"
                )
            if cursor + 4 > len(raw) - 1:
                raise RomFormatError("关卡标题 FE 指令头不完整。")
            x, y, width = raw[cursor + 1 : cursor + 4]
            if width == 0:
                raise RomFormatError("关卡标题宽度不能为 0。")
            end = cursor + 4 + width * 2
            if end > len(raw) - 1:
                raise RomFormatError("关卡标题图块数少于宽度声明。")
            tiles = raw[cursor + 4 : end]
            if any(tile == 0xFF for tile in tiles):
                raise RomFormatError("关卡标题图块不能使用 FF 结束码。")
            segments.append(ChapterTitleSegment(x, y, width, tiles))
            cursor = end
        if cursor != len(raw) - 1 or not segments:
            raise RomFormatError("关卡标题脚本边界无效。")
        return tuple(segments)

    @classmethod
    def supports(cls, data: bytes | bytearray) -> bool:
        source = bytes(data)
        if len(source) <= CHAPTER_TITLE_POINTER_TABLE_OFFSET + CHAPTER_TITLE_COUNT * 2:
            return False
        try:
            for scenario_id in range(CHAPTER_TITLE_COUNT):
                pointer_offset = CHAPTER_TITLE_POINTER_TABLE_OFFSET + scenario_id * 2
                pointer = int.from_bytes(
                    source[pointer_offset : pointer_offset + 2], "little"
                )
                offset = cls.pointer_to_file_offset(pointer)
                end = source.find(b"\xFF", offset, CHAPTER_TITLE_FILE_BASE + 0x2000)
                if end < 0:
                    return False
                cls.parse_segments(source[offset : end + 1])
            return True
        except RomFormatError:
            return False

    @classmethod
    def _scan_layouts(
        cls,
        data: bytes,
    ) -> tuple[tuple[int, int, int], ...]:
        layouts: list[tuple[int, int, int]] = []
        bank_end = CHAPTER_TITLE_FILE_BASE + 0x2000
        for scenario_id in range(CHAPTER_TITLE_COUNT):
            pointer_offset = CHAPTER_TITLE_POINTER_TABLE_OFFSET + scenario_id * 2
            pointer = int.from_bytes(data[pointer_offset : pointer_offset + 2], "little")
            offset = cls.pointer_to_file_offset(pointer)
            end = data.find(b"\xFF", offset, bank_end)
            if end < 0:
                raise RomFormatError(
                    f"关卡 ${scenario_id:02X} 的标题脚本缺少 FF 结束码。"
                )
            raw = data[offset : end + 1]
            cls.parse_segments(raw)
            layouts.append((pointer, offset, len(raw)))
        return tuple(layouts)

    @property
    def count(self) -> int:
        return len(self._layouts)

    def decode(
        self,
        scenario_id: int,
        data: bytes | bytearray | None = None,
    ) -> ChapterTitleRecord:
        if not 0 <= scenario_id < self.count:
            raise IndexError(
                f"关卡标题编号必须在 00—{self.count - 1:02X} 之间。"
            )
        source = self._source if data is None else bytes(data)
        pointer, offset, capacity = self._layouts[scenario_id]
        raw = bytes(source[offset : offset + capacity])
        segments = self.parse_segments(raw)
        chr_offset = CHAPTER_TITLE_CHR_TABLE_OFFSET + scenario_id * 3
        chr_banks = tuple(source[chr_offset : chr_offset + 3])
        if len(chr_banks) != 3:
            raise RomFormatError("关卡标题的三个 CHR 图库记录不完整。")
        return ChapterTitleRecord(
            scenario_id,
            pointer,
            offset,
            raw,
            chr_banks,  # type: ignore[arg-type]
            segments,
        )

    def replacement_patches(
        self,
        data: bytes | bytearray,
        scenario_id: int,
        chr_banks: tuple[int, int, int],
        raw: bytes,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        current_codec = ChapterTitleCodec(self.rom, data)
        current = current_codec.decode(scenario_id, data)
        try:
            self.parse_segments(bytes(raw))
        except RomFormatError as error:
            raise ValueError(str(error)) from error
        if len(chr_banks) != 3:
            raise ValueError("关卡标题必须选择三个 CHR 图库。")
        chr_bank_count = self.rom.data[5] * 8
        if any(not 0 <= bank < chr_bank_count for bank in chr_banks):
            raise ValueError(
                f"CHR 图库必须在 00—{chr_bank_count - 1:02X} 之间。"
            )
        records = [
            current_codec.decode(index, data).raw
            for index in range(CHAPTER_TITLE_COUNT)
        ]
        records[scenario_id] = bytes(raw)
        capacity = self.pool_file_end - self.pool_file_start
        used = sum(len(record) for record in records)
        if used > capacity:
            raise ValueError(
                f"关卡标题共享池容量不足：需要 {used} 字节，"
                f"固定容量为 {capacity} 字节。请缩短其他关卡标题。"
            )
        cursor = self.pool_file_start
        pointers: list[int] = []
        packed = bytearray()
        for record in records:
            pointers.append(
                CHAPTER_TITLE_CPU_BASE + cursor - CHAPTER_TITLE_FILE_BASE
            )
            packed.extend(record)
            cursor += len(record)
        packed.extend(b"\xFF" * (capacity - len(packed)))

        chr_offset = CHAPTER_TITLE_CHR_TABLE_OFFSET + scenario_id * 3
        old_banks = bytes(data[chr_offset : chr_offset + 3])
        table_size = CHAPTER_TITLE_COUNT * 2
        table_before = bytes(
            data[
                CHAPTER_TITLE_POINTER_TABLE_OFFSET:
                CHAPTER_TITLE_POINTER_TABLE_OFFSET + table_size
            ]
        )
        pool_before = bytes(data[self.pool_file_start : self.pool_file_end])
        return (
            (chr_offset, old_banks, bytes(chr_banks)),
            (
                CHAPTER_TITLE_POINTER_TABLE_OFFSET,
                table_before,
                struct.pack(f"<{len(pointers)}H", *pointers),
            ),
            (self.pool_file_start, pool_before, bytes(packed)),
        )

    def round_trip(self, scenario_id: int) -> bool:
        record = self.decode(scenario_id)
        return all(
            before == after
            for _offset, before, after in self.replacement_patches(
                self._source,
                scenario_id,
                record.chr_banks,
                record.raw,
            )
        )
