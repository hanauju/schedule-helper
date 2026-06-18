from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app import main as app_main


def test_application_icon_loads_orot_sizes() -> None:
    QApplication.instance() or QApplication([])

    icon = app_main._application_icon()

    assert not icon.isNull()
    assert {(size.width(), size.height()) for size in icon.availableSizes()} == {
        (16, 16),
        (32, 32),
        (48, 48),
        (64, 64),
        (128, 128),
        (256, 256),
    }


@pytest.mark.skipif(sys.platform != "win32", reason="Windows AppUserModelID is Windows-only")
def test_windows_app_user_model_id_is_explicit() -> None:
    app_main._set_windows_app_user_model_id()

    assert _current_app_user_model_id() == app_main.APP_USER_MODEL_ID


def _current_app_user_model_id() -> str:
    app_id = wintypes.LPWSTR()
    result = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(app_id))
    assert result == 0
    try:
        return app_id.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(app_id)
