# Synclayer

A self-hosted cloud for your files. Run the server on a machine you control, then browse, upload and
sync folders from a web browser, a desktop app, an Android app, the command line or Python code.

## What is included

| Part | What it does |
|---|---|
| Server | FastAPI app that stores the files and serves the web app and API. Has an admin panel (web, desktop tab and CLI). |
| Web app | File manager with drag and drop for files and folders, search, recent and starred views, trash, version history and share links. |
| Desktop app | Windows and Linux app with tray icon, notifications and launch at login. macOS works on a best-effort basis. |
| Terminal app | `synclayer` (or `sl`). With no arguments it opens a full-screen menu; with arguments it behaves like a normal CLI (`synclayer --help`). |
| Android app | WebView client for the server's web app with native upload and download handling. No background folder sync. |
| Python package | `import synclayer` to pull, push and sync project files from your own code. |

Other features: multiple users with private drives and per-user quotas, folder sharing between users,
password-protected share links, resumable uploads, `.slignore` files to exclude paths from sync, and
optional admin multi-factor authentication.

## Try it locally

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv && source .venv/bin/activate     # Windows: py -3 -m venv .venv, then .venv\Scripts\activate
pip install -e .
cp .env.example .env                                   # Windows: Copy-Item .env.example .env
synclayer server serve
```

Open `http://localhost:8787` and sign in as `admin`. If `SL_ADMIN_PASSWORD` is empty, a random password is
printed once on first start. Set your own later with `synclayer server passwd`. To listen on this machine
only, set `SL_HOST=127.0.0.1` in `.env`; the example file listens on all interfaces.

Check that it is running:

```bash
curl --fail http://127.0.0.1:8787/api/health
```

To test from the command line, create a device token on the server and use it from a client:

```bash
synclayer server token add sample-client
synclayer login --server http://127.0.0.1:8787 --token "dst_TOKEN_FROM_SERVER"
synclayer put ./sample.txt
synclayer ls
synclayer get sample.txt ./sample-downloaded.txt
```

The token is shown once. Store it somewhere private and revoke it if the device is lost.

There is also an interactive manager that covers setup, running, building, updating, Docker, the boot
service and PyPI publishing: `bash scripts/manage/manage.sh` (Linux, macOS) or `scripts\manage\manage.bat` (Windows).

### Install options

| Command | You get | Typical use |
|---|---|---|
| `pip install synclayer` | server, CLI, Python package (no Qt) | servers, scripts |
| `pip install "synclayer[gui]"` | plus the desktop app (`synclayer-gui`) | desktops |
| `pip install "synclayer[winservice]"` | plus the Windows Service | Windows servers |
| `pip install -e ".[dev]"` / `".[build]"` | tests and lint / packaging tools | working on Synclayer |

From a checkout of this repository, use `pip install -e` in place of `pip install`.

## Hosting on your own server

The server targets Ubuntu/Debian (any systemd distribution works). Windows runs it as a real Windows
Service. macOS is supported as a LaunchAgent, best effort.

You need Python 3.10+, a domain whose `A` record points at the server (for HTTPS), and ports 80 and 443 open
(`sudo ufw allow 'Nginx Full'`). Behind a router, forward TCP 80 and 443. Only publish an `AAAA` record if
IPv6 and its firewall rules are set up too; Let's Encrypt validates over port 80.

### Linux: one command

From a checkout on the server:

```bash
sudo bash scripts/install-service.sh install --nginx files.example.com --certbot you@example.com
```

This creates a `synclayer` system user, installs the app into `/opt/synclayer`, writes
`/etc/synclayer/synclayer.env`, installs a sandboxed systemd service that starts at boot and restarts on
failure, configures nginx for your domain and requests a Let's Encrypt certificate. Leave out `--nginx` and
`--certbot` to do it in steps. Without `--nginx` the server listens on `127.0.0.1` only; set `SL_HOST=0.0.0.0`
in the env file to expose port 8787 directly.

Then find the one-time admin password, or set your own:

```bash
sudo journalctl -u synclayer-server --no-pager | grep -A4 'first start'
sudo synclayer server passwd
```

| Task | Command |
|---|---|
| Status, restart, logs | `sudo bash scripts/install-service.sh status` / `restart` / `logs` |
| Update from this checkout (or PyPI) | `sudo bash scripts/install-service.sh update` |
| Remove the service (files are kept) | `sudo bash scripts/install-service.sh uninstall` |

