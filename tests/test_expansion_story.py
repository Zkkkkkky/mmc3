from __future__ import annotations

import unittest
from pathlib import Path

from fc_editor.codecs.story_text import StoryTextCodec
from fc_editor.expansion_story import (
    STORY_DATA_CAPACITY,
    STORY_DATA_START,
    VERIFIED_STORY_SELECTORS,
    build_story_group,
    extract_story_group,
    pack_story_group,
    story_descriptor_offset,
)
from fc_editor.rom_image import RomImage


ROOT = Path(__file__).resolve().parents[1]
TARGET_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


class StoryExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rom = RomImage.load(TARGET_ROM)
        cls.codec = StoryTextCodec(cls.rom)

    def test_all_1785_indices_survive_semantic_relocation(self) -> None:
        source_groups = {
            selector: extract_story_group(self.codec, selector)
            for selector in VERIFIED_STORY_SELECTORS
        }
        targets = {
            selector: 0x40 + index * 2
            for index, selector in enumerate(VERIFIED_STORY_SELECTORS)
        }
        moved = bytearray(self.rom.data)
        packed_groups = {}
        for selector, records in source_groups.items():
            packed = pack_story_group(records, targets[selector])
            packed_groups[selector] = packed
            moved[
                packed.pair_file_offset : packed.pair_file_offset
                + len(packed.pair_image)
            ] = packed.pair_image
            moved[
                packed.descriptor_file_offset : packed.descriptor_file_offset + 2
            ] = packed.descriptor

        moved_codec = StoryTextCodec(
            self.rom,
            moved,
            group_bank_overrides=targets,
        )
        checked = 0
        for selector in VERIFIED_STORY_SELECTORS:
            restored = extract_story_group(moved_codec, selector)
            self.assertEqual(
                restored.raw_by_index,
                source_groups[selector].raw_by_index,
            )
            checked += len(restored.raw_by_index)
        self.assertEqual(checked, 7 * 255)

        # Group $39's highest pointer is a real 20-byte record, not an empty
        # shared sentinel.  This guards the bug that motivated the custom
        # terminal scanner in expansion_story.
        self.assertEqual(len(source_groups[0x39].record_for_index(0x69).raw), 20)
        self.assertEqual(
            extract_story_group(moved_codec, 0x39, moved).record_for_index(0x69).raw,
            source_groups[0x39].record_for_index(0x69).raw,
        )

    def test_original_pointer_alias_topology_is_preserved(self) -> None:
        for index, selector in enumerate(VERIFIED_STORY_SELECTORS):
            source = extract_story_group(self.codec, selector)
            packed = pack_story_group(source, 0x40 + index * 2)
            canonical_by_pointer: dict[int, int] = {}
            relocated_signature = []
            for pointer in packed.pointers:
                if pointer not in canonical_by_pointer:
                    canonical_by_pointer[pointer] = len(canonical_by_pointer)
                relocated_signature.append(canonical_by_pointer[pointer])
            self.assertEqual(tuple(relocated_signature), source.alias_signature)

        # Equal payloads created by editing must remain independent when their
        # original pointers were independent.
        source = extract_story_group(self.codec, 0x33)
        highest = source.records[-1]
        changed = source.with_replacement(0, highest.raw)
        packed = pack_story_group(changed, 0x40)
        self.assertNotEqual(packed.pointers[0], packed.pointers[highest.indices[0]])
        self.assertEqual(
            len({packed.pointers[item] for item in highest.indices}),
            1,
        )

    def test_single_pair_capacity_overflow_is_rejected(self) -> None:
        self.assertEqual(STORY_DATA_START, 0x820E)
        self.assertEqual(STORY_DATA_CAPACITY, 15_858)
        source = extract_story_group(self.codec, 0x32)
        oversized = source.with_replacement(0, b"A" * STORY_DATA_CAPACITY + b"\xFF")
        with self.assertRaisesRegex(ValueError, "16 KiB pair"):
            pack_story_group(oversized, 0x40)

    def test_descriptor_offsets_and_direct_bank_bytes(self) -> None:
        expected_offsets = {
            0x32: 0x0FF456,
            0x33: 0x0FF458,
            0x36: 0x0FF45E,
            0x38: 0x0FF462,
            0x39: 0x0FF464,
            0x3A: 0x0FF466,
            0x3B: 0x0FF468,
        }
        for index, selector in enumerate(VERIFIED_STORY_SELECTORS):
            bank = 0x40 + index * 2
            packed = build_story_group(self.codec, selector, bank)
            self.assertEqual(story_descriptor_offset(selector), expected_offsets[selector])
            self.assertEqual(packed.descriptor_file_offset, expected_offsets[selector])
            self.assertEqual(packed.descriptor, bytes((0xF0, bank)))
            self.assertEqual(packed.pair_image[:16], bytes.fromhex("10 80") + bytes(14))
            self.assertEqual(len(packed.pair_image), 0x4000)

        with self.assertRaisesRegex(ValueError, "偶数"):
            build_story_group(self.codec, 0x32, 0x41)


if __name__ == "__main__":
    unittest.main()
