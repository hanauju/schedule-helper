from __future__ import annotations

from typing import Final, Literal, assert_never

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QPaintEvent, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.storage.database import ScheduleRepository

SortDirection = Literal["asc", "desc"]

_ASC_BAR_WIDTHS: Final[tuple[int, ...]] = (4, 8, 12, 16)
_DESC_BAR_WIDTHS: Final[tuple[int, ...]] = (16, 12, 8, 4)
_BADGE_STYLE: Final[str] = """
QLabel#tagBadge, QLabel#pinBadge {
    color: #111315;
    background-color: #fafafa;
    border: 1px solid #e7e7ec;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 12px;
    font-weight: 600;
}
"""
_SORT_BUTTON_STYLE: Final[str] = """
QPushButton#sortDirectionButton {
    background-color: #fafafa;
    border: 1px solid #e7e7ec;
    border-radius: 9px;
    padding: 4px;
}
QPushButton#sortDirectionButton:hover {
    background-color: #f4f4f6;
}
"""


class InvalidSortDirectionError(ValueError):
    def __init__(self, direction: str) -> None:
        self.direction = direction
        super().__init__(f"Unsupported sort direction: {direction}")


def _normalize_direction(direction: str) -> SortDirection:
    match direction:
        case "asc":
            return "asc"
        case "desc":
            return "desc"
        case _:
            raise InvalidSortDirectionError(direction)


def _direction_label(direction: SortDirection) -> str:
    match direction:
        case "asc":
            return "오름차순 정렬"
        case "desc":
            return "내림차순 정렬"
        case unreachable:
            assert_never(unreachable)


