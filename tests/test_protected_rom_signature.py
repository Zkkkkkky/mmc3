from __future__ import annotations

import unittest
from pathlib import Path

from fc_editor.constants import (
    DC_EXPANDED_MMC3_MUTABLE_DESCRIPTOR_SELECTORS,
    DC_EXPANDED_MMC3_NORMALIZED_PROTECTED_SHA256,
    INES_HEADER_SIZE,
    PRG_BANK_SIZE,
)
from fc_editor.errors import RomFormatError
from fc_editor.expansion import resource_descriptor_offset
from fc_editor.profiles import (
    DC_EXPANDED_MMC3_PROFILE,
    dc_expanded_mmc3_protected_sha256,
)
from fc_editor.rom_image import RomImage
from fc_rom_editor_core import RomProject


ROOT = Path(__file__).resolve().parents[1]
TARGET_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"


class ProtectedRomSignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = TARGET_ROM.read_bytes()

    def test_authenticated_baseline_has_expected_normalized_signature(self) -> None:
        self.assertEqual(
            dc_expanded_mmc3_protected_sha256(self.baseline),
            DC_EXPANDED_MMC3_NORMALIZED_PROTECTED_SHA256,
        )

    def test_managed_resource_descriptors_do_not_break_authentication(self) -> None:
        edited = bytearray(self.baseline)
        for selector in DC_EXPANDED_MMC3_MUTABLE_DESCRIPTOR_SELECTORS:
            offset = resource_descriptor_offset(selector)
            edited[offset : offset + 2] = bytes((selector, selector ^ 0xFF))

        rom = RomImage(bytes(edited))
        self.assertIs(rom.profile, DC_EXPANDED_MMC3_PROFILE)
        self.assertEqual(
            dc_expanded_mmc3_protected_sha256(edited),
            DC_EXPANDED_MMC3_NORMALIZED_PROTECTED_SHA256,
        )

    def test_fixed_banks_are_authenticated_against_canonical_baseline(self) -> None:
        for bank in (0x64, 0x7E, 0x7F):
            with self.subTest(bank=bank):
                edited = bytearray(self.baseline)
                offset = INES_HEADER_SIZE + bank * PRG_BANK_SIZE + 0x100
                edited[offset] ^= 0x01
                with self.assertRaisesRegex(RomFormatError, "认证|音频引擎"):
                    RomImage(bytes(edited))

    def test_header_is_authenticated_against_canonical_baseline(self) -> None:
        edited = bytearray(self.baseline)
        edited[8] ^= 0x01
        with self.assertRaisesRegex(RomFormatError, "扩容 Mapper 194"):
            RomImage(bytes(edited))

    def test_validation_does_not_trust_corrupt_original_as_its_baseline(self) -> None:
        project = RomProject.load(TARGET_ROM)
        corrupted = bytearray(project.original)
        offset = INES_HEADER_SIZE + 0x7E * PRG_BANK_SIZE + 0x100
        corrupted[offset] ^= 0x01
        project.original = bytes(corrupted)
        project.working = bytearray(corrupted)

        issues = project.validate()
        self.assertTrue(
            any(
                issue.severity == "error"
                and issue.module == "安全"
                and "认证固定代码签名" in issue.message
                for issue in issues
            )
        )


if __name__ == "__main__":
    unittest.main()
