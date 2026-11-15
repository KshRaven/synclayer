"""Thin HTTP client for the Synclayer server API."""
from __future__ import annotations

import os
import time
from pathlib import Path

import httpx


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"[{status}] {detail}" if status else detail)
        self.status, self.detail = status, detail


LIMITS = {"up": 0, "down": 0}   # bytes per second, 0 = unlimited (set from the app's bandwidth settings)


def set_limits(up_kb: int = 0, down_kb: int = 0) -> None:
    LIMITS["up"], LIMITS["down"] = max(0, int(up_kb)) * 1024, max(0, int(down_kb)) * 1024


class _Pace:
    """Sleeps just enough to keep a transfer under a bytes/second cap."""

    def __init__(self, kind: str):
        self.kind, self.t0, self.sent = kind, time.monotonic(), 0

    def __call__(self, n: int) -> None:
        cap = LIMITS[self.kind]
        self.sent += n
        if cap:
            ahead = self.sent / cap - (time.monotonic() - self.t0)
            if ahead > 0:
                time.sleep(min(ahead, 2.0))


def _chunks(fp, size=1 << 20):
    pace = _Pace("up")
    size = min(size, max(16 * 1024, LIMITS["up"])) if LIMITS["up"] else size
    while True:
        b = fp.read(size)
        if not b:
            return
        pace(len(b))
        yield b


def _paced(data: bytes, size: int = 64 * 1024):
    pace = _Pace("up")
    for i in range(0, len(data), size):
        piece = data[i:i + size]
        pace(len(piece))
        yield piece