Data locations: files in `/var/lib/synclayer/files`, settings in `/var/lib/synclayer/config`, environment in
`/etc/synclayer/synclayer.env`.

### Linux: step by step

```bash
pip install synclayer
sudo synclayer service install --domain files.example.com
sudo synclayer nginx install --domain files.example.com --install-packages --certbot --email you@example.com
sudo synclayer service restart
synclayer service status
```

`synclayer nginx show --domain D` prints the nginx config without installing it, for setups you manage
yourself. The generated site keeps WebSocket updates working, streams uploads and downloads, and removes
nginx's body-size limit; the server enforces upload size and quota itself. Without root, use
`synclayer service install --user` for a systemd user unit (`sudo loginctl enable-linger $USER` makes it start
without a login).

### Windows

```powershell
pip install "synclayer[winservice]"
synclayer service install        # from an Administrator prompt
synclayer service status | stop | start | restart | uninstall
```

The service uses `SL_PORT` (8787 by default); use `--port` if something else owns it, and update clients and
any proxy to match. It starts automatically (delayed), restarts on failure and runs as LocalSystem. Data and
logs are in `%ProgramData%\Synclayer`, and its `config\` folder (signing key, tokens) is restricted to
Administrators, so run `synclayer server passwd` from an Administrator prompt. Settings come from a `.env` in
the folder you run `install` from (or `--env-file`), or from the admin panel.

If registration fails with a `pythonservice.exe` or DLL error, run
`python -m pywin32_postinstall -install` once as Administrator and try again. To allow other machines, set
`SL_HOST=0.0.0.0` and open the port:
`netsh advfirewall firewall add rule name="Synclayer" dir=in action=allow protocol=TCP localport=8787`.
The packaged `.exe` cannot host the service; use `synclayer autostart enable --server` (Task Scheduler)
instead. For HTTPS, put any reverse proxy in front; the config from `synclayer nginx show` works.

### Docker

```bash
docker compose up -d --build                     # http://localhost:8787
```

For HTTPS with nginx and Let's Encrypt, set `SL_DOMAIN=your.domain` and `SL_TRUST_PROXY=true` in `.env`, point
DNS at the server, open ports 80 and 443, then:

```bash
docker compose --profile proxy up -d --build     # nginx on :80, serves the certificate challenge
docker compose --profile certbot run --rm certbot certonly --webroot -w /var/www/certbot \
    -d your.domain --email you@example.com --agree-tos --no-eff-email
