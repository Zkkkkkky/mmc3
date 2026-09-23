from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dc_modifier.app import MainWindow
from dc_modifier.beginner_guide import BeginnerGuideDialog, GUIDE_TOPICS
from tests.qt_test_case import QtTestCase


class BeginnerGuideTests(QtTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_every_beginner_topic_has_plain_steps_and_a_route(self) -> None:
        self.assertGreaterEqual(len(GUIDE_TOPICS), 15)
        self.assertEqual(len({topic.title for topic in GUIDE_TOPICS}), len(GUIDE_TOPICS))
        for topic in GUIDE_TOPICS:
            self.assertTrue(topic.route, topic.title)
            self.assertGreaterEqual(len(topic.steps), 3, topic.title)
            self.assertTrue(topic.summary, topic.title)
            self.assertTrue(topic.result, topic.title)

    def test_guide_before_rom_only_opens_rom_and_save_editor(self) -> None:
        dialog = BeginnerGuideDialog(has_project=False)
        self.addCleanup(dialog.deleteLater)
        for row, topic in enumerate(GUIDE_TOPICS):
            dialog.topic_list.setCurrentRow(row)
            expected = topic.route in {"open_rom", "save"}
            self.assertEqual(dialog.open_button.isEnabled(), expected, topic.title)
            self.assertIn("统一规则", dialog.content.toPlainText())

    def test_guide_with_rom_can_emit_every_route(self) -> None:
        dialog = BeginnerGuideDialog(has_project=True)
        self.addCleanup(dialog.deleteLater)
        routes: list[str] = []
        dialog.route_requested.connect(routes.append)
        target = next(
            index for index, topic in enumerate(GUIDE_TOPICS)
            if topic.route == "database:2"
        )
        dialog.topic_list.setCurrentRow(target)
        dialog.open_button.click()
        self.assertEqual(routes, ["database:2"])

    def test_main_window_exposes_f1_and_routes_to_map_and_database_tab(self) -> None:
        window = MainWindow(open_default=True)
        self.addCleanup(window.close)
        self.assertEqual(window.beginner_guide_action.shortcut().toString(), "F1")
        self.assertEqual(window.beginner_guide_action.text(), "新手操作向导")

        window._open_beginner_route("maps")
        self.assertIs(window.workspace.currentWidget(), window.map_page)

        with patch.object(window, "_execute_database_dialog") as execute:
            window._open_beginner_route("database:2")
        dialog = execute.call_args.args[0]
        self.assertEqual(dialog.tabs.currentIndex(), 2)


if __name__ == "__main__":
    unittest.main()
