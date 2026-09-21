from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from dc_modifier.app import DEFAULT_ROM
from dc_modifier.database_graphics import palette_color
from dc_modifier.map_tiles import (
    TILESET_BANKS,
    TILESET_PALETTE_ONE_VALUES,
    TILESET_PALETTE_ROUTES,
    VERIFIED_BATTLEFIELD_PALETTES,
    render_map_tile,
)
from fc_editor.codecs.map_tile_attribute import (
    MapTileAttributeCodec,
    MapTilesetAttributes,
)
from fc_editor.errors import RomFormatError
from fc_rom_editor_core import RomProject


class MapTileAttributeCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DEFAULT_ROM.is_file():
            raise unittest.SkipTest(f"缺少图块属性测试 ROM：{DEFAULT_ROM}")

    def setUp(self) -> None:
        self.project = RomProject.load(DEFAULT_ROM)

    def test_all_verified_records_decode_with_expected_offsets_and_selectors(self) -> None:
        self.assertTrue(self.project.supports_map_tile_attributes)
        for index, key in enumerate("ABCDEFG"):
            value = self.project.get_map_tileset_attributes(key)
            self.assertEqual(
                MapTileAttributeCodec.record_offset(key), 0x6060 + index * 0x54
            )
            self.assertEqual(
                value.graphic_selector,
                MapTileAttributeCodec.EXPECTED_GRAPHIC_SELECTORS[key],
            )
            self.assertEqual(len(value.tiles), 16)

    def test_water_tile_sea_property_is_read_and_repairs_omitted_rom_flags(self) -> None:
        self.assertTrue(self.project.get_map_tileset_attributes("A").tiles[5].sea)
        current = self.project.get_map_tileset_attributes("D")
        self.assertFalse(current.tiles[5].sea)
        for key in "ABCD":
            self.assertTrue(MapTileAttributeCodec.is_visual_sea(key, 5))
        base = MapTileAttributeCodec.record_offset("D")
        repaired = replace(
            current,
            tiles=current.tiles[:5]
            + (replace(current.tiles[5], sea=True),)
            + current.tiles[6:],
        )
        patches = MapTileAttributeCodec.patches(
            self.project.working, "D", repaired
        )
        sea_patch = next(
            patch for patch in patches if patch[0] == base + 20 + 5
        )
        self.assertEqual(sea_patch[1][0] & 0x80, 0)
        self.assertEqual(sea_patch[2][0] & 0x80, 0x80)

    def test_shared_battlefield_palettes_match_verified_rom_template(self) -> None:
        self.assertEqual(
            VERIFIED_BATTLEFIELD_PALETTES,
            {
                0: (0x0F, 0x30, 0x10, 0x00),
                2: (0x0F, 0x30, 0x21, 0x02),
                3: (0x0F, 0x37, 0x27, 0x16),
            },
        )
        self.assertEqual(
            bytes(self.project.working[0x3B2C0 : 0x3B2D0]),
            bytes.fromhex("0F 30 10 00 80 81 82 30 21 02 37 27 16 30 23 0F"),
        )

    def test_map_rendering_uses_game_effect_route_not_property_field(self) -> None:
        attributes = SimpleNamespace(
            colors=(0x27, 0x2A, 0x1A),
            tiles=tuple(SimpleNamespace(palette=2) for _ in range(16)),
        )
        project = SimpleNamespace(
            supports_map_tile_attributes=True,
            chr_tile_pixels=lambda _index: [2] * 64,
        )
        self.assertEqual(
            render_map_tile(project, "D", 0, attributes=attributes).pixelColor(0, 0),
            palette_color(0x10),
        )

    def test_every_tileset_tile_uses_the_game_effect_palette_route(self) -> None:
        for key in "ABCDEFG":
            attributes = self.project.get_map_tileset_attributes(key)
            for tile_index, palette_index in enumerate(TILESET_PALETTE_ROUTES[key]):
                with self.subTest(tileset=key, tile=tile_index):
                    image = render_map_tile(
                        self.project, key, tile_index, attributes=attributes
                    )
                    pixels = self.project.chr_tile_pixels(
                        TILESET_BANKS[key] * 64 + tile_index * 4
                    )
                    expected_palette = (
                        (0x0F, *attributes.colors)
                        if palette_index == 1
                        else VERIFIED_BATTLEFIELD_PALETTES[palette_index]
                    )
                    self.assertEqual(
                        image.pixelColor(0, 0),
                        palette_color(expected_palette[pixels[0]]),
                    )

    def test_bitmap_zero_uses_the_background_palette_in_every_library(self) -> None:
        self.assertTrue(all(TILESET_PALETTE_ROUTES[key][0] == 0 for key in "ABCDEFGH"))
        self.assertEqual(
            TILESET_PALETTE_ROUTES["D"],
            (0, 1, 0, 0, 3, 2, 1, 1, 3, 0, 0, 0, 0, 0, 0, 0),
        )
        image = render_map_tile(self.project, "D", 0)
        expected = {
            palette_color(value).name()
            for value in VERIFIED_BATTLEFIELD_PALETTES[0]
        }
        actual = {
            image.pixelColor(x, y).name()
            for y in range(image.height())
            for x in range(image.width())
        }
        self.assertEqual(actual, expected)

    def test_tileset_palette_one_values_match_verified_records(self) -> None:
        for key in "ABCDEFG":
            attributes = self.project.get_map_tileset_attributes(key)
            self.assertEqual(
                TILESET_PALETTE_ONE_VALUES[key], (0x0F, *attributes.colors)
            )

    def test_each_field_isolated_to_its_verified_byte(self) -> None:
        original = self.project.get_map_tileset_attributes("D")
        tile_index = 1
        cases = (
            (replace(original, colors=((original.colors[0] + 1) & 0x3F,) + original.colors[1:]), 0),
            (replace(original, tiles=original.tiles[:tile_index] + (replace(original.tiles[tile_index], palette=(original.tiles[tile_index].palette + 1) % 4),) + original.tiles[tile_index + 1:]), 4 + tile_index),
            (replace(original, tiles=original.tiles[:tile_index] + (replace(original.tiles[tile_index], defense=(original.tiles[tile_index].defense + 1) & 0x7F),) + original.tiles[tile_index + 1:]), 20 + tile_index),
            (replace(original, tiles=original.tiles[:tile_index] + (replace(original.tiles[tile_index], sea=not original.tiles[tile_index].sea),) + original.tiles[tile_index + 1:]), 20 + tile_index),
            (replace(original, tiles=original.tiles[:tile_index] + (replace(original.tiles[tile_index], air_move=(original.tiles[tile_index].air_move + 1) % 17),) + original.tiles[tile_index + 1:]), 36 + tile_index),
            (replace(original, tiles=original.tiles[:tile_index] + (replace(original.tiles[tile_index], land_move=(original.tiles[tile_index].land_move + 1) % 17),) + original.tiles[tile_index + 1:]), 52 + tile_index),
            (replace(original, tiles=original.tiles[:tile_index] + (replace(original.tiles[tile_index], sea_move=(original.tiles[tile_index].sea_move + 1) % 17),) + original.tiles[tile_index + 1:]), 68 + tile_index),
        )
        base = MapTileAttributeCodec.record_offset("D")
        for value, relative_offset in cases:
            with self.subTest(relative_offset=relative_offset):
                patches = MapTileAttributeCodec.patches(self.project.working, "D", value)
                self.assertEqual(len(patches), 1)
                self.assertEqual(patches[0][0], base + relative_offset)
                self.assertNotEqual(patches[0][0], base + 3)

    def test_invalid_encoding_fails_closed(self) -> None:
        data = bytearray(self.project.working)
        data[MapTileAttributeCodec.record_offset("D") + 4] = 0x01
        with self.assertRaises(RomFormatError):
            MapTileAttributeCodec.decode(data, "D")
        with self.assertRaises(ValueError):
            self.project.get_map_tileset_attributes("H")

    def test_apply_undo_reset_and_reopen(self) -> None:
        original = self.project.get_map_tileset_attributes("D")
        changed = replace(original, colors=((original.colors[0] + 1) & 0x3F,) + original.colors[1:])
        self.project.set_map_tileset_attributes("D", changed)
        self.assertEqual(self.project.get_map_tileset_attributes("D"), changed)
        self.assertEqual(self.project.undo_description, "图库 D 图块属性")
        self.project.undo()
        self.assertEqual(self.project.get_map_tileset_attributes("D"), original)
        self.project.redo()
        self.project.reset_map_tileset_attributes("D")
        self.assertEqual(self.project.get_map_tileset_attributes("D"), original)

        self.project.set_map_tileset_attributes("D", changed)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tile-attributes.nes"
            self.project.save_as(path, make_backup=False)
            reopened = RomProject.load(path)
            self.assertEqual(reopened.get_map_tileset_attributes("D"), changed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
