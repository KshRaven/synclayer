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
# Contact address for HTTPS certificates (certbot / Let's Encrypt expiry notices). Used by `nginx install --certbot`.
SL_EMAIL=
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
def _run(cmd: list[str], check: bool = True, quiet: bool = False, env: dict | None = None) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if not quiet:
        out = (r.stdout or "").strip()
        if out:
            print(out)
    if check and r.returncode:
        raise DeployError(f"`{' '.join(cmd)}` failed: {(r.stderr or r.stdout).strip()}")
    return r


def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _elevate(what: str):
    """Re-run this very command through sudo (with this interpreter and its import path, so a `pip install --user`
    copy still works for root and sudo's restricted PATH does not matter). Never returns when it succeeds."""
    if (sys.platform.startswith("win") or not shutil.which("sudo") or os.environ.get("SL_NO_SUDO")
            or os.environ.get("SL_ELEVATED")):
        return
    frozen = getattr(sys, "frozen", False)
    env = [f"{k}={v}" for k, v in os.environ.items() if k.startswith("SL_")] + ["SL_ELEVATED=1"]
    if not frozen:
        env.append("PYTHONPATH=" + os.pathsep.join(dict.fromkeys(p for p in sys.path if p and os.path.isdir(p))))
    base = [sys.executable] if frozen else [sys.executable, "-m", "synclayer"]
    print(f"{what} needs root - continuing with sudo ...", flush=True)
    os.execvp("sudo", ["sudo", "env", *env, *base, *sys.argv[1:]])


def need_root(what: str):
    if not is_root():
        _elevate(what)
        raise DeployError(f"{what} needs root and sudo is not available. Run it as root.")


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


_CRED_CODE = """
import os, sys
from synclayer.config import Settings
s = Settings()
if sys.argv[1] == "check":
    print("set" if (s.get("admin_password_hash") or s.get("admin_password")) else "unset")
else:
    if os.environ.get("SL_NEW_ADMIN_USER"):
        s.update({"admin_user": os.environ["SL_NEW_ADMIN_USER"]})
    if os.environ.get("SL_NEW_ADMIN_PASSWORD"):
        from synclayer.server.security import hash_password
        s.set_internal("admin_password_hash", hash_password(os.environ["SL_NEW_ADMIN_PASSWORD"]))
    print("ok")
"""


def _ask_admin(admin_user: str = "", admin_password: str = "", prompt: bool = True) -> tuple[str, str]:
    """Admin login for a new service: arguments > SL_ADMIN_USER / SL_ADMIN_PASSWORD > interactive prompt.
    ('', '') means: nothing chosen, the server generates a password on first start."""
    import getpass
    user = admin_user or os.environ.get("SL_ADMIN_USER", "")
    pw = admin_password or os.environ.get("SL_ADMIN_PASSWORD", "")
    if pw and len(pw) < 10:
        raise DeployError("the admin password must be at least 10 characters")
    if not prompt or not sys.stdin.isatty():
        return user.strip(), pw
    if not user:
        user = input("Admin username [admin]: ").strip() or "admin"
    if not pw:
        for _ in range(3):
            p1 = getpass.getpass("Admin password (min 10 chars, Enter = generate one at first start): ")
            if not p1:
                break
            if len(p1) < 10:
                print("too short - at least 10 characters")
                continue
            if getpass.getpass("Repeat: ") != p1:
                print("passwords differ")
                continue
            pw = p1
            break
        else:
            raise DeployError("no valid password entered (service not installed; run the command again)")
    return user.strip(), pw


