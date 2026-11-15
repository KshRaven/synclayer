"""Host the Synclayer server on an OS: boot-time service + nginx reverse proxy.

  Linux (Ubuntu/Debian first)  systemd system service, run as the unprivileged user 'synclayer'
  Windows                      real Windows Service (needs:  pip install "synclayer[winservice]")
  macOS                        launchd (best effort)

All of it is reachable from the CLI:  `synclayer service ...`  and  `synclayer nginx ...`
The shell script scripts/install-service.sh does the same for Linux and also builds /opt/synclayer.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "synclayer-server"          # systemd unit / launchd label suffix
WIN_SERVICE_NAME = "SynclayerServer"       # Windows service name
LINUX_USER = "synclayer"
LINUX_APP_DIR = Path("/opt/synclayer")
LINUX_ETC = Path("/etc/synclayer")
LINUX_DATA = Path("/var/lib/synclayer")
UNIT_PATH = Path("/etc/systemd/system") / f"{SERVICE_NAME}.service"

NGINX_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_ENABLED = Path("/etc/nginx/sites-enabled")
NGINX_CONFD = Path("/etc/nginx/conf.d")
NGINX_NAME = "synclayer.conf"

ENV_TEMPLATE = """\
# Synclayer server settings (read live by the running server, except host/port/trust_proxy).
# Full list of keys: see .env.example in the repository, or run `synclayer server show`.
# SL_HOST=127.0.0.1 listens on this machine only: put nginx in front (`sudo synclayer nginx install ...`).
# To reach the server directly instead, set SL_HOST=0.0.0.0, open the port, then restart the service.
SL_HOST=127.0.0.1
SL_PORT=8787
SL_DOMAIN=
SL_TRUST_PROXY=false
SL_MAX_UPLOAD_MB=0
# Disk space the cloud may use (0 = unlimited). Change live: `synclayer server set quota_mb 400`
SL_QUOTA_MB=0
SL_MIN_FREE_MB=0
SL_BLOCKED_EXTENSIONS=
SL_USER_WRITES=true
"""


class DeployError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- helpers
def _run(cmd: list[str], check: bool = True, quiet: bool = False) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not quiet:
        out = (r.stdout or "").strip()
        if out:
            print(out)
    if check and r.returncode:
        raise DeployError(f"`{' '.join(cmd)}` failed: {(r.stderr or r.stdout).strip()}")
    return r


def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def need_root(what: str):
    if not is_root():
        raise DeployError(f"{what} needs root. Re-run with sudo, e.g.:  sudo {Path(sys.argv[0]).name} {' '.join(sys.argv[1:])}")


def set_env_key(path: Path, key: str, value: str):
    """Edit KEY=VALUE in an env file (append if missing)."""
    lines = path.read_text("utf-8").splitlines() if path.exists() else []
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if pat.match(line):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", "utf-8")


# ----------------------------------------------------------------------------- Linux (systemd)
def render_unit(python: str, user: str = LINUX_USER, env_file: Path = LINUX_ETC / "synclayer.env",
                data_dir: Path = LINUX_DATA) -> str:
    return f"""\
[Unit]
Description=Synclayer server
After=network-online.target
Wants=network-online.target

