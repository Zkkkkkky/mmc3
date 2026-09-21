from __future__ import annotations

import json
import hashlib
import unittest
from pathlib import Path

from tools.research.collect_m08_all_physical_fields import (
    CATALOG_PATH,
    diff_ranges,
    mutation_for,
    unique_fields,
)


class M08AllPhysicalFieldsTests(unittest.TestCase):
    def test_every_physical_field_has_an_equal_width_mutation(self) -> None:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        fields = unique_fields(catalog)
        self.assertEqual(len(fields), 1095)
        for field in fields:
            mutation = mutation_for(field)
            self.assertNotEqual(mutation, field["text"])

    def test_diff_ranges_are_complete_and_disjoint(self) -> None:
        before = bytes([0, 1, 2, 3, 4, 5])
        after = bytes([9, 1, 8, 7, 4, 6])
        self.assertEqual(
            diff_ranges(before, after),
            [
                {"start": 0, "end_exclusive": 1, "before_hex": "00", "after_hex": "09"},
                {"start": 2, "end_exclusive": 4, "before_hex": "0203", "after_hex": "0807"},
                {"start": 5, "end_exclusive": 6, "before_hex": "05", "after_hex": "06"},
            ],
        )

    def test_archived_save_chain_replays_to_final_rom(self) -> None:
        root = CATALOG_PATH.parents[2]
        evidence = root / "output/verification/legacy-m08-all-fields-20260920/field-save-chain.jsonl"
        summary = json.loads(
            (root / "output/verification/legacy-m08-all-fields-20260920/summary.json").read_text(encoding="utf-8")
        )
        data = bytearray(
            (root / "output/build/legacy-diff-audit/m05-reference-baseline.nes").read_bytes()
        )
        rows = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1095)
        for row in rows:
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["before_sha256"])
            for change in row["ranges"]:
                start, end = change["start"], change["end_exclusive"]
                self.assertEqual(bytes(data[start:end]).hex().upper(), change["before_hex"])
                data[start:end] = bytes.fromhex(change["after_hex"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["after_sha256"])
        self.assertEqual(hashlib.sha256(data).hexdigest(), summary["final_sha256"])
        self.assertEqual(summary["saved_fields"], 1090)
        self.assertEqual(summary["no_effect_fields"], 4)
        self.assertEqual(summary["unsafe_orphan_write_fields"], 1)


if __name__ == "__main__":
    unittest.main()
