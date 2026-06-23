from __future__ import annotations

from typing import Final

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.models import LayoutProfile
from app.storage.database import ScheduleRepository
from app.ui.quick_markers import paint_marker
from app.ui.quick_switch import (
    MAX_QUICK_BUTTONS,
    QuickShape,
    _QUICK_SHAPE_LABELS,
    _QUICK_SHAPES,
    _normalize_shape,
    normalize_quick_config,
)

_DEFAULT_COLOR: Final[str] = "#68a8f5"

# Curated palette shown in the colour popover. A small, harmonious set reads far
# better than a raw OS colour wheel — a custom entry stays available below it.
_PRESET_COLORS: Final[tuple[tuple[str, str], ...]] = (
    ("블루", "#68a8f5"),
    ("인디고", "#5a5ad6"),
    ("그린", "#4f8c6b"),
    ("라벤더", "#8f8fd6"),
    ("코랄", "#d98b6b"),
    ("잉크", "#16181d"),
)

_DIALOG_STYLE: Final[str] = """
QDialog { background: #fbfbfc; }
QLabel { color: #1b1b20; }
QLabel#dialogHint { color: #6f6c74; font-size: 13px; }
QLabel#columnCaption { color: #b0b0ba; font-size: 11px; font-weight: 600; }
QLabel#slotLabel { color: #9c9ca6; font-size: 11px; font-weight: 600; }
QLabel#previewCaption { color: #9c9ca6; font-size: 11px; }

QFrame#configRow { background: #ffffff; border: 1px solid #e7e7ec; border-radius: 12px; }
QFrame#configRow[empty="true"] { background: #fafafb; border: 1px solid #eeeef1; }
QFrame#previewTrack { background: #f1f1f4; border-radius: 17px; }

QComboBox {
    background: #ffffff; border: 1px solid #e3e3e9; border-radius: 9px;
    padding: 0 10px; min-height: 34px; color: #1b1b20; font-size: 14px;
}
QComboBox:hover { border-color: #cfd0d8; }
QComboBox:focus { border-color: #68a8f5; }
QComboBox::drop-down { width: 22px; border: none; }
QComboBox QAbstractItemView {
    background: #ffffff; border: 1px solid #e7e7ec; border-radius: 8px;
    selection-background-color: #eef4fb; selection-color: #1b1b20; outline: none; padding: 4px;
}

QPushButton#colorSwatch { border-radius: 14px; }

QMenu { background: #ffffff; border: 1px solid #e7e7ec; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 14px 7px 10px; border-radius: 6px; color: #1b1b20; font-size: 13px; }
QMenu::item:selected { background: #f1f1f4; }

QDialogButtonBox QPushButton {
    min-height: 38px; min-width: 84px; border-radius: 10px; font-size: 14px; padding: 0 16px;
}
QPushButton#dlgCancel { background: #ffffff; border: 1px solid #e3e3e9; color: #5c5c66; font-weight: 500; }
QPushButton#dlgCancel:hover { background: #f4f4f6; }
QPushButton#dlgSave { background: #68a8f5; border: 1px solid #68a8f5; color: #ffffff; font-weight: 600; }
QPushButton#dlgSave:hover { background: #5b9cea; }
"""


