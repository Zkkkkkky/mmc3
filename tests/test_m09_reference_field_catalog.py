from __future__ import annotations

import unittest

from tools.report_m09_reference_field_catalog import DEFAULT_CAPTURE, DEFAULT_ROM, build


class M09ReferenceFieldCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build(DEFAULT_ROM, DEFAULT_CAPTURE)

    def test_exact_reference_counts(self) -> None:
        counts = self.report["counts"]
        self.assertEqual(counts["logical_fields"], 414)
        self.assertEqual(counts["persistent_physical_fields"], 212)
        self.assertEqual(
            counts["logical_by_family"],
            {"distance": 80, "experience": 60, "system": 221, "growth": 53},
        )
        self.assertEqual(
            counts["physical_by_family"],
            {"distance": 80, "experience": 60, "system": 62, "growth": 11},
        )

    def test_exact_reference_layout(self) -> None:
        layout = self.report["layout"]
        self.assertEqual(layout["distance_offset"], 0xB642)
        self.assertEqual(layout["experience_offset"], 0xB69A)
        self.assertTrue(layout["experience_max_level_next_constant"])
        self.assertEqual(layout["system_table_pointer"], 0xA55D)
        self.assertEqual(layout["growth_pointer_table_offset"], 0xA720)

    def test_shared_reference_records_are_explicit(self) -> None:
        fields = self.report["fields"]
        growth_211 = next(item for item in fields if item["field_id"] == "M09/growth/211")
        self.assertEqual(growth_211["aliases"], list(range(211, 254)))
        empty_system = next(item for item in fields if item["field_id"] == "M09/system/218")
        self.assertGreater(len(empty_system["aliases"]), 100)

    def test_experience_maps_editable_needed_values_not_read_only_totals(self) -> None:
        fields = self.report["fields"]
        level_1 = next(item for item in fields if item["field_id"] == "M09/experience/01")
        level_60 = next(item for item in fields if item["field_id"] == "M09/experience/60")
        self.assertEqual(level_1["value"], 30)
        self.assertEqual(level_1["total_experience_read_only"], 0)
        self.assertEqual(level_1["file_offset"], 0xB69A)
        self.assertEqual(level_60["value"], 0)
        self.assertEqual(level_60["physical_id"], "constant/max-level-next-0")


if __name__ == "__main__":
    unittest.main()
