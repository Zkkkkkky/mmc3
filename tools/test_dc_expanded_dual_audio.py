from __future__ import annotations

import hashlib
import json
import unittest

import build_dc_expanded_dual_audio as builder
from fc_rom_editor_core import apply_ips


EXPECTED_OUTPUT_SHA256 = (
    "82c218275459d53c0f306f6bc036c4797316976e0fa7ad1d5a8247e338995b8e"
)
EXPECTED_ENGINE_SHA256 = (
    "e046ac7a47a0d92ec1c41840896d323ced35d68656970d74fede42eb9711e0dc"
)


def bank(data: bytes, index: int) -> bytes:
    start = builder.prg_bank_offset(index)
    return data[start : start + builder.PRG_BANK_SIZE]


class ExpandedDualAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        builder.main()
        cls.source = builder.SOURCE_ROM.read_bytes()
        cls.output = builder.OUTPUT_ROM.read_bytes()
        cls.ips = builder.OUTPUT_IPS.read_bytes()

    def test_source_output_hash_size_and_header(self) -> None:
        self.assertEqual(
            hashlib.sha256(self.source).hexdigest(),
            builder.EXPECTED_SOURCE_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(self.output).hexdigest(), EXPECTED_OUTPUT_SHA256
        )
        self.assertEqual(len(self.source), builder.EXPECTED_SOURCE_SIZE)
        self.assertEqual(len(self.output), builder.OUTPUT_SIZE)

        expected_header = bytearray(self.source[: builder.INES_HEADER_SIZE])
        expected_header[4] = 0x40
        self.assertEqual(self.output[: builder.INES_HEADER_SIZE], expected_header)
        mapper = (self.output[6] >> 4) | (self.output[7] & 0xF0)
        self.assertEqual(mapper, 194)

    def test_source_rom_is_unchanged_and_delivery_is_derived(self) -> None:
        self.assertEqual(
            hashlib.sha256(builder.SOURCE_ROM.read_bytes()).hexdigest(),
            builder.EXPECTED_SOURCE_SHA256,
        )
        self.assertEqual(builder.DELIVERY_ROM.read_bytes(), self.output)

    def test_original_prg_has_only_approved_patches_and_active_chr_is_exact(self) -> None:
        original_prg_end = builder.INES_HEADER_SIZE + builder.ORIGINAL_PRG_SIZE
        source_chr = self.source[original_prg_end:]
        expected_prg = bytearray(
            self.source[builder.INES_HEADER_SIZE:original_prg_end]
        )
        audio_start = builder.STOCK_AUDIO_BANK * builder.PRG_BANK_SIZE
        expected_prg[audio_start : audio_start + builder.PRG_BANK_SIZE] = (
            builder.patched_stock_audio_bank(
                self.source,
                builder.TRAMPOLINE_BIN.read_bytes(),
                builder.HANDOFF_BIN.read_bytes(),
            )
        )
        for selector, (attacker, defender) in builder.GAMEPLAY_MUSIC_BINDINGS.items():
            expected_prg[
                builder.BATTLE_MUSIC_ATTACKER_OFFSET
                - builder.INES_HEADER_SIZE
                + selector
            ] = attacker
            expected_prg[
                builder.BATTLE_MUSIC_DEFENDER_OFFSET
                - builder.INES_HEADER_SIZE
                + selector
            ] = defender
        self.assertEqual(
            self.output[builder.INES_HEADER_SIZE:original_prg_end],
            expected_prg,
        )
        active_chr = builder.INES_HEADER_SIZE + builder.EXPANDED_PRG_SIZE
        self.assertEqual(
            self.output[active_chr : active_chr + builder.ORIGINAL_CHR_SIZE],
            source_chr,
        )

    def test_stock_audio_is_patched_in_place_and_bank_60_is_free(self) -> None:
        expected = builder.patched_stock_audio_bank(
            self.source,
            builder.TRAMPOLINE_BIN.read_bytes(),
            builder.HANDOFF_BIN.read_bytes(),
        )
        self.assertEqual(bank(self.output, builder.STOCK_AUDIO_BANK), expected)
        self.assertEqual(bank(self.output, 0x60), bytes(builder.PRG_BANK_SIZE))

    def test_three_music_banks_and_engine_match_payloads(self) -> None:
        for music_bank in builder.MUSIC_BANK_ASM:
            payload = (
                builder.ANALYSIS / f"dc_dual_music_{music_bank:02x}.bin"
            ).read_bytes()
            self.assertEqual(bank(self.output, music_bank), payload)

        engine = builder.ENGINE_BIN.read_bytes()
        self.assertEqual(hashlib.sha256(engine).hexdigest(), EXPECTED_ENGINE_SHA256)
        self.assertEqual(bank(self.output, builder.ENGINE_BANK), engine)
        bridge_end = (
            builder.label_address(builder.ENGINE_LST, "dc_dual_audio_bridge_end")
            - 0xA000
        )
        bridge = engine[0x1500:bridge_end]
        self.assertIn(bytes.fromhex("A9 86 8D 00 80 A9 18 8D 01 80"), bridge)
        self.assertNotIn(bytes.fromhex("A9 86 8D 00 80 A9 60 8D 01 80"), bridge)

    def test_reserved_expansion_banks_are_zero(self) -> None:
        for first, end in ((0x40, 0x61), (0x65, 0x7E)):
            for index in range(first, end):
                self.assertEqual(bank(self.output, index), bytes(builder.PRG_BANK_SIZE))

    def test_expanded_fixed_banks_are_exact_copies_with_audio_operands(self) -> None:
        self.assertEqual(
            bank(self.output, builder.FIXED_BANK_C000),
            bank(self.source, builder.STOCK_FIXED_C000_BANK),
        )
        expected = bytearray(bank(self.source, builder.STOCK_FIXED_E000_BANK))
        for address in builder.FIXED_E000_AUDIO_OPERANDS:
            expected[address - 0xE000] = builder.STOCK_AUDIO_BANK
        self.assertEqual(bank(self.output, builder.FIXED_BANK_E000), expected)

    def test_famistudio_state_reuses_only_certified_stock_audio_ram(self) -> None:
        expected_labels = {
            "famistudio_r0": 0x0028,
            "famistudio_ptr1": 0x0030,
            "famistudio_song_speed": 0x002F,
            "famistudio_chn_return_hi": 0x0032,
            "famistudio_output_buf": 0x004C,
            "famistudio_env_value": 0x0400,
            "famistudio_pitch_env_fine_value": 0x0432,
            "famistudio_env_ptr": 0x0435,
            "famistudio_chn_return_lo": 0x0454,
            "famistudio_sfx_base_addr": 0x0459,
            "bridge_magic_a": 0x0468,
            "custom_state": 0x046B,
            "famistudio_instrument_lo": 0x046C,
        }
        for label, address in expected_labels.items():
            self.assertEqual(
                builder.label_address(builder.ENGINE_LST, label), address, label
            )
        layout = builder.validate_ram_layout()
        self.assertEqual(layout["certifiedStockAudioBytes"], 165)
        self.assertEqual(layout["savedOutputBytes"], 11)
        self.assertEqual(
            builder.label_address(builder.ENGINE_LST, "dc_dual_audio_bridge"),
            0xB500,
        )
        self.assertEqual(
            builder.label_address(
                builder.HANDOFF_LST, "stock_handoff_dispatch"
            ),
            0x99EC,
        )

    def test_capacity_report_records_preservation_and_compatibility(self) -> None:
        report = json.loads(builder.CAPACITY_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["preservation"]["headerChangedOffsets"], ["0x4"])
        self.assertFalse(report["preservation"]["sourceRomOverwritten"])
        self.assertTrue(report["preservation"]["stockAudioPatchedInPlace"])
        self.assertTrue(report["preservation"]["oldChrPrgBanksZeroFilled"])
        self.assertTrue(report["preservation"]["activeChrCopyMatchesSource"])
        self.assertEqual(report["preservation"]["managedCapacityBytes"], 464 * 1024)
        self.assertEqual(report["output"]["mapper"], 194)
        self.assertEqual(report["engines"]["stock"]["musicTracks"], 20)
        self.assertEqual(report["engines"]["famiStudio"]["musicTracks"], 3)
        self.assertEqual(report["engines"]["famiStudio"]["sfxCommands"], 56)
        self.assertIn("FCEUX 2.6.6", report["compatibility"]["knownIncompatible"])

    def test_ips_round_trip(self) -> None:
        self.assertEqual(apply_ips(self.source, self.ips), self.output)


if __name__ == "__main__":
    unittest.main()
