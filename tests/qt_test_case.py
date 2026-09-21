"""Deterministic Qt widget disposal for tests without QApplication.exec()."""

from __future__ import annotations

import unittest

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


class QtTestCase(unittest.TestCase):
    def doCleanups(self) -> bool:  # noqa: N802 - unittest API
        try:
            return super().doCleanups()
        finally:
            application = QApplication.instance()
            if application is not None:
                # close() can prompt for dirty drafts and does not imply
                # deletion. Dispose every test-owned top-level widget after
                # assertions and tearDown, when no widget signal is active.
                for widget in application.topLevelWidgets():
                    if widget.parent() is None:
                        widget.hide()
                        widget.deleteLater()
                # processEvents() alone does not drain DeferredDelete without
                # a running event loop. Do not leave stale Qt ownership graphs
                # to a later test's cyclic garbage collection.
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
