from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.golden_pipeline_core import AUDIT_DIR_RELATIVE
from tools.prepare_golden_case_retry import prepare_retries


class PrepareGoldenCaseRetryTests(unittest.TestCase):
    def test_moves_evidence_and_removes_only_matching_live_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            live_root = repo / AUDIT_DIR_RELATIVE / "cases" / "legacy_live"
            target = live_root / "M05" / "hp" / "cold_start_01"
            target.mkdir(parents=True)
            (target / "error.json").write_text('{"error":"transient"}', encoding="utf-8")
            other = live_root / "M17" / "hit" / "cold_start_01"
            other.mkdir(parents=True)
            (other / "case.json").write_text("{}", encoding="utf-8")
            results_path = repo / AUDIT_DIR_RELATIVE / "legacy-live-results.json"
            results_path.write_text(
                json.dumps(
                    [
                        {"module": "M05", "field": "hp", "case_id": "cold_start_01"},
                        {"module": "M17", "field": "hit", "case_id": "cold_start_01"},
                    ]
                ),
                encoding="utf-8",
            )

            manifest_path = prepare_retries(
                repo,
                [("M05", "hp", "cold_start_01")],
                reason="retry transient failure",
                timestamp="20260920T000000",
            )

            self.assertFalse(target.exists())
            moved = (
                repo
                / AUDIT_DIR_RELATIVE
                / "cases"
                / "diagnostic"
                / "retry_history"
                / "20260920T000000"
                / "M05"
                / "hp"
                / "cold_start_01"
            )
            self.assertTrue((moved / "error.json").is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["live_result_rows_removed"], 1)
            self.assertTrue(manifest["moved"][0]["had_error_json"])
            results = json.loads(results_path.read_text(encoding="utf-8"))
            self.assertEqual(results, [{"module": "M17", "field": "hit", "case_id": "cold_start_01"}])
            self.assertTrue(other.is_dir())


if __name__ == "__main__":
    unittest.main()