[Service]
User={user}
Group={user}
Environment=SL_ENV_FILE={env_file}
Environment=SL_CONFIG_DIR={data_dir}/config
Environment=SL_STORAGE_ROOT={data_dir}/files
ExecStart={python} -m synclayer server serve
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
UMask=0027
LimitNOFILE=65535
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
"""


def _linux_install(env_file: str | None, domain: str, enable_now: bool = True) -> str:
    need_root("Installing the service")
    if not shutil.which("systemctl"):
        raise DeployError("systemd not found (this command targets Ubuntu/Debian and other systemd distros)")
    py = sys.executable
    if py.startswith(("/home/", "/root/")):
        print(f"warning: {py} lives in a home folder; the unprivileged '{LINUX_USER}' user may not be able "
              f"to run it.\n         Prefer scripts/install-service.sh, which builds {LINUX_APP_DIR}.")
    if _run(["id", LINUX_USER], check=False, quiet=True).returncode:
        _run(["useradd", "--system", "--home-dir", str(LINUX_DATA), "--create-home",
              "--shell", "/usr/sbin/nologin", LINUX_USER])
        print(f"created system user '{LINUX_USER}'")
    for d in (LINUX_ETC, LINUX_DATA / "config", LINUX_DATA / "files"):
        d.mkdir(parents=True, exist_ok=True)
    target_env = LINUX_ETC / "synclayer.env"
    if not target_env.exists():
        src = Path(env_file) if env_file else Path(".env")
        target_env.write_text(src.read_text("utf-8") if src.is_file() else ENV_TEMPLATE, "utf-8")
        print(f"wrote {target_env}")
    if domain:
        set_env_key(target_env, "SL_DOMAIN", domain)
    _run(["chown", f"root:{LINUX_USER}", str(target_env)])
    os.chmod(target_env, 0o640)
    _run(["chown", "-R", f"{LINUX_USER}:{LINUX_USER}", str(LINUX_DATA)])
    os.chmod(LINUX_DATA / "config", 0o700)
    UNIT_PATH.write_text(render_unit(py), "utf-8")
    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable"] + (["--now"] if enable_now else []) + [f"{SERVICE_NAME}.service"])
    return (f"Service '{SERVICE_NAME}' installed and enabled (starts at boot).\n"
            f"  settings file : {target_env}   (edit it; the server reloads it live)\n"
            f"  data          : {LINUX_DATA}\n"
            f"  logs          : journalctl -u {SERVICE_NAME} -f\n"
            f"  first password: journalctl -u {SERVICE_NAME} --no-pager | grep -A4 'first start'\n"
            f"  or set your own: sudo synclayer server passwd   (uses {LINUX_DATA}/config automatically)")


def _linux_uninstall() -> str:
    need_root("Removing the service")
    _run(["systemctl", "disable", "--now", f"{SERVICE_NAME}.service"], check=False, quiet=True)
    UNIT_PATH.unlink(missing_ok=True)
    _run(["systemctl", "daemon-reload"], check=False, quiet=True)
    return (f"Service removed. Kept your data and settings: {LINUX_DATA}, {LINUX_ETC} "
            "(delete them yourself if you really want to).")


def _linux_control(action: str) -> str:
    if action == "logs":
        r = _run(["journalctl", "-u", f"{SERVICE_NAME}.service", "-n", "60", "--no-pager"], check=False, quiet=True)
        return (r.stdout or r.stderr or "no log entries").strip()
    cmd = ["systemctl", "status", "--no-pager", f"{SERVICE_NAME}.service"] if action == "status" else \
          ["systemctl", action, f"{SERVICE_NAME}.service"]
    if action != "status":
        need_root(f"`service {action}`")
    r = _run(cmd, check=False, quiet=True)
    return (r.stdout or r.stderr or "").strip() or f"{action}: done"


# ----------------------------------------------------------------------------- macOS
def _mac_control(action: str) -> str:
    from . import autostart
    if action == "install":
        return autostart.enable("server")
    if action == "uninstall":
        return autostart.disable("server")
    label = "com.synclayer.server"
    if action == "logs":
        from . import autostart  # noqa: F401
        return f"launchd log: {Path.home() / 'Library' / 'Logs' / 'Synclayer'} (see 'synclayer autostart -h')"
    if action == "status":
        r = _run(["launchctl", "list"], check=False, quiet=True)
        return "running" if label in (r.stdout or "") else "not running"
    if action == "start":
        return (_run(["launchctl", "start", label], check=False, quiet=True).stderr or "started").strip()
    if action == "stop":
        return (_run(["launchctl", "stop", label], check=False, quiet=True).stderr or "stopped").strip()
    _run(["launchctl", "stop", label], check=False, quiet=True)
    _run(["launchctl", "start", label], check=False, quiet=True)
    return "restarted"


# ----------------------------------------------------------------------------- public: service
def service(action: str, env_file: str | None = None, domain: str = "", user_mode: bool = False,
            no_start: bool = False, port: int | None = None) -> str:
    """action: install | uninstall | start | stop | restart | status | logs"""
    if sys.platform.startswith("win"):
        from . import winservice
        return winservice.control(action, env_file=env_file, no_start=no_start, port=port)
    if port is not None:
        raise DeployError("--port is supported for Windows service installation only; set SL_PORT in the server settings on this platform.")
    if sys.platform == "darwin":
        return _mac_control(action)
    if user_mode:  # no root: systemd --user unit written by autostart.py
        from . import autostart
        if action == "install":
            return autostart.enable("server")
        if action == "uninstall":
            return autostart.disable("server")
        if action == "status":
            return "installed" if autostart.is_enabled("server") else "not installed"
        r = _run(["systemctl", "--user", action, f"{SERVICE_NAME}.service"], check=False, quiet=True)
        return (r.stderr or r.stdout or f"{action}: done").strip()
    if action == "install":
        return _linux_install(env_file, domain, enable_now=not no_start)
    if action == "uninstall":
        return _linux_uninstall()
    return _linux_control(action)


# ----------------------------------------------------------------------------- public: nginx
def render_nginx(domain: str, port: int = 8787, max_upload_mb: int = 0, cert: str = "", key: str = "",
                 upstream_host: str = "127.0.0.1") -> str:
    """Server block for nginx. Without cert/key it serves plain HTTP on :80 (add TLS with certbot);
    with cert and key it serves HTTPS and redirects HTTP to it."""
    if not re.fullmatch(r"[A-Za-z0-9.-]+", domain or ""):
        raise DeployError("a valid --domain is required (letters, digits, dots, dashes)")
    body = f"{max_upload_mb}m" if max_upload_mb else "0"
    proxy = f"""\
    client_max_body_size {body};          # 0 = unlimited; the server enforces its own limits/quota

    location / {{
        proxy_pass http://synclayer_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;              # live updates (WebSocket)
        proxy_set_header Connection $synclayer_conn_upgrade;
        proxy_request_buffering off;                         # stream uploads straight to the app
        proxy_buffering off;                                 # stream downloads
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }}
"""
    head = f"""\
