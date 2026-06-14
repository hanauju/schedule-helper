from __future__ import annotations

from app.models import Preference
from app.ui.main_window import (
    _action_button_theme_palette,
    _button_theme_palette,
    _color_luminance,
    _resolved_theme_palette,
)


def test_background_color_drives_unset_surfaces() -> None:
    palette = _resolved_theme_palette(Preference(background_color="#224433"))

    assert palette["bg"] == "#224433"
    assert palette["app"] != "#fbfcfb"
    assert palette["surface"] != "#ffffff"
    assert palette["surface_2"] != "#f3f6f4"
    assert palette["table"] == palette["surface"]
    assert palette["text"] == "#18201b"


def test_specific_surface_colors_override_global_background() -> None:
    palette = _resolved_theme_palette(
        Preference(
            background_color="#224433",
            panel_color="#f6e6c8",
            table_color="#d9e7f5",
            text_color="#111315",
        )
    )

    assert palette["bg"] == "#224433"
    assert palette["surface"] == "#f6e6c8"
    assert palette["table"] == "#d9e7f5"
    assert palette["text"] == "#111315"


def test_button_palette_keeps_buttons_tinted_on_light_surfaces() -> None:
    palette = _resolved_theme_palette(Preference(panel_color="#ffffff"))
    button_palette = _button_theme_palette("#4f8c6b", palette)

    assert button_palette["bg"] != "#ffffff"
    assert button_palette["bg"] != palette["surface"]
    assert button_palette["text"] == "#18201b"


def test_button_palette_uses_button_color_independently_from_accent() -> None:
    palette = _resolved_theme_palette(Preference(accent_color="#d95050", button_color="#4f8c6b"))
    accent_based_button = _button_theme_palette("#d95050", palette)
    configured_button = _button_theme_palette("#4f8c6b", palette)

    assert configured_button["bg"] != accent_based_button["bg"]


def test_light_theme_rejects_too_light_text_colors() -> None:
    palette = _resolved_theme_palette(Preference(text_color="#f8f9fa"))

    assert palette["text"] == "#18201b"
    assert _color_luminance(palette["muted"]) <= 150
    assert _color_luminance(palette["secondary"]) <= 164


def test_dark_theme_allows_light_text_colors() -> None:
    palette = _resolved_theme_palette(Preference(appearance_theme="dark", text_color="#f8f9fa"))

    assert palette["text"] == "#f8f9fa"


def test_action_buttons_use_dark_text_outside_dark_theme() -> None:
    light_button = _action_button_theme_palette("#4f8c6b", "#6da884", False)
    dark_button = _action_button_theme_palette("#4f8c6b", "#6da884", True)

    assert light_button["text"] == "#18201b"
    assert dark_button["text"] == "#ffffff"