class SortDirectionButton(QPushButton):
    def __init__(self, direction: SortDirection = "desc", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._direction = _normalize_direction(direction)
        self.setObjectName("sortDirectionButton")
        self.setText("")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(QSize(34, 30))
        self.setStyleSheet(_SORT_BUTTON_STYLE)
        self._refresh_accessible_text()

    @property
    def direction(self) -> SortDirection:
        return self._direction

    @direction.setter
    def direction(self, value: str) -> None:
        self._direction = _normalize_direction(value)
        self._refresh_accessible_text()
        self.update()

    def bar_widths(self) -> tuple[int, ...]:
        match self._direction:
            case "asc":
                return _ASC_BAR_WIDTHS
            case "desc":
                return _DESC_BAR_WIDTHS
            case unreachable:
                assert_never(unreachable)

    def _refresh_accessible_text(self) -> None:
        label = _direction_label(self._direction)
        self.setAccessibleName(label)
        self.setToolTip(label)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self.palette().color(QPalette.ColorRole.ButtonText), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        widths = self.bar_widths()
        max_width = max(widths)
        spacing = 5
        top = self.rect().center().y() - ((len(widths) - 1) * spacing // 2)
        left = self.rect().center().x() - (max_width // 2)
        for index, width in enumerate(widths):
            y = top + (index * spacing)
            painter.drawLine(QPoint(left, y), QPoint(left + width, y))


class TagBadge(QLabel):
    def __init__(self, tag_name: str, parent: QWidget | None = None) -> None:
        super().__init__(tag_name, parent)
        self.setObjectName("tagBadge")
        self.setStyleSheet(_BADGE_STYLE)


class PinBadge(QLabel):
    def __init__(self, text: str = "PIN", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("pinBadge")
        self.setStyleSheet(_BADGE_STYLE)


class TagAssignmentDialog(QDialog):
    def __init__(
        self,
        repository: ScheduleRepository,
        target_type: str,
        target_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.target_type = target_type
        self.target_id = target_id
        self.setObjectName("tagAssignmentDialog")
        self.setWindowTitle("태그 관리")
        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(420, 440))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        heading = QLabel("태그")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        create_row = QHBoxLayout()
        self.new_tag_edit = QLineEdit()
        self.new_tag_edit.setObjectName("tagAssignmentInput")
        self.new_tag_edit.setPlaceholderText("새 태그 이름")
        self.new_tag_edit.returnPressed.connect(self.create_tag)
        create_button = QPushButton("추가")
        create_button.setObjectName("primaryButton")
        create_button.clicked.connect(self.create_tag)
        create_row.addWidget(self.new_tag_edit, 1)
        create_row.addWidget(create_button)
        layout.addLayout(create_row)

        self.tag_list = QListWidget()
        self.tag_list.setObjectName("tagAssignmentList")
        self.tag_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tag_list.itemDoubleClicked.connect(lambda _item: self.rename_selected_tag())
        layout.addWidget(self.tag_list, 1)

        action_row = QHBoxLayout()
        rename_button = QPushButton("이름 변경")
        rename_button.setObjectName("ghostButton")
        rename_button.clicked.connect(self.rename_selected_tag)
        delete_button = QPushButton("삭제")
        delete_button.setObjectName("ghostButton")
        delete_button.clicked.connect(self.delete_selected_tag)
        action_row.addWidget(rename_button)
        action_row.addWidget(delete_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.setObjectName("tagAssignmentButtons")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.refresh_tags()

    def refresh_tags(self, selected_tag_id: int | None = None) -> None:
        assigned_ids = {tag.id for tag in self.repository.list_tags_for_target(self.target_type, self.target_id)}
        self.tag_list.clear()
        selected_row = 0
        for row, tag in enumerate(self.repository.list_tags()):
            if tag.id is None:
                continue
            item = QListWidgetItem(tag.name)
            item.setData(Qt.ItemDataRole.UserRole, tag.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            state = Qt.CheckState.Checked if tag.id in assigned_ids else Qt.CheckState.Unchecked
            item.setCheckState(state)
            self.tag_list.addItem(item)
            if selected_tag_id == tag.id:
                selected_row = row
        if self.tag_list.count() > 0:
            self.tag_list.setCurrentRow(selected_row)

    def checked_tag_ids(self) -> list[int]:
        tag_ids: list[int] = []
        for row in range(self.tag_list.count()):
            item = self.tag_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                tag_ids.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return tag_ids

    def current_tag_id(self) -> int | None:
        item = self.tag_list.currentItem()
        if item is None:
            return None
        return int(item.data(Qt.ItemDataRole.UserRole))

    def create_tag(self) -> None:
        name = self.new_tag_edit.text().strip()
        if not name:
            QMessageBox.information(self, "태그 추가", "태그 이름을 입력하세요.")
            return
        try:
            tag = self.repository.create_tag(name)
        except ValueError as error:
            QMessageBox.warning(self, "태그 추가", str(error))
            return
        self.new_tag_edit.clear()
        self.refresh_tags(tag.id)

    def rename_selected_tag(self) -> None:
        tag_id = self.current_tag_id()
        current_item = self.tag_list.currentItem()
        if tag_id is None or current_item is None:
            QMessageBox.information(self, "태그 이름 변경", "이름을 바꿀 태그를 선택하세요.")
            return
        name, accepted = QInputDialog.getText(self, "태그 이름 변경", "새 태그 이름", text=current_item.text())
        if not accepted:
            return
        try:
            renamed = self.repository.rename_tag(tag_id, name)
        except ValueError as error:
            QMessageBox.warning(self, "태그 이름 변경", str(error))
            return
        self.refresh_tags(renamed.id if renamed is not None else None)

    def delete_selected_tag(self) -> None:
        tag_id = self.current_tag_id()
        current_item = self.tag_list.currentItem()
        if tag_id is None or current_item is None:
            QMessageBox.information(self, "태그 삭제", "삭제할 태그를 선택하세요.")
            return
        answer = QMessageBox.question(
            self,
            "태그 삭제",
            f"'{current_item.text()}' 태그를 삭제할까요? 메모, 할 일, 일정은 삭제되지 않고 태그 연결만 해제됩니다.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.repository.delete_tag(tag_id)
        self.refresh_tags()

    def accept(self) -> None:
        self.repository.set_tags_for_target(self.target_type, self.target_id, self.checked_tag_ids())
        super().accept()
