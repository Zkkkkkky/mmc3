from __future__ import annotations

from dataclasses import dataclass

from ..errors import RomFormatError
from ..rom_image import RomImage
from .story_text import StoryTextCodec


# The verified DC-family objective table lives in the final source PRG pair.
# It is not one of the ordinary pointer-based story groups: records are stored
# consecutively and each starts with the text-window prologue below.
CHAPTER_VICTORY_PRG_BANK = 0x3D
CHAPTER_VICTORY_CPU_START = 0x8000
CHAPTER_VICTORY_CPU_END = 0x8289
CHAPTER_VICTORY_HEADER = bytes.fromhex("FC 20 0F FD 40")
CHAPTER_VICTORY_COUNT = 13


@dataclass(frozen=True)
class ChapterVictoryRecord:
    scenario_id: int
    file_offset: int
    raw: bytes
    body: bytes

    @property
    def capacity(self) -> int:
        return len(self.raw)

    @property
    def body_capacity(self) -> int:
        return len(self.body)


class ChapterVictoryCodec:
    """Lossless shared-pool access to the playable chapter objectives.

    The first thirteen records have been correlated with the reference
    editor's chapter list.  An ``FF`` byte can also be the low byte of a DC
    two-byte glyph, so record boundaries must be found with the shared token
    parser rather than a byte-level ``find``.
    """

    def __init__(
        self,
        rom: RomImage,
        data: bytes | bytearray | None = None,
    ) -> None:
        self.rom = rom
        self._source = rom.data if data is None else bytes(data)
        baseline = self._scan_records(bytes(rom.data))
        self.pool_file_start = self.file_offset()
        self.pool_file_end = self.pool_file_start + (
            CHAPTER_VICTORY_CPU_END - CHAPTER_VICTORY_CPU_START
        )
        used_end = baseline[-1].file_offset + baseline[-1].capacity
        if baseline[0].file_offset != self.pool_file_start or (
            used_end > self.pool_file_end
        ) or any(
            value != 0xFF for value in bytes(rom.data)[used_end:self.pool_file_end]
        ):
            raise RomFormatError("初始胜利文字基准记录未完整覆盖已验证数据池。")
        self._records = self._scan_records(self._source)

    @staticmethod
    def file_offset() -> int:
        return (
            16
            + CHAPTER_VICTORY_PRG_BANK * 0x2000
            + (CHAPTER_VICTORY_CPU_START - 0x8000)
        )

    @classmethod
    def supports(cls, data: bytes | bytearray) -> bool:
        start = cls.file_offset()
        return (
            len(data) > start + len(CHAPTER_VICTORY_HEADER)
            and bytes(data[start : start + len(CHAPTER_VICTORY_HEADER)])
            == CHAPTER_VICTORY_HEADER
        )

    @staticmethod
    def _record_length(block: bytes) -> int:
        end = StoryTextCodec.standalone_terminator_end(block)
        if end is None:
            raise RomFormatError("初始胜利文字记录缺少独立 FF 结束码。")
        return end

    @classmethod
    def _scan_records(cls, data: bytes) -> tuple[ChapterVictoryRecord, ...]:
        cursor = cls.file_offset()
        bank_end = 16 + (CHAPTER_VICTORY_PRG_BANK + 1) * 0x2000
        if len(data) < bank_end:
            raise RomFormatError("ROM 不含完整的初始胜利文字 Bank。")
        records: list[ChapterVictoryRecord] = []
        for scenario_id in range(CHAPTER_VICTORY_COUNT):
            if data[cursor : cursor + len(CHAPTER_VICTORY_HEADER)] != CHAPTER_VICTORY_HEADER:
                raise RomFormatError(
                    f"关卡 ${scenario_id:02X} 的初始胜利文字头无效。"
                )
            length = cls._record_length(data[cursor:bank_end])
            raw = bytes(data[cursor : cursor + length])
            body = raw[len(CHAPTER_VICTORY_HEADER) : -1]
            records.append(ChapterVictoryRecord(scenario_id, cursor, raw, body))
            cursor += length
        return tuple(records)

    @property
    def count(self) -> int:
        return len(self._records)

    @property
    def records(self) -> tuple[ChapterVictoryRecord, ...]:
        return self._records

    def decode(
        self,
        scenario_id: int,
        data: bytes | bytearray | None = None,
    ) -> ChapterVictoryRecord:
        if not 0 <= scenario_id < self.count:
            raise IndexError(
                f"初始胜利文字关卡必须在 00—{self.count - 1:02X} 之间。"
            )
        layout = self._records[scenario_id]
        source = self._source if data is None else bytes(data)
        raw = bytes(source[layout.file_offset : layout.file_offset + layout.capacity])
        if not raw.startswith(CHAPTER_VICTORY_HEADER) or raw[-1:] != b"\xFF":
            raise RomFormatError(
                f"关卡 ${scenario_id:02X} 的初始胜利文字结构已损坏。"
            )
        if StoryTextCodec.standalone_terminator_end(raw) != len(raw):
            raise RomFormatError(
                f"关卡 ${scenario_id:02X} 的初始胜利文字提前结束。"
            )
        return ChapterVictoryRecord(
            scenario_id,
            layout.file_offset,
            raw,
            raw[len(CHAPTER_VICTORY_HEADER) : -1],
        )

    def replacement_patches(
        self,
        data: bytes | bytearray,
        scenario_id: int,
        body: bytes,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        current_codec = ChapterVictoryCodec(self.rom, data)
        current = current_codec.decode(scenario_id, data)
        replacement = CHAPTER_VICTORY_HEADER + bytes(body) + b"\xFF"
        if StoryTextCodec.standalone_terminator_end(replacement) != len(replacement):
            raise ValueError("初始胜利文字正文不能包含独立 FF 结束码。")
        records = [record.raw for record in current_codec.records]
        records[scenario_id] = replacement
        capacity = self.pool_file_end - self.pool_file_start
        used = sum(len(record) for record in records)
        if used > capacity:
            raise ValueError(
                f"初始胜利文字共享池容量不足：需要 {used} 字节，"
                f"固定容量为 {capacity} 字节。请缩短其他关卡文字。"
            )
        packed = b"".join(records) + b"\xFF" * (capacity - used)
        before = bytes(data[self.pool_file_start : self.pool_file_end])
        return ((self.pool_file_start, before, packed),)

    def round_trip(self, scenario_id: int) -> bool:
        record = self.decode(scenario_id)
        patches = self.replacement_patches(
            self._source,
            scenario_id,
            record.body,
        )
        return all(before == after for _offset, before, after in patches)
