from __future__ import annotations

import struct
import unittest

from fc_editor.legacy_bitmap import (
    LEGACY_MATERIAL_BACKGROUND_RGB,
    LEGACY_MATERIAL_BLUE_RGB,
    LEGACY_MATERIAL_GREEN_RGB,
    LEGACY_MATERIAL_LIGHT_RGB,
    LEGACY_MATERIAL_PALETTE_RGB,
    encode_legacy_bmp24,
)


class LegacyBitmapTests(unittest.TestCase):
    def test_confirmed_material_palette_constants(self) -> None:
        self.assertEqual(LEGACY_MATERIAL_BACKGROUND_RGB, (0x00, 0x00, 0x00))
        self.assertEqual(LEGACY_MATERIAL_GREEN_RGB, (0x63, 0xCF, 0x63))
        self.assertEqual(LEGACY_MATERIAL_BLUE_RGB, (0x39, 0x33, 0xFF))
        self.assertEqual(LEGACY_MATERIAL_LIGHT_RGB, (0xDC, 0xFF, 0xFF))
        self.assertEqual(
            LEGACY_MATERIAL_PALETTE_RGB,
            (
                LEGACY_MATERIAL_BACKGROUND_RGB,
                LEGACY_MATERIAL_GREEN_RGB,
                LEGACY_MATERIAL_BLUE_RGB,
                LEGACY_MATERIAL_LIGHT_RGB,
            ),
        )

    def test_reference_export_dimensions_have_expected_lengths(self) -> None:
        for size, expected_length in ((16, 822), (32, 3_126), (128, 49_206)):
            with self.subTest(size=size):
                pixels = [LEGACY_MATERIAL_BACKGROUND_RGB] * (size * size)
                encoded = encode_legacy_bmp24(size, size, pixels)
                self.assertEqual(len(encoded), expected_length)
                self.assertEqual(struct.unpack_from("<I", encoded, 2)[0], expected_length)

    def test_header_matches_statically_confirmed_fields(self) -> None:
        encoded = encode_legacy_bmp24(1, 1, [(0x12, 0x34, 0x56)])

        self.assertEqual(
            struct.unpack_from("<2sIHHI", encoded, 0),
            (b"BM", 58, 0, 0, 54),
        )
        self.assertEqual(
            struct.unpack_from("<IiiHHIIiiII", encoded, 14),
            (40, 1, 1, 1, 24, 0, 0, 0, 0, 0, 0),
        )

    def test_pixels_are_bgr_bottom_up_with_zero_row_padding(self) -> None:
        encoded = encode_legacy_bmp24(
            2,
            2,
            (
                (0x11, 0x22, 0x33),
                (0x44, 0x55, 0x66),
                (0x77, 0x88, 0x99),
                (0xAA, 0xBB, 0xCC),
            ),
        )

        self.assertEqual(
            encoded[54:],
            bytes.fromhex(
                "99 88 77 CC BB AA 00 00 "
                "33 22 11 66 55 44 00 00"
            ),
        )

    def test_accepts_an_exact_pixel_generator(self) -> None:
        encoded = encode_legacy_bmp24(
            1,
            2,
            (pixel for pixel in ((0x01, 0x02, 0x03), (0x04, 0x05, 0x06))),
        )
        self.assertEqual(encoded[54:], bytes.fromhex("06 05 04 00 03 02 01 00"))

    def test_rejects_invalid_dimensions_and_file_size_overflow(self) -> None:
        for width, height, error_type in (
            (0, 1, ValueError),
            (1, 0, ValueError),
            (-1, 1, ValueError),
            (1, -1, ValueError),
            (True, 1, TypeError),
            (1, 1.5, TypeError),
            (0x80000000, 1, ValueError),
            (0x7FFFFFFF, 1, ValueError),
        ):
            with self.subTest(width=width, height=height):
                with self.assertRaises(error_type):
                    encode_legacy_bmp24(width, height, [])

    def test_rejects_wrong_pixel_count(self) -> None:
        with self.assertRaises(ValueError):
            encode_legacy_bmp24(2, 1, [(0, 0, 0)])
        with self.assertRaises(ValueError):
            encode_legacy_bmp24(1, 1, [(0, 0, 0), (0, 0, 0)])

        # Pixel-count validation must precede allocating the encoded image.
        with self.assertRaises(ValueError):
            encode_legacy_bmp24(1, 1_000_000, [])

    def test_rejects_malformed_pixels_and_channel_boundaries(self) -> None:
        invalid_pixels = (
            ((0, 0), ValueError),
            ((0, 0, 0, 0), ValueError),
            ((-1, 0, 0), ValueError),
            ((0, 0, 256), ValueError),
            ((0, 0, True), TypeError),
            ((0, 0, 1.5), TypeError),
            (b"\x00\x00\x00", TypeError),
        )
        for pixel, error_type in invalid_pixels:
            with self.subTest(pixel=pixel):
                with self.assertRaises(error_type):
                    encode_legacy_bmp24(1, 1, [pixel])

        encoded = encode_legacy_bmp24(1, 1, [(0, 255, 0)])
        self.assertEqual(encoded[54:58], bytes((0, 255, 0, 0)))


if __name__ == "__main__":
    unittest.main()
