from __future__ import annotations

import unittest

from tools import analyze_m05_pending_actions as analysis


class M05PendingActionAnalysisTests(unittest.TestCase):
    def test_preview_only_and_secondary_writes_are_separated(self) -> None:
        report = analysis.analyze()
        self.assertTrue(report["passed"])
        self.assertEqual(report["counts"]["cases"], 8)
        self.assertEqual(report["counts"]["previewOnlyConfirmed"], 2)
        self.assertEqual(report["counts"]["savePromotedAfterRequestCorrection"], 1)
        self.assertEqual(report["counts"]["secondaryResourceWriteUnresolved"], 0)
        self.assertEqual(report["counts"]["resourceSaveConfirmedCaptureMismatch"], 4)
        self.assertEqual(report["counts"]["invalidReferenceUpload"], 1)
        self.assertTrue(report["checks"]["allActionSpecificOffsetsMapped"])

        cases = report["cases"]
        for field in ("body_upload_bmp", "fragment_upload_bmp"):
            self.assertEqual(
                cases[field]["classification"],
                "reference_preview_only_confirmed",
            )
            self.assertEqual(cases[field]["actionSpecificDiff"]["count"], 0)
            self.assertTrue(cases[field]["reopenMatchesOriginal"])

        self.assertEqual(
            cases["body_puzzle_template_8x8"]["classification"],
            "reference_save_promoted_after_request_correction",
        )
        self.assertTrue(report["checks"]["template8x8CorrectionAudited"])

        self.assertEqual(
            cases["fragment_compressed_upload_bmp"]["classification"],
            "reference_resource_save_confirmed_capture_mismatch",
        )
        self.assertTrue(report["checks"]["compressedBodyEncodingConfirmed"])
        self.assertTrue(report["checks"]["compressedFragmentEncodingConfirmed"])
        self.assertTrue(report["checks"]["clearActionsConfirmed"])
        self.assertTrue(report["checks"]["iconUploadClearsTarget"])

    def test_ordinary_body_and_fragment_uploads_have_identical_output(self) -> None:
        report = analysis.analyze()
        cases = report["cases"]
        self.assertEqual(
            cases["body_upload_bmp"]["outputSha256"],
            cases["fragment_upload_bmp"]["outputSha256"],
        )

    def test_action_specific_offsets_are_in_known_resource_regions(self) -> None:
        cases = analysis.analyze()["cases"]
        template_regions = cases["body_puzzle_template_8x8"][
            "actionSpecificRegions"
        ]
        self.assertEqual(template_regions["unitCompositionPair"]["count"], 13524)
        self.assertEqual(template_regions["activeChr"]["count"], 0)

        icon_regions = cases["icon_upload_bmp"]["actionSpecificRegions"]
        self.assertEqual(icon_regions["unitCompositionPair"]["count"], 0)
        self.assertEqual(icon_regions["activeChr"]["count"], 56)


if __name__ == "__main__":
    unittest.main()
