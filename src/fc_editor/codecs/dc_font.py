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

GLYPH_PAGE_LEADS = (0xB8, 0xB9, 0xBA, 0xBB, 0xC8, 0xC9, 0xCA, 0xCB, 0xD8, 0xD9, 0xDA, 0xDB)
GLYPH_SIZE = 18
PAGE_PAYLOAD_SIZE = 16 * 14 * GLYPH_SIZE
FULL_FONT_PAYLOAD_SIZE = len(GLYPH_PAGE_LEADS) * PAGE_PAYLOAD_SIZE
FULL_FONT_MAGIC = b"DCFNTALL"
FULL_FONT_VERSION = 1
_FULL_FONT_HEADER = struct.Struct("<8sHII")
SUPPORTED_PROFILES = frozenset(("dc-kuorong-mmc3-v1", "dc-kuorong-mmc3-v2"))


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
    if len(set(mappings.values())) != len(mappings):
        raise ValueError("全字库文件的自定义字符存在重复编码。")
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
