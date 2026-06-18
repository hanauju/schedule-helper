# OROT (오롯) Design System

This document is extracted from the existing PySide6 QSS in `app/ui/main_window.py`
(`_app_style`) and the OROT window-header brand direction. It reflects what the code
actually ships today, plus the OROT brand tokens added for the app header. Every color,
size, spacing, and radius below maps to a value already used in the stylesheet unless it
is explicitly marked `NEW (OROT)`.

Qt note: QSS is not CSS. There are no CSS variables, no `box-shadow`, and no transitions.
"Tokens" here are documented constants. When a value must respond to the user's accent
choice it is injected at runtime through `__PLACEHOLDER__` markers in the stylesheet
(for example `__ACTION_BUTTON_BG__`, `__MAIN_FONT_FAMILY__`).

## 1. Atmosphere & Identity

A calm, monochrome focus desk. Almost the entire surface is near-white cream; depth comes
from quiet 1px borders and faint tonal steps between panels, never from shadows. Color is
rationed: a sky-blue brand hue carries the OROT identity (ring + title), a single indigo
accent marks live/interactive state, and an optional user accent (green by default) fills the
one primary action. The signature is the OROT mark itself - a clean **open ring** in sky blue
(a circle with a small gap, rotated so the gap sits toward the upper-right) paired with the
Korean wordmark `오롯` and a quiet Latin `OROT`. The ring being open, not closed, is the
recognizable idea: focused but unfinished, room to fill.

## 2. Color

### Palette

| Role | Token | Value | Usage |
|------|-------|-------|-------|
| Surface/base | surface-base | `#fbfbfc` | App shell, body, workspace |
| Surface/sunken | surface-sunken | `#ececed` | Outer scroll viewport behind cards |
| Surface/card | surface-card | `#ffffff` | Cards, header focus card, timer card, header bar |
| Surface/muted | surface-muted | `#f4f4f6` | Soft control panels, nested metric cards |
| Surface/disabled | surface-disabled | `#e9e9ef` | Disabled button fills |
| Text/primary | text-primary | `#1b1b20` | Titles, primary labels |
| Text/secondary | text-secondary | `#5c5c66` | Button text, secondary labels |
| Text/tertiary | text-tertiary | `#9c9ca6` | Eyebrows, muted captions, OROT wordmark |
| Text/disabled | text-disabled | `#c3c3cc` | Disabled text |
| Border/default | border-default | `#e7e7ec` | Card outlines, control borders, neutral dots |
| Border/subtle | border-subtle | `#f0f0f3` | Header bottom divider, soft panel borders |
| Accent/ui | accent-ui | `#5a5ad6` | Live focus state, checked controls, status dot |
| Accent/ui-tint | accent-ui-tint | `rgba(90, 90, 214, 0.10)` | Hover/checked wash for accent controls |
| Accent/action | accent-action | `#4f8c6b` (default; user-set) | The one filled primary action |
| Brand/sky | brand-sky | `#6fa8e0` | OROT ring stroke + window title `오롯` (`chromeTitle`) |

### Rules

- Two accents, two jobs. `accent-ui` (indigo) is the fixed system accent for live state and
  selection; it is hard-coded in the stylesheet. `accent-action` is the user's color
  (`preferences.accent_color` / `button_color`, default `#4f8c6b`) injected via
  `__ACTION_BUTTON_*__`; it fills exactly one primary action per surface.
- Accent is for interactive or live state only, never decoration.
- Depth is tonal + bordered, never shadowed. Prefer a tonal step
  (`surface-base` -> `surface-muted` -> `surface-card`) plus a 1px border.
- Do not introduce a new hex. Extend this table first, then reference it.

## 3. Typography

### Scale

