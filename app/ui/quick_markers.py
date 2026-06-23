"""Quick-switch marker icons - one source of truth, drawn with QPainter.

Six single-colour vector markers (점·별·하트·달·다이아·반짝). Every marker is
filled with one colour, so recolouring is just passing a different ``color``.
Corners are softened with a round-join pen (same trick as ``stroke-linejoin:
round`` in SVG) so the shapes read friendly rather than spiky.

Drop-in usage from a widget's ``paintEvent``::

    from app.ui.quick_markers import paint_marker
    paint_marker(painter, self.rect(), self._shape, self._color)
"""

from __future__ import annotations

import math
from typing import Final, Literal

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

Marker = Literal["dot", "star", "heart", "moon", "diamond", "sparkle"]

MARKERS: Final[tuple[Marker, ...]] = ("dot", "star", "heart", "moon", "diamond", "sparkle")
MARKER_LABELS: Final[dict[Marker, str]] = {
    "dot": "점",
    "star": "별",
    "heart": "하트",
    "moon": "달",
    "diamond": "다이아",
    "sparkle": "반짝",
}


def normalize_marker(shape: object) -> Marker:
    for marker in MARKERS:
        if shape == marker:
            return marker
    return "dot"


def _star_points(spikes: int, inner_ratio: float) -> list[tuple[float, float]]:
    """Unit star points (outer radius 1), first spike pointing up."""
    points: list[tuple[float, float]] = []
    for i in range(spikes * 2):
        angle = (i * (180.0 / spikes) - 90.0) * math.pi / 180.0
        radius = 1.0 if i % 2 == 0 else inner_ratio
        points.append((radius * math.cos(angle), radius * math.sin(angle)))
    return points


_STAR_PTS: Final = _star_points(5, 0.46)
_SPARKLE_PTS: Final = _star_points(4, 0.40)
_DIAMOND_PTS: Final = [(0.0, -1.0), (1.0, 0.0), (0.0, 1.0), (-1.0, 0.0)]


def _heart_path(rect: QRectF) -> QPainterPath:
    def p(ux: float, uy: float) -> QPointF:
        return QPointF(rect.left() + ux * rect.width(), rect.top() + uy * rect.height())

    path = QPainterPath()
    path.moveTo(p(0.50, 0.95))
    path.cubicTo(p(0.05, 0.62), p(0.05, 0.30), p(0.28, 0.18))
    path.cubicTo(p(0.40, 0.11), p(0.50, 0.20), p(0.50, 0.30))
    path.cubicTo(p(0.50, 0.20), p(0.60, 0.11), p(0.72, 0.18))
    path.cubicTo(p(0.95, 0.30), p(0.95, 0.62), p(0.50, 0.95))
    path.closeSubpath()
    return path


def _moon_path(cx: float, cy: float, r: float) -> QPainterPath:
    outer = QPainterPath()
    outer.addEllipse(QPointF(cx, cy), r, r)
    cut = QPainterPath()
    cut.addEllipse(QPointF(cx + r * 0.42, cy - r * 0.16), r * 0.92, r * 0.92)
    return outer.subtracted(cut)


def paint_marker(painter: QPainter, rect: QRect | QRectF, shape: object, color: object) -> None:
    """Paint one marker filling ``rect`` in ``color`` (hex str or QColor)."""
    box = QRectF(rect)
    c = color if isinstance(color, QColor) else QColor(str(color))
    cx = box.center().x()
    cy = box.center().y()
    r = min(box.width(), box.height()) / 2.0
    marker = normalize_marker(shape)

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    if marker == "dot":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c)
        painter.drawEllipse(QPointF(cx, cy), r * 0.62, r * 0.62)

    elif marker == "heart":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c)
        side = r * 1.78
        heart_box = QRectF(cx - side / 2.0, cy - side / 2.0, side, side)
        painter.drawPath(_heart_path(heart_box))

    elif marker == "moon":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(_moon_path(cx, cy, r * 0.92), c)

    else:  # star / sparkle / diamond - polygon with round joins
        pts = {"star": _STAR_PTS, "sparkle": _SPARKLE_PTS, "diamond": _DIAMOND_PTS}[marker]
        geom_r = r * 0.84
        polygon = QPolygonF([QPointF(cx + ux * geom_r, cy + uy * geom_r) for ux, uy in pts])
        pen = QPen(c)
        pen.setWidthF(r * 0.32)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(c)
        painter.drawPolygon(polygon)

    painter.restore()
