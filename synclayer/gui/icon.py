"""Application icon, drawn in code so no binary asset is needed (used for the window, tray,
launcher entries and the built executables)."""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap

from .. import theme

SIZES = (16, 24, 32, 48, 64, 128, 256)


LOGO_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
    "<rect x='4' y='4' width='56' height='56' rx='14' fill='{accent}'/>"
    "<g fill='#fff'><circle cx='22' cy='39' r='8'/><circle cx='32' cy='31' r='11'/><circle cx='43' cy='39' r='8'/>"
    "<rect x='22' y='39' width='21' height='8'/></g>"
    "<path fill='{accent}' transform='translate(32.5 38.5) scale(.62) translate(-12 -12)' "
    "d='M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46A7.93 7.93 0 0 0 20 12c0-4.42-3.58-8-8-8z"
    "m0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74A7.93 7.93 0 0 0 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z'/></svg>"
)


def render(size: int) -> QImage:
    """Draw the logo (a cloud with a sync symbol) at `size` x `size` pixels, transparent background."""
    from PySide6.QtSvg import QSvgRenderer
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(LOGO_SVG.format(accent=theme.PALETTES["light"]["accent"]).encode())).render(p)
    p.end()
    return img


def make_icon() -> QIcon:
    icon = QIcon()
    for s in SIZES:
        icon.addPixmap(QPixmap.fromImage(render(s)))
    return icon


def png_bytes(size: int) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    render(size).save(buf, "PNG")
    buf.close()
    return bytes(ba)


def ico_bytes(sizes=(16, 24, 32, 48, 64, 128, 256)) -> bytes:
    """A multi-size .ico (PNG-compressed entries, supported since Windows Vista)."""
    import struct
    pngs = [(s, png_bytes(s)) for s in sizes]
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, blobs = b"", b""
    for s, data in pngs:
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return head + entries + blobs