| Level | Size | Weight | Tracking | Usage |
|-------|------|--------|----------|-------|
| Focus time | 19px | 600 | 0 | Live timer readout (`headerFocusTime`) |
| Panel title | 15px | 650 | 0 | Feature panel headers (`panelTitleLabel`) |
| Title/body | 13px | 600 | 0 | Window title `오롯` (`chromeTitle`), default body |
| Caption | 12px | 600 | 0 | Buttons, status text, pin/segment controls |
| Overline | 10px | 600 | 1px | Eyebrow labels (`eyebrowLabel`) |
| Wordmark | 10px | 600 | 2px | Latin `OROT` lockup (`orotWordmark`) - NEW (OROT) |

### Font Stack

- Primary (UI/Korean): user `main_font_family` when set, else the Qt default; Korean must
  render cleanly (Malgun Gothic / Segoe UI on Windows). Injected as `__MAIN_FONT_FAMILY__`.
- Mono (eyebrow + Latin wordmark): `"IBM Plex Mono", "Consolas", "Pretendard", "Segoe UI", "Malgun Gothic", monospace`.

### Rules

- Two families max: the primary UI sans and the mono lockup family. The OROT Latin wordmark
  reuses the existing mono stack - it does not add a new font dependency.
- Body/title text never below 12px; 10px is reserved for tracked overline/wordmark labels.
- Korean UI strings (e.g. `오롯`) are intentional Unicode; all other source stays ASCII.

## 4. Spacing & Layout

### Scale (de facto, from the stylesheet/layouts)

| Token | Value | Usage |
|-------|-------|-------|
| space-1 | 4px | Tight control padding (button vertical) |
| space-2 | 7px | Dot gaps, checkbox spacing |
| space-2b | 8px | Action-button cluster gap - NEW (OROT), was 12px |
| space-3 | 10px | Brand lockup gap, card inner spacing |
| space-3b | 11px | Button horizontal padding |
| space-4 | 12px | Header inter-group spacing |
| space-4b | 13px | Header focus card horizontal padding |
| space-5 | 16px | Header bar left/right margin |

### Header bar (OROT)

The window is **frameless** (native OS title bar hidden); this 56px bar IS the title bar. - NEW (OROT)

- Height: **56px** - NEW (OROT), was 50px.
- Margins: `16, 0, 8, 0` (8px right so the window controls sit near the edge). Top-level group spacing: `12`.
- Left lockup (`orotBrand`): `[ring 22px] (10) [오롯] (8) [OROT]`, internal margins 0.
- Right action cluster: bordered menu buttons + pin, gap `8px`, then a `1px x 22px`
  `chromeDivider`, then the window controls (minimize / maximize-restore / close). - NEW (OROT)
- The empty bar/brand area is the drag surface (system move + OS snap); double-click toggles
  maximize. A 7px border around the whole window is the edge/corner resize handle. - NEW (OROT)

### Rules

- The de facto scale is not a strict 4px grid (7/11/13 exist). Honor the existing values
  when matching neighbors; do not invent new magic numbers.
- Action buttons live in the header row only. Never relocate them into dashboard content.

### Radii (from the stylesheet)

| Value | Usage |
|-------|-------|
| 5px | Window/status dots, small indicators |
| 8px | Window control hit areas (min/max/close) - NEW (OROT) |
| 9px | Header buttons, pin control, memo buttons |
| 11px | OROT ring mark widget radius - NEW (OROT) |
| 13px | Header focus card |
| 14px | Soft panels, metric cards |
| 18px | Focus dashboard / timer cards |

## 5. Components

### OROT brand lockup - NEW (OROT)

- **Structure**: horizontal `orotBrand` container -> `OrotRingMark#orotMark` +
  `QLabel#chromeTitle` (Korean title) + `QLabel#orotWordmark` (`OROT`).
- **Mark**: `OrotRingMark` (in `app/ui/orot_brand.py`) paints a sky-blue open ring -
  ~300 degrees of arc with the gap rotated toward the upper-right, stroke `brand-sky`,
  antialiased, no fill. ~22px box, ~2.4px stroke. Object name `orotMark`.
- **Title**: `chromeTitle` shows `preferences.app_title` (default `오롯`) in `brand-sky`; user
  custom titles (e.g. `안녕`) drive both this label and `windowTitle()`.