class _ShapeSwatch(QWidget):
    """Small preview chip: a soft tinted disc with the workspace glyph on top."""

    def __init__(self, size: int = 30, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self._shape: QuickShape = "dot"
        self._color = _DEFAULT_COLOR
        self._empty = False
        self.setFixedSize(size, size)

    def configure(self, shape: QuickShape, color: str, empty: bool) -> None:
        self._shape = shape
        self._color = color
        self._empty = empty
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = self.rect()
        if self._empty:
            painter.setBrush(QColor("#f0f0f3"))
            painter.drawEllipse(rect)
            painter.setBrush(QColor("#d2d2da"))
            painter.drawEllipse(rect.adjusted(int(self._size * 0.36), int(self._size * 0.36),
                                              -int(self._size * 0.36), -int(self._size * 0.36)))
            return
        tint = QColor(self._color)
        tint.setAlpha(36)
        painter.setBrush(tint)
        painter.drawEllipse(rect)
        inset = int(self._size * 0.27)
        paint_marker(painter, rect.adjusted(inset, inset, -inset, -inset), self._shape, self._color)


class _ToggleSwitch(QPushButton):
    """iOS-style on/off switch. Checkable; keeps isChecked()/setChecked() API."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(40, 23))
        self.setStyleSheet("border: none; background: transparent;")

    def sizeHint(self) -> QSize:
        return QSize(40, 23)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        on = self.isChecked() and self.isEnabled()
        track = QColor("#68a8f5") if on else QColor("#e3e3e9")
        if not self.isEnabled():
            track = QColor("#ececef")
        painter.setBrush(track)
        painter.drawRoundedRect(self.rect(), 11.5, 11.5)
        painter.setBrush(QColor("#ffffff"))
        d = 18
        x = self.width() - d - 2.5 if on else 2.5
        painter.drawEllipse(QRectF(x, 2.5, d, d))


def _color_icon(color: str, size: int = 18) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return QIcon(pix)


class QuickSwitchConfigDialog(QDialog):
    """Pick up to 5 workspaces and set shape/color/visibility per slot."""

    def __init__(
        self,
        repository: ScheduleRepository,
        current_config: list[dict[str, object]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self._initial = normalize_quick_config(current_config)
        self.setWindowTitle("빠른 전환 버튼 설정")
        self.setMinimumSize(QSize(520, 560))
        self.setStyleSheet(_DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        hint = QLabel("최대 5개 작업공간을 골라 모양·색·표시를 설정하세요. 표시된 슬롯만 타이틀바에 나타납니다.")
        hint.setObjectName("dialogHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # ----- live preview -----
        preview = QFrame()
        preview.setObjectName("previewTrack")
        preview.setFixedHeight(34)
        self._preview_layout = QHBoxLayout(preview)
        self._preview_layout.setContentsMargins(4, 4, 4, 4)
        self._preview_layout.setSpacing(3)
        self._preview_caption = QLabel("표시할 슬롯이 없습니다")
        self._preview_caption.setObjectName("previewCaption")
        preview_wrap = QHBoxLayout()
        preview_wrap.setContentsMargins(0, 0, 0, 0)
        preview_wrap.setSpacing(10)
        preview_wrap.addWidget(preview, 0, Qt.AlignmentFlag.AlignLeft)
        preview_wrap.addWidget(self._preview_caption, 0, Qt.AlignmentFlag.AlignVCenter)
        preview_wrap.addStretch(1)
        layout.addLayout(preview_wrap)

        # ----- column captions -----
        captions = QHBoxLayout()
        captions.setContentsMargins(10, 2, 10, 0)
        captions.setSpacing(10)
        captions.addSpacing(30 + 40 + 20)
        ws_cap = QLabel("작업공간")
        ws_cap.setObjectName("columnCaption")
        captions.addWidget(ws_cap, 1)
        shape_cap = QLabel("모양")
        shape_cap.setObjectName("columnCaption")
        shape_cap.setFixedWidth(96)
        captions.addWidget(shape_cap, 0)
        color_cap = QLabel("색")
        color_cap.setObjectName("columnCaption")
        color_cap.setFixedWidth(32)
        color_cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        captions.addWidget(color_cap, 0)
        show_cap = QLabel("표시")
        show_cap.setObjectName("columnCaption")
        show_cap.setFixedWidth(44)
        show_cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        captions.addWidget(show_cap, 0)
        layout.addLayout(captions)

        # ----- rows -----
        self._rows: list[_ConfigRow] = []
        rows_box = QVBoxLayout()
        rows_box.setContentsMargins(0, 0, 0, 0)
        rows_box.setSpacing(7)
        layout.addLayout(rows_box)
        profiles = repository.list_user_workspace_profiles()
        for slot in range(MAX_QUICK_BUTTONS):
            row = self._build_row(slot, profiles)
            self._rows.append(row)
            rows_box.addWidget(row.container)

        layout.addStretch(1)

        # ----- footer -----
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setObjectName("dlgSave")
        save_btn.setText("저장")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setObjectName("dlgCancel")
        cancel_btn.setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_preview()

    def _build_row(self, slot: int, profiles: list[LayoutProfile]) -> _ConfigRow:
        container = QFrame()
        container.setObjectName("configRow")
        row_layout = QHBoxLayout(container)
        row_layout.setContentsMargins(10, 8, 10, 8)
        row_layout.setSpacing(10)

        swatch = _ShapeSwatch(30)
        slot_label = QLabel(f"슬롯 {slot + 1}")
        slot_label.setObjectName("slotLabel")
        slot_label.setFixedWidth(40)

        workspace_combo = QComboBox()
        workspace_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        workspace_combo.addItem("(없음)", None)
        for profile in profiles:
            if profile.id is None:
                continue
            workspace_combo.addItem(profile.name, int(profile.id))

        shape_combo = QComboBox()
        shape_combo.setFixedWidth(96)
        for shape in _QUICK_SHAPES:
            shape_combo.addItem(_QUICK_SHAPE_LABELS[shape], shape)

        color_button = QPushButton()
        color_button.setObjectName("colorSwatch")
        color_button.setFixedSize(28, 28)
        color_button.setCursor(Qt.CursorShape.PointingHandCursor)

        visible_check = _ToggleSwitch()

        entry = self._initial[slot] if slot < len(self._initial) else None
        selected_id: int | None = None
        shape_value: QuickShape = "dot"
        color_value = _DEFAULT_COLOR
        visible_value = True
        if entry is not None:
            raw_id = entry.get("workspace_id")
            if isinstance(raw_id, int):
                selected_id = raw_id
            raw_shape = entry.get("shape")
            if raw_shape == "dot" or raw_shape == "heart" or raw_shape == "star":
                shape_value = raw_shape
            raw_color = entry.get("color")
            if isinstance(raw_color, str) and raw_color:
                color_value = raw_color
            raw_visible = entry.get("visible")
            if isinstance(raw_visible, bool):
                visible_value = raw_visible

        if selected_id is not None:
            for i in range(workspace_combo.count()):
                if workspace_combo.itemData(i) == selected_id:
                    workspace_combo.setCurrentIndex(i)
                    break
        for i in range(shape_combo.count()):
            if shape_combo.itemData(i) == shape_value:
                shape_combo.setCurrentIndex(i)
                break
        visible_check.setChecked(visible_value)

        row = _ConfigRow(container, workspace_combo, shape_combo, color_button, visible_check, color_value)
        row.swatch = swatch

        def apply_swatch_style() -> None:
            color_button.setStyleSheet(
                f"#colorSwatch {{ background: {row.color}; border-radius: 14px;"
                f" border: 1px solid rgba(0,0,0,0.12); }}"
            )

        def refresh_row() -> None:
            empty = workspace_combo.currentData() is None
            container.setProperty("empty", "true" if empty else "false")
            container.style().unpolish(container)
            container.style().polish(container)
            shape: QuickShape = _normalize_shape(shape_combo.currentData())
            swatch.configure(shape, row.color, empty)
            self._update_preview()

        def open_palette() -> None:
            menu = QMenu(self)
            menu.setStyleSheet(_DIALOG_STYLE)
            for name, hex_color in _PRESET_COLORS:
                act = menu.addAction(_color_icon(hex_color), name)
                act.triggered.connect(lambda _checked=False, c=hex_color: set_color(c))
            menu.addSeparator()
            custom = menu.addAction("사용자 지정…")
            custom.triggered.connect(pick_custom_color)
            menu.exec(color_button.mapToGlobal(color_button.rect().bottomLeft()))

        def set_color(hex_color: str) -> None:
            row.color = hex_color
            apply_swatch_style()
            refresh_row()

        def pick_custom_color(_checked: bool = False) -> None:
            chosen = QColorDialog.getColor(QColor(row.color), self, "색상 선택")
            if chosen.isValid():
                set_color(chosen.name())

        apply_swatch_style()
        color_button.clicked.connect(open_palette)
        workspace_combo.currentIndexChanged.connect(lambda _i: refresh_row())
        shape_combo.currentIndexChanged.connect(lambda _i: refresh_row())
        visible_check.toggled.connect(lambda _v: self._update_preview())

        row_layout.addWidget(swatch)
        row_layout.addWidget(slot_label)
        row_layout.addWidget(workspace_combo, 1)
        row_layout.addWidget(shape_combo)
        row_layout.addWidget(color_button)
        row_layout.addWidget(visible_check)

        refresh_row()
        return row

    def _update_preview(self) -> None:
        while self._preview_layout.count():
            item = self._preview_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        shown = 0
        for row in self._rows:
            if row.workspace_combo.currentData() is None or not row.visible_check.isChecked():
                continue
            chip = _ShapeSwatch(26, self)
            chip.configure(_normalize_shape(row.shape_combo.currentData()), row.color, False)
            self._preview_layout.addWidget(chip)
            shown += 1
        self._preview_caption.setText("표시된 슬롯" if shown else "표시할 슬롯이 없습니다")

    def config(self) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for row in self._rows:
            workspace_id = row.workspace_combo.currentData()
            if not isinstance(workspace_id, int):
                continue
            shape: QuickShape = _normalize_shape(row.shape_combo.currentData())
            color = row.color or _DEFAULT_COLOR
            visible = row.visible_check.isChecked()
            result.append(
                {
                    "workspace_id": workspace_id,
                    "shape": shape,
                    "color": color,
                    "visible": visible,
                }
            )
            if len(result) >= MAX_QUICK_BUTTONS:
                break
        return result


class _ConfigRow:
    """Typed holder for a single config slot's widgets."""

    __slots__ = (
        "container",
        "workspace_combo",
        "shape_combo",
        "color_button",
        "visible_check",
        "color",
        "swatch",
    )

    def __init__(
        self,
        container: QWidget,
        workspace_combo: QComboBox,
        shape_combo: QComboBox,
        color_button: QPushButton,
        visible_check: QPushButton,
        color: str,
    ) -> None:
        self.container = container
        self.workspace_combo = workspace_combo
        self.shape_combo = shape_combo
        self.color_button = color_button
        self.visible_check = visible_check
        self.color = color
        self.swatch: _ShapeSwatch | None = None
