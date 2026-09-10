"""Deterministic 24-bit BMP encoding for the legacy editor export protocol.

Static analysis of ``references/legacy_modifier/SRW2_patched.exe`` confirms that
its bitmap creator uses a 40-byte ``BITMAPINFOHEADER``, a positive height,
one plane, 24 bits per pixel, ``BI_RGB``, and zero for ``biSizeImage``, both
pixels-per-metre fields, ``clrUsed``, and ``clrImportant``.  Its file serializer
writes a 14-byte ``BITMAPFILEHEADER`` with zero reserved fields before that DIB.

This module reproduces those confirmed header choices, writes BGR pixels in
bottom-up row order, and fills four-byte row padding with zero.  It has not yet
been compared byte-for-byte with a bitmap dynamically exported by the legacy
program, so it is a deterministic protocol encoder rather than a claim of
golden-byte parity for the legacy program's complete image-building pipeline.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import struct
from typing import TypeAlias


RgbColor: TypeAlias = tuple[int, int, int]

LEGACY_MATERIAL_BACKGROUND_RGB: RgbColor = (0x00, 0x00, 0x00)
LEGACY_MATERIAL_GREEN_RGB: RgbColor = (0x63, 0xCF, 0x63)
LEGACY_MATERIAL_BLUE_RGB: RgbColor = (0x39, 0x33, 0xFF)
LEGACY_MATERIAL_LIGHT_RGB: RgbColor = (0xDC, 0xFF, 0xFF)
LEGACY_MATERIAL_PALETTE_RGB: tuple[RgbColor, ...] = (
    LEGACY_MATERIAL_BACKGROUND_RGB,
    LEGACY_MATERIAL_GREEN_RGB,
    LEGACY_MATERIAL_BLUE_RGB,
    LEGACY_MATERIAL_LIGHT_RGB,
)

_BITMAP_FILE_HEADER_SIZE = 14
_BITMAP_INFO_HEADER_SIZE = 40
_PIXEL_DATA_OFFSET = _BITMAP_FILE_HEADER_SIZE + _BITMAP_INFO_HEADER_SIZE
_BITS_PER_PIXEL = 24
_BI_RGB = 0
_MAX_SIGNED_DWORD = 0x7FFFFFFF
_MAX_UNSIGNED_DWORD = 0xFFFFFFFF


def encode_legacy_bmp24(
    width: int,
    height: int,
    pixels: Iterable[Sequence[int]],
) -> bytes:
    """Encode top-to-bottom RGB pixels as a legacy-compatible 24-bit BMP.

    ``pixels`` must contain exactly ``width * height`` RGB triples in ordinary
    display order: the first pixel is the top-left pixel and rows proceed from
    top to bottom.  The BMP payload reverses the row order because its positive
    height denotes a bottom-up DIB.  Each channel must be an integer from 0 to
    255 inclusive.

    Header fields that are conventionally optional are emitted as zero, matching
    the values observed in the legacy bitmap initializer.  Despite that static
    match, no dynamically exported golden BMP has yet established byte-for-byte
    identity with every incidental behavior of the original implementation.
    """

    _validate_dimension("width", width)
    _validate_dimension("height", height)

    row_stride = ((width * _BITS_PER_PIXEL + 31) // 32) * 4
    pixel_data_size = row_stride * height
    file_size = _PIXEL_DATA_OFFSET + pixel_data_size
    if file_size > _MAX_UNSIGNED_DWORD:
        raise ValueError("encoded BMP exceeds the 32-bit BMP file-size field")

    materialized_pixels = tuple(pixels)
    expected_pixel_count = width * height
    if len(materialized_pixels) != expected_pixel_count:
        raise ValueError(
            f"expected {expected_pixel_count} pixels for {width}x{height}, "
            f"got {len(materialized_pixels)}"
        )

    checked_pixels = tuple(
        _checked_rgb(pixel, pixel_index)
        for pixel_index, pixel in enumerate(materialized_pixels)
    )

    encoded = bytearray(file_size)
    struct.pack_into(
        "<2sIHHI",
        encoded,
        0,
        b"BM",
        file_size,
        0,
        0,
        _PIXEL_DATA_OFFSET,
    )
    struct.pack_into(
        "<IiiHHIIiiII",
        encoded,
        _BITMAP_FILE_HEADER_SIZE,
        _BITMAP_INFO_HEADER_SIZE,
        width,
        height,
        1,
        _BITS_PER_PIXEL,
        _BI_RGB,
        0,
        0,
        0,
        0,
        0,
    )

    for output_row, input_row in enumerate(range(height - 1, -1, -1)):
        output_offset = _PIXEL_DATA_OFFSET + output_row * row_stride
        input_offset = input_row * width
        for column in range(width):
            red, green, blue = checked_pixels[input_offset + column]
            pixel_offset = output_offset + column * 3
            encoded[pixel_offset : pixel_offset + 3] = bytes((blue, green, red))

    return bytes(encoded)


def _validate_dimension(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    if value > _MAX_SIGNED_DWORD:
        raise ValueError(f"{name} exceeds the signed 32-bit BMP dimension field")


def _checked_rgb(pixel: Sequence[int], pixel_index: int) -> RgbColor:
    if isinstance(pixel, (str, bytes, bytearray)) or not isinstance(pixel, Sequence):
        raise TypeError(f"pixel {pixel_index} must be an RGB sequence")
    if len(pixel) != 3:
        raise ValueError(f"pixel {pixel_index} must contain exactly three channels")

    channels: list[int] = []
    for channel_index, channel in enumerate(pixel):
        if isinstance(channel, bool) or not isinstance(channel, int):
            raise TypeError(
                f"pixel {pixel_index} channel {channel_index} must be an integer"
            )
        if not 0 <= channel <= 0xFF:
            raise ValueError(
                f"pixel {pixel_index} channel {channel_index} is outside 0..255"
            )
        channels.append(channel)
    return channels[0], channels[1], channels[2]
