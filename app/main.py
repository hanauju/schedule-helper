from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.storage.database import ScheduleRepository, default_database_path
from app.ui.main_window import MainWindow


APP_USER_MODEL_ID: Final = "Orot.ScheduleHelper.Desktop"


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return

    import ctypes

    result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    if result != 0:
        raise OSError(result, "SetCurrentProcessExplicitAppUserModelID failed")


def _application_icon() -> QIcon:
    icon_path = Path(__file__).resolve().parent / "assets" / "orot.ico"
    return QIcon(str(icon_path))


def main() -> int:
    _set_windows_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName("Schedule Helper")
    icon = _application_icon()
    app.setWindowIcon(icon)
    repository = ScheduleRepository(default_database_path())
    window = MainWindow(repository)
    window.setWindowIcon(icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
