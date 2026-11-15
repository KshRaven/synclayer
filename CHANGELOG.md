# Changelog

## Unreleased

## 0.1.0
- Added a self-hosted cloud with a FastAPI server, web file manager, admin controls, MFA, and configurable storage quotas.
- Added multi-user accounts with private drives, folder sharing, and a Shared with me view.
- Added file search, recent and starred views, trash and restore, version history, protected share links, and resumable uploads.
- Added cross-platform clients: CLI/TUI, Python API, Windows and Linux desktop sync apps, and an Android WebView app with native upload and download support. Sync supports `.slignore`, bandwidth limits, and selective folder sync.
- Added multi-server support and a first-run connect screen to the desktop and Android apps, and Android camera backup.
- Added Docker and service deployment, desktop and Android build tools, and CI/release workflows for PyPI, GitHub Releases, container images, a Windows installer, and a Linux .deb.
- Added setup, contribution, support, and security documentation.
- Changed sync so deleting a file on a device keeps the server copy unless deletion sync is turned on.
- Updated repository ignore rules and platform-specific text-file handling.
