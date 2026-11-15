"""Single source of truth for the Synclayer look.

A calm, flat, neutral design (think Google Drive / OneDrive): white or graphite surfaces, one blue accent,
no glow, no gradients. The web UI receives these tokens as CSS variables (served at /static/theme.css, light and
dark, following the system setting) and the desktop app builds its Qt stylesheet from the same values.
"""
from __future__ import annotations

FONT_UI = '"Segoe UI Variable", "Segoe UI", "Inter", "Roboto", "Cantarell", system-ui, -apple-system, sans-serif'
FONT_MONO = '"Cascadia Code", "JetBrains Mono", Consolas, "DejaVu Sans Mono", monospace'

PALETTES = {
    "light": {
        "bg": "#f6f8fc", "surface": "#ffffff", "surface2": "#eef1f6", "border": "#dde2ea",
        "text": "#1f2329", "muted": "#5f6877", "accent": "#1a73e8", "accent-soft": "#e3eefd",
        "accent-text": "#ffffff", "hover": "#eef1f6", "selected": "#d3e3fd",
        "ok": "#188038", "warn": "#b06000", "danger": "#d93025", "shadow": "rgba(31,35,41,.16)",
    },
    "dark": {
        "bg": "#14171c", "surface": "#1c2027", "surface2": "#252a33", "border": "#333a46",
        "text": "#e6e9ef", "muted": "#9aa3b2", "accent": "#7aa7ff", "accent-soft": "#25344f",
        "accent-text": "#0b1a33", "hover": "#252a33", "selected": "#2c3f63",
        "ok": "#6fcf8a", "warn": "#f0b45a", "danger": "#ff7b72", "shadow": "rgba(0,0,0,.5)",
    },
}

# Legacy flat token set (terminal UI, tray icon, older code) mapped onto the dark palette.
_D = PALETTES["dark"]
TOKENS = {
    "bg0": _D["bg"], "bg1": _D["surface"], "bg2": _D["surface2"],
    "cyan": _D["accent"], "magenta": "#a98bff", "violet": "#5b8def", "yellow": _D["warn"],
    "ok": _D["ok"], "danger": _D["danger"], "text": _D["text"], "muted": _D["muted"],
    "glass": _D["surface"], "glass-strong": _D["surface2"], "glass-border": _D["border"],
    "font-ui": FONT_UI, "font-mono": FONT_MONO, "radius": "12px",
}


def _load_user_theme() -> None:
    """Optional overrides: <config dir>/theme.json (or the file named by SL_THEME_FILE), e.g.
    {"accent": "#0b8043"}. Palette keys apply to light and dark; legacy token keys still work.
    Only known keys with valid values are applied."""
    import json
    import os
    import re
    from pathlib import Path
    try:
        path = os.environ.get("SL_THEME_FILE")
        if not path:
            from platformdirs import user_config_dir
            path = str(Path(user_config_dir("synclayer")) / "theme.json")
        data = json.loads(Path(path).read_text("utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    hexcolor = re.compile(r"#[0-9a-fA-F]{6}")
    for key, val in data.items():
        if not isinstance(val, str) or len(val) > 200 or re.search(r"[;{}<>]", val):
            continue
        if key in PALETTES["light"]:
            if key != "shadow" and not hexcolor.fullmatch(val):
                continue
            for pal in PALETTES.values():
                pal[key] = val
        elif key in TOKENS and (not TOKENS[key].startswith("#") or hexcolor.fullmatch(val)):
            TOKENS[key] = val


_load_user_theme()
# keep the legacy tokens in step with a user-chosen accent
TOKENS["cyan"] = PALETTES["dark"]["accent"]


def css_variables() -> str:
    def block(pal):
        return ";".join(f"--sl-{k}:{v}" for k, v in pal.items())
    legacy = ";".join(f"--sl-{k}:{v}" for k, v in TOKENS.items() if k in ("font-ui", "font-mono", "radius"))
    return (f":root{{color-scheme:light dark;{legacy};{block(PALETTES['light'])}}}\n"
            f"@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{{block(PALETTES['dark'])}}}}}\n"
            f":root[data-theme=dark]{{{block(PALETTES['dark'])}}}\n"
            f":root[data-theme=light]{{{block(PALETTES['light'])}}}\n")


def qss(dark: bool = True) -> str:
    p = PALETTES["dark" if dark else "light"]
    t = TOKENS
    return f"""
* {{ font-family: {t['font-ui']}; color: {p['text']}; font-size: 13px; }}
QMainWindow, QDialog, QWidget#root {{ background: {p['bg']}; }}
QWidget {{ background: transparent; }}
QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 12px; background: {p['surface']}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {p['muted']}; padding: 9px 20px; margin-right: 2px;
  border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {p['accent']}; border-bottom: 2px solid {p['accent']}; }}
QTabBar::tab:hover:!selected {{ background: {p['hover']}; border-radius: 8px; }}
QFrame#card, QGroupBox {{ background: {p['surface']}; border: 1px solid {p['border']};
  border-radius: 12px; margin-top: 10px; padding: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; color: {p['muted']}; padding: 0 6px; font-weight: 600; }}
QLabel#title {{ font-size: 20px; font-weight: 600; color: {p['text']}; }}
QLabel#muted {{ color: {p['muted']}; }}
QLabel#ok {{ color: {p['ok']}; }} QLabel#danger {{ color: {p['danger']}; }}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{ background: {p['surface']}; border: 1px solid {p['border']};
  border-radius: 8px; padding: 7px 10px; selection-background-color: {p['selected']}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 2px solid {p['accent']}; padding: 6px 9px; }}
QPushButton {{ background: {p['accent']}; border: none; color: {p['accent-text']};
  border-radius: 18px; padding: 8px 18px; font-weight: 600; }}
QPushButton:hover {{ background: {p['accent']}; }}
QPushButton:pressed {{ background: {p['selected']}; color: {p['text']}; }}
QPushButton#danger {{ background: transparent; border: 1px solid {p['danger']}; color: {p['danger']}; }}
QPushButton:disabled {{ color: {p['muted']}; background: {p['surface2']}; }}
QTableWidget, QListWidget, QTreeWidget {{ background: {p['surface']}; border: 1px solid {p['border']};
  border-radius: 10px; gridline-color: {p['border']}; alternate-background-color: {p['bg']}; }}
QTableWidget::item:selected, QListWidget::item:selected {{ background: {p['selected']}; color: {p['text']}; }}
QHeaderView::section {{ background: {p['surface']}; color: {p['muted']}; border: none;
  border-bottom: 1px solid {p['border']}; padding: 8px; font-weight: 600; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {p['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QProgressBar {{ border: none; border-radius: 4px; text-align: center; background: {p['surface2']}; max-height: 8px; }}
QProgressBar::chunk {{ background: {p['accent']}; border-radius: 4px; }}
QStatusBar {{ color: {p['muted']}; }}
QMenu {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 7px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p['hover']}; }}
QToolTip {{ background: {p['surface2']}; color: {p['text']}; border: 1px solid {p['border']}; }}
"""