- **Wordmark**: static Latin `OROT`, mono stack, `text-tertiary`, 2px tracking.
- **States**: static brand; no hover. Title text updates on preference change.

### Header buttons

- **Bordered menu button** (`topBarButton`): `surface` fill, 1px `border-default`, radius 9px,
  12px text, min-height 26px, padding `4px 11px`. Used for `날짜별 보기`, `할 일 폴더`, `설정`,
  and `통합 위젯`.
- **Pin toggle** (`pinCheck`): bordered checkbox styled as a button; checked uses
  `accent-ui` text + `accent-ui-tint` fill + `accent-ui` border. Used for `항상 위`.
- **Filled accent button** (`topBarAccentButton`): action-accent fill via `__ACTION_BUTTON_BG__`,
  radius 9px, same compact metrics as the bordered button. Style remains defined for a filled
  primary action, but the default header carries no accent button. - NEW (OROT)

### Window chrome controls - NEW (OROT)

The main window is frameless, so the header supplies its own controls.

- **Divider** (`QFrame#chromeDivider`): a `1px x 22px` `border-default` rule that separates the
  action cluster from the window controls.
- **Controls** (`WindowControlButton`): three 34x34 buttons - `windowMinButton`, `windowMaxButton`,
  `windowCloseButton` - with an 8px-radius hit area, transparent fill, and a `surface-muted`
  (`#f4f4f6`) hover wash. The glyph (a minimize bar, a maximize square / restore double-square, or
  a close X) is painted as real vector shapes in a fixed chrome grey `#9a9a9e`, never a text glyph
  or emoji. They invoke `showMinimized`, `toggle_max_restore`, and `close`.
- **Maximize/restore**: `windowMaxButton` swaps its glyph between the single square (maximize) and
  the offset double square (restore) as the window state changes, kept in sync by `changeEvent`.
- **Edge resize** - NEW (OROT): with the native frame gone, a 7px (`WINDOW_RESIZE_MARGIN`) border
  around the window is the resize handle. A `MainWindow` event filter on the non-interactive chrome
  surfaces detects the edge/corner under the cursor, shows the matching resize cursor
  (`SizeHor` / `SizeVer` / `SizeFDiag` / `SizeBDiag`), and on left-press starts a native resize via
  `windowHandle().startSystemResize(edges)`. Interactive controls and a maximized window are never
  resize handles.

## 6. Motion & Interaction

Qt QSS has no transitions; interaction is expressed through pseudo-state rules
(`:hover`, `:checked`, `:pressed`, `:disabled`) and QTimer-driven updates.

| Type | Mechanism | Usage |
|------|-----------|-------|
| Hover/checked | QSS pseudo-states | Buttons, pin, checkboxes shift to accent-ui tint |
| Live timer | QTimer tick | `headerFocusTime` / status update once per tick |

### Rules

- Every interactive control defines hover, checked/pressed, and disabled appearances.
- The OROT mark is static (no spin/pulse); it is identity, not status.
- The header focus card is hidden until a focus session is live; do not animate its reveal.

## 7. Depth & Surface

Strategy: **borders + tonal-shift** (committed; no shadows anywhere).

| Type | Value | Usage |
|------|-------|-------|
| Border default | `1px solid #e7e7ec` | Cards, controls, header focus card, vertical `chromeDivider` |
| Border subtle | `1px solid #f0f0f3` | Header bottom divider, soft panel separation |
| Tonal step | `#fbfbfc` -> `#f4f4f6` -> `#ffffff` | Base -> muted panel -> elevated card |

### Rules

- No `box-shadow`. Separation is a border, a tonal step, or both.
- The header bar reads as `surface-card` (white) with a single `border-subtle` bottom divider.
- The window is frameless (`FramelessWindowHint`); native OS chrome is hidden and the OROT header
  bar is the only title bar, providing brand, actions, drag-to-move, and min/max/close. Window move
  and edge resize go through `startSystemMove()` / `startSystemResize()` so OS snap and Aero still
  work, with a manual `move()` fallback. - NEW (OROT)
