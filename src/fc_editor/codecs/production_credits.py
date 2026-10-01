from __future__ import annotations

from dataclasses import dataclass

from ..dc_text import reference_dc_text_table
from ..errors import RomFormatError
from ..text_table import TextTable
from .story_text import StoryTextCodec


PRODUCTION_RECORD_START = 0x07BC50
PRODUCTION_TEXT_START = 0x07BCA9
PRODUCTION_RECORD_END = 0x07BCF5
CAST_RECORD_START = 0x07BD11
CAST_RECORD_END = 0x07BD7F
PRODUCTION_PREFIX = bytes.fromhex("FC 20 00 FC 20 4F")
CAST_PREFIX = bytes.fromhex("CA D7 CB 27")  # “出演” in the reference table.
LINE_BREAK = b"\xF1"
ALIGN_SPACE = b"\xAF"


@dataclass(frozen=True)
class ProductionCreditsRecord:
    key: str
    label: str
    payload_start: int
    record_end: int
    raw: bytes
    text: str
    max_lines: int
    max_columns: int

    @property
    def capacity(self) -> int:
        return self.record_end - self.payload_start - 1


class ProductionCreditsCodec:
    """Two fixed-size Bank $3D credit strings used by the DC build.

    The production record has a verified binary drawing/control prefix that is
    never exposed for editing. Only its visible text tail and the separate cast
    list are writable. Shorter replacements are padded with the original AF
    alignment byte so the following ROM data never moves.
    """

    def __init__(self, data: bytes | bytearray) -> None:
        self.data = bytes(data)
        if not self.supports(self.data):
            raise RomFormatError("当前 ROM 不含已验证的制作信息文字块。")

    @staticmethod
    def supports(data: bytes | bytearray) -> bool:
        source = bytes(data)
        return (
            len(source) >= CAST_RECORD_END
            and source[PRODUCTION_RECORD_START:PRODUCTION_RECORD_START + len(PRODUCTION_PREFIX)]
            == PRODUCTION_PREFIX
            and source[PRODUCTION_RECORD_END - 1] == 0xFF
            and source[CAST_RECORD_END - 1] == 0xFF
        )

    @staticmethod
    def _friendly_table(table: TextTable) -> TextTable:
        mapping = dict(table.byte_to_text)
        mapping[LINE_BREAK] = "\n"
        mapping[ALIGN_SPACE] = " "
        return TextTable(mapping)

    @staticmethod
    def _friendly_decode(raw: bytes, table: TextTable) -> str:
        return ProductionCreditsCodec._friendly_table(table).decode(raw).rstrip(" ")

    @staticmethod
    def encode_text(text: str, table: TextTable) -> bytes:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        encoded = ProductionCreditsCodec._friendly_table(table).encode(normalized)
        if any(token.raw == b"\xFF" for token in StoryTextCodec.tokenize(encoded)):
            raise ValueError("制作信息正文不能包含结束码 FF。")
        return encoded

    def records(
        self,
        data: bytes | bytearray | None = None,
        *,
        text_table: TextTable | None = None,
    ) -> tuple[ProductionCreditsRecord, ProductionCreditsRecord]:
        source = self.data if data is None else bytes(data)
        if not self.supports(source):
            raise RomFormatError("制作信息文字块边界或结束码已损坏。")
        table = text_table or reference_dc_text_table()
        definitions = (
            (
                "production", "制作信息", PRODUCTION_TEXT_START,
                PRODUCTION_RECORD_END, 3, 18,
            ),
            (
                "cast", "出演名单", CAST_RECORD_START,
                CAST_RECORD_END, 11, 10,
            ),
        )
        result = []
        for key, label, start, end, max_lines, max_columns in definitions:
            raw = source[start:end - 1]
            result.append(
                ProductionCreditsRecord(
                    key,
                    label,
                    start,
                    end,
                    raw,
                    self._friendly_decode(raw, table),
                    max_lines,
                    max_columns,
                )
            )
        return result[0], result[1]

    def replacement_patches(
        self,
        data: bytes | bytearray,
        production_text: str,
        cast_text: str,
        *,
        text_table: TextTable,
    ) -> tuple[tuple[int, bytes, bytes], ...]:
        source = bytes(data)
        current = self.records(source, text_table=text_table)
        replacements = (production_text, cast_text)
        patches = []
        for record, text in zip(current, replacements):
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            lines = normalized.split("\n")
            if len(lines) > record.max_lines:
                raise ValueError(
                    f"{record.label}最多 {record.max_lines} 行，当前为 "
                    f"{len(lines)} 行；继续增加会超出原滚屏版面。"
                )
            widest = max(map(len, lines), default=0)
            if widest > record.max_columns:
                raise ValueError(
                    f"{record.label}每行最多 {record.max_columns} 个显示格，"
                    f"当前最长 {widest} 格；继续增加可能在滚屏中被截断。"
                )
            encoded = self._friendly_table(text_table).encode_preserving_tokens(
                record.raw,
                normalized,
            )
            if len(encoded) > record.capacity:
                raise ValueError(
                    f"{record.label}需要 {len(encoded)} 字节，固定容量只有 "
                    f"{record.capacity} 字节；请缩短内容。"
                )
            after = encoded + ALIGN_SPACE * (record.capacity - len(encoded)) + b"\xFF"
            before = source[record.payload_start:record.record_end]
            if after != before:
                patches.append((record.payload_start, before, after))
        return tuple(patches)
