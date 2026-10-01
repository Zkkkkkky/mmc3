"""Fixed-size DC 12×12 glyph records; no pointers or layout are moved.

Each page contains 16 rows of 256 bytes: 14 packed 18-byte glyphs followed
by four reserved bytes. Legacy display columns E/F alias column 0.
Pixels are stored as three 4×12 vertical strips (six bytes each). Each
byte holds an even-row nibble followed by an odd-row nibble; zero is ink.
"""
from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from dataclasses import dataclass

from ..text_table import TextTable

GLYPH_PAGE_LEADS = (0xB8, 0xB9, 0xBA, 0xBB, 0xC8, 0xC9, 0xCA, 0xCB, 0xD8, 0xD9, 0xDA, 0xDB)
GLYPH_SIZE = 18
PAGE_PAYLOAD_SIZE = 16 * 14 * GLYPH_SIZE
FULL_FONT_PAYLOAD_SIZE = len(GLYPH_PAGE_LEADS) * PAGE_PAYLOAD_SIZE
FULL_FONT_MAGIC = b"DCFNTALL"
FULL_FONT_VERSION = 1
_FULL_FONT_HEADER = struct.Struct("<8sHII")
SUPPORTED_PROFILES = frozenset(("dc-kuorong-mmc3-v1", "dc-kuorong-mmc3-v2"))

# Page reachability differs by runtime renderer. Story and battle text may use
# all twelve pages, while the verified name/system renderers use only C/D.
# Allocation order is deterministic inside each renderer-compatible set.
STORY_FONT_LEADS = GLYPH_PAGE_LEADS
NAME_FONT_LEADS = (0xD8, 0xD9, 0xDA, 0xDB, 0xC8, 0xC9, 0xCA, 0xCB)
FONT_CHANNEL_PAGE_ORDER = {
    "story": (0xBA, 0xBB, 0xB8, 0xB9, 0xC8, 0xC9, 0xCA, 0xCB, 0xD8, 0xD9, 0xDA, 0xDB),
    "battle": (0xBA, 0xBB, 0xB8, 0xB9, 0xC8, 0xC9, 0xCA, 0xCB, 0xD8, 0xD9, 0xDA, 0xDB),
    "name": NAME_FONT_LEADS,
    "unit": NAME_FONT_LEADS,
    "character": NAME_FONT_LEADS,
    "weapon": NAME_FONT_LEADS,
    "item": NAME_FONT_LEADS,
    "system": NAME_FONT_LEADS,
}


def channel_font_leads(channel: str) -> tuple[int, ...]:
    """Return runtime-compatible glyph pages for one text renderer."""

    return FONT_CHANNEL_PAGE_ORDER.get(channel, NAME_FONT_LEADS)


def incompatible_channel_tokens(raw: bytes, channel: str) -> tuple[bytes, ...]:
    """Return glyph tokens that the selected runtime text renderer cannot use."""

    from .story_text import StoryTextCodec

    allowed = set(channel_font_leads(channel))
    return tuple(
        token.raw
        for token in StoryTextCodec.tokenize(raw)
        if len(token.raw) == 2
        and token.raw[0] in GLYPH_PAGE_LEADS
        and token.raw[0] not in allowed
    )


@dataclass(frozen=True)
class FontUsageAudit:
    referenced_tokens: frozenset[bytes]
    unused_builtin_tokens: tuple[bytes, ...]
    unused_custom_tokens: tuple[bytes, ...]
    unused_unmapped_glyphs: tuple[bytes, ...]
    disabled_builtin_tokens: tuple[bytes, ...] = ()


def glyph_file_offset(token: bytes, *, writable: bool = False) -> int:
    if len(token) != 2 or token[0] not in GLYPH_PAGE_LEADS:
        raise ValueError("字模代码必须是 B8—BB、C8—CB 或 D8—DB 页的双字节代码。")
    lead, index = token
    row, column = divmod(index, 16)
    if writable and column >= 14:
        raise ValueError("E/F 列是该行 0 列的别名，不是独立字模；请编辑 0 列。")
    base = {0xB0: 0x6C010, 0xC0: 0x70010, 0xD0: 0x74010}[lead & 0xF0]
    return base + (lead & 3) * 0x1000 + row * 0x100 + (column if column < 14 else 0) * 18


