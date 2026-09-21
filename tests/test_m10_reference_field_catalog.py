from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class M10ReferenceFieldCatalogTests(unittest.TestCase):
    def test_reference_probe_is_read_only_and_complete(self) -> None:
        source = json.loads((ROOT / "output/verification/legacy-m10-reference-catalog-20260920/catalog.json").read_text(encoding="utf-8"))
        self.assertTrue(source["passed"])
        self.assertTrue(source["rom_unchanged"])
        self.assertEqual(source["counts"], {"items": 24, "shops": 14, "dialogue_slots_per_shop": 7})
        self.assertEqual([shop["label"] for shop in source["shops"]], [*(f"商店F{x:X}" for x in range(13)), "商店FE"])

    def test_catalog_covers_every_visible_edit_surface(self) -> None:
        report = json.loads((ROOT / "output/reports/m10-reference-field-catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(report["counts"]["logical_fields"], 254)
        self.assertEqual(report["counts"]["product_safe_candidates"], 134)
        self.assertEqual(report["counts"]["product_blocked_candidates"], 120)
        self.assertEqual(report["counts"]["families"], {
            "item_description": 24, "item_name": 24, "item_price": 24,
            "shop_clerk": 14, "shop_dialogue_id": 14, "shop_dialogue_text": 98,
            "shop_item": 56,
        })
        self.assertEqual({field["control_id"] for field in report["fields"] if field["family"] == "shop_dialogue_text"}, {1970, 1990, 2010, 2020, 2040, 2060, 2090})


if __name__ == "__main__":
    unittest.main()
