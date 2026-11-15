"""Client-side configuration (server address, token, sync profiles)."""
from __future__ import annotations

import json
import os
import re
import socket
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from platformdirs import user_config_dir

from .. import APP_NAME


def client_config_dir() -> Path:
    p = os.environ.get("SL_CLIENT_DIR")
    path = Path(p).expanduser() if p else Path(user_config_dir(APP_NAME)) / "client"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_server_url() -> str:
    """SL_SERVER env > value baked in at build time (private builds) > nothing: the app asks on first launch."""
    if os.environ.get("SL_SERVER"):
        return os.environ["SL_SERVER"]
    try:
        data = json.loads((Path(__file__).resolve().parent.parent / "_build_defaults.json").read_text("utf-8"))
        if data.get("server_url"):
            return data["server_url"]
    except (OSError, ValueError):
        pass
    return ""


def normalize_url(url: str) -> str:
    """'files.example.com' -> 'https://files.example.com'; keeps http:// for explicit/local addresses."""
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if "://" not in u:
        host = u.split("/")[0].split(":")[0].lower()
        local = host in ("localhost", "127.0.0.1") or host.endswith(".local") or re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", host)
        u = ("http://" if local else "https://") + u
    return u


def default_sync_dir() -> Path:
    return Path.home() / "Synclayer"


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


@dataclass
class Profile:
    name: str
    local_dir: str
    remote_root: str = "main"
    remote_path: str = ""
    interval: int = 60      # safety-net period; changes sync within seconds anyway
    enabled: bool = True
    mode: str = "two-way"   # two-way | upload (backup: never changes/deletes local files) | download (mirror)
    propagate_deletes: bool = False   # False: deleting here never deletes on the server; True: deletions sync both ways
    sid: str = ""           # id of the server this folder belongs to (set when loaded; keeps sync state apart)


@dataclass
class Server:
    """One server this device is connected to (your own, a friend's ...), with its own sign-in and sync folders."""
    id: str
    url: str
    name: str = ""
    token: str = ""
    user: str = ""
    profiles: list = field(default_factory=list)  # list[Profile]

    @property
    def label(self) -> str:
        return self.name or self.url.split("://")[-1]


class ClientConfig:
    """Several servers, one active. The old single-server attributes (server_url, token, profiles) keep working:
    they read and write the active server, so existing code and scripts need no change."""

    def __init__(self):
        self.servers: list[Server] = []
        self.active: str = ""
        self.device: str = socket.gethostname()
        self.prefs: dict = {}

    # ---- servers ----
    @staticmethod
    def path() -> Path:
        return client_config_dir() / "config.json"

    def current(self) -> Server | None:
        return next((s for s in self.servers if s.id == self.active), None) or (self.servers[0] if self.servers else None)

    def add_server(self, url: str, name: str = "", token: str = "", user: str = "", activate: bool = True) -> Server:
        url = normalize_url(url)
        srv = next((s for s in self.servers if s.url.lower() == url.lower()), None)
        if srv is None:
            srv = Server(id=uuid.uuid4().hex[:8], url=url, name=name)
            self.servers.append(srv)
        if name:
            srv.name = name
        if token:
            srv.token, srv.user = token, user or srv.user
        if activate:
            self.active = srv.id
        return srv

    def remove_server(self, sid: str):
        self.servers = [s for s in self.servers if s.id != sid]
        if self.active == sid:
            self.active = self.servers[0].id if self.servers else ""

    def switch(self, sid: str):
        if any(s.id == sid for s in self.servers):
            self.active = sid

    def all_profiles(self):
        """[(server, profile)] for every server with a sign-in; used by the background sync."""
        return [(s, p) for s in self.servers if s.token for p in s.profiles]

    # ---- single-server compatibility ----
    @property
    def server_url(self) -> str:
        s = self.current()
        return s.url if s else default_server_url()

    @server_url.setter
    def server_url(self, value: str):
        if (value or "").strip():
            self.add_server(value)

    @property
    def token(self) -> str:
        s = self.current()
        return s.token if s else ""

    @token.setter
    def token(self, value: str):
        s = self.current()
        if s is None:
            if not value:
                return
            s = self.add_server(default_server_url() or "http://localhost:8787")
        s.token = value
        if not value:
            s.user = ""

    @property
    def profiles(self) -> list:
        s = self.current()
        return s.profiles if s else []

    @profiles.setter
    def profiles(self, value: list):
        s = self.current()
        if s is not None:
            s.profiles = value

    # ---- persistence ----
    @classmethod
    def load(cls) -> "ClientConfig":
        cfg = cls()
        try:
            raw = json.loads(cls.path().read_text("utf-8"))
        except (OSError, ValueError):
            raw = {}
        cfg.device = raw.get("device") or cfg.device
        if isinstance(raw.get("prefs"), dict):
            cfg.prefs = raw["prefs"]
        if "servers" in raw:
            for sd in raw.get("servers", []):
                try:
                    srv = Server(id=sd["id"], url=sd["url"], name=sd.get("name", ""), token=sd.get("token", ""),
                                 user=sd.get("user", ""))
                except KeyError:
                    continue
                for p in sd.get("profiles", []):
                    try:
                        srv.profiles.append(Profile(**{**p, "sid": srv.id}))
                    except TypeError:
                        continue
                cfg.servers.append(srv)
            cfg.active = raw.get("active", "")
        elif raw.get("server_url") and (raw.get("token") or raw.get("profiles")):   # older single-server file
            srv = cfg.add_server(raw["server_url"], token=raw.get("token", ""))
            for p in raw.get("profiles", []):
                try:
                    srv.profiles.append(Profile(**{**p, "sid": srv.id}))
                except TypeError:
                    continue
        elif default_server_url():
            cfg.add_server(default_server_url(), activate=True)      # a private build that ships with its server
        return cfg

    def save(self):
        for s in self.servers:
            for p in s.profiles:
                p.sid = s.id
        data = {"active": self.current().id if self.current() else "", "device": self.device, "prefs": self.prefs,
                "servers": [{"id": s.id, "url": s.url, "name": s.name, "token": s.token, "user": s.user,
                             "profiles": [{k: v for k, v in asdict(p).items() if k != "sid"} for p in s.profiles]}
                            for s in self.servers]}
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), "utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path())

    def pref(self, key: str, default=None):
        return self.prefs.get(key, default)

    def profile(self, name: str):
        return next((p for p in self.profiles if p.name == name), None)
