"""Project-specific settings for pypimgr in this repository."""

PROJECT_NAME = "synclayer"
PYPI_PACKAGE_NAME = "synclayer"
GIT_REMOTE = "origin"
TAG_PREFIX = "v"
RELEASE_COMMIT_TEMPLATE = "Release v{version}"

# Project-relative paths.
PROJECT_FILE = "pyproject.toml"
CHANGELOG_FILE = "CHANGELOG.md"
ENV_FILE = ".env.release"
COMMIT_MESSAGE_FILE = "commit.txt"
REQUIRED_FILES = (
    "README.md",
    "LICENSE",
    PROJECT_FILE,
    CHANGELOG_FILE,
    "MANIFEST.in",
    ".gitignore",
)
# Directory names omitted from the source staging copy and regexes checked against archive paths.
TOP_LEVEL_EXCLUDES = ("android", "packaging", "docker", "data")
EXTRA_FORBIDDEN_PATHS = (r"(^|/)android/", r"(^|/)data/")

# Files that end up inside the desktop apps (PyInstaller bundles) or the Android APK. A release whose changes touch
# none of these is "PyPI only": no app builds, no GitHub release (the tag and CHANGELOG still record it).
# Entries ending in "/" are folders. Force either way with `pypimgr release --apps` / `--no-apps`.
APP_PATHS = (
    "android/", "packaging/", "scripts/build.py", "requirements-gui.txt", "requirements-build.txt",
    "synclayer/gui/", "synclayer/client/", "synclayer/common/",
    "synclayer/theme.py", "synclayer/desktop.py", "synclayer/autostart.py", "synclayer/tui.py",
)

# Extra files that repeat the version; pypimgr updates them with the version file on every release/bump/fix.
# Each entry is (project-relative path, regex with three groups: text before, the version, text after).
VERSION_TARGETS = (
    ("android/app/build.gradle", r'(def pyVersion = ")([^"]+)(")'),
    ("packaging/windows/synclayer.iss", r"(/DAppVersion=)(\S+)()"),
)

PYPI_JSON_URL = "https://pypi.org/pypi/{package}/json"

PROJECT_LINKS = {
    "Repository": "https://github.com/KshRaven/synclayer",
    "Release workflow": "https://github.com/KshRaven/synclayer/actions/workflows/release.yml",
    "PyPI": "https://pypi.org/project/synclayer/",
    "TestPyPI": "https://test.pypi.org/project/synclayer/",
    "PyPI publisher settings": "https://pypi.org/manage/project/synclayer/settings/publishing/",
    "TestPyPI publisher settings": "https://test.pypi.org/manage/project/synclayer/settings/publishing/",
}