def page_tokens(lead: int) -> tuple[bytes, ...]:
    if lead not in GLYPH_PAGE_LEADS:
        raise ValueError("未知字库页。")
    return tuple(bytes((lead, row * 16 + column)) for row in range(16) for column in range(14))


def font_tokens() -> tuple[bytes, ...]:
    """Return every independent glyph token in deterministic page order."""

    return tuple(token for lead in GLYPH_PAGE_LEADS for token in page_tokens(lead))


def safe_unmapped_tokens(data: bytes, mapped_tokens: set[bytes]) -> tuple[bytes, ...]:
    """Find conservative slots that can receive a newly assigned character.

    A slot is eligible only when its token is absent from the complete ROM,
    its glyph consists of one uniform fill byte, and no text table maps it.
    The whole-ROM absence check is deliberately conservative: false positives
    merely reduce capacity, while reusing a token already present in unknown
    data could change existing text at runtime.
    """

    result: list[bytes] = []
    for token in font_tokens():
        if token in mapped_tokens or data.count(token):
            continue
        offset = glyph_file_offset(token, writable=True)
        raw = data[offset : offset + GLYPH_SIZE]
        if len(raw) == GLYPH_SIZE and len(set(raw)) == 1:
            result.append(token)
    return tuple(result)


def safe_channel_tokens(
    data: bytes,
    mapped_tokens: set[bytes],
    channel: str,
    reclaimed_tokens: set[bytes] | frozenset[bytes] = frozenset(),
    *,
    reclaimed_data: bytes | None = None,
) -> tuple[bytes, ...]:
    """Return conservative empty slots ordered for one text family.

    ``data`` should be the immutable base ROM so clearing glyph bitmaps cannot
    make unrelated byte pairs look newly unused. Explicitly reclaimed slots
    are validated against ``reclaimed_data`` (the mutable working ROM).
    """

    order = channel_font_leads(channel)
    allowed = set(order)
    candidates = {
        token for token in safe_unmapped_tokens(data, mapped_tokens)
        if token[0] in allowed
    }
    working = data if reclaimed_data is None else reclaimed_data
    working_references = font_reference_counts(working)
    # A base-ROM empty slot can later be referenced through raw-code editing or
    # receive a hand-drawn glyph. Revalidate the mutable ROM immediately before
    # offering it instead of trusting only the immutable baseline.
    candidates = {
        token for token in candidates
        if not working_references.get(token, 0)
        and len(set(working[
            glyph_file_offset(token, writable=True):
            glyph_file_offset(token, writable=True) + GLYPH_SIZE
        ])) == 1
    }
    if reclaimed_tokens:
        for token in reclaimed_tokens:
            if (
                token[0] not in allowed
                or token in mapped_tokens
                or working_references.get(token, 0)
            ):
                continue
            offset = glyph_file_offset(token, writable=True)
            raw = working[offset : offset + GLYPH_SIZE]
            if len(raw) == GLYPH_SIZE and len(set(raw)) == 1:
                candidates.add(token)
    rank = {lead: index for index, lead in enumerate(order)}
    return tuple(
        sorted(candidates, key=lambda token: (rank.get(token[0], len(rank)), token))
    )


def missing_text_characters(table: TextTable, text: str) -> tuple[str, ...]:
    """Return unencodable characters while respecting multi-character tokens."""

    values = sorted(table.text_to_byte, key=len, reverse=True)
    missing: list[str] = []
    cursor = 0
    while cursor < len(text):
        if text[cursor] == "<":
            close = text.find(">", cursor + 1)
            if close >= 0:
                compact = "".join(text[cursor + 1 : close].split())
                if compact and len(compact) % 2 == 0:
                    try:
                        bytes.fromhex(compact)
                        cursor = close + 1
                        continue
                    except ValueError:
                        pass
        match = next(
            (value for value in values if text.startswith(value, cursor)),
            None,
        )
        if match is not None:
            cursor += len(match)
            continue
        character = text[cursor]
        if character not in missing:
            missing.append(character)
        cursor += 1
    return tuple(missing)