docker compose --profile proxy down && docker compose --profile https up -d
```

Renew about monthly with
`docker compose --profile certbot run --rm certbot renew && docker compose exec nginx nginx -s reload`.
On a LAN, or when TLS is handled elsewhere (Cloudflare, a load balancer), stay on `--profile proxy`.

## Configuration

Settings are `SL_*` variables (see `.env.example`). Precedence, lowest to highest: defaults, process
environment, `.env`, `settings.json`. The server re-reads `.env` and `settings.json` within about a second,
so most settings apply without a restart. Host, port, proxy mode and secret key need one.

Change settings from the web Admin panel, the desktop Admin tab, `synclayer admin set KEY VALUE` (from any
computer) or `synclayer server set KEY VALUE` (on the server). `synclayer server show` prints the effective values.

### Storage and limits

Files live in a per-OS data folder by default. Set `SL_STORAGE_ROOT` to move them, and
`SL_MOUNTS="name=/abs/path;other=/abs/path"` to expose existing server folders for syncing.

| Setting | Effect |
|---|---|
| `quota_mb` | Cap for the main storage folder. Uploads past it fail with HTTP 507. `0` means unlimited. |
| `min_free_mb` | Refuse writes that would leave less than this much free disk. |
| `max_upload_mb` | Largest single file. |
| `blocked_extensions` | File types that cannot be stored, for example `.exe,.php`. |
| `user_writes` | `false` makes everyone except the admin read-only. |

```bash
synclayer server set quota_mb 400
synclayer server usage        # usage, quota, free disk, largest folders (`synclayer admin usage` from another computer)
```

The quota covers the main storage folder only; `SL_MOUNTS` folders are not counted. Usage is scanned and
cached for about 15 seconds, so two uploads started at the same moment can overshoot by their own size.

### Users and sharing

The admin creates users from the Admin panel. Each user gets a private drive and can have their own quota.
A user can share a folder with another user as read-only or read-write, and create share links (optionally
password protected). Share links and starred items belong to the user who made them. Users cannot reach the
admin API. Disabling a user blocks sign-in; deleting one lets you keep or purge their data.

Devices (the desktop app, CLI, scripts) sign in with revocable tokens: `synclayer server token add NAME`.
Tokens can be read-only (`--read-only`).

### Multi-factor authentication

The server can require a second factor on admin password logins: authenticator-app codes (TOTP), SMS (Twilio or
a webhook), e-mail (SMTP) and one-time recovery codes. Configure delivery with the `sms_twilio_*`,
`sms_webhook_*` or `smtp_*` settings and manage factors through `/api/admin/mfa/...`. Sign-in codes by SMS or
e-mail use `/api/auth/mfa/send`.

The bundled web, Android, desktop, CLI and Python password logins do not yet prompt for the second factor, so
do not enable MFA for an account that signs in through them. Device-token authentication is unaffected.

### Security

Passwords are hashed, sessions are signed, login attempts are rate limited and paths cannot escape their
root. Serve over HTTPS on the internet, use a strong admin password and keep `SL_SECRET_KEY` private.
See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

### Backups and troubleshooting

Back up both the file data and the server configuration (settings, device tokens, signing key, MFA state).
Losing the configuration invalidates sessions and tokens. Locations: `/var/lib/synclayer` and
`/etc/synclayer/synclayer.env` on Linux, `%ProgramData%\Synclayer` on Windows, and the `synclayer-data` volume
(`/data/config`, `/data/files`) in Docker. The storage root may be elsewhere if you changed it. Stop the
service or use a filesystem snapshot while copying, and test a restore. `docker compose down -v` deletes the volumes.

If something fails, check `synclayer service status` and `synclayer service logs` (Docker: `docker compose ps`
and `docker compose logs`), then `/api/health`, DNS, firewall and ports 80/443. If an upload is rejected, check
the limits above and free disk space. If a setting seems ignored, remember that `settings.json` overrides `.env`.

## Using the apps

```bash
synclayer login --server https://your.domain          # or: --token dst_...
synclayer ls | put FILE_OR_DIR [REMOTE] | get REMOTE [LOCAL] | mkdir | mv | rm
synclayer sync add work ~/Work --path projects/alpha  # pair a local folder with a server folder
synclayer sync run                                    # one pass; `synclayer daemon` keeps syncing
synclayer gui                                         # desktop app; `synclayer tray --minimized` for the tray only
synclayer autostart enable                            # start the tray app at login (--server for the server)
```

Sync is two-way by default; `--mode upload` makes a backup that never changes local files and `--mode download`
mirrors the server. If both sides changed a file, the newest copy wins and the other is saved as
`name.conflict-<time>.ext`. Deleting a file on a device does not delete it on the server unless you add
`--propagate-deletes` to that sync folder. The default local folder is `~/Synclayer`; each sync profile can use
another folder and another server path. Put patterns in a `.slignore` file to leave paths out of sync.

The desktop and Android apps start with no server and ask for an address on first launch. They can keep several
servers and switch between them, and the desktop app has a picker for the server folder of each sync folder.

The web and desktop apps both have **Account** (who you are, which server, sign in or out, device token) and
**Settings** (confirm before delete, date format, parallel uploads, notifications, launch at login). Admins also
get a shortcut to the server-wide Admin panel. CLI equivalents: `synclayer login | logout | status`.

### Desktop app

```bash
pip install "synclayer[gui]"
synclayer-gui
```

The first run adds an application-menu entry and icon (Linux: a `.desktop` file under `~/.local/share`;
Windows: a Start Menu shortcut you can pin) and keeps the app in the system tray when the window is closed.
Manage the launcher with `synclayer desktop install | uninstall | status`.

On Ubuntu, Qt needs `sudo apt install libxcb-cursor0 libegl1`, and GNOME shows tray icons only with the
AppIndicator extension (`sudo apt install gnome-shell-extension-appindicator`).

macOS (11+, best effort): the same commands work. The first run creates `~/Applications/Synclayer.app`,
`synclayer autostart enable` adds a LaunchAgent, and `synclayer service install` runs the server as a
LaunchAgent that starts at login (logs in `~/Library/Logs/Synclayer`). Release builds include an unsigned
Apple Silicon app: right-click it and choose Open the first time, or run
`xattr -dr com.apple.quarantine Synclayer.app`. For a server that must run before anyone logs in, use Linux.

### Android app

A WebView shell around the web app: choose a server address, use the file manager and admin panel, pick files
to upload and download through Android's DownloadManager. Optional camera backup uploads new photos and videos to
`Camera Uploads` on the active server in the background (Wi-Fi only by default, with an option to include existing
media). Background sync of arbitrary folders is not included (see [TODO.md](TODO.md)).

Build an APK with JDK 17, the Android SDK and Gradle, or let `synclayer dev android` download them for you:

```bash
bash android/build-apk.sh [https://files.example.com]    # optional default server address
```

The APK is written to `dist/synclayer-<version>-android.apk`. Without a keystore it is signed with the debug
key, which is fine for sideloading. For your own signing, set `SL_KEYSTORE_FILE`, `SL_KEYSTORE_PASSWORD`,
`SL_KEY_ALIAS` and `SL_KEY_PASSWORD`.

### Python package

```python
import synclayer

cloud = synclayer.connect("https://your.domain", token="dst_...")   # or set SL_SERVER / SL_TOKEN
cloud.pull("projects/alpha", "./workdir")                 # fetch your files on another machine
cloud.push("./workdir/results", "projects/alpha/results")
cloud.sync("./workdir", "projects/alpha")                 # two-way
watcher = cloud.watch("./workdir", "projects/alpha", interval=30)   # background sync; watcher.stop()
cloud.write_text("notes/todo.txt", "hello"); print(cloud.read_text("notes/todo.txt"))
```

## Building and releasing

Build the desktop and CLI apps on the operating system you are targeting:

```bash
pip install -e ".[gui,build]"
python scripts/build.py --package                      # dist/synclayer, dist/synclayer-gui and an archive
python scripts/build.py --server https://your.domain   # also bake in a default server address
```

Releases are automated by `scripts/pypimgr`. Add notes under `## Unreleased` in `CHANGELOG.md`, then:

```bash
python scripts/pypimgr/pypimgr.py check                  # tests, build and verify; changes nothing
python scripts/pypimgr/pypimgr.py release patch --push
```

This bumps `synclayer/_version.py`, stamps the changelog, builds from a clean copy, makes one commit and a
`vX.Y.Z` tag, and pushes. The tag starts `.github/workflows/release.yml`, which:

- builds the Windows and Linux apps, a Windows installer and a Linux `.deb` package (macOS, Linux ARM and Android
  are best effort) and attaches them to a GitHub Release with the changelog notes;
- publishes to TestPyPI, then PyPI, through Trusted Publishing (no tokens);
- pushes the server image to `ghcr.io`.

One-time setup: add a Trusted Publisher for this repository and workflow on pypi.org and test.pypi.org
(environments `pypi` and `testpypi`). Optional repository variable `SL_BUILD_SERVER` bakes a default server
address into released apps. Android signing uses the secrets `ANDROID_KEYSTORE_BASE64`,
`ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` and `ANDROID_KEY_PASSWORD`; without them the APK is
debug-signed. Running the workflow by hand builds the apps only, with no release or PyPI upload. Check every
job and artifact before announcing a release. Windows and macOS builds are unsigned.

## Development

```bash
pip install -e ".[gui,dev,build]"
synclayer dev doctor      # shows what is installed or missing (extras, JDK, Android SDK, Gradle)
python -m compileall -q synclayer scripts packaging
ruff check .
pytest -q
```

CI runs compile and import checks, Ruff and the tests on Linux and macOS with Python 3.10 and 3.12. The tests
cover the server API, authentication, users and sharing, trash and versions, quotas, path safety, device
monitoring, sync ignore rules and terminal-app helpers. They are not a full deployment or cross-device test.
See [CONTRIBUTING.md](CONTRIBUTING.md).

### Known limitations

No per-device folder permissions, polling instead of a filesystem watcher, no block-level delta transfers, no
Android background sync, and incomplete MFA support in password-login clients. Deferred work and
clean-machine verification gaps are in [TODO.md](TODO.md).

### Repository layout

```
synclayer/         server/ (API, web UI, MFA)  client/ (API client, sync)  gui/  cli.py  remote.py  vault.py
android/           Kotlin WebView app and APK build script
scripts/           manage/ setup menu, pypimgr/ release tool, build.py, install-service.sh
packaging/         entry points for built executables, installer scripts
docker/            nginx templates (Dockerfile and docker-compose.yml are in the root)
.github/workflows/ CI and release automation
tests/             server, storage and client tests
```
