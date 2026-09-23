import json
import unittest
from pathlib import Path

from tools.golden_pipeline_collect import CaseSpec
from tools.prepare_m05_legacy_upload_samples import prepare


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY = ROOT / "tools/golden_pipeline/discovery_history"
CASES = ROOT / "tools/golden_pipeline/cases"

PROMOTED = {
    "body-puzzle-clear",
    "body-puzzle-move-up",
    "body-puzzle-move-down",
    "body-puzzle-move-left",
    "body-puzzle-move-right",
    "body-puzzle-swap-banks",
    "body-puzzle-template-7x9",
    "body-puzzle-template-9x7",
    "body-puzzle-template-10x6",
    "fragment-puzzle-move-up",
    "fragment-puzzle-move-down",
    "fragment-puzzle-move-left",
    "fragment-puzzle-move-right",
    "fragment-puzzle-clear",
    "fragment-puzzle-flip-horizontal",
    "fragment-puzzle-flip-vertical",
}


RECIPES = {
    "body-puzzle-clear": (280, "F3 F7 07", "FF "),
    "body-puzzle-move-up": (360, "F3 F7 07", "F3 F6 07"),
    "body-puzzle-move-down": (380, "F3 F7 07", "F3 F7 07"),
    "body-puzzle-move-left": (370, "F3 F7 07", "F3 F7 07"),
    "body-puzzle-move-right": (390, "F3 F7 07", "F3 F7 08"),
    "fragment-puzzle-move-up": (260, "06 BE 05", "06 BD 05"),
    "fragment-puzzle-move-down": (280, "06 BE 05", "06 BF 05"),
    "fragment-puzzle-move-left": (270, "06 BE 05", "05 BE 05"),
    "fragment-puzzle-move-right": (290, "06 BE 05", "07 BE 05"),
    "fragment-puzzle-clear": (340, "06 BE 05", "00 F0 00 00 FF "),
    "fragment-puzzle-flip-horizontal": (430, "06 BE 05", "72 BE 05"),
    "fragment-puzzle-flip-vertical": (440, "06 BE 05", "06 BA 05"),
}


