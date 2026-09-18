from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dc_modifier.app import DEFAULT_ROM, MainWindow
from dc_modifier.legacy_unit_export import (
    LEGACY_UNIT_EXPORT_DIRECTORY,
    LEGACY_UNIT_EXPORT_SUFFIXES,
    LegacyUnitExportResult,
    export_legacy_unit_bitmaps,
    legacy_unit_export_bitmaps,
    legacy_unit_export_name,
)
from fc_rom_editor_core import RomProject
from tests.qt_test_case import QtTestCase


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = (
    ROOT
    / "output"
    / "verification"
    / "legacy-user-evidence-2026-09-14"
    / "legacy-unit-export-samples.zip"
)
SAMPLE_SHA256 = "230E55274B647D0E903C6B2753EE9BD54580F188FD8B3F0DC74F57F8FB0E2C39"


class LegacyUnitExportProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        QApplication.instance() or QApplication([])
        cls.project = RomProject.load(DEFAULT_ROM)
        cls.sample_payloads: dict[tuple[int, str], bytes] = {}
        cls.sample_directories: dict[int, str] = {}
        with zipfile.ZipFile(SAMPLES) as archive:
            for info in archive.infolist():
                if not info.filename.endswith(".bmp"):
                    continue
                parts = info.filename.split("/")
                unit_id = int(parts[1][:3])
                kind = parts[2].rsplit("[", 1)[1].removesuffix("].bmp")
                cls.sample_directories[unit_id] = parts[1]
                cls.sample_payloads[unit_id, kind] = archive.read(info)

    def test_all_1275_bmps_and_names_match_the_complete_reference_export(self) -> None:
        self.assertEqual(hashlib.sha256(SAMPLES.read_bytes()).hexdigest().upper(), SAMPLE_SHA256)
        self.assertEqual(len(self.sample_directories), 255)
        self.assertEqual(len(self.sample_payloads), 1_275)
        before = bytes(self.project.working)

        for unit_id in range(1, 256):
            name = legacy_unit_export_name(self.project, unit_id)
            self.assertEqual(
                self.sample_directories[unit_id],
                f"{unit_id:03d}：{name}",
            )
            generated = legacy_unit_export_bitmaps(self.project, unit_id)
            self.assertEqual(tuple(generated), LEGACY_UNIT_EXPORT_SUFFIXES)
            for kind, payload in generated.items():
                with self.subTest(unit_id=unit_id, kind=kind):
                    self.assertEqual(payload, self.sample_payloads[unit_id, kind])
                    width = 16 if kind.startswith("图标") else 128
                    self.assertEqual(struct.unpack_from("<2sI", payload), (b"BM", len(payload)))
                    self.assertEqual(struct.unpack_from("<I", payload, 10)[0], 54)
                    self.assertEqual(struct.unpack_from("<I", payload, 14)[0], 40)
                    self.assertEqual(struct.unpack_from("<ii", payload, 18), (width, width))
                    self.assertEqual(struct.unpack_from("<HH", payload, 26), (1, 24))

        self.assertEqual(legacy_unit_export_name(self.project, 246), "")
        self.assertEqual(bytes(self.project.working), before)

    def test_batch_export_continues_after_one_unit_failure(self) -> None:
        class ThreeUnitProject:
            unit_count = 4

        def bitmaps(_project, unit_id: int) -> dict[str, bytes]:
            if unit_id == 2:
                raise ValueError("故意失败")
            return {kind: f"{unit_id}:{kind}".encode("utf-8") for kind in LEGACY_UNIT_EXPORT_SUFFIXES}

        progress: list[tuple[int, int]] = []
        with tempfile.TemporaryDirectory() as directory, patch(
            "dc_modifier.legacy_unit_export.legacy_unit_export_name",
            side_effect=lambda _project, unit_id: f"机体{unit_id}",
        ), patch(
            "dc_modifier.legacy_unit_export.legacy_unit_export_bitmaps",
            side_effect=bitmaps,
        ):
            result = export_legacy_unit_bitmaps(
                ThreeUnitProject(),
                Path(directory),
                progress=lambda done, total: progress.append((done, total)),
            )

            self.assertEqual(result.root, Path(directory) / LEGACY_UNIT_EXPORT_DIRECTORY)
            self.assertEqual(len(result.written_files), 10)
            self.assertEqual(result.failures, ((2, "故意失败"),))
            self.assertEqual(progress, [(1, 3), (2, 3), (3, 3)])
            self.assertTrue((result.root / "001：机体1" / "机体1[效果].bmp").is_file())
            failed_directory = result.root / "002：机体2"
            self.assertTrue(failed_directory.is_dir())
            self.assertEqual(tuple(failed_directory.iterdir()), ())
            self.assertTrue((result.root / "003：机体3" / "机体3[图标2].bmp").is_file())

    def test_batch_writer_creates_all_255_directories_and_1275_paths(self) -> None:
        tiny_payloads = {kind: kind.encode("utf-8") for kind in LEGACY_UNIT_EXPORT_SUFFIXES}
        with tempfile.TemporaryDirectory() as directory, patch(
            "dc_modifier.legacy_unit_export.legacy_unit_export_bitmaps",
            return_value=tiny_payloads,
        ):
            result = export_legacy_unit_bitmaps(self.project, Path(directory))

            self.assertEqual(result.failures, ())
            self.assertEqual(len(result.written_files), 1_275)
            directories = tuple(path for path in result.root.iterdir() if path.is_dir())
            self.assertEqual(len(directories), 255)
            self.assertTrue((result.root / "001：盖塔" / "盖塔[效果].bmp").is_file())
            self.assertTrue((result.root / "246：" / "[图标2].bmp").is_file())


class LegacyUnitExportUiTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_data_menu_batch_export_uses_native_save_location_and_keeps_rom(self) -> None:
        window = MainWindow(open_default=True)
        self.addCleanup(window.close)
        assert window.project is not None
        before = bytes(window.project.working)

        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / LEGACY_UNIT_EXPORT_DIRECTORY
            result = LegacyUnitExportResult(
                marker,
                tuple(marker / f"{index}.bmp" for index in range(1_275)),
                (),
            )
            with patch(
                "dc_modifier.app.QFileDialog.getSaveFileName",
                return_value=(str(marker), "导出位置 (*)"),
            ) as save_dialog, patch(
                "dc_modifier.legacy_unit_export.export_legacy_unit_bitmaps",
                return_value=result,
            ) as export:
                window.export_unit()

            save_dialog.assert_called_once()
            export.assert_called_once()
            self.assertIs(export.call_args.args[0], window.project)
            self.assertEqual(export.call_args.args[1], Path(directory))
            self.assertIn("1275 个 BMP", window.status.currentMessage())
        self.assertEqual(bytes(window.project.working), before)

    def test_canceling_native_save_dialog_writes_nothing(self) -> None:
        window = MainWindow(open_default=True)
        self.addCleanup(window.close)
        assert window.project is not None
        before = bytes(window.project.working)
        with patch(
            "dc_modifier.app.QFileDialog.getSaveFileName",
            return_value=("", ""),
        ), patch(
            "dc_modifier.legacy_unit_export.export_legacy_unit_bitmaps",
        ) as export:
            window.export_unit()

        export.assert_not_called()
        self.assertEqual(bytes(window.project.working), before)

    def test_d2_keeps_reference_avatar_entry_disabled_and_extension_enabled(self) -> None:
        window = MainWindow(open_default=True)
        self.addCleanup(window.close)

        self.assertEqual(window.export_avatar_action.text(), "导出头像(&L)")
        self.assertEqual(window.export_avatar_action.shortcut().toString(), "Ctrl+L")
        self.assertFalse(window.export_avatar_action.isEnabled())
        self.assertIn("参考版此入口不可触发", window.export_avatar_action.statusTip())
        self.assertTrue(window.export_avatar_extended_action.isEnabled())
        self.assertEqual(window.export_avatar_extended_action.shortcut().toString(), "")
        self.assertIn(window.export_avatar_extended_action, window.extension_menu.actions())


if __name__ == "__main__":
    unittest.main(verbosity=2)
