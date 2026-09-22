from __future__ import annotations

import unittest

from tools.report_m12_call_address_candidates import CALL, ROM, SOURCE, reference_addresses


class M12CallAddressCandidateTests(unittest.TestCase):
    @unittest.skipUnless(SOURCE.is_file() and ROM.is_file(), "需要资料集与推荐 ROM")
    def test_reference_list_marks_offset_mismatch_without_equating_it_to_exact(self):
        addresses = reference_addresses(SOURCE.read_bytes().decode("gbk"))
        self.assertEqual(len(addresses), 13)
        self.assertIn(0x38983, addresses)
        rom = ROM.read_bytes()
        self.assertEqual(rom[0x38982:0x38985], CALL)
        self.assertNotEqual(rom[0x38983:0x38986], CALL)
        exact = sum(rom[address:address + 3] == CALL for address in addresses)
        self.assertEqual(exact, 7)


if __name__ == "__main__":
    unittest.main()
