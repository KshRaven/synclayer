"""Synclayer desktop application (needs the optional extra:  pip install "synclayer[gui]")."""
from __future__ import annotations

import sys


def main(argv=None):
    """Entry point of the `synclayer-gui` launcher (no console window on Windows)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        from .app import run_gui
    except ImportError as e:
        msg = ('The desktop app needs PySide6.  Install it with:\n    pip install "synclayer[gui]"\n'
               f"(import error: {e})")
        print(msg, file=sys.stderr)
        if sys.platform.startswith("win"):  # no console with the GUI launcher: show a dialog
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, msg, "Synclayer", 0x10)
            except Exception:  # noqa: BLE001
                pass
        sys.exit(1)
    run_gui(minimized="--minimized" in argv)
