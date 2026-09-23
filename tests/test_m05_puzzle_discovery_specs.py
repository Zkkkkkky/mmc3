import json
import unittest
from pathlib import Path

from dc_modifier.unit_appearance_dialog import flip_fragment_script
from tools.golden_pipeline_collect import CaseSpec
from tools.prepare_m05_legacy_upload_samples import prepare


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY = ROOT / "tools/golden_pipeline/discovery_history"


RECIPES = {
    "body-puzzle-clear": (280, "F3 F8 00", "FF"),
    "body-puzzle-move-up": (360, "F3 F8 00", "F3 F7 00"),
    "body-puzzle-move-down": (380, "F3 F8 00", "F3 F9 00"),
    "body-puzzle-move-left": (370, "F3 F8 00", "F3 F8 FF"),
    "body-puzzle-move-right": (390, "F3 F8 00", "F3 F8 01"),
    "fragment-puzzle-move-up": (260, "08 C6 60", "08 C5 60"),
    "fragment-puzzle-move-down": (280, "08 C6 60", "08 C7 60"),
    "fragment-puzzle-move-left": (270, "08 C6 60", "07 C6 60"),
    "fragment-puzzle-move-right": (290, "08 C6 60", "09 C6 60"),
    "fragment-puzzle-clear": (340, "08 C6 60", "00 F0 00 00 FF"),
    "fragment-puzzle-flip-horizontal": (430, "08 C6 60", "08 C6 60"),
    "fragment-puzzle-flip-vertical": (440, "08 C6 60", "08 C6 60"),
}


class M05PuzzleDiscoverySpecTests(unittest.TestCase):
    def _load(self, stem: str) -> CaseSpec:
        path = DISCOVERY / f"M05-{stem}-discovery-cold-start-01.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return CaseSpec.from_payload(payload)

    def test_all_puzzle_recipes_are_guarded_discovery(self) -> None:
        files = sorted(DISCOVERY.glob("M05-*-puzzle-*-discovery-cold-start-01.json"))
        self.assertEqual(len(files), 17)
        for stem, (control_id, before_prefix, requested_prefix) in RECIPES.items():
            with self.subTest(stem=stem):
                spec = self._load(stem)
                self.assertEqual(spec.module, "M05")
                self.assertEqual(spec.case_kind, "discovery")
                self.assertEqual(spec.expected_offsets, ())
                self.assertEqual(spec.required_offsets, ())
                self.assertEqual(spec.optional_offsets, ())
                self.assertTrue(str(spec.expected_before).startswith(before_prefix))
                self.assertTrue(str(spec.requested_value).startswith(requested_prefix))
                self.assertIn(
                    {"op": "click_id", "class": "Button", "control_id": control_id},
                    spec.edit_steps,
                )

    def test_fragment_flip_recipes_toggle_every_orientation_bit(self) -> None:
        baseline = self._load("fragment-puzzle-move-up").expected_before
        self.assertIsInstance(baseline, str)
        original = bytes.fromhex(baseline)
        for stem, mask in (
            ("fragment-puzzle-flip-horizontal", 0x40),
            ("fragment-puzzle-flip-vertical", 0x80),
        ):
            with self.subTest(stem=stem):
                requested = bytes.fromhex(str(self._load(stem).requested_value))
                self.assertEqual(requested, flip_fragment_script(original, mask))

    def test_icon_binding_double_click_recipe_stops_before_empty_save(self) -> None:
        path = DISCOVERY / "M05-icon-binding-double-click-discovery-cold-start-01.json"
        spec = CaseSpec.from_payload(json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(spec.module, "M05")
        self.assertEqual(spec.case_kind, "discovery")
        self.assertEqual(spec.expected_offsets, ())
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
                path = (
                    DISCOVERY
                    / f"M05-body-puzzle-template-{name}-discovery-cold-start-01.json"
                )
                spec = CaseSpec.from_payload(json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(spec.requested_value, "$capture_after")
                self.assertEqual(spec.capture_after_step, 1)
                self.assertEqual(spec.expected_offsets, ())
                self.assertEqual(spec.read_selector["control_id"], 270)
                self.assertEqual(
                    spec.edit_steps[0],
                    {"op": "click_id", "class": "Button", "control_id": button_id},
                )

    def test_body_bank_swap_recipe_captures_script_before_closing_dialog(self) -> None:
        spec = self._load("body-puzzle-swap-banks")
        self.assertEqual(spec.requested_value, "$capture_after")
        self.assertEqual(spec.capture_after_step, 1)
        self.assertEqual(spec.expected_offsets, ())
        self.assertEqual(spec.read_selector["control_id"], 270)
        self.assertEqual(
            spec.edit_steps[0],
            {"op": "click_id", "class": "Button", "control_id": 450},
        )


if __name__ == "__main__":
    unittest.main()
