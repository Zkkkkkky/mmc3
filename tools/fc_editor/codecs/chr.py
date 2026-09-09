from __future__ import annotations

from ..errors import RomFormatError
from ..rom_image import RomImage


CHR_TILE_BYTES = 16
CHR_TILE_PIXELS = 64


class ChrCodec:
    """Lossless codec for the active iNES CHR-ROM 2bpp tile stream."""

    def __init__(self, rom: RomImage) -> None:
        self.rom = rom
        header = rom.data[:16]
        trainer_size = 512 if header[6] & 0x04 else 0
        self.offset = 16 + trainer_size + header[4] * 0x4000
        self.size = header[5] * 0x2000
        if self.size <= 0 or self.offset + self.size != rom.size:
            raise RomFormatError("当前ROM没有可安全定位的CHR-ROM区域。")
        if self.size % CHR_TILE_BYTES:
            raise RomFormatError("CHR-ROM大小不是16字节图块的整数倍。")

    @property
    def tile_count(self) -> int:
        return self.size // CHR_TILE_BYTES

    def tile_offset(self, tile_index: int) -> int:
        if not 0 <= tile_index < self.tile_count:
            raise IndexError(f"CHR图块必须在 0000—{self.tile_count - 1:04X} 之间。")
        return self.offset + tile_index * CHR_TILE_BYTES

    def tile_bytes(self, tile_index: int, data: bytes | None = None) -> bytes:
        source = self.rom.data if data is None else data
        offset = self.tile_offset(tile_index)
        raw = bytes(source[offset : offset + CHR_TILE_BYTES])
        if len(raw) != CHR_TILE_BYTES:
            raise RomFormatError(f"CHR图块 {tile_index:04X} 数据不完整。")
        return raw

    def decode_tile(
        self,
        tile_index: int,
        data: bytes | None = None,
    ) -> tuple[int, ...]:
        raw = self.tile_bytes(tile_index, data)
        pixels: list[int] = []
        for y in range(8):
            low = raw[y]
            high = raw[y + 8]
            for x in range(8):
                mask = 0x80 >> x
                pixels.append(
                    (1 if low & mask else 0) | (2 if high & mask else 0)
                )
        return tuple(pixels)

    @staticmethod
    def encode_tile(pixels: tuple[int, ...] | list[int]) -> bytes:
        if len(pixels) != CHR_TILE_PIXELS:
            raise ValueError("CHR图块必须正好包含8×8个像素。")
        if any(pixel not in (0, 1, 2, 3) for pixel in pixels):
            raise ValueError("CHR像素索引必须在0—3之间。")
        result = bytearray(CHR_TILE_BYTES)
        for y in range(8):
            low = 0
            high = 0
            for x in range(8):
                pixel = pixels[y * 8 + x]
                mask = 0x80 >> x
                if pixel & 1:
                    low |= mask
                if pixel & 2:
                    high |= mask
            result[y] = low
            result[y + 8] = high
        return bytes(result)

    def range_bytes(
        self,
        first_tile: int,
        tile_count: int,
        data: bytes | None = None,
    ) -> bytes:
        if tile_count <= 0:
            raise ValueError("CHR图块数量必须大于零。")
        start = self.tile_offset(first_tile)
        end_tile = first_tile + tile_count
        if end_tile > self.tile_count:
            raise ValueError("CHR图块范围超出有效CHR-ROM。")
        source = self.rom.data if data is None else data
        return bytes(source[start : start + tile_count * CHR_TILE_BYTES])
