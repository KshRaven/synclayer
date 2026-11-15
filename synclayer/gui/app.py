"""Synclayer desktop app (PySide6).

A modern shell: sidebar navigation, the server's own web app embedded for browsing / previews / editing
(so it looks and behaves exactly like the web and Android versions), native pages for sync folders, account
and settings, a system-tray icon with notifications and launch-on-boot."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QDir, QLockFile, QObject, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
                               QSystemTrayIcon, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, autostart, desktop, theme
from ..client.api import ApiError, Client, set_limits
from ..client.config import ClientConfig, Profile, default_sync_dir
from ..client.sync import Runner
from .icon import make_icon

BUS: "Bus | None" = None

# ------------------------------------------------------------------ plumbing


class Bus(QObject):
    """Marshals callables from worker threads onto the GUI thread."""
    call = Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(self._run)

    @Slot(object)
    def _run(self, fn):
        fn()


def run_async(fn, cb):
    def job():
        try:
            r, e = fn(), None
        except Exception as ex:  # noqa: BLE001 - surfaced to the UI
            r, e = None, ex
        BUS.call.emit(lambda: cb(r, e))
    threading.Thread(target=job, daemon=True).start()


def call_api(fn, cb):
    def job():
        cfg = ClientConfig.load()
        if not cfg.token:
            raise ApiError(0, "Not signed in.")
        c = Client(cfg.server_url, cfg.token)
        try:
            return fn(c)
        finally:
            c.close()
    run_async(job, cb)


def human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return str(n)


def ago(ts: float) -> str:
    if not ts:
        return "never"
    s = int(time.time() - ts)
    return "just now" if s < 10 else f"{s}s ago" if s < 90 else f"{s // 60} min ago" if s < 5400 else f"{s // 3600} h ago" if s < 172800 else f"{s // 86400} d ago"


# ------------------------------------------------------------------ icons & style
ICONS = {
    "files": "M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8z",
    "sync": "M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46A7.93 7.93 0 0 0 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74A7.93 7.93 0 0 0 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z",
    "account": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z",
    "settings": "M19.14 12.94c.04-.3.06-.61.06-.94s-.02-.64-.07-.94l2.03-1.58a.5.5 0 0 0 .12-.61l-1.92-3.32a.5.5 0 0 0-.59-.22l-2.39.96a7 7 0 0 0-1.62-.94l-.36-2.54a.48.48 0 0 0-.48-.41h-3.84a.48.48 0 0 0-.48.41l-.36 2.54a7.4 7.4 0 0 0-1.62.94l-2.39-.96a.48.48 0 0 0-.59.22L2.74 8.87a.48.48 0 0 0 .12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.5.5 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32a.5.5 0 0 0-.12-.61zM12 15.6A3.6 3.6 0 1 1 12 8.4a3.6 3.6 0 0 1 0 7.2z",
}


def svg_icon(name: str, color: str, size: int = 24) -> QIcon:
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path fill='{color}' d='{ICONS[name]}'/></svg>"
    img = QImage(size * 2, size * 2, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    return QIcon(QPixmap.fromImage(img))


def qss(dark: bool) -> str:
    c = theme.PALETTES["dark" if dark else "light"]
    return f"""
