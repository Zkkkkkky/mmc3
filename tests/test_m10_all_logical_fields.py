from __future__ import annotations

import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/verification/legacy-m10-all-fields-20260920"


class M10AllLogicalFieldsTests(unittest.TestCase):
    def test_completed_evidence_chain_replays(self) -> None:
        summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["logical_fields"], 254)
        self.assertEqual(summary["product_safe_candidates"], 134)
        self.assertEqual(summary["product_blocked_candidates"], 120)
        lines = [json.loads(line) for line in (OUT / "field-save-chain.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lines), 254)
        self.assertEqual([item["sequence"] for item in lines], list(range(254)))
        data = bytearray((ROOT / "output/build/legacy-diff-audit/audit.nes").read_bytes())
        for item in lines:
            self.assertEqual(hashlib.sha256(data).hexdigest(), item["before_sha256"])
            for change in item["ranges"]:
                start, end = change["start"], change["end_exclusive"]
                self.assertEqual(bytes(data[start:end]).hex().upper(), change["before_hex"])
                data[start:end] = bytes.fromhex(change["after_hex"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), item["after_sha256"])
        self.assertEqual(hashlib.sha256(data).hexdigest(), summary["final_sha256"])
        self.assertEqual(Counter(item["status"] for item in lines), Counter(summary["statuses"]))

    def test_cold_process_matches_same_process_for_all_logical_fields(self) -> None:
        warm = json.loads((OUT / "same-process-final-values.json").read_text(encoding="utf-8"))
        cold = json.loads((OUT / "cold-process-final-values.json").read_text(encoding="utf-8"))
        self.assertEqual(len(warm), 254)
        self.assertEqual(cold, warm)


if __name__ == "__main__":
    unittest.main()