def _ensure_admin(py: str, env_file: Path, config_dir: Path, admin_user: str, admin_password: str, prompt: bool) -> str:
    """Linux: set the admin login in the service's own settings (through the service environment) unless one exists.
    Returns a line describing what happened."""
    env = {k: v for k, v in os.environ.items() if k not in ("SL_ADMIN_USER", "SL_ADMIN_PASSWORD")}
    env.update(SL_CONFIG_DIR=str(config_dir), SL_ENV_FILE=str(env_file))
    r = _run([py, "-c", _CRED_CODE, "check"], check=False, quiet=True, env=env)
    exists = (r.stdout or "").strip() == "set"
    explicit = bool(admin_password or os.environ.get("SL_ADMIN_PASSWORD"))
    if exists and not explicit:
        return "kept the existing admin login"
    user, pw = _ask_admin(admin_user, admin_password, prompt)
    if not pw:
        if user and not exists:
            _run([py, "-c", _CRED_CODE, "set"], check=False, quiet=True, env={**env, "SL_NEW_ADMIN_USER": user})
        return ("a password will be generated at first start: "
                f"journalctl -u {SERVICE_NAME} --no-pager | grep -A4 'first start'")
    r = _run([py, "-c", _CRED_CODE, "set"], check=False, quiet=True,
             env={**env, "SL_NEW_ADMIN_USER": user, "SL_NEW_ADMIN_PASSWORD": pw})
    if r.returncode:
        raise DeployError("could not save the admin login: " + (r.stderr or r.stdout).strip()[-300:])
    return f"admin login saved (user: {user or 'admin'})"


def _ensure_admin_inproc(config_dir: Path, admin_user: str, admin_password: str, prompt: bool) -> str:
    """Windows: same thing in this process (the Windows service keeps its settings in ProgramData)."""
    config_dir.mkdir(parents=True, exist_ok=True)
    os.environ["SL_CONFIG_DIR"] = str(config_dir)
    from .config import Settings
    s = Settings()
    exists = bool(s.get("admin_password_hash") or s.get("admin_password"))
    explicit = bool(admin_password or os.environ.get("SL_ADMIN_PASSWORD"))
    if exists and not explicit:
        return "kept the existing admin login"
    user, pw = _ask_admin(admin_user, admin_password, prompt)
    if user:
        s.update({"admin_user": user})
    if pw:
        from .server.security import hash_password
        s.set_internal("admin_password_hash", hash_password(pw))
        return f"admin login saved (user: {user or 'admin'})"
    return "a password will be generated at first start (see the service log)"


def _base_python() -> str:
    """A Python that the unprivileged service user can run: never one that lives in a home folder."""
    for c in (sys.executable, shutil.which("python3") or "", "/usr/bin/python3"):
        if c and os.path.exists(c) and not os.path.realpath(c).startswith(("/home/", "/root/")):
            return c
    raise DeployError("no system-wide Python found (only copies inside home folders). "
                      "Install one: `sudo apt install python3 python3-venv` or `sudo pymgr install 3.13 --system`.")


def _ensure_runtime() -> str:
    """Create/refresh /opt/synclayer (a root-owned venv with this same Synclayer) and return its python.
    The service always runs from here, whatever way the command that installed it was installed."""
    vpy = LINUX_APP_DIR / "bin" / "python"
    if not vpy.exists():
        print(f"creating {LINUX_APP_DIR} ...")
        LINUX_APP_DIR.mkdir(parents=True, exist_ok=True)
        base = _base_python()
        r = _run([base, "-m", "venv", str(LINUX_APP_DIR)], check=False, quiet=True)
        if r.returncode and shutil.which("apt-get"):
            print("venv module missing - installing python3-venv ...")
            _run(["apt-get", "update"], check=False, quiet=True)
            _run(["apt-get", "install", "-y", "python3-venv"], check=False, quiet=True)
            r = _run([base, "-m", "venv", str(LINUX_APP_DIR)], check=False, quiet=True)
        if r.returncode or not vpy.exists():
            raise DeployError(f"could not create {LINUX_APP_DIR}: {(r.stderr or r.stdout).strip()[-300:]}")
    from ._version import __version__
    src = Path(__file__).resolve().parents[1]
    targets = ([str(src)] if (src / "pyproject.toml").is_file() else [f"synclayer=={__version__}"]) + ["synclayer"]
    print("installing Synclayer into the service environment ...")
    for t in targets:
        r = _run([str(vpy), "-m", "pip", "install", "--quiet", "--upgrade", t], check=False, quiet=True)
        if r.returncode == 0:
            break
    else:
        raise DeployError("pip could not install Synclayer into the service environment:\n" + (r.stderr or r.stdout)[-600:])
    return str(vpy)


