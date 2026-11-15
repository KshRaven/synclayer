"""Accounts and folder grants for multi-user servers.

The original admin (SL_ADMIN_USER / password) is unchanged. Extra people are "members": each gets a private
drive (`u:<name>`) and can be given other people's folders (`s:<grant id>`) read-only or read/write.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from .security import hash_password, verify_password

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,31}$")
_DUMMY = hash_password("not-a-real-password", iters=1000)


def _load(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), "utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


class UserStore:
    def __init__(self, path: Path):
        self.path, self.lock = Path(path), threading.Lock()

    def _all(self) -> dict:
        return _load(self.path, {})

    def get(self, name: str) -> dict | None:
        return self._all().get(name.lower())

    def exists(self, name: str) -> bool:
        return name.lower() in self._all()

    def create(self, name: str, password: str, quota_mb: int = 0, display: str = "") -> dict:
        if not NAME_RE.match(name):
            raise ValueError("Username: 2-32 letters, digits, dot, dash or underscore")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        with self.lock:
            data = self._all()
            if name.lower() in data:
                raise ValueError("That username is taken")
            data[name.lower()] = {"name": name, "hash": hash_password(password), "quota_mb": max(0, int(quota_mb)),
                                  "display": display[:60], "created": int(time.time()), "disabled": False}
            _save(self.path, data)
        return self.public(data[name.lower()])

    def verify(self, name: str, password: str) -> dict | None:
        rec = self.get(name or "")
        ok = verify_password(password, rec["hash"] if rec else _DUMMY)   # same work either way
        return rec if rec and ok and not rec.get("disabled") else None

    def update(self, name: str, password: str | None = None, quota_mb: int | None = None,
               disabled: bool | None = None, display: str | None = None) -> dict:
        with self.lock:
            data = self._all()
            rec = data.get(name.lower())
            if not rec:
                raise KeyError(name)
            if password is not None:
                if len(password) < 8:
                    raise ValueError("Password must be at least 8 characters")
                rec["hash"] = hash_password(password)
            if quota_mb is not None:
                rec["quota_mb"] = max(0, int(quota_mb))
            if disabled is not None:
                rec["disabled"] = bool(disabled)
            if display is not None:
                rec["display"] = display[:60]
            _save(self.path, data)
        return self.public(rec)

    def delete(self, name: str) -> bool:
        with self.lock:
            data = self._all()
            if data.pop(name.lower(), None) is None:
                return False
            _save(self.path, data)
            return True

    @staticmethod
    def public(rec: dict) -> dict:
        return {k: rec.get(k) for k in ("name", "display", "quota_mb", "created", "disabled")}

    def list(self) -> list[dict]:
        return sorted((self.public(r) for r in self._all().values()), key=lambda r: r["name"].lower())


class Grants:
    """Folder shared with a specific user: {id, owner, root, path, to, perm('ro'|'rw'), created}."""

    def __init__(self, path: Path):
        self.path, self.lock = Path(path), threading.Lock()

    def _all(self) -> dict:
        return _load(self.path, {})

    def add(self, owner: str, root: str, rel: str, to: str, perm: str) -> dict:
        if perm not in ("ro", "rw"):
            raise ValueError("perm must be ro or rw")
        with self.lock:
            data = self._all()
            for g in data.values():
                if g["owner"] == owner and g["root"] == root and g["path"] == rel and g["to"].lower() == to.lower():
                    g["perm"] = perm
                    _save(self.path, data)
                    return g
            gid = secrets.token_hex(5)
            data[gid] = {"id": gid, "owner": owner, "root": root, "path": rel, "to": to, "perm": perm,
                         "created": int(time.time())}
            _save(self.path, data)
            return data[gid]

    def get(self, gid: str) -> dict | None:
        return self._all().get(gid)

    def received(self, user: str) -> list[dict]:
        return [g for g in self._all().values() if g["to"].lower() == user.lower()]

    def given(self, owner: str, root: str | None = None, rel: str | None = None) -> list[dict]:
        return [g for g in self._all().values() if g["owner"] == owner
                and (root is None or g["root"] == root) and (rel is None or g["path"] == rel)]

    def for_root(self, root: str) -> list[dict]:
        return [g for g in self._all().values() if g["root"] == root]

    def remove(self, gid: str, who: str, is_admin: bool = False) -> bool:
        with self.lock:
            data = self._all()
            g = data.get(gid)
            if not g or not (is_admin or g["owner"] == who or g["to"].lower() == who.lower()):
                return False
            del data[gid]
            _save(self.path, data)
            return True

    def drop_where(self, pred) -> int:
        with self.lock:
            data = self._all()
            keep = {k: v for k, v in data.items() if not pred(v)}
            n = len(data) - len(keep)
            if n:
                _save(self.path, keep)
            return n
