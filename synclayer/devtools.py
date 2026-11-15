"""Developer tooling (stdlib only): `synclayer dev doctor` and `synclayer dev android`.

pip can install Python packages (`pip install -e ".[dev]"`, `".[build]"`, `".[gui]"`) but not a JDK or the Android SDK.
This module downloads what the Android build needs - Temurin JDK 17, the Android command-line tools + platform 34,
and Gradle 8.9 - into a per-user folder, headless, on Windows, Linux and macOS. Nothing system-wide is changed.

    synclayer dev doctor                       what is installed / missing
    synclayer dev android                      install missing tools, build dist/synclayer-<ver>-android.apk
    synclayer dev android --server https://files.example.com
    synclayer dev android --install-only       only fetch the toolchain
"""
from __future__ import annotations

import importlib.util
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from platformdirs import user_data_dir

ROOT = Path(__file__).resolve().parents[1]
HOME = Path(user_data_dir("synclayer")) / "toolchain"
WIN = os.name == "nt"
OS = "windows" if WIN else "mac" if sys.platform == "darwin" else "linux"
ARCH = "aarch64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
GRADLE_VER, PLATFORM, BUILD_TOOLS = "8.9", "android-34", "34.0.0"
CMDLINE = {"windows": "win", "linux": "linux", "mac": "mac"}[OS]
CMDLINE_URL = f"https://dl.google.com/android/repository/commandlinetools-{CMDLINE}-11076708_latest.zip"
GRADLE_URL = f"https://services.gradle.org/distributions/gradle-{GRADLE_VER}-bin.zip"
JDK_URL = f"https://api.adoptium.net/v3/binary/latest/17/ga/{OS}/{ARCH}/jdk/hotspot/normal/eclipse"


def say(msg: str):
    print(msg, flush=True)


def _exe(name: str, kind: str = "exe") -> str:
    return name + (".exe" if kind == "exe" else ".bat") if WIN else name


def _download(url: str, label: str) -> Path:
    say(f"  downloading {label} ...")
    fd, tmp = tempfile.mkstemp(suffix=".download")
    os.close(fd)
    req = urllib.request.Request(url, headers={"User-Agent": "synclayer-devtools"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    return Path(tmp)


def _extract(archive: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest)          # trusted vendor archives (Adoptium)
    archive.unlink(missing_ok=True)


def _chmod_bins(base: Path):
    if WIN:
        return
    for p in base.rglob("*"):
        if p.is_file() and p.parent.name in ("bin", "lib") and not p.suffix:
            try:
                p.chmod(p.stat().st_mode | 0o111)
            except OSError:
                pass


# ------------------------------------------------------------------------------------ locating tools
def find_jdk() -> Path | None:
    """JAVA_HOME of a JDK >= 17 (ours, then $JAVA_HOME, then java on PATH)."""
    def ok(home: Path) -> bool:
        java = home / "bin" / _exe("java")
        if not java.exists():
            return False
        try:
            out = subprocess.run([str(java), "-version"], capture_output=True, text=True, timeout=20)
            m = re.search(r'version "(\d+)', out.stderr + out.stdout)
            return bool(m and int(m.group(1)) >= 17)
        except Exception:
            return False
    cands = [p.parent.parent for p in (HOME / "jdk").glob("**/bin/" + _exe("java"))][:1]
    if os.environ.get("JAVA_HOME"):
        cands.append(Path(os.environ["JAVA_HOME"]))
    w = shutil.which("java")
    if w:
        cands.append(Path(w).resolve().parent.parent)
    return next((c for c in cands if ok(c)), None)


def sdk_dir() -> Path:
    for v in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(v) and (Path(os.environ[v]) / "platforms" / PLATFORM).exists():
            return Path(os.environ[v])
    return HOME / "android-sdk"


def sdk_ready() -> bool:
    s = sdk_dir()
    return (s / "platforms" / PLATFORM).exists() and (s / "build-tools" / BUILD_TOOLS).exists()


def gradle_bin() -> Path | None:
    wrapper = ROOT / "android" / _exe("gradlew", "bat")
    if wrapper.exists():
        return wrapper
    g = HOME / f"gradle-{GRADLE_VER}" / "bin" / _exe("gradle", "bat")
    return g if g.exists() else None


# ------------------------------------------------------------------------------------ installing
def ensure_jdk() -> Path:
    jdk = find_jdk()
    if jdk:
        return jdk
    say("JDK 17 not found - installing Temurin 17 into " + str(HOME / "jdk"))
    _extract(_download(JDK_URL, "Temurin JDK 17 (~190 MB)"), HOME / "jdk")
    _chmod_bins(HOME / "jdk")
    jdk = find_jdk()
    if not jdk:
        raise SystemExit("JDK download finished but java was not found. Install JDK 17 manually and set JAVA_HOME.")
    return jdk


def ensure_sdk(jdk: Path) -> Path:
    sdk = sdk_dir()
    if sdk_ready():
        return sdk
    say("Android SDK missing - installing into " + str(sdk))
    sm = sdk / "cmdline-tools" / "latest" / "bin" / _exe("sdkmanager", "bat")
    if not sm.exists():
        tmp = Path(tempfile.mkdtemp())
        _extract(_download(CMDLINE_URL, "Android command-line tools (~150 MB)"), tmp)
        (sdk / "cmdline-tools").mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp / "cmdline-tools"), str(sdk / "cmdline-tools" / "latest"))
        _chmod_bins(sdk / "cmdline-tools")
    env = {**os.environ, "JAVA_HOME": str(jdk)}
    base = [str(sm), f"--sdk_root={sdk}"]
    subprocess.run(base + ["--licenses"], input="y\n" * 60, text=True, env=env, capture_output=True)
    r = subprocess.run(base + ["platform-tools", f"platforms;{PLATFORM}", f"build-tools;{BUILD_TOOLS}"], env=env)
    if r.returncode != 0 or not sdk_ready():
        raise SystemExit("sdkmanager failed - check your network connection and re-run.")
    return sdk


