from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.storage.database import ScheduleRepository, default_database_path
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Schedule Helper")
    repository = ScheduleRepository(default_database_path())
    window = MainWindow(repository)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