class M05PuzzleDiscoverySpecTests(unittest.TestCase):
    def _path(self, stem: str) -> Path:
        golden = CASES / f"M05-{stem}-cold-start-01.json"
        if golden.is_file():
            return golden
        return DISCOVERY / f"M05-{stem}-discovery-cold-start-01.json"

    def _load(self, stem: str) -> CaseSpec:
        path = self._path(stem)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return CaseSpec.from_payload(payload)

    def test_puzzle_recipes_have_reviewed_evidence_status(self) -> None:
        files = sorted(DISCOVERY.glob("M05-*-puzzle-*-discovery-cold-start-01.json"))
        files += sorted(CASES.glob("M05-*-puzzle-*-cold-start-01.json"))
        self.assertEqual(len(files), 17)
        for stem, (control_id, before_prefix, requested_prefix) in RECIPES.items():
            with self.subTest(stem=stem):
                spec = self._load(stem)
                self.assertEqual(spec.module, "M05")
                expected_kind = "golden" if stem in PROMOTED else "discovery"
                self.assertEqual(spec.case_kind, expected_kind)
                if expected_kind == "golden":
                    if spec.expected_noop:
                        self.assertEqual(spec.expected_offsets, ())
                        self.assertEqual(spec.required_offsets, ())
                    else:
                        self.assertTrue(spec.expected_offsets)
                        self.assertEqual(spec.required_offsets, spec.expected_offsets)
                else:
                    self.assertEqual(spec.expected_offsets, ())
                    self.assertEqual(spec.required_offsets, ())
                self.assertEqual(spec.optional_offsets, ())
                self.assertTrue(str(spec.expected_before).startswith(before_prefix))
                self.assertTrue(str(spec.requested_value).startswith(requested_prefix))
                self.assertIn(
                    {"op": "click_id", "class": "Button", "control_id": control_id},
                    spec.edit_steps,
                )

    def test_fragment_flip_recipes_match_live_reference_results(self) -> None:
        expected_results = {
            "fragment-puzzle-flip-horizontal": (
                "72 BE 05 4E BF 02 4E 2D 04 46 F8 4E E3 01 4E 37 01 4E C8 02 "
                "46 F8 4E 2D 04 4E E0 03 4E FE 01 46 F8 4E 30 05 4E F8 02 4E "
                "FF 07 46 F6 4E 10 05 4E F8 03 42 FF "
            ),
            "fragment-puzzle-flip-vertical": (
                "06 BA 05 8E 41 FE 8E D3 FC 82 8E 1D FF 8E C9 FF 8E 38 FE 82 "
                "8E D3 FC 8E 20 FD 8E 02 FF 82 8E D0 FB 8E 08 FE 8E 01 F9 86 "
                "0A 8E F0 FB 8E 08 FD 82 FF "
            ),
        }
        for stem, expected in expected_results.items():
            with self.subTest(stem=stem):
                self.assertEqual(self._load(stem).requested_value, expected)

    def test_icon_binding_double_click_recipe_stops_before_empty_save(self) -> None:
        path = CASES / "M05-icon-binding-double-click-cold-start-01.json"
        spec = CaseSpec.from_payload(json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(spec.module, "M05")
        self.assertEqual(spec.case_kind, "golden")
        self.assertTrue(spec.expected_noop)
        self.assertEqual(spec.expected_offsets, ())
        self.assertEqual(spec.expected_before, 2)
        self.assertEqual(spec.requested_value, 2)
        self.assertIn(
            {
                "op": "click_control_coords",
                "control_id": 170,
                "x": 20,
                "y": 16,
                "click_count": 2,
            },
            spec.edit_steps,
        )
        self.assertIn(
            {
                "op": "assert_value",
                "class": "ComboBox",
                "control_id": 130,
                "value_type": "combo_index",
                "value": "$requested",
            },
            spec.edit_steps,
        )

    def test_upload_recipes_use_guarded_file_dialog_and_visual_capture(self) -> None:
        manifest = prepare()
        self.assertEqual(manifest["files"]["body.bmp"]["dimensions"], [128, 128])
        self.assertEqual(manifest["files"]["fragment.bmp"]["dimensions"], [128, 128])
        self.assertEqual(manifest["files"]["icon.bmp"]["dimensions"], [16, 16])
        self.assertNotEqual(
            manifest["files"]["body.bmp"]["sha256"],
            manifest["files"]["fragment.bmp"]["sha256"],
        )
        recipes = {
            "body": (150, "Afx:400000:b:10003:900015:0"),
            "fragment": (150, "Afx:400000:b:10003:900015:0"),
            "icon": (1340, "_EL_DrawPanel"),
        }
        for kind, (control_id, control_class) in recipes.items():
            with self.subTest(kind=kind):
                path = DISCOVERY / f"M05-{kind}-upload-bmp-discovery-cold-start-01.json"
                spec = CaseSpec.from_payload(json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(spec.requested_value, "$capture_after")
                self.assertEqual(spec.expected_offsets, ())
                self.assertEqual(spec.read_selector["control_id"], control_id)
                self.assertEqual(spec.read_selector["class"], control_class)
                self.assertEqual(spec.read_selector["value_type"], "control_pixel_sha256")
                file_steps = [
                    step
                    for step in spec.edit_steps
                    if step.get("control_id") == 1148
                ]
                self.assertEqual(len(file_steps), 1)
                self.assertTrue(str(file_steps[0]["value"]).startswith("$repo_path:"))
                self.assertTrue(str(file_steps[0]["value"]).endswith(f"/{kind}.bmp"))

    def test_main_clear_recipes_capture_changed_preview_before_cold_reopen(self) -> None:
        for kind, button_id in (("body", 2670), ("fragment", 2680)):
            with self.subTest(kind=kind):
                path = DISCOVERY / f"M05-main-clear-{kind}-discovery-cold-start-01.json"
                spec = CaseSpec.from_payload(json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(spec.requested_value, "$capture_after")
                self.assertEqual(spec.expected_offsets, ())
                self.assertEqual(spec.read_selector["control_id"], 150)
                self.assertIn(
                    {"op": "click_id", "class": "Button", "control_id": button_id},
                    spec.edit_steps,
                )

    def test_compressed_upload_recipes_enable_reference_compression(self) -> None:
        recipes = {
            "body": (170, 180, 160),
            "fragment": (1300, 1290, 1310),
        }
        for kind, (offset_id, check_id, upload_id) in recipes.items():
            with self.subTest(kind=kind):
                path = (
                    DISCOVERY
                    / f"M05-{kind}-compressed-upload-bmp-discovery-cold-start-01.json"
                )
                spec = CaseSpec.from_payload(json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(spec.requested_value, "$capture_after")
                self.assertEqual(spec.expected_offsets, ())
                self.assertEqual(spec.read_selector["control_id"], 150)
                self.assertIn(
                    {
                        "op": "set_text",
                        "class": "Edit",
                        "control_id": offset_id,
                        "value": "0",
                    },
                    spec.edit_steps,
                )
                self.assertIn(
                    {
                        "op": "set_check",
                        "class": "Button",
                        "control_id": check_id,
                        "value": 1,
                    },
                    spec.edit_steps,
                )
                self.assertIn(
                    {"op": "click_id", "class": "Button", "control_id": upload_id},
                    spec.edit_steps,
                )
                file_step = next(
                    step for step in spec.edit_steps if step.get("control_id") == 1148
                )
                self.assertTrue(str(file_step["value"]).endswith(f"/{kind}.bmp"))

    def test_body_template_recipes_capture_script_before_closing_dialog(self) -> None:
        for name, button_id in (
            ("8x8", 290),
            ("7x9", 300),
            ("9x7", 310),
            ("10x6", 320),
        ):
            with self.subTest(name=name):
                path = self._path(f"body-puzzle-template-{name}")
                spec = CaseSpec.from_payload(json.loads(path.read_text(encoding="utf-8")))
                if name == "7x9":
                    self.assertEqual(spec.requested_value, spec.expected_before)
                    self.assertIsNone(spec.capture_after_step)
                else:
                    self.assertNotEqual(spec.requested_value, "$capture_after")
                    self.assertIsNone(spec.capture_after_step)
                if name in {"8x8", "7x9", "9x7", "10x6"}:
                    self.assertEqual(spec.case_kind, "golden")
                    if name == "7x9":
                        self.assertTrue(spec.expected_noop)
                    else:
                        self.assertTrue(spec.expected_offsets)
                self.assertEqual(spec.read_selector["control_id"], 270)
                self.assertEqual(
                    spec.edit_steps[0],
                    {"op": "click_id", "class": "Button", "control_id": button_id},
                )

    def test_body_bank_swap_recipe_captures_script_before_closing_dialog(self) -> None:
        spec = self._load("body-puzzle-swap-banks")
        self.assertEqual(spec.requested_value, spec.expected_before)
        self.assertEqual(spec.case_kind, "golden")
        self.assertTrue(spec.expected_noop)
        self.assertIsNone(spec.capture_after_step)
        self.assertEqual(spec.expected_offsets, ())
        self.assertEqual(spec.read_selector["control_id"], 270)
        self.assertEqual(
            spec.edit_steps[0],
            {"op": "click_id", "class": "Button", "control_id": 450},
        )


if __name__ == "__main__":
    unittest.main()