def ensure_gradle() -> Path:
    g = gradle_bin()
    if g:
        return g
    say(f"Gradle {GRADLE_VER} missing - installing (the Android plugin here needs Gradle 8.x)")
    _extract(_download(GRADLE_URL, f"Gradle {GRADLE_VER} (~130 MB)"), HOME)
    _chmod_bins(HOME / f"gradle-{GRADLE_VER}")
    g = gradle_bin()
    if not g:
        raise SystemExit("Gradle download failed.")
    return g


# ------------------------------------------------------------------------------------ commands
def doctor() -> int:
    say("Python packages (install with pip extras):")
    for mod, extra in (("PySide6", "gui"), ("PyInstaller", "build"), ("build", "build"), ("twine", "build"),
                       ("pytest", "dev"), ("ruff", "dev")):
        have = importlib.util.find_spec(mod) is not None
        say(f"  {'ok     ' if have else 'MISSING'} {mod:<12} pip install -e \".[{extra}]\"" if not have else f"  ok      {mod}")
    say("Android toolchain (installed by `synclayer dev android`):")
    jdk = find_jdk()
    say(f"  {'ok     ' if jdk else 'MISSING'} JDK 17+   {jdk or ''}")
    say(f"  {'ok     ' if sdk_ready() else 'MISSING'} Android SDK ({PLATFORM}) {sdk_dir() if sdk_ready() else ''}")
    g = gradle_bin()
    say(f"  {'ok     ' if g else 'MISSING'} Gradle {GRADLE_VER}   {g or ''}")
    say(f"Source checkout: {'yes' if (ROOT / 'android').is_dir() else 'NO (Android builds need the repository)'}")
    return 0


def android(server: str = "", install_only: bool = False) -> int:
    proj = ROOT / "android"
    if not (proj / "build.gradle").exists():
        raise SystemExit("Run this from a source checkout (pip install -e . inside the repository): android/ not found.")
    jdk = ensure_jdk()
    sdk = ensure_sdk(jdk)
    gradle = ensure_gradle()
    say(f"Toolchain ready: JDK {jdk}, SDK {sdk}, Gradle {gradle}")
    if install_only:
        return 0
    (proj / "local.properties").write_text("sdk.dir=" + str(sdk).replace("\\", "/") + "\n", "ascii")
    env = {**os.environ, "JAVA_HOME": str(jdk), "ANDROID_HOME": str(sdk), "ANDROID_SDK_ROOT": str(sdk)}
    cmd = [str(gradle), "--no-daemon", "assembleRelease"] + ([f"-PslServer={server}"] if server else [])
    if subprocess.run(cmd, cwd=proj, env=env).returncode != 0:
        raise SystemExit("Gradle build failed (see the output above).")
    from . import __version__
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    dest = out / f"synclayer-{__version__}-android.apk"
    shutil.copy(proj / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk", dest)
    say(f"APK: {dest}")
    return 0
