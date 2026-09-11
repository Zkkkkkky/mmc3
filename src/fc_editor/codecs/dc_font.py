"""Fixed-size DC 12×12 glyph records; no pointers or layout are moved.

Each page contains 16 rows of 256 bytes: 14 packed 18-byte glyphs followed
by four reserved bytes. Legacy display columns E/F alias column 0.
Pixels are stored as three 4×12 vertical strips (six bytes each). Each
byte holds an even-row nibble followed by an odd-row nibble; zero is ink.
"""
from __future__ import annotations

GLYPH_PAGE_LEADS = (0xB8, 0xB9, 0xBA, 0xBB, 0xC8, 0xC9, 0xCA, 0xCB, 0xD8, 0xD9, 0xDA, 0xDB)
GLYPH_SIZE = 18
PAGE_PAYLOAD_SIZE = 16 * 14 * GLYPH_SIZE
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