# Managed by `synclayer nginx install` - safe to edit; re-running overwrites it.
upstream synclayer_backend {{
    server {upstream_host}:{port};
    keepalive 16;
}}

map $http_upgrade $synclayer_conn_upgrade {{
    default upgrade;
    ''      close;
}}

"""
    if cert and key:
        return head + f"""\
server {{
    listen 80;
    listen [::]:80;
    server_name {domain};
    location /.well-known/acme-challenge/ {{ root /var/www/html; }}
    location / {{ return 301 https://$host$request_uri; }}
}}

server {{
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name {domain};

    ssl_certificate     {cert};
    ssl_certificate_key {key};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:synclayer_ssl:10m;
    add_header Strict-Transport-Security "max-age=31536000" always;

{proxy}}}
"""
    return head + f"""\
server {{
    listen 80;
    listen [::]:80;
    server_name {domain};

{proxy}}}
"""


def _nginx_paths() -> tuple[Path, Path | None]:
    if NGINX_AVAILABLE.is_dir() and NGINX_ENABLED.is_dir():       # Debian/Ubuntu layout
        return NGINX_AVAILABLE / NGINX_NAME, NGINX_ENABLED / NGINX_NAME
    return NGINX_CONFD / NGINX_NAME, None                         # RHEL/Alpine/other layout


def nginx_install(domain: str, port: int = 8787, max_upload_mb: int = 0, certbot: bool = False,
                  email: str = "", cert: str = "", key: str = "", install_packages: bool = False,
                  env_file: str | None = None) -> str:
    need_root("Installing the nginx site")
    if install_packages and shutil.which("apt-get"):
        pk = ["nginx"] + (["certbot", "python3-certbot-nginx"] if certbot else [])
        _run(["apt-get", "update"], quiet=True)
        _run(["apt-get", "install", "-y"] + pk)
    if not shutil.which("nginx"):
        raise DeployError("nginx not found. Install it:  sudo apt install nginx"
                          + (" certbot python3-certbot-nginx" if certbot else "")
                          + "   (or add --install-packages)")
    avail, enabled = _nginx_paths()
    avail.write_text(render_nginx(domain, port, max_upload_mb, cert, key), "utf-8")
    if enabled is not None:
        if enabled.is_symlink() or enabled.exists():
            enabled.unlink()
        enabled.symlink_to(avail)
    r = _run(["nginx", "-t"], check=False, quiet=True)
    if r.returncode:
        raise DeployError("nginx rejected the config:\n" + (r.stderr or r.stdout))
    if shutil.which("systemctl"):
        _run(["systemctl", "reload", "nginx"], check=False, quiet=True)
    else:
        _run(["nginx", "-s", "reload"], check=False, quiet=True)
    notes = [f"nginx site written: {avail}"]

    env = Path(env_file) if env_file else (LINUX_ETC / "synclayer.env")
    if env.exists():
        set_env_key(env, "SL_DOMAIN", domain)
        set_env_key(env, "SL_TRUST_PROXY", "true")
        set_env_key(env, "SL_HOST", "127.0.0.1")
        set_env_key(env, "SL_PORT", str(port))
        notes.append(f"updated {env}: SL_DOMAIN, SL_TRUST_PROXY=true, SL_HOST=127.0.0.1 "
                     f"-> restart the server once:  sudo synclayer service restart")
    else:
        notes.append("remember to set  SL_TRUST_PROXY=true  and  SL_HOST=127.0.0.1  for the server "
                     "(then restart it) so real client addresses reach the login rate limiter.")

    if certbot:
        if not shutil.which("certbot"):
            raise DeployError("certbot not found:  sudo apt install certbot python3-certbot-nginx")
        cmd = ["certbot", "--nginx", "-d", domain, "--non-interactive", "--agree-tos", "--redirect"]
        cmd += ["-m", email] if email else ["--register-unsafely-without-email"]
        _run(cmd)
        notes.append("HTTPS enabled by certbot (auto-renewal is installed by the certbot package).")
    else:
        notes.append(f"HTTP only so far. Add HTTPS:  sudo synclayer nginx install --domain {domain} --certbot --email you@example.com")
    notes.append("Firewall (Ubuntu):  sudo ufw allow 'Nginx Full'")
    return "\n".join(notes)


def nginx_remove() -> str:
    need_root("Removing the nginx site")
    avail, enabled = _nginx_paths()
    if enabled is not None and (enabled.is_symlink() or enabled.exists()):
        enabled.unlink()
    avail.unlink(missing_ok=True)
    if shutil.which("nginx") and _run(["nginx", "-t"], check=False, quiet=True).returncode == 0:
        if shutil.which("systemctl"):
            _run(["systemctl", "reload", "nginx"], check=False, quiet=True)
    return "nginx site removed (certificates, if any, are left in /etc/letsencrypt)."