def font_reference_counts(data: bytes) -> dict[bytes, int]:
    """Count possible two-byte font references outside the font storage.

    Glyph bitmap bytes frequently resemble text tokens by accident.  Exclude
    all twelve page rows, including their four reserved bytes, then scan every
    remaining byte boundary conservatively.  A hit may still be non-text data,
    which is why zero is safe evidence while a positive count is only treated
    as "possibly referenced".
    """

    excluded: list[tuple[int, int]] = []
    for lead in GLYPH_PAGE_LEADS:
        page_start = glyph_file_offset(bytes((lead, 0)), writable=True)
        excluded.extend(
            (page_start + row * 0x100, page_start + (row + 1) * 0x100)
            for row in range(16)
        )
    excluded.sort()
    counts: dict[bytes, int] = {}
    range_index = 0
    position = 0
    while position + 1 < len(data):
        while range_index < len(excluded) and position >= excluded[range_index][1]:
            range_index += 1
        if (
            range_index < len(excluded)
            and excluded[range_index][0] <= position < excluded[range_index][1]
        ):
            position = excluded[range_index][1]
            continue
        if data[position] in GLYPH_PAGE_LEADS:
            token = bytes(data[position : position + 2])
            counts[token] = counts.get(token, 0) + 1
        position += 1
    return counts


def audit_font_usage(
    data: bytes,
    builtin_tokens: set[bytes],
    custom_tokens: set[bytes],
    disabled_builtin_tokens: set[bytes] | None = None,
) -> FontUsageAudit:
    disabled_builtin_tokens = disabled_builtin_tokens or set()
    counts = font_reference_counts(data)
    referenced = frozenset(token for token, count in counts.items() if count)
    independent = set(font_tokens())
    unused_builtin = tuple(
        sorted((builtin_tokens & independent) - referenced - disabled_builtin_tokens)
    )
    unused_custom = tuple(sorted((custom_tokens & independent) - referenced))
    mapped = builtin_tokens | custom_tokens
    orphaned = []
    for token in sorted(independent - mapped - referenced):
        offset = glyph_file_offset(token, writable=True)
        raw = bytes(data[offset : offset + GLYPH_SIZE])
        if len(raw) == GLYPH_SIZE and len(set(raw)) > 1:
            orphaned.append(token)
    return FontUsageAudit(
        referenced,
        unused_builtin,
        unused_custom,
        tuple(orphaned),
        tuple(sorted(disabled_builtin_tokens & independent)),
    )


def full_font_payload(data: bytes) -> bytes:
    """Extract all 2,688 independent glyphs without row padding or aliases."""

    glyphs: list[bytes] = []
    for token in font_tokens():
        offset = glyph_file_offset(token, writable=True)
        raw = data[offset : offset + GLYPH_SIZE]
        if len(raw) != GLYPH_SIZE:
            raise ValueError(
                f"ROM 在字模 {token.hex().upper()} 之前结束。"
            )
        glyphs.append(raw)
    return b"".join(glyphs)


def glyphs_from_full_payload(payload: bytes) -> dict[bytes, bytes]:
    if len(payload) != FULL_FONT_PAYLOAD_SIZE:
        raise ValueError(
            f"全字库点阵必须恰好为 {FULL_FONT_PAYLOAD_SIZE} 字节。"
        )
    return {
        token: payload[index * GLYPH_SIZE : (index + 1) * GLYPH_SIZE]
        for index, token in enumerate(font_tokens())
    }


