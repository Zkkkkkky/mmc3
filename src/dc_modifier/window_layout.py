"""Keep legacy forms reachable on small screens and high-DPI desktops."""
from PySide6.QtWidgets import QDialog, QScrollArea, QVBoxLayout, QWidget


def fit_dialog_to_screen(dialog: QDialog) -> None:
    available = dialog.screen().availableGeometry()
    width_limit = max(240, available.width() - 40)
    height_limit = max(200, available.height() - 60)
    oversized_minimum = dialog.minimumWidth() > width_limit or dialog.minimumHeight() > height_limit
    if (dialog.minimumSize() == dialog.maximumSize() or oversized_minimum) and dialog.layout() is not None:
        # Older reference-shaped tools have large fixed forms. Preserve their
        # controls but provide scrolling instead of inaccessible offscreen UI.
        content = QWidget()
        content.setLayout(dialog.layout())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(scroll)
        dialog.setMinimumSize(min(640, width_limit), min(480, height_limit))
        dialog.setMaximumSize(16777215, 16777215)
    dialog.setSizeGripEnabled(True)
    dialog.resize(min(dialog.width(), width_limit), min(dialog.height(), height_limit))
