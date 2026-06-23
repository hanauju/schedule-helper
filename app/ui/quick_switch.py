from __future__ import annotations

from collections.abc import Callable
from typing import Final

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPaintEvent, QPainter, QPen
from PySide6.QtWidgets import QApplication, QPushButton, QSizePolicy, QWidget

from app.ui.quick_markers import (
    MARKER_LABELS as _QUICK_SHAPE_LABELS,
    MARKERS as _QUICK_SHAPES,
    Marker as QuickShape,
    normalize_marker as _normalize_shape,
    paint_marker,
)

MAX_QUICK_BUTTONS: Final[int] = 5

_QUICK_BUTTON_WIDTH = 17
_QUICK_BUTTON_HEIGHT = 17
_QUICK_BUTTON_RING_INSET = 0.75

# Each button is a round chip: a white circle (width == height, radius == half)
# holding the colored workspace marker. The border ring is drawn in paintEvent so
# the ACTIVE button can swap the neutral gray ring for one in its own workspace
# color - a clean, friendly "current" cue with no harsh black outline. The QSS
# below only paints the circular background + hover/pressed feedback (no border).
#
# The explicit min/max width+height and zero padding are REQUIRED: the app-wide
# `QPushButton { min-height: 28px; padding: ... }` rule otherwise cascades into
# this QPushButton subclass and inflates the height (a fixed 24x14 was rendering
# 24x38). Stating the exact box here overrides that cascade so the circle is true.
_QUICK_BUTTON_STYLE: Final[str] = f"""
QuickSwitchButton {{
    border: none;
    border-radius: {_QUICK_BUTTON_HEIGHT // 2}px;
    background: #ffffff;
    min-width: {_QUICK_BUTTON_WIDTH}px;
    max-width: {_QUICK_BUTTON_WIDTH}px;
    min-height: {_QUICK_BUTTON_HEIGHT}px;
    max-height: {_QUICK_BUTTON_HEIGHT}px;
    padding: 0px;
    margin: 0px;
}}
QuickSwitchButton:hover {{
    background: #f4f5f7;
}}
QuickSwitchButton:pressed {{
    background: #ececef;
}}
"""

_QUICK_RING_COLOR: Final[str] = "#e3e3e9"


def _normalize_color(color: object) -> str:
    if isinstance(color, str) and color:
        return color
    return "#68a8f5"


def _normalize_visible(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return True


def normalize_quick_config(raw: list[dict[str, object]]) -> list[dict[str, object]]:
    """Coerce repository-stored config entries into a normalized list (max 5)."""
    normalized: list[dict[str, object]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        workspace_id = entry.get("workspace_id")
        if not isinstance(workspace_id, int):
            continue
        normalized.append(
            {
                "workspace_id": workspace_id,
                "shape": _normalize_shape(entry.get("shape")),
                "color": _normalize_color(entry.get("color")),
                "visible": _normalize_visible(entry.get("visible")),
            }
        )
        if len(normalized) >= MAX_QUICK_BUTTONS:
            break
    return normalized


class QuickSwitchButton(QPushButton):
    """Title-bar push button that switches to a workspace on click.

    Renders as a round white chip with the colored workspace marker centered on
    top. The active button's border ring is drawn in its own workspace color;
    inactive buttons get a neutral gray ring. Click fires the workspace switch;
    a mouse-move past the drag threshold instead fires the reorder callback with
    the source index and the drop target index computed from the cursor.
    """

    def __init__(
        self,
        workspace_id: int,
        shape: QuickShape,
        color: str,
        index: int,
        on_click: Callable[[int], None],
        on_reorder: Callable[[int, int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.workspace_id = workspace_id
        self._shape = shape
        self._color = color
        self._index = index
        self._active = False
        self._on_click = on_click
        self._on_reorder = on_reorder
        self._drag_start: QPoint | None = None
        self._dragging = False
        self.setObjectName("QuickSwitchButton")
        self.setFixedSize(QSize(_QUICK_BUTTON_WIDTH, _QUICK_BUTTON_HEIGHT))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("")
        self.setStyleSheet(_QUICK_BUTTON_STYLE)
        self.clicked.connect(self._handle_clicked)

    def _handle_clicked(self) -> None:
        self._on_click(self.workspace_id)

    @property
    def index(self) -> int:
        return self._index

    @index.setter
    def index(self, value: int) -> None:
        self._index = value

    @property
    def shape(self) -> QuickShape:
        return self._shape

    @property
    def color(self) -> str:
        return self._color

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def set_tooltip(self, name: str) -> None:
        self.setToolTip(name)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_start is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.globalPosition().toPoint() - self._drag_start).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_start is not None and event.button() == Qt.MouseButton.LeftButton:
            was_dragging = self._dragging
            self._dragging = False
            self._drag_start = None
            self.unsetCursor()
            self.setDown(False)
            target = self._target_index(event.globalPosition().toPoint())
            if was_dragging and target != self._index:
                self._on_reorder(self._index, target)
            else:
                # A plain click - or a tiny jitter that never left this slot -
                # switches workspaces. Handling it here (instead of leaning on the
                # clicked signal) keeps a single click reliable on the small chip
                # rather than getting swallowed as a no-op reorder.
                self._on_click(self.workspace_id)
            event.accept()
            return
        self._drag_start = None
        self.unsetCursor()
        super().mouseReleaseEvent(event)

    def _target_index(self, global_pos: QPoint) -> int:
        row = self.parent()
        if row is None:
            return self._index
        local = row.mapFromGlobal(global_pos)
        if local.x() < self.x() + self.width() // 2:
            return self._index
        return min(self._index + 1, MAX_QUICK_BUTTONS - 1)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)  # circular background + hover/pressed feedback
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        ring_rect = QRectF(self.rect()).adjusted(
            _QUICK_BUTTON_RING_INSET,
            _QUICK_BUTTON_RING_INSET,
            -_QUICK_BUTTON_RING_INSET,
            -_QUICK_BUTTON_RING_INSET,
        )
        if self._active:
            pen = QPen(QColor(self._color))
            pen.setWidthF(2.0)
        else:
            pen = QPen(QColor(_QUICK_RING_COLOR))
            pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(ring_rect)

        icon_side = min(self.width(), self.height()) - _QUICK_BUTTON_RING_INSET * 2 - 2
        icon_size = QSize(int(icon_side), int(icon_side))
        icon_top = (self.height() - icon_size.height()) // 2
        icon_left = (self.width() - icon_size.width()) // 2
        icon_rect = QRectF(icon_left, icon_top, icon_size.width(), icon_size.height())
        paint_marker(painter, icon_rect, self._shape, self._color)