def _link_cli() -> str:
    """/usr/local/bin/synclayer -> the service environment, so plain `sudo synclayer ...` always works."""
    src, dst = LINUX_APP_DIR / "bin" / "synclayer", Path("/usr/local/bin/synclayer")
    if not src.exists():
        return ""
    if dst.is_symlink() or not dst.exists():
        if dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)
        return f"  command       : {dst} (works with sudo)\n"
    return ""


def _linux_install(env_file: str | None, domain: str, enable_now: bool = True, email: str = "",
                   admin_user: str = "", admin_password: str = "", prompt: bool = True) -> str:
    need_root("Installing the service")
    if not shutil.which("systemctl"):
        raise DeployError("systemd not found (this command targets Ubuntu/Debian and other systemd distros)")
    py = _ensure_runtime()
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
    if email:
        set_env_key(target_env, "SL_EMAIL", email)
    _run(["chown", f"root:{LINUX_USER}", str(target_env)])
    os.chmod(target_env, 0o640)
    cred_note = _ensure_admin(py, target_env, LINUX_DATA / "config", admin_user, admin_password, prompt)
    _run(["chown", "-R", f"{LINUX_USER}:{LINUX_USER}", str(LINUX_DATA)])   # after: the login was written as root
    os.chmod(LINUX_DATA / "config", 0o700)
    UNIT_PATH.write_text(render_unit(py), "utf-8")
    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable"] + (["--now"] if enable_now else []) + [f"{SERVICE_NAME}.service"])
    return (f"Service '{SERVICE_NAME}' installed and enabled (starts at boot).\n"
            f"  settings file : {target_env}   (edit it; the server reloads it live)\n"
            f"  data          : {LINUX_DATA}\n"
            + _link_cli() +
            f"  runtime       : {LINUX_APP_DIR} (the service runs from here)\n"
            f"  logs          : journalctl -u {SERVICE_NAME} -f\n"
            f"  admin login   : {cred_note}\n"
            f"  change later  : sudo synclayer server passwd   (uses {LINUX_DATA}/config automatically)")


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
            no_start: bool = False, port: int | None = None, email: str = "",
            admin_user: str = "", admin_password: str = "", prompt: bool = True) -> str:
    """action: install | uninstall | start | stop | restart | status | logs"""
    if sys.platform.startswith("win"):
        from . import winservice
        note = ""
        if action == "install":
            base = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Synclayer" / "config"
            note = "\nadmin login: " + _ensure_admin_inproc(base, admin_user, admin_password, prompt)
        return winservice.control(action, env_file=env_file, no_start=no_start, port=port) + note
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
        return _linux_install(env_file, domain, enable_now=not no_start, email=email,
                              admin_user=admin_user, admin_password=admin_password, prompt=prompt)
    if action == "uninstall":
        return _linux_uninstall()
    return _linux_control(action)


# ----------------------------------------------------------------------------- public: nginx
def render_nginx(domain: str, port: int = 8787, max_upload_mb: int = 0, cert: str = "", key: str = "",
                 upstream_host: str = "127.0.0.1", listen_port: int = 0, https_port: int = 0) -> str:
    """Server block for nginx. Without cert/key it serves plain HTTP (add TLS with certbot or a certificate);
    with cert and key it serves HTTPS and redirects HTTP to it.
    No domain = IP mode: the block answers for any host name (default_server), so http://SERVER-IP[:port]/ works.
    listen_port / https_port are the PUBLIC ports nginx listens on (default 80 / 443)."""
    if domain and not re.fullmatch(r"[A-Za-z0-9.-]+", domain):
        raise DeployError("--domain may only contain letters, digits, dots and dashes")
    ip_mode = not domain
    sname = domain or "_"
    ds = " default_server" if ip_mode else ""
    hp, tp = listen_port or 80, https_port or 443
    body = f"{max_upload_mb}m" if max_upload_mb else "0"
    proxy = f"""\
    client_max_body_size {body};          # 0 = unlimited; the server enforces its own limits/quota

    location / {{
        proxy_pass http://synclayer_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
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
        tail = "" if tp == 443 else f":{tp}"
        return head + f"""\
