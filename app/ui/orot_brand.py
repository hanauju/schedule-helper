from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

OROT_RING_COLOR = "#6fa8e0"
OROT_RING_SIZE = 22
OROT_RING_STROKE = 2.4

# Open ring: a 60-degree gap centered on the upper-right (45 deg in Qt angle
# space, where 0 deg is 3 o'clock and angles grow counter-clockwise). This is
# the "transparent top, rotated 45deg" mark from the OROT design direction.
_GAP_DEGREES = 60.0
_GAP_CENTER_DEGREES = 45.0


class OrotRingMark(QWidget):
    """Monochrome open-ring OROT brand mark.

    Paints a single antialiased ring stroke with a gap toward the upper-right.
    No fill and no animation - it is brand identity, not status.
    """

    def __init__(
        self,
        size: int = OROT_RING_SIZE,
        stroke: float = OROT_RING_STROKE,
        color: str = OROT_RING_COLOR,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._stroke = stroke
        self._color = QColor(color)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        event.accept()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self._color)
        pen.setWidthF(self._stroke)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        inset = self._stroke / 2.0 + 1.0
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        start_angle = _GAP_CENTER_DEGREES + _GAP_DEGREES / 2.0
        span_angle = 360.0 - _GAP_DEGREES
        painter.drawArc(rect, round(start_angle * 16), round(span_angle * 16))


def build_orot_brand(title_text: str) -> tuple[QWidget, QLabel, OrotRingMark]:
    """Build the OROT header lockup: open ring, Korean title, Latin wordmark.

    Returns the brand container, the Korean title label (so the caller keeps
    driving the title from ``preferences.app_title``), and the ring mark (so the
    caller can recolor it for the active theme).
    """
    container = QWidget()
    container.setObjectName("orotBrand")
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    mark = OrotRingMark()
    mark.setObjectName("orotMark")
    layout.addWidget(mark)

    title_label = QLabel(title_text)
    title_label.setObjectName("chromeTitle")
    title_label.setMinimumWidth(0)
    layout.addWidget(title_label)

    wordmark = QLabel("OROT")
    wordmark.setObjectName("orotWordmark")
    wordmark.setMinimumWidth(0)
    layout.addWidget(wordmark, 0, Qt.AlignmentFlag.AlignVCenter)

    return container, title_label, mark