class Client:
    def __init__(self, base_url: str, token: str = ""):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, follow_redirects=True,
                                 timeout=httpx.Timeout(30.0, read=600.0, write=600.0))

    def close(self):
        self.http.close()

    def _req(self, method: str, url: str, retries: int = 2, **kw) -> httpx.Response:
        """One request; network blips and 502/503/504 are retried with a short backoff (not for streamed bodies)."""
        for attempt in range(retries + 1):
            try:
                r = self.http.request(method, url, **kw)
            except httpx.HTTPError as exc:
                if attempt < retries and "content" not in kw:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise ApiError(0, f"{type(exc).__name__}: {exc}") from exc
            if r.status_code in (502, 503, 504) and attempt < retries and "content" not in kw:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text[:200]
            raise ApiError(r.status_code, str(detail))
        return r

    # ---- session ----
    def health(self) -> dict:
        return self._req("GET", "/api/health").json()

    def login(self, user: str, password: str, device: str | None = None, code: str = "") -> dict:
        body = {"username": user, "password": password, "device": device}
        if code:
            body["code"] = code
        return self._req("POST", "/api/auth/login", json=body).json()

    def me(self) -> dict:
        return self._req("GET", "/api/me").json()

    def usage(self) -> dict:
        return self._req("GET", "/api/usage").json()

    def roots(self) -> list[str]:
        return self._req("GET", "/api/roots").json()["roots"]

    # ---- files ----
    def list(self, root: str = "main", path: str = "") -> list[dict]:
        return self._req("GET", "/api/files", params={"root": root, "path": path}).json()["items"]

    def manifest(self, root: str, path: str = "") -> dict:
        return self._req("GET", "/api/manifest", params={"root": root, "path": path}).json()["entries"]

    def hash(self, root: str, path: str) -> str:
        return self._req("GET", "/api/hash", params={"root": root, "path": path}).json()["sha256"]

    CHUNK = 8 << 20
    RESUMABLE_FROM = 32 << 20

    def upload(self, root: str, path: str, local: Path, progress=None):
        """Upload one file. Big files go in resumable chunks and survive dropped connections."""
        st = os.stat(local)
        if st.st_size >= self.RESUMABLE_FROM:
            return self.upload_resumable(root, path, local, progress)
        last: ApiError | None = None
        for attempt in range(3):
            try:
                with open(local, "rb") as fp:
                    self._req("PUT", "/api/files", params={"root": root, "path": path}, content=_chunks(fp),
                              headers={"X-SL-Mtime": str(st.st_mtime), "Content-Length": str(st.st_size)})
                if progress:
                    progress(st.st_size, st.st_size)
                return
            except ApiError as exc:
                last = exc
                if exc.status not in (0, 502, 503, 504):
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise last  # type: ignore[misc]

    def upload_resumable(self, root: str, path: str, local: Path, progress=None, attempts: int = 6):
        st = os.stat(local)
        uid = self._req("POST", "/api/uploads", json={"root": root, "path": path, "size": st.st_size,
                                                        "mtime": st.st_mtime}).json()["id"]
        offset, fails = 0, 0
        with open(local, "rb") as fp:
            while True:
                fp.seek(offset)
                data = fp.read(self.CHUNK)
                try:
                    r = self._req("PATCH", f"/api/uploads/{uid}", params={"root": root}, content=_paced(data) if LIMITS["up"] else data,
                                  headers={"Upload-Offset": str(offset), "Content-Type": "application/octet-stream",
                                           "Content-Length": str(len(data))})
                    offset, fails = r.json()["offset"], 0
                    if progress:
                        progress(offset, st.st_size)
                    if r.json()["done"] or (not data and offset >= st.st_size):
                        return
                except ApiError as exc:
                    fails += 1
                    if exc.status not in (0, 409, 502, 503, 504) or fails > attempts:
                        if exc.status not in (0, 409, 502, 503, 504):
                            try:
                                self._req("DELETE", f"/api/uploads/{uid}", params={"root": root}, retries=0)
                            except ApiError:
                                pass
                        raise
                    time.sleep(min(30, 2 ** fails))
                    try:    # ask the server how much it really has, then carry on from there
                        offset = self._req("GET", f"/api/uploads/{uid}", params={"root": root}).json()["offset"]
                    except ApiError:
                        pass

    def download(self, root: str, path: str, dest: Path, mtime: float | None = None):
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".slpart")
        try:
            with self.http.stream("GET", "/api/download", params={"root": root, "path": path}) as r:
                if r.status_code >= 400:
                    r.read()
                    raise ApiError(r.status_code, r.text[:200])
                pace = _Pace("down")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
                        pace(len(chunk))
            if mtime:
                os.utime(tmp, (time.time(), mtime))
            os.replace(tmp, dest)
        except httpx.HTTPError as exc:
            tmp.unlink(missing_ok=True)
            raise ApiError(0, f"{type(exc).__name__}: {exc}") from exc
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def mkdir(self, root: str, path: str):
        self._req("POST", "/api/mkdir", json={"root": root, "path": path})

    def move(self, root: str, src: str, dst: str):
        self._req("POST", "/api/move", json={"root": root, "src": src, "dst": dst})

    def delete(self, root: str, path: str, permanent: bool = False):
        """Delete moves to the server trash (restorable) unless permanent=True."""
        self._req("DELETE", "/api/files", params={"root": root, "path": path, "permanent": str(permanent).lower()})

    def copy(self, root: str, paths: list[str], dest: str):
        return self._req("POST", "/api/batch", json={"root": root, "op": "copy", "paths": paths, "dest": dest}).json()

    def batch(self, root: str, op: str, paths: list[str], dest: str = ""):
        return self._req("POST", "/api/batch", json={"root": root, "op": op, "paths": paths, "dest": dest}).json()

    # ---- drive features ----
    def search(self, q: str, root: str = "main", kind: str = "") -> list[dict]:
        return self._req("GET", "/api/search", params={"root": root, "q": q, "kind": kind}).json()["items"]

    def recent(self, root: str = "main", limit: int = 60) -> list[dict]:
        return self._req("GET", "/api/recent", params={"root": root, "limit": limit}).json()["items"]

    def trash(self, root: str = "main") -> list[dict]:
        return self._req("GET", "/api/trash", params={"root": root}).json()["items"]

    def trash_restore(self, tid: str, root: str = "main") -> str:
        return self._req("POST", "/api/trash/restore", json={"root": root, "id": tid}).json()["path"]

    def trash_purge(self, tid: str = "", root: str = "main"):
        self._req("DELETE", "/api/trash", params={"root": root, "id": tid})

    def versions(self, path: str, root: str = "main") -> list[dict]:
        return self._req("GET", "/api/versions", params={"root": root, "path": path}).json()["items"]

    def version_restore(self, path: str, vid: str, root: str = "main"):
        self._req("POST", "/api/versions/restore", json={"root": root, "path": path, "id": vid})

    def share(self, path: str, root: str = "main", days: int = 7, password: str = "", max_downloads: int = 0) -> dict:
        """Create a public link. Returns {token, url (relative to the server), expires}."""
        return self._req("POST", "/api/shares", json={"root": root, "path": path, "days": days,
                                                       "password": password, "max_downloads": max_downloads}).json()

    def shares(self) -> list[dict]:
        return self._req("GET", "/api/shares").json()["items"]

    def unshare(self, token: str):
        self._req("DELETE", f"/api/shares/{token}")

    def star(self, path: str, root: str = "main"):
        self._req("PUT", "/api/stars", json={"root": root, "path": path})

    def unstar(self, path: str, root: str = "main"):
        self._req("DELETE", "/api/stars", params={"root": root, "path": path})

    def stars(self) -> list[dict]:
        return self._req("GET", "/api/stars").json()["items"]

    # ---- admin ----
    def admin_settings(self) -> dict:
        return self._req("GET", "/api/admin/settings").json()

    def admin_usage(self) -> dict:
        return self._req("GET", "/api/admin/usage").json()

    def admin_update(self, changes: dict) -> dict:
        return self._req("PATCH", "/api/admin/settings", json={"changes": changes}).json()

    def admin_password(self, new_password: str):
        self._req("POST", "/api/admin/password", json={"new_password": new_password})

    def admin_tokens(self) -> list[dict]:
        return self._req("GET", "/api/admin/tokens").json()["tokens"]

    def admin_token_create(self, name: str, read_only: bool = False) -> dict:
        return self._req("POST", "/api/admin/tokens", json={"name": name, "read_only": read_only}).json()

    def admin_token_revoke(self, tid: str):
        self._req("DELETE", f"/api/admin/tokens/{tid}")

    def admin_rotate(self) -> str:
        return self._req("POST", "/api/admin/rotate-secret").json()["token"]

    def admin_devices(self) -> dict:
        return self._req("GET", "/api/admin/devices").json()