def encode_full_font_file(
    glyphs: Mapping[bytes, bytes],
    custom_mappings: Mapping[bytes, str] | None = None,
) -> bytes:
    """Encode the versioned ``.dcfontset`` product interchange format.

    The payload is the 12 page payloads in :func:`font_tokens` order.  Only
    project-specific assignments are stored as UTF-8 JSON; the built-in table
    remains the stable baseline and is not duplicated in every file.
    """

    tokens = font_tokens()
    parts: list[bytes] = []
    for token in tokens:
        try:
            raw = bytes(glyphs[token])
        except KeyError as error:
            raise ValueError(
                f"全字库缺少字模 {bytes(error.args[0]).hex().upper()}。"
            ) from error
        if len(raw) != GLYPH_SIZE:
            raise ValueError(
                f"字模 {token.hex().upper()} 必须恰好为 {GLYPH_SIZE} 字节。"
            )
        parts.append(raw)
    payload = b"".join(parts)
    mappings: dict[str, str] = {}
    for token, character in sorted((custom_mappings or {}).items()):
        glyph_file_offset(token, writable=True)
        if len(character) != 1:
            raise ValueError("自定义字库映射必须是一枚 Unicode 字符。")
        mappings[token.hex().upper()] = character
    mapping_payload = json.dumps(
        mappings,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return (
        _FULL_FONT_HEADER.pack(
            FULL_FONT_MAGIC,
            FULL_FONT_VERSION,
            len(payload),
            len(mapping_payload),
        )
        + payload
        + mapping_payload
    )


def decode_full_font_file(raw: bytes) -> tuple[dict[bytes, bytes], dict[bytes, str]]:
    """Decode and strictly validate a versioned ``.dcfontset`` file."""

    if len(raw) < _FULL_FONT_HEADER.size:
        raise ValueError("全字库文件头不完整。")
    magic, version, payload_size, mapping_size = _FULL_FONT_HEADER.unpack_from(raw)
    if magic != FULL_FONT_MAGIC:
        raise ValueError("不是新DC修改器的全字库文件。")
    if version != FULL_FONT_VERSION:
        raise ValueError(f"不支持的全字库文件版本：{version}。")
    if payload_size != FULL_FONT_PAYLOAD_SIZE:
        raise ValueError("全字库文件的点阵区长度无效。")
    expected_size = _FULL_FONT_HEADER.size + payload_size + mapping_size
    if len(raw) != expected_size:
        raise ValueError("全字库文件长度与文件头不一致。")
    payload_start = _FULL_FONT_HEADER.size
    payload_end = payload_start + payload_size
    try:
        mapping_value = json.loads(raw[payload_end:].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("全字库文件的自定义码表无效。") from error
    if not isinstance(mapping_value, dict):
        raise ValueError("全字库文件的自定义码表必须是对象。")
    mappings: dict[bytes, str] = {}
    for code, character in mapping_value.items():
        if not isinstance(code, str) or not isinstance(character, str):
            raise ValueError("全字库文件的自定义码表字段类型无效。")
        try:
            token = bytes.fromhex(code)
        except ValueError as error:
            raise ValueError(f"全字库文件含无效字模代码：{code!r}。") from error
        glyph_file_offset(token, writable=True)
        if len(character) != 1:
            raise ValueError("全字库文件的映射值必须是一枚 Unicode 字符。")
        mappings[token] = character
    return glyphs_from_full_payload(raw[payload_start:payload_end]), mappings


def decode_glyph(raw: bytes) -> tuple[tuple[int, ...], ...]:
    if len(raw) != GLYPH_SIZE:
        raise ValueError("12×12 字模必须恰好为 18 字节。")
    return tuple(tuple(1 - ((raw[(x // 4) * 6 + y // 2] >> (7 - (y % 2) * 4 - x % 4)) & 1)
                       for x in range(12)) for y in range(12))


def encode_glyph(pixels: tuple[tuple[int, ...], ...] | list[list[int]]) -> bytes:
    if len(pixels) != 12 or any(len(row) != 12 for row in pixels):
        raise ValueError("字模点阵必须是 12×12。")
    raw = bytearray(b"\xff" * GLYPH_SIZE)
    for y, row in enumerate(pixels):
        for x, pixel in enumerate(row):
            if pixel not in (0, 1):
                raise ValueError("字模只能使用 0、1 两种颜色。")
            if pixel:
                raw[(x // 4) * 6 + y // 2] &= ~(1 << (7 - (y % 2) * 4 - x % 4))
    return bytes(raw)
