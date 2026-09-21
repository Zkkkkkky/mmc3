from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from tools.report_m09_reference_field_catalog import DEFAULT_ROM


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/verification/legacy-m09-all-fields-20260920"


class M09AllPhysicalFieldsTests(unittest.TestCase):
    def test_completed_evidence_chain_replays(self) -> None:
        summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["logical_fields"], 414)
        self.assertEqual(summary["save_probe_fields"], 414)
        self.assertEqual(summary["initial_physical_candidates"], 213)
        data = bytearray(DEFAULT_ROM.read_bytes())
        lines = (OUT / "field-save-chain.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 414)
        for raw_line in lines:
            item = json.loads(raw_line)
            self.assertEqual(hashlib.sha256(data).hexdigest(), item["before_sha256"])
            for change in item["ranges"]:
                start = change["start"]
                end = change["end_exclusive"]
                self.assertEqual(bytes(data[start:end]).hex().upper(), change["before_hex"])
                data[start:end] = bytes.fromhex(change["after_hex"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), item["after_sha256"])
        self.assertEqual(hashlib.sha256(data).hexdigest(), summary["final_sha256"])


if __name__ == "__main__":
    unittest.main()
