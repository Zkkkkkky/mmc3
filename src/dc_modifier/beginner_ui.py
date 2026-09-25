from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QToolButton, QVBoxLayout, QWidget


def task_hint(text: str) -> QLabel:
    """Return the single short instruction line used by ordinary editors."""

    label = QLabel(text)
    label.setObjectName("beginnerTask")
    label.setWordWrap(True)
    return label


def collapsible_details(
    content: QWidget,
    title: str = "高级诊断（通常不用）",
) -> QWidget:
    """Keep technical evidence reachable without occupying the editing view."""

    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)
    toggle = QToolButton()
    toggle.setObjectName("advancedDiagnosticsToggle")
    toggle.setText(title)
    toggle.setCheckable(True)
    toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    toggle.setArrowType(Qt.ArrowType.RightArrow)
    toggle.toggled.connect(content.setVisible)
    toggle.toggled.connect(
        lambda expanded: toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
    )
    layout.addWidget(toggle)
    layout.addWidget(content)
    content.hide()
    host.toggle = toggle
    host.content = content
    return host
