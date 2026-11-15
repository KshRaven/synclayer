# Changelog

## Unreleased

## 0.1.1
- Changed `service install` to re-run itself with sudo, build a root-owned runtime in /opt/synclayer and link `synclayer` into /usr/local/bin, so pip --user installs no longer break it.
- Added the `SL_EMAIL` / `email` setting for HTTPS certificate notices, used by `nginx install --certbot`.
- Added IP-only reverse proxy mode (`nginx install` without a domain) with `--listen-port`, `--https-port` and `--self-signed`.
- Added an admin username and password prompt to `service install` (also `--admin-user`, `--admin-password`, `--no-prompt`).
- Changed the release workflow to build desktop and Android apps and create the GitHub release only when app files changed (`pypimgr release --apps` / `--no-apps` to override); other versions go to PyPI only.
- Changed `pypimgr release fix` to rewrite a release that is already pushed: it amends the commit, keeps its message, saves the original under `refs/pypimgr/backup/`, force-pushes with a lease, replaces the tag, and deletes the old GitHub release.
- Added `VERSION_TARGETS` so every release, bump or fix also updates the Android build file and the Windows installer script, and made the release workflow replace an existing release for the same tag.
- Fixed the server image push to ghcr.io being denied: the image now carries source labels, the login can use an optional `GHCR_TOKEN` / `GHCR_USER` secret, and the `latest` tag is no longer listed twice.
- Fixed the guided release menu in `pypimgr` failing with `'Namespace' object has no attribute 'apps'`.
- Changed `pypimgr release fix` to move the tag with a single forced push instead of deleting it first, so a failed push can no longer leave the remote without the tag; a failure prints the exact retry command.

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