* {{ font-family: "Segoe UI Variable","Segoe UI","Inter","Roboto","Cantarell",sans-serif; font-size: 14px; }}
QMainWindow, QWidget#root, QDialog {{ background: {c['bg']}; color: {c['text']}; }}
QWidget {{ color: {c['text']}; }}
QFrame#rail {{ background: {c['bg']}; }}
QToolButton#nav {{ border: none; border-radius: 14px; padding: 10px 4px 8px 4px; min-width: 64px; color: {c['muted']}; font-size: 11px; font-weight: 500; }}
QToolButton#nav:hover {{ background: {c['hover']}; }}
QToolButton#nav:checked {{ background: {c['accent-soft']}; color: {c['accent']}; }}
QFrame#page {{ background: {c['surface']}; border: 1px solid {c['border']}; border-top-left-radius: 18px; border-bottom-left-radius: 18px; border-right: none; }}
QFrame#card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QFrame#foot {{ background: transparent; }}
QLabel#h1 {{ font-size: 24px; font-weight: 600; }}
QLabel#h2 {{ font-size: 16px; font-weight: 600; }}
QLabel#muted {{ color: {c['muted']}; }}
QLabel[pill="ok"], QLabel[pill="busy"], QLabel[pill="err"], QLabel[pill="off"] {{ border-radius: 10px; padding: 2px 10px; font-size: 12px; font-weight: 600; }}
QLabel[pill="ok"] {{ background: {c['accent-soft']}; color: {c['ok']}; }}
QLabel[pill="busy"] {{ background: {c['accent-soft']}; color: {c['accent']}; }}
QLabel[pill="err"] {{ background: {c['accent-soft']}; color: {c['danger']}; }}
QLabel[pill="off"] {{ background: {c['surface2']}; color: {c['muted']}; }}
QPushButton {{ border: 1px solid {c['border']}; border-radius: 18px; padding: 8px 18px; background: {c['surface']}; font-weight: 500; }}
QPushButton:hover {{ background: {c['hover']}; }}
QPushButton:disabled {{ color: {c['muted']}; }}
QPushButton#primary {{ background: {c['accent']}; color: {c['accent-text']}; border-color: {c['accent']}; }}
QPushButton#primary:hover {{ background: {c['accent']}; }}
QPushButton#flat {{ border: none; background: transparent; color: {c['accent']}; padding: 8px 12px; }}
QPushButton#flat:hover {{ background: {c['accent-soft']}; }}
QPushButton#danger {{ color: {c['danger']}; }}
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 8px 12px; selection-background-color: {c['selected']}; selection-color: {c['text']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{ border: 2px solid {c['accent']}; padding: 7px 11px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {c['surface']}; border: 1px solid {c['border']}; selection-background-color: {c['selected']}; selection-color: {c['text']}; outline: none; }}
QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 2px solid {c['muted']}; background: transparent; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QProgressBar {{ border: none; border-radius: 4px; background: {c['surface2']}; max-height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ border-radius: 4px; background: {c['accent']}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 8px 24px; border-radius: 6px; }}
QMenu::item:selected {{ background: {c['hover']}; }}
QToolTip {{ background: {c['surface2']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px 8px; }}
"""


def pill(label: QLabel, kind: str, text: str):
    label.setText(text)
    label.setProperty("pill", kind)
    label.style().unpolish(label)
    label.style().polish(label)


def card() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(10)
    return f, lay


def label(text: str, name: str = "") -> QLabel:
    x = QLabel(text)
    if name:
        x.setObjectName(name)
    return x



class FolderPicker(QDialog):
    """Browse the server's folders (loaded one level at a time) and pick one: selective sync."""

    def __init__(self, root: str, current: str = "", parent=None):
        super().__init__(parent)
        self.root, self.chosen = root, current.strip("/")
        self.setWindowTitle("Choose a server folder")
        self.setMinimumSize(460, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label("Choose what to sync", "h2"))
        lay.addWidget(label("Only the selected folder (and what is inside it) is kept on this computer.", "muted"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemExpanded.connect(self.expand)
        self.tree.itemSelectionChanged.connect(self.picked)
        lay.addWidget(self.tree, 1)
        self.where = label("", "muted")
        lay.addWidget(self.where)
        bar = QHBoxLayout()
        bar.addStretch(1)
        c, ok = QPushButton("Cancel"), QPushButton("Use this folder")
        ok.setObjectName("primary")
        c.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        bar.addWidget(c)
        bar.addWidget(ok)
        lay.addLayout(bar)
        top = QTreeWidgetItem(["Everything in this folder"])
        top.setData(0, Qt.ItemDataRole.UserRole, "")
        top.setData(0, Qt.ItemDataRole.UserRole + 1, True)
        self.tree.addTopLevelItem(top)
        self.fetch(top)
        top.setExpanded(True)
        top.setSelected(not self.chosen)
        self.picked()

    def fetch(self, item):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, True)
        item.takeChildren()
        loading = QTreeWidgetItem(["Loading…"])
        item.addChild(loading)

        def done(items, err):
            item.takeChildren()
            if err:
                return item.addChild(QTreeWidgetItem([f"Cannot load: {err}"]))
            for i in items or []:
                if i["type"] != "dir":
                    continue
                full = f"{path}/{i['name']}".strip("/")
                ch = QTreeWidgetItem([i["name"]])
                ch.setData(0, Qt.ItemDataRole.UserRole, full)
                ch.setData(0, Qt.ItemDataRole.UserRole + 1, False)
                ch.addChild(QTreeWidgetItem(["…"]))
                item.addChild(ch)
                if full == self.chosen:
                    self.tree.setCurrentItem(ch)
                elif self.chosen.startswith(full + "/"):
                    ch.setExpanded(True)
        call_api(lambda c: c.list(self.root, path), done)

    def expand(self, item):
        if not item.data(0, Qt.ItemDataRole.UserRole + 1):
            self.fetch(item)

    def picked(self):
        s = self.tree.selectedItems()
        self.chosen = (s[0].data(0, Qt.ItemDataRole.UserRole) or "") if s else self.chosen
        self.where.setText(f"{self.root}:/{self.chosen}")


class WelcomePage(QWidget):
    """First run (and "add a server"): the app ships without a server, so ask for one and sign in."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        box = QVBoxLayout()
        box.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(make_icon().pixmap(QSize(64, 64)))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(logo)
        self.title = label("Connect to your server", "h1")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.title)
        sub = label("Enter the address of your Synclayer server, or a friend's, and sign in.", "muted")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(sub)
        c, cl = card()
        c.setFixedWidth(440)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://files.example.com")
        self.user = QLineEdit()
        self.user.setPlaceholderText("Username")
        self.pw = QLineEdit()
        self.pw.setPlaceholderText("Password")
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.code = QLineEdit()
        self.code.setPlaceholderText("Verification code (only if two-step is on)")
        self.tok = QLineEdit()
        self.tok.setPlaceholderText("…or paste a device token instead of a password")
        for w in (self.url, self.user, self.pw, self.code, self.tok):
            cl.addWidget(w)
            w.returnPressed.connect(self.connect_now)
        self.msg = label("", "muted")
        self.msg.setWordWrap(True)
        cl.addWidget(self.msg)
        bar = QHBoxLayout()
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(lambda: win.show_page(0))
        self.go = QPushButton("Connect")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.connect_now)
        bar.addWidget(self.cancel)
        bar.addStretch(1)
        bar.addWidget(self.go)
        cl.addLayout(bar)
        box.addWidget(c, 0, Qt.AlignmentFlag.AlignHCenter)
        row.addLayout(box)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

    def prepare(self, adding: bool):
        self.cancel.setVisible(adding)
        self.title.setText("Add another server" if adding else "Connect to your server")
        for w in (self.url, self.user, self.pw, self.code, self.tok):
            w.clear()
        self.msg.setText("")
        self.url.setFocus()

    def connect_now(self):
        url, user, pw, tok = self.url.text().strip(), self.user.text().strip(), self.pw.text(), self.tok.text().strip()
        if not url or not (tok or (user and pw)):
            return self.msg.setText("Enter the server address and either your sign-in or a device token.")
        if "://" not in url:
            url = "https://" + url
        cfg = ClientConfig.load()
        dev, code = cfg.device, self.code.text().strip()
        self.go.setEnabled(False)
        self.msg.setText("Connecting…")

        def job():
            c = Client(url, tok)
            try:
                if tok:
                    c.me()
                    return tok, ""
                return c.login(user, pw, device=dev or "desktop", code=code)["token"], user
            finally:
                c.close()

        def done(res, err):
            self.go.setEnabled(True)
            if err:
                return self.msg.setText(f"Could not connect: {err}")
            cfg = ClientConfig.load()
            cfg.add_server(url, token=res[0], user=res[1], activate=True)
            cfg.save()
            self.pw.clear()
            self.win.reload_all(go_files=True)
        run_async(job, done)


# ------------------------------------------------------------------ files (embedded web app)
class _Opener(QWebEnginePage):
    """Pages opened with target=_blank go to the system browser."""
    def acceptNavigationRequest(self, url, _type, _main):  # noqa: N802
        QDesktopServices.openUrl(url)
        return False


class AppPage(QWebEnginePage):
    def __init__(self, profile, parent, server):
        super().__init__(profile, parent)
        self.server = server

    def acceptNavigationRequest(self, url, nav_type, is_main):  # noqa: N802
        if is_main and url.scheme() in ("http", "https") and not url.toString().startswith(self.server):
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main)

    def createWindow(self, _type):  # noqa: N802
        return _Opener(self.profile(), self)


class FilesPage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.profile = QWebEngineProfile("synclayer", self)
        self.profile.downloadRequested.connect(self.on_download)
        self.view = QWebEngineView()
        self.view.setStyleSheet("background: transparent;")
        lay.addWidget(self.view)
        self.script = None
        self.server = ""
        self.token = ""
        self.view.loadFinished.connect(self.on_loaded)
        self.reload_session()

    def reload_session(self):
        cfg = ClientConfig.load()
        self.server, self.token = cfg.server_url.rstrip("/"), cfg.token
        scripts = self.profile.scripts()
        if self.script:
            scripts.remove(self.script)
        s = QWebEngineScript()
        s.setName("synclayer-session")
        s.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        s.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        s.setRunsOnSubFrames(False)
        origin = self.server.replace("\\", "\\\\").replace("'", "\\'")
        tok = self.token.replace("\\", "\\\\").replace("'", "\\'")
        s.setSourceCode("try{if(location.origin==='%s'){%s}}catch(e){}" % (
            origin, f"localStorage.setItem('sl_token','{tok}');sessionStorage.removeItem('sl_token');" if tok else
            "localStorage.removeItem('sl_token');sessionStorage.removeItem('sl_token');"))
        scripts.insert(s)
        self.script = s
        page = AppPage(self.profile, self.view, self.server)
        st = page.settings()
        for attr in (QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, QWebEngineSettings.WebAttribute.PdfViewerEnabled,
                     QWebEngineSettings.WebAttribute.PluginsEnabled, QWebEngineSettings.WebAttribute.LocalStorageEnabled):
            st.setAttribute(attr, True)
        st.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        page.fullScreenRequested.connect(self.on_fullscreen)
        self.view.setPage(page)
        self.view.setUrl(QUrl(self.server or "about:blank"))

    def on_loaded(self, ok: bool):
        if ok:
            return
        retry = self.server
        self.view.setHtml(f"""<body style="font-family:Segoe UI,system-ui,sans-serif;display:grid;place-items:center;height:90vh;margin:0;
            background:#f6f8fc;color:#1f2329"><div style="text-align:center;max-width:420px"><h2>Can’t reach your server</h2>
            <p style="color:#5f6877">{retry}<br>Check the address in Account, or that the server is running.</p>
            <p><a href="{retry}" style="background:#1a73e8;color:#fff;padding:10px 22px;border-radius:20px;text-decoration:none">Try again</a></p></div></body>""",
                          QUrl("about:blank"))

    def on_fullscreen(self, req):
        req.accept()
        self.win.set_fullscreen(req.toggleOn())

    def on_download(self, dl):
        name = dl.downloadFileName()
        start = str(Path.home() / "Downloads" / name)
        path, _ = QFileDialog.getSaveFileName(self.win, "Save file", start)
        if not path:
            dl.cancel()
            return
        p = Path(path)
        dl.setDownloadDirectory(str(p.parent))
        dl.setDownloadFileName(p.name)
        dl.isFinishedChanged.connect(lambda: self.win.notify("Download complete", p.name) if dl.isFinished() else None)
        dl.accept()


# ------------------------------------------------------------------ sync
class ProfileDialog(QDialog):
    MODES = [("Two-way sync", "two-way"), ("Backup (upload only)", "upload"), ("Mirror (download only)", "download")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add a folder to sync")
        self.setMinimumWidth(520)
        f = QFormLayout(self)
        f.setContentsMargins(24, 24, 24, 20)
        f.setSpacing(12)
        self.name = QLineEdit("documents")
        self.local = QLineEdit(str(default_sync_dir()))
        b = QPushButton("Browse…")
        b.clicked.connect(lambda: self.local.setText(QFileDialog.getExistingDirectory(self, "Local folder", self.local.text()) or self.local.text()))
        row = QHBoxLayout()
        row.addWidget(self.local, 1)
        row.addWidget(b)
        self.root = QComboBox()
        self.root.setEditable(True)
        self.root.addItem("main")
        self.rpath = QLineEdit()
        self.rpath.setPlaceholderText("Leave empty for the whole server folder")
        pick = QPushButton("Choose…")
        pick.clicked.connect(self.pick_remote)
        prow = QHBoxLayout()
        prow.addWidget(self.rpath, 1)
        prow.addWidget(pick)
        self.mode = QComboBox()
        for t, v in self.MODES:
            self.mode.addItem(t, v)
        self.propagate = QCheckBox("Also delete on the server when I delete here")
        self.propagate.setToolTip("Off (default): files you delete on this computer stay safe on the server.")
        self.interval = QSpinBox()
        self.interval.setRange(5, 86400)
        self.interval.setValue(60)
        self.interval.setSuffix(" s safety check")
        f.addRow("Name", self.name)
        f.addRow("Folder on this computer", row)
        f.addRow("Server folder", self.root)
        f.addRow("Subfolder", prow)
        f.addRow("Mode", self.mode)
        f.addRow("Check every", self.interval)
        f.addRow("Deleting", self.propagate)
        bar = QHBoxLayout()
        bar.addStretch(1)
        c, ok = QPushButton("Cancel"), QPushButton("Add folder")
        ok.setObjectName("primary")
        c.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        bar.addWidget(c)
        bar.addWidget(ok)
        f.addRow(bar)
        call_api(lambda c: c.me(), self.fill_roots)

    def fill_roots(self, me, err):
        items = (me or {}).get("roots") or []
        if not err and items:
            self.root.setEditable(False)
            self.root.clear()
            for r in items:
                self.root.addItem(r["label"], r["id"])

    def pick_remote(self):
        d = FolderPicker(self.root.currentData() or self.root.currentText().strip() or "main", self.rpath.text(), self)
        if d.exec() == QDialog.DialogCode.Accepted:
            self.rpath.setText(d.chosen)

    def profile(self) -> Profile:
        return Profile(self.name.text().strip(), str(Path(self.local.text()).expanduser()),
                       (self.root.currentData() or self.root.currentText().strip() or "main"), self.rpath.text().strip("/ "), self.interval.value(),
                       True, self.mode.currentData(), self.propagate.isChecked())


class ProfileCard(QFrame):
    def __init__(self, page: "SyncPage", p: Profile):
        super().__init__()
        self.setObjectName("card")
        self.page, self.name = page, p.name
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 16, 16, 16)
        lay.setSpacing(14)
        col = QVBoxLayout()
        col.setSpacing(3)
        top = QHBoxLayout()
        top.addWidget(label(p.name, "h2"))
        self.pill = QLabel()
        top.addWidget(self.pill)
        top.addStretch(1)
        col.addLayout(top)
        mode = {"two-way": "Two-way sync", "upload": "Backup (upload only)", "download": "Mirror (download only)"}.get(p.mode, p.mode)
        col.addWidget(label(f"{p.local_dir}  ↔  {p.remote_root}:/{p.remote_path}", "muted"))
        mode += "  ·  deletes sync to server" if getattr(p, "propagate_deletes", False) and p.mode == "two-way" else "  ·  deleting here keeps the server copy" if p.mode == "two-way" else ""
        self.line = label(mode, "muted")
        col.addWidget(self.line)
        lay.addLayout(col, 1)
        self.mode_txt = mode
        for text, fn in (("Open folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(p.local_dir))),
                         ("Sync now", page.win.sync_now), ("Pause" if p.enabled else "Resume", self.toggle), ("Remove", self.remove)):
            b = QPushButton(text)
            b.setObjectName("flat")
            b.clicked.connect(fn)
            lay.addWidget(b)

    def toggle(self):
        cfg = ClientConfig.load()
        for p in cfg.profiles:
            if p.name == self.name:
                p.enabled = not p.enabled
        cfg.save()
        self.page.rebuild()

    def remove(self):
        if QMessageBox.question(self, "Remove folder", f"Stop syncing “{self.name}”? Files on this computer and on the server stay as they are.") \
                == QMessageBox.StandardButton.Yes:
            cfg = ClientConfig.load()
            cfg.profiles = [p for p in cfg.profiles if p.name != self.name]
            cfg.save()
            self.page.rebuild()

    def update_status(self, st: dict):
        s = st.get("state", "idle")
        kind, text = {"idle": ("ok", "Up to date"), "syncing": ("busy", "Syncing…"), "error": ("err", "Problem"),
                      "paused": ("off", "Paused"), "off": ("off", "Off")}.get(s, ("off", s))
        pill(self.pill, kind, text)
        extra = st.get("error") if s == "error" else (f"Last sync {ago(st.get('last', 0))}" + (f" · {st['summary']}" if st.get("summary") else ""))
        self.line.setText(f"{self.mode_txt}  ·  {extra}" if extra else self.mode_txt)


class SyncPage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win, self.cards = win, {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 30, 36, 20)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(label("Sync folders", "h1"))
        head.addStretch(1)
        add = QPushButton("+  Add folder")
        add.setObjectName("primary")
        add.clicked.connect(self.add)
        head.addWidget(add)
        lay.addLayout(head)
        lay.addWidget(label("Keep folders on this computer identical to folders on your server. Changes sync within seconds.", "muted"))
        self.holder = QWidget()
        self.col = QVBoxLayout(self.holder)
        self.col.setContentsMargins(0, 4, 0, 4)
        self.col.setSpacing(12)
        self.col.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.holder)
        lay.addWidget(sc, 1)
        lay.addWidget(label("Activity", "h2"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(400)
        self.log.setMaximumHeight(140)
        lay.addWidget(self.log)
        self.empty = label("No folders yet. Add one to start syncing.", "muted")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1500)
        self.rebuild()

    def rebuild(self):
        for c in self.cards.values():
            c.setParent(None)
            c.deleteLater()
        self.cards.clear()
        cfg = ClientConfig.load()
        self.empty.setParent(None)
        for p in cfg.profiles:
            c = ProfileCard(self, p)
            self.cards[p.name] = c
            self.col.insertWidget(self.col.count() - 1, c)
        if not cfg.profiles:
            self.col.insertWidget(0, self.empty)
        self.tick()

    def tick(self):
        st = self.win.runner.status() if self.win.runner else {}
        for n, c in self.cards.items():
            c.update_status(st.get(n, {"state": "idle"}))

    def add(self):
        d = ProfileDialog(self)
        if d.exec() == QDialog.DialogCode.Accepted:
            p = d.profile()
            cfg = ClientConfig.load()
            if not p.name or cfg.profile(p.name):
                return self.win.status("Name is empty or already used", True)
            cfg.profiles.append(p)
            cfg.save()
            self.rebuild()
            self.win.sync_now()

    def append(self, msg: str):
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {msg}")


# ------------------------------------------------------------------ account & settings
class AccountPage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        cfg = ClientConfig.load()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 30, 36, 20)
        lay.setSpacing(14)
        lay.addWidget(label("Account", "h1"))
        self.ident = label("", "muted")
        lay.addWidget(self.ident)
        c, cl = card()
        cl.addWidget(label("Your server", "h2"))
        f = QFormLayout()
        f.setSpacing(10)
        self.url = QLineEdit(cfg.server_url)
        self.url.setPlaceholderText("https://files.example.com")
        self.device = QLineEdit(cfg.device)
        self.user = QLineEdit("admin")
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw.returnPressed.connect(self.login)
        self.code = QLineEdit()
        self.code.setPlaceholderText("Only if two-step verification is on")
        self.token = QLineEdit(cfg.token)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        for k, w in (("Server address", self.url), ("This device is called", self.device), ("Username", self.user),
                     ("Password", self.pw), ("Verification code", self.code), ("…or a device token", self.token)):
            f.addRow(k, w)
        cl.addLayout(f)
        row = QHBoxLayout()
        b1, b2 = QPushButton("Sign in"), QPushButton("Save token")
        b1.setObjectName("primary")
        b1.clicked.connect(self.login)
        b2.clicked.connect(self.save)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        out = QPushButton("Sign out of this device")
        out.setObjectName("danger")
        out.clicked.connect(self.sign_out)
        row.addWidget(out)
        rm = QPushButton("Remove server")
        rm.setObjectName("danger")
        rm.clicked.connect(self.remove_server)
        row.addWidget(rm)
        cl.addLayout(row)
        self.state = label("", "muted")
        cl.addWidget(self.state)
        lay.addWidget(c)
        c2, c2l = card()
        c2l.addWidget(label("Storage", "h2"))
        self.use = label("—", "muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        c2l.addWidget(self.use)
        c2l.addWidget(self.bar)
        lay.addWidget(c2)
        lay.addStretch(1)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self.refresh_identity()

    def refresh_identity(self):
        cfg = ClientConfig.load()
        self.url.setText(cfg.server_url)
        self.token.setText(cfg.token)
        if not cfg.token:
            self.ident.setText("Welcome! Enter your server address and sign in to get started.")
            self.use.setText("—")
            self.bar.setValue(0)
            return
        self.ident.setText("Checking…")

        def done(me, err):
            if err:
                self.ident.setText(f"Cannot reach the server: {err}")
            else:
                self.ident.setText(f"Signed in as {me.get('name')} on {cfg.server_url}")
        call_api(lambda c: c.me(), done)

        def usage(u, err):
            if err or not u:
                return
            total = u.get("quota") or (u.get("disk") or {}).get("total") or 0
            self.use.setText(f"{human(u.get('used', 0))} used" + (f" of {human(total)}" if total else ""))
            self.bar.setValue(int(min(1, u.get("used", 0) / total) * 1000) if total else 0)
        call_api(lambda c: c.usage(), usage)

    def save(self):
        cfg = ClientConfig.load()
        cfg.server_url = self.url.text().strip().rstrip("/")
        if cfg.server_url and "://" not in cfg.server_url:
            cfg.server_url = "https://" + cfg.server_url
        cfg.device = self.device.text().strip() or cfg.device
        cfg.token = self.token.text().strip()
        if cfg.current() and cfg.token and self.user.text().strip():
            cfg.current().user = self.user.text().strip()
        cfg.save()
        self.state.setText("Saved.")
        self.win.reload_all(go_files=bool(cfg.token))

    def login(self):
        url, user, pw, dev = self.url.text().strip().rstrip("/"), self.user.text(), self.pw.text(), self.device.text().strip()
        if url and "://" not in url:
            url = "https://" + url
            self.url.setText(url)
        code = self.code.text().strip()
        self.state.setText("Signing in…")

        def job():
            c = Client(url)
            try:
                return c.login(user, pw, device=dev or "desktop", code=code)["token"]
            finally:
                c.close()

        def done(tok, err):
            if err:
                return self.state.setText(f"Sign-in failed: {err}")
            self.token.setText(tok)
            self.pw.clear()
            self.code.clear()
            self.save()
        run_async(job, done)

    def sign_out(self):
        cfg = ClientConfig.load()
        cfg.token = ""
        cfg.save()
        self.token.clear()
        self.win.reload_all()
        self.win.status("Signed out. The device token was removed from this computer.")

    def remove_server(self):
        cfg = ClientConfig.load()
        s = cfg.current()
        if not s:
            return
        if QMessageBox.question(self, "Remove server", f"Forget “{s.label}” and its sync folders on this computer? Nothing is deleted on the server or in the folders.") \
                != QMessageBox.StandardButton.Yes:
            return
        cfg.remove_server(s.id)
        cfg.save()
        self.win.reload_all(go_files=True)


class SettingsPage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        cfg = ClientConfig.load()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 30, 36, 20)
        lay.setSpacing(14)
        lay.addWidget(label("Settings", "h1"))
        c, cl = card()
        cl.addWidget(label("General", "h2"))
        self.boot = QCheckBox("Start Synclayer when I sign in (runs quietly in the tray)")
        try:
            self.boot.setChecked(autostart.is_enabled("tray"))
        except Exception:  # noqa: BLE001
            pass
        self.boot.toggled.connect(self.toggle_boot)
        self.notify = QCheckBox("Show notifications about sync activity")
        self.notify.setChecked(bool(cfg.pref("notify", True)))
        self.notify.toggled.connect(self.save_prefs)
        cl.addWidget(self.boot)
        cl.addWidget(self.notify)
        lay.addWidget(c)
        c2, c2l = card()
        c2l.addWidget(label("Server", "h2"))
        b = QPushButton("Open the web app in my browser")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(ClientConfig.load().server_url)))
        c2l.addWidget(label("Administrators manage users, devices and storage in the web app (Admin in the sidebar).", "muted"))
        c2l.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(c2)
        c3, c3l = card()
        c3l.addWidget(label("Bandwidth", "h2"))
        c3l.addWidget(label("Cap how fast Synclayer uploads and downloads so it never slows down your connection. 0 means no limit.", "muted"))
        f = QFormLayout()
        self.up, self.down = QSpinBox(), QSpinBox()
        for w, k in ((self.up, "limit_up_kb"), (self.down, "limit_down_kb")):
            w.setRange(0, 1_000_000)
            w.setSuffix(" KB/s")
            w.setSpecialValueText("Unlimited")
            w.setValue(int(cfg.pref(k, 0) or 0))
            w.editingFinished.connect(self.save_prefs)
        f.addRow("Upload limit", self.up)
        f.addRow("Download limit", self.down)
        c3l.addLayout(f)
        lay.addWidget(c3)
        lay.addWidget(label(f"{APP_NAME} {__version__}", "muted"))
        lay.addStretch(1)

    def save_prefs(self):
        cfg = ClientConfig.load()
        cfg.prefs["notify"] = self.notify.isChecked()
        cfg.prefs["limit_up_kb"], cfg.prefs["limit_down_kb"] = self.up.value(), self.down.value()
        cfg.save()
        set_limits(self.up.value(), self.down.value())

    def toggle_boot(self, on):
        try:
            self.win.status(autostart.enable("tray") if on else autostart.disable("tray"))
        except Exception as e:  # noqa: BLE001
            self.win.status(f"Autostart failed: {e}", True)


# ------------------------------------------------------------------ window
class MainWindow(QMainWindow):
    def __init__(self, dark: bool):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        self.setMinimumSize(860, 560)
        self.tray: QSystemTrayIcon | None = None
        self.runner: Runner | None = None
        self.told_tray = False
        c = theme.PALETTES["dark" if dark else "light"]
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.rail = QFrame()
        self.rail.setObjectName("rail")
        self.rail.setFixedWidth(88)
        rl = QVBoxLayout(self.rail)
        rl.setContentsMargins(12, 16, 4, 14)
        rl.setSpacing(6)
        logo = QLabel()
        logo.setPixmap(make_icon().pixmap(QSize(40, 40)))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(logo)
        rl.addSpacing(10)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, (name, text) in enumerate((("files", "Files"), ("sync", "Sync"), ("account", "Account"), ("settings", "Settings"))):
            b = QToolButton()
            b.setObjectName("nav")
            b.setText(text)
            b.setCheckable(True)
            b.setIcon(svg_icon(name, c["muted"]))
            b.setIconSize(QSize(24, 24))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.clicked.connect(lambda _=False, n=i: self.show_page(n))
            self.group.addButton(b, i)
            if name == "account":
                rl.addStretch(1)
            rl.addWidget(b)
        self.navs = self.group.buttons()
        self.icons = {i: (svg_icon(n, c["muted"]), svg_icon(n, c["accent"])) for i, n in enumerate(("files", "sync", "account", "settings"))}
        self.group.idToggled.connect(self.nav_icons)
        outer.addWidget(self.rail)

        page = QFrame()
        page.setObjectName("page")
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        self.files, self.sync, self.account, self.settings = FilesPage(self), SyncPage(self), AccountPage(self), SettingsPage(self)
        self.welcome = WelcomePage(self)
        self.stack = QStackedWidget()
        for w in (self.files, self.sync, self.account, self.settings, self.welcome):
            self.stack.addWidget(w)
        pl.addWidget(self.stack, 1)
        foot = QFrame()
        foot.setObjectName("foot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(18, 6, 14, 8)
        self.servers = QComboBox()
        self.servers.setMinimumWidth(200)
        self.servers.activated.connect(self.pick_server)
        fl.addWidget(self.servers)
        self.dot = QLabel()
        pill(self.dot, "ok", "Up to date")
        self.sync_lbl = label("Ready", "muted")
        fl.addWidget(self.dot)
        fl.addWidget(self.sync_lbl, 1)
        for text, fn in (("Sync now", self.sync_now), ("Pause / resume", self.toggle_pause)):
            b = QPushButton(text)
            b.setObjectName("flat")
            b.clicked.connect(fn)
            fl.addWidget(b)
        pl.addWidget(foot)
        outer.addWidget(page, 1)

        QTimer(self, interval=2000, timeout=self.update_pill).start()
        set_limits(int(ClientConfig.load().pref("limit_up_kb", 0) or 0), int(ClientConfig.load().pref("limit_down_kb", 0) or 0))
        self.refresh_servers()
        if ClientConfig.load().token:
            self.show_page(0)
        else:
            self.show_welcome(False)

    def refresh_servers(self):
        cfg = ClientConfig.load()
        cur = cfg.current()
        self.servers.blockSignals(True)
        self.servers.clear()
        for s in cfg.servers:
            self.servers.addItem(s.label + (f"  ·  {s.user}" if s.user else ""), s.id)
        self.servers.addItem("+  Add a server…", "")
        if cur:
            self.servers.setCurrentIndex(self.servers.findData(cur.id))
        self.servers.blockSignals(False)

    def pick_server(self, i: int):
        sid = self.servers.itemData(i)
        if not sid:
            self.refresh_servers()
            return self.show_welcome(True)
        cfg = ClientConfig.load()
        cfg.switch(sid)
        cfg.save()
        self.reload_all(go_files=True)

    def show_welcome(self, adding: bool):
        self.rail.setVisible(False)
        self.welcome.prepare(adding)
        self.stack.setCurrentWidget(self.welcome)

    def reload_all(self, go_files: bool = False):
        """Re-read the server list: reload the web view, sync folders and account for whichever server is active."""
        cfg = ClientConfig.load()
        self.refresh_servers()
        self.files.reload_session()
        self.sync.rebuild()
        self.account.refresh_identity()
        if not cfg.token:
            self.show_welcome(any(s.token for s in cfg.servers))
        elif go_files:
            self.show_page(0)
        if self.runner:
            self.runner.sync_now()

    def nav_icons(self, i, on):
        self.navs[i].setIcon(self.icons[i][1 if on else 0])

    def show_page(self, i: int):
        self.rail.setVisible(True)
        self.stack.setCurrentIndex(i)
        self.navs[i].setChecked(True)
        self.nav_icons(i, True)

    def set_fullscreen(self, on: bool):
        self.rail.setVisible(not on)
        self.showFullScreen() if on else self.showNormal()

    def update_pill(self):
        if not self.runner:
            return
        st = self.runner.status().values()
        if self.runner.paused:
            pill(self.dot, "off", "Paused")
        elif any(s["state"] == "syncing" for s in st):
            pill(self.dot, "busy", "Syncing…")
        elif any(s["state"] == "error" for s in st):
            pill(self.dot, "err", "Problem")
        else:
            pill(self.dot, "ok", "Up to date")

    def status(self, msg, err=False):
        self.sync_lbl.setText(("✕ " if err else "") + msg)

    def notify(self, title, msg):
        if self.tray and self.tray.isVisible() and ClientConfig.load().pref("notify", True):
            self.tray.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 5000)

    # runner hooks (GUI thread)
    def on_status(self, msg):
        self.sync_lbl.setText(msg[:120])
        self.sync.append(msg)
        self.update_pill()

    def on_result(self, name, res, err):
        self.sync.tick()
        if err:
            self.notify(f"Sync problem - {name}", err)
        elif res and (res.changed or res.conflicts or res.errors):
            self.notify(f"Synced {name}", res.summary())

    def sync_now(self):
        if self.runner:
            self.runner.sync_now()
            self.status("Sync requested")

    def toggle_pause(self):
        if self.runner:
            self.runner.paused = not self.runner.paused
            self.status("Sync paused" if self.runner.paused else "Sync resumed")
            self.update_pill()
            self.sync.tick()

    def closeEvent(self, e):  # noqa: N802
        if self.tray and self.tray.isVisible():
            e.ignore()
            self.hide()
            if not self.told_tray:
                self.told_tray = True
                self.notify(APP_NAME, "Still running in the system tray. Right-click the icon to quit.")
        else:
            e.accept()
            QApplication.quit()


def run_gui(minimized: bool = False):
    global BUS
    if sys.platform.startswith("win"):
        try:  # own taskbar identity so Windows shows the Synclayer icon instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(desktop.AUMID)
        except Exception:  # noqa: BLE001
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("synclayer")
    lock = QLockFile(QDir.temp().filePath("synclayer-gui.lock"))
    if not lock.tryLock(100):
        print("Synclayer is already running.")
        return
    BUS = Bus()
    try:
        dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # noqa: BLE001  (Qt < 6.5)
        dark = False
    app.setStyleSheet(qss(dark))
    icon = make_icon()
    app.setWindowIcon(icon)
    win = MainWindow(dark)
    win.setWindowIcon(icon)
    note = desktop.ensure_registered()
    if note:
        win.status(note)

    have_tray = QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not have_tray)
    if have_tray:
        tray = QSystemTrayIcon(icon, app)
        tray.setToolTip(APP_NAME)
        menu = QMenu()
        for text, fn in (("Open Synclayer", lambda: (win.show(), win.raise_(), win.activateWindow())),
                         ("Sync now", win.sync_now), ("Pause / resume sync", win.toggle_pause)):
            a = QAction(text, menu)
            a.triggered.connect(fn)
            menu.addAction(a)
        menu.addSeparator()
        q = QAction("Quit", menu)
        q.triggered.connect(app.quit)
        menu.addAction(q)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda r: (win.hide() if win.isVisible() else (win.show(), win.raise_()))
                               if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.show()
        win.tray = tray
        app._tray, app._menu = tray, menu  # keep references alive

    runner = Runner(on_status=lambda m: BUS.call.emit(lambda: win.on_status(m)),
                    on_result=lambda n, r, e: BUS.call.emit(lambda: win.on_result(n, r, e)))
    win.runner = runner
    runner.start()
    app.aboutToQuit.connect(runner.stop)

    if not (minimized and have_tray):
        win.show()
    code = app.exec()
    lock.unlock()
    sys.exit(code)