server {{
    listen {hp}{ds};
    listen [::]:{hp}{ds};
    server_name {sname};
    location /.well-known/acme-challenge/ {{ root /var/www/html; }}
    location / {{ return 301 https://$host{tail}$request_uri; }}
}}

server {{
    listen {tp} ssl http2{ds};
    listen [::]:{tp} ssl http2{ds};
    server_name {sname};

    ssl_certificate     {cert};
    ssl_certificate_key {key};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:synclayer_ssl:10m;
    add_header Strict-Transport-Security "max-age=31536000" always;

{proxy}}}
"""
    return head + f"""\
server {{
    listen {hp}{ds};
    listen [::]:{hp}{ds};
    server_name {sname};

{proxy}}}
"""


def _detect_ip() -> str:
    """The address other machines most likely use to reach this one (best effort, no traffic is sent)."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("192.0.2.1", 9))
            return sk.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _self_signed(host: str, install_packages: bool = False) -> tuple[str, str]:
    """Create (or reuse) a self-signed certificate for an IP / host name. Browsers warn once until you trust it."""
    if not shutil.which("openssl") and install_packages and shutil.which("apt-get"):
        _run(["apt-get", "install", "-y", "openssl"], quiet=True)
    if not shutil.which("openssl"):
        raise DeployError("openssl not found. Install it:  sudo apt install openssl   (or add --install-packages)")
    d = LINUX_ETC / "tls"
    d.mkdir(parents=True, exist_ok=True)
    crt, key = d / "selfsigned.crt", d / "selfsigned.key"
    if not (crt.exists() and key.exists()):
        san = f"IP:{host}" if re.fullmatch(r"[0-9.]+|[0-9a-fA-F:]+", host) else f"DNS:{host}"
        _run(["openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "825", "-keyout", str(key),
              "-out", str(crt), "-subj", f"/CN={host}", "-addext", f"subjectAltName={san}"], quiet=True)
        os.chmod(key, 0o600)
    return str(crt), str(key)


def _nginx_paths() -> tuple[Path, Path | None]:
    if NGINX_AVAILABLE.is_dir() and NGINX_ENABLED.is_dir():       # Debian/Ubuntu layout
        return NGINX_AVAILABLE / NGINX_NAME, NGINX_ENABLED / NGINX_NAME
    return NGINX_CONFD / NGINX_NAME, None                         # RHEL/Alpine/other layout


def nginx_install(domain: str, port: int = 8787, max_upload_mb: int = 0, certbot: bool = False,
                  email: str = "", cert: str = "", key: str = "", install_packages: bool = False,
                  env_file: str | None = None, listen_port: int = 0, https_port: int = 0,
                  self_signed: bool = False, ip: str = "") -> str:
    """domain empty = IP mode (no domain needed): proxy on http://SERVER-IP[:listen_port]/ , optionally with a
    self-signed certificate (self_signed=True). Certbot/Let's Encrypt needs a real domain."""
    need_root("Installing the nginx site")
    if certbot and not domain:
        raise DeployError("--certbot needs a domain name (Let's Encrypt cannot certify a bare IP here). "
                          "Add --domain, or use --self-signed for encryption without a domain.")
    if self_signed and (cert or key):
        raise DeployError("use either --self-signed or --cert/--key, not both")
    if bool(cert) != bool(key):
        raise DeployError("--cert and --key go together")
    host_ip = ip or ("" if domain else _detect_ip())
    if install_packages and shutil.which("apt-get"):
        pk = ["nginx"] + (["certbot", "python3-certbot-nginx"] if certbot else [])
        _run(["apt-get", "update"], quiet=True)
        _run(["apt-get", "install", "-y"] + pk)
    if not shutil.which("nginx"):
        raise DeployError("nginx not found. Install it:  sudo apt install nginx"
                          + (" certbot python3-certbot-nginx" if certbot else "")
                          + "   (or add --install-packages)")
    if self_signed:
        cert, key = _self_signed(domain or host_ip, install_packages)
    avail, enabled = _nginx_paths()
    stock = NGINX_ENABLED / "default"
    stock_note = ""
    if not domain and (listen_port or 80) == 80 and stock.is_symlink():   # the stock "Welcome to nginx" site owns port 80
        stock.unlink()
        stock_note = "disabled nginx's stock 'default' site (it owned port 80); restore: sudo ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/"
    avail.write_text(render_nginx(domain, port, max_upload_mb, cert, key, listen_port=listen_port, https_port=https_port), "utf-8")
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
    notes = [f"nginx site written: {avail}"] + ([stock_note] if stock_note else [])

    env = Path(env_file) if env_file else (LINUX_ETC / "synclayer.env")
    if env.exists():
        if domain:
            set_env_key(env, "SL_DOMAIN", domain)
        if email:
            set_env_key(env, "SL_EMAIL", email)
        set_env_key(env, "SL_TRUST_PROXY", "true")
        set_env_key(env, "SL_HOST", "127.0.0.1")
        set_env_key(env, "SL_PORT", str(port))
        notes.append(f"updated {env}: {'SL_DOMAIN, ' if domain else ''}SL_TRUST_PROXY=true, SL_HOST=127.0.0.1 "
                     f"-> restart the server once:  sudo synclayer service restart")
    else:
        notes.append("remember to set  SL_TRUST_PROXY=true  and  SL_HOST=127.0.0.1  for the server "
                     "(then restart it) so real client addresses reach the login rate limiter.")

    if certbot:
        if not shutil.which("certbot"):
            raise DeployError("certbot not found:  sudo apt install certbot python3-certbot-nginx")
        if not email and sys.stdin.isatty():
            email = input("Email for certificate notices (Enter to skip; saved as SL_EMAIL): ").strip()
            if email and env.exists():
                set_env_key(env, "SL_EMAIL", email)
        cmd = ["certbot", "--nginx", "-d", domain, "--non-interactive", "--agree-tos", "--redirect"]
        cmd += ["-m", email] if email else ["--register-unsafely-without-email"]
        if not email:
            notes.append("No email set: certbot registered without one (no expiry notices). Add it later: SL_EMAIL / `synclayer server set email you@example.com`.")
        _run(cmd)
        notes.append("HTTPS enabled by certbot (auto-renewal is installed by the certbot package).")
    elif domain:
        notes.append(f"HTTP only so far. Add HTTPS:  sudo synclayer nginx install --domain {domain} --certbot --email you@example.com   (or set SL_EMAIL once)")
    hp, tp = listen_port or 80, https_port or 443
    scheme, pp = ("https", tp) if (cert and key) else ("http", hp)
    host = domain or host_ip
    shown = f"{scheme}://{host}" + ("" if (scheme, pp) in (("http", 80), ("https", 443)) else f":{pp}") + "/"
    notes.append(f"Open: {shown}" + ("   (self-signed certificate: the browser warns once; install the .crt from "
                 f"{LINUX_ETC / 'tls'} on your devices to trust it)" if self_signed else ""))
    if not domain:
        notes.append("No domain: if this machine is behind a router/NAT or a cloud firewall, forward/open the port "
                     "above and use the PUBLIC IP in the address.")
    ports = sorted({hp, tp} if (cert and key) else {hp})
    notes.append("Firewall (Ubuntu):  " + "; ".join(f"sudo ufw allow {p}/tcp" for p in ports)
                 + ("   or   sudo ufw allow 'Nginx Full'" if ports == [80, 443] else ""))
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
