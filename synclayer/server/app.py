"""Synclayer FastAPI application: auth, files, sync manifest, admin, live events."""
from __future__ import annotations

import asyncio
import contextvars
import re
import mimetypes
import os
import shutil
import tempfile
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from .. import APP_NAME, __version__
from ..common.scan import ignored, scan_tree
from ..config import Settings
from . import library as lib
from .mfa import MfaStore, SmsError
from .users import Grants, UserStore
from .quota import MB, UsageCache, breakdown, check_space, disk_info
from .security import (Presence, Principal, RateLimiter, TokenStore, merge_devices, ct_eq, hash_password, sign, unsign,
                       verify_password)

WEB_DIR = Path(__file__).parent / "web"
CUR: contextvars.ContextVar = contextvars.ContextVar("sl_principal", default=(None, "GET"))


class PwChange(BaseModel):
    current: str
    new_password: str


class GrantBody(BaseModel):
    root: str = "main"
    path: str = ""
    to: str
    perm: str = "ro"


class NewUser(BaseModel):
    name: str
    password: str
    quota_mb: int = 0
    display: str = ""


class UserPatch(BaseModel):
    password: str | None = None
    quota_mb: int | None = None
    disabled: bool | None = None
    display: str | None = None


class LoginBody(BaseModel):
    username: str
    password: str
    device: str | None = None
    code: str | None = None          # second factor (authenticator / text / e-mail / recovery code)


class MfaSendBody(BaseModel):
    username: str
    password: str
    method: str                       # "sms" | "email"


class CodeBody(BaseModel):
    code: str


class TargetBody(BaseModel):
    target: str                       # phone number or e-mail address


class PathBody(BaseModel):
    root: str = "main"
    path: str


class MoveBody(BaseModel):
    root: str = "main"
    src: str
    dst: str


class SettingsBody(BaseModel):
    changes: dict


class TextBody(BaseModel):
    root: str = "main"
    path: str
    content: str
    encoding: str = "utf-8"
    eol: str = "lf"
    mtime: float | None = None


MAX_TEXT_BYTES = 2 * 1024 * 1024  # largest file the in-browser editor will open


class PasswordBody(BaseModel):
    new_password: str


class TokenBody(BaseModel):
    name: str
    read_only: bool = False


class BatchBody(BaseModel):
    root: str = "main"
    op: str
    paths: list[str]
    dest: str = ""

class IdBody(BaseModel):
    root: str = "main"
    id: str
    path: str = ""

class ShareBody(BaseModel):
    root: str = "main"
    path: str
    days: int = 7
    password: str = ""
    max_downloads: int = 0

class UploadStart(BaseModel):
    root: str = "main"
    path: str
    size: int
    mtime: float | None = None


class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.meta: dict[WebSocket, dict] = {}
        self.norm = lambda root: root
        self.visible = lambda meta, root: [root]       # replaced by create_app(): which root names this client sees

    async def broadcast(self, msg: dict):
        dead = []
        src = self.norm(msg.get("root", ""))
        for c in list(self.clients):
            try:
                for root in self.visible(self.meta.get(c, {}), src):
                    await c.send_json({**msg, "root": root})
            except Exception:
                dead.append(c)
        for c in dead:
            self.clients.discard(c)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    tokens = TokenStore(settings.dir / "tokens.json")
    presence = Presence(settings.dir / "presence.json")
    limiter = RateLimiter()
    mfa = MfaStore(settings.dir / "mfa.json")
    hub = Hub()

    def _canon(root: str) -> str:
        if root.startswith("s:"):
            g = grants.get(root[2:])
            return g["root"] if g else root
        return root

    def _visible(meta: dict, root: str) -> list[str]:
        root = _canon(root)
        if meta.get("role") != "member":
            return [root]
        name = meta.get("name", "")
        out = [root] if root == f"u:{name.lower()}" else []
        return out + [f"s:{g['id']}" for g in grants.received(name) if g["root"] == root]
    hub.visible = _visible
    hub.norm = lambda r: norm(r)
    usage = UsageCache()
    users = UserStore(settings.dir / "users.json")
    grants = Grants(settings.dir / "grants.json")
    def stars_of(pr: Principal | None) -> lib.Stars:
        who = re.sub(r"[^A-Za-z0-9._-]", "_", (pr.name if pr and pr.role == "member" else "_admin"))
        return lib.Stars(settings.dir / "stars" / f"{who}.json")
    shares = lib.Shares(settings.dir / "shares.json")

    def cleanup():
        for name, base in all_root_paths().items():
            try:
                lib.Trash(base).expire(int(settings.get("trash_days")))
                lib.Uploads(base).expire()
            except OSError:
                pass

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bootstrap_admin(settings)
        try:
            settings.storage_root()
        except OSError as exc:
            raise RuntimeError(
                f"Cannot create the storage folder ({exc}). The service runs as an unprivileged user: point "
                "SL_STORAGE_ROOT at a folder it can write (e.g. /var/lib/synclayer/files), or give it ownership: "
                "sudo chown -R synclayer:synclayer <folder>. Folders under /home are not writable for the service.") from exc
        async def janitor():
            while True:
                try:
                    await run_in_threadpool(cleanup)
                except Exception:
                    pass
                await asyncio.sleep(3600)
        task = asyncio.create_task(janitor())
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(title=APP_NAME, version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        CUR.set((soft_principal(request), request.method))
        resp = await call_next(request)
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Content-Security-Policy",
                     "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                     "connect-src 'self' ws: wss:; media-src 'self'; frame-src 'self'; frame-ancestors 'self'")
        if request.url.path.startswith("/static") or request.url.path == "/":
            h["Cache-Control"] = "no-cache"
        return resp

    def sid_of(token: str) -> str:
        import hashlib
        return hashlib.sha256(token.encode()).hexdigest()[:8]

    # ---- auth dependencies ---------------------------------------------------
    def soft_principal(request: Request, touch: bool = False) -> Principal | None:
        """Who is calling (None if not signed in). authenticate() enforces; this only identifies."""
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header[:7].lower() == "bearer " else ""
        ip = request.client.host if request.client else ""
        agent = request.headers.get("user-agent", "")
        if token.startswith("dst_"):
            rec = tokens.verify(token)
            if not rec:
                return None
            owner = rec.get("owner") or ""
            if owner:
                u = users.get(owner)
                if not u or u.get("disabled"):
                    return None
            if touch:
                tokens.touch(rec["id"], ip, agent)
            return Principal("member" if owner else "user", owner or rec["name"], bool(rec.get("read_only")))
        if token:
            data = unsign(settings.secret(), token)
            if not data or data.get("typ") != "session":
                return None
            if data.get("u"):
                u = users.get(data["u"])
                if not u or u.get("disabled"):
                    return None
                if touch:
                    presence.touch(sid_of(token), ip, agent)
                return Principal("member", u["name"])
            if touch:
                presence.touch(sid_of(token), ip, agent)
            return Principal("admin", settings.get("admin_user"))
        if request.method == "GET" and request.query_params.get("ticket"):
            data = unsign(settings.secret(), request.query_params["ticket"])
            if data and data.get("typ") == "ticket":
                return Principal(data.get("role", "user"), data.get("name", ""), bool(data.get("ro")))
        return None

    def authenticate(request: Request) -> Principal:
        settings.reload()
        pr = soft_principal(request, touch=True)
        if pr is None:
            raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})
        if settings.get("lockdown") and pr.role != "admin":
            raise HTTPException(503, "Server is in lockdown mode")
        return pr

    def writer(pr: Principal = Depends(authenticate)) -> Principal:
        if settings.get("read_only"):
            raise HTTPException(403, "Server is in read-only mode")
        if pr.read_only:
            raise HTTPException(403, "This device token is read-only")
        if pr.role == "user" and not settings.get("user_writes"):
            raise HTTPException(403, "Only the admin may change files on this server")
        return pr

    def admin_only(pr: Principal = Depends(authenticate)) -> Principal:
        if pr.role != "admin":
            raise HTTPException(403, "Admin only")
        return pr

    def admin_writer(pr: Principal = Depends(admin_only)) -> Principal:
        return pr

    def norm(root: str, pr: Principal | None = None) -> str:
        """Members may say "main" (older clients, scripts): that means their own drive."""
        pr = pr or CUR.get()[0]
        return f"u:{pr.name.lower()}" if root == "main" and pr is not None and pr.role == "member" else root

    def user_base(name: str) -> Path:
        p = settings.storage_root() / "_users" / name.lower()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def owner_base(owner: str, root: str) -> Path | None:
        if root.startswith("u:"):
            return user_base(root[2:]) if users.exists(root[2:]) else None
        return settings.roots().get(root)

    def grant_dir(g: dict) -> Path | None:
        base = owner_base(g["owner"], g["root"])
        if not base:
            return None
        try:
            d = (base.resolve() / g["path"]).resolve()
        except (OSError, ValueError):
            return None
        return d if d.is_dir() and (d == base.resolve() or base.resolve() in d.parents) else None

    def roots_for(pr: Principal | None) -> dict[str, tuple[Path, bool]]:
        """root id -> (folder, writable) for this caller."""
        if pr is None:
            return {}
        if pr.role != "member":
            return {k: (v, True) for k, v in settings.roots().items()}
        out = {f"u:{pr.name.lower()}": (user_base(pr.name), True)}
        for g in grants.received(pr.name):
            d = grant_dir(g)
            if d:
                out[f"s:{g['id']}"] = (d, g["perm"] == "rw")
        return out

    def all_root_paths() -> dict[str, Path]:
        out = dict(settings.roots())
        for u in users.list():
            out[f"u:{u['name'].lower()}"] = user_base(u["name"])
        return out

    def trusted_root(root: str) -> tuple[Path, bool] | None:
        """Resolve any root (for public share links, which are authorised by their token instead)."""
        if root.startswith("s:"):
            g = grants.get(root[2:])
            d = grant_dir(g) if g else None
            return (d, g["perm"] == "rw") if d else None
        b = owner_base("", root)
        return (b, True) if b else None

    def safe_path(root: str, rel: str, trusted: bool = False) -> tuple[Path, Path]:
        pr, method = CUR.get()
        root = root if trusted else norm(root, pr)
        if trusted:
            hit = trusted_root(root)
        else:
            hit = roots_for(pr).get(root)
        if not hit:
            raise HTTPException(404, "Unknown root")
        rbase, writable = hit
        if not writable and method not in ("GET", "HEAD"):
            raise HTTPException(403, "This shared folder is read-only for you")
        try:
            base = rbase.resolve()
            rel = (rel or "").replace("\\", "/").strip("/")
            target = (base / rel).resolve() if rel else base
        except (ValueError, OSError):
            raise HTTPException(400, "Bad path")
        if target != base and base not in target.parents:
            raise HTTPException(400, "Path escapes root")
        if target != base and target.relative_to(base).parts[0] == lib.META:
            raise HTTPException(404, "Not found")
        return base, target

    def check_name(name: str):
        bad = settings.blocked_exts()
        ext = Path(name).suffix.lower()
        if bad and ext in bad:
            raise HTTPException(400, f"Files of type '{ext}' are not allowed on this server")

    def quota_for(root: str, base: Path) -> tuple[int, Path]:
        """(quota bytes, folder whose total size counts against it) for a root."""
        def user_quota(name: str) -> int:
            rec = users.get(name) or {}
            return int(rec.get("quota_mb") or settings.get("user_quota_mb") or 0) * MB
        if root.startswith("u:"):
            return user_quota(root[2:]), base
        if root.startswith("s:"):
            g = grants.get(root[2:])
            ob = owner_base(g["owner"], g["root"]) if g else None
            if g and ob:
                if g["root"].startswith("u:"):
                    return user_quota(g["root"][2:]), ob
                return (int(settings.get("quota_mb")) * MB if g["root"] == "main" else 0), ob
            return 0, base
        return (int(settings.get("quota_mb")) * MB if root == "main" else 0), base

    def space_guard(root: str, base: Path, existing: int = 0):
        """Return check(size) that raises HTTP 507 when a write would break the quota / disk reserve."""
        quota, qbase = quota_for(norm(root), base)
        reserve = int(settings.get("min_free_mb")) * MB
        used = max(0, usage.used(qbase) - existing) if quota else 0
        free = disk_info(base).get("free", 0) + existing if reserve else 0

        def check(size: int):
            try:
                check_space(used=used, quota=quota, free=free, reserve=reserve, size=size)
            except ValueError as exc:
                raise HTTPException(507, str(exc))
        return check

    def storage_report(pr: Principal | None = None, root: str = "") -> dict:
        pr = pr or CUR.get()[0]
        if pr is not None and pr.role == "member":
            rid = root if root in roots_for(pr) else f"u:{pr.name.lower()}"
            base = roots_for(pr)[rid][0]
            quota, qbase = quota_for(rid, base)
            return {"root": rid, "used": usage.used(qbase) if quota or rid.startswith("u:") else usage.used(base),
                    "quota": quota, "reserve": 0, "disk": {}}
        base = settings.storage_root()
        return {"root": "main", "used": usage.used(base),
                "quota": int(settings.get("quota_mb")) * MB,
                "reserve": int(settings.get("min_free_mb")) * MB, "disk": disk_info(base)}

    def relpath(base: Path, target: Path) -> str:
        r = target.relative_to(base).as_posix()
        return "" if r == "." else r

    # ---- public --------------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"ok": True, "name": APP_NAME, "version": __version__}

    def password_ok(username: str, password: str) -> bool:
        stored = settings.get("admin_password_hash")
        plain = settings.get("admin_password")
        # A plain SL_ADMIN_PASSWORD in .env / the environment is the owner's explicit choice and wins over an
        # older generated hash (otherwise editing .env after the first start silently does nothing).
        if plain:
            pw_ok = ct_eq(password, plain)
        else:
            pw_ok = bool(stored) and verify_password(password, stored)
        return bool(ct_eq(username, settings.get("admin_user")) and pw_ok)

    @app.post("/api/auth/login")
    def login(body: LoginBody, request: Request):
        ip = request.client.host if request.client else "?"
        limiter.check(ip)
        settings.reload()
        if body.username.lower() != str(settings.get("admin_user")).lower() and users.exists(body.username):
            rec = users.verify(body.username, body.password)
            if not rec:
                limiter.fail(ip)
                raise HTTPException(401, "Invalid credentials")
            limiter.ok(ip)
            user_base(rec["name"])
            if body.device:
                _, tok = tokens.create(body.device.strip()[:64] or "device", owner=rec["name"])
                return {"token": tok, "role": "member", "persistent": True, "name": rec["name"]}
            exp = time.time() + int(settings.get("session_hours")) * 3600
            return {"token": sign(settings.secret(), {"typ": "session", "u": rec["name"], "exp": exp}),
                    "role": "member", "expires": exp, "name": rec["name"]}
        if not password_ok(body.username, body.password):
            limiter.fail(ip)
            raise HTTPException(401, "Invalid credentials")
        if mfa.enabled():
            if not (body.code or "").strip():
                # password was right: tell the client which second factors it can use (it then asks for a code)
                raise HTTPException(401, "mfa_required:" + ",".join(mfa.methods(settings)))
            if not mfa.verify_login(body.code):
                limiter.fail(ip)
                raise HTTPException(401, "Invalid or expired code")
        limiter.ok(ip)
        if body.device:
            _, tok = tokens.create(body.device.strip()[:64] or "device")
            return {"token": tok, "role": "user", "persistent": True}
        exp = time.time() + int(settings.get("session_hours")) * 3600
        return {"token": sign(settings.secret(), {"typ": "session", "exp": exp}),
                "role": "admin", "expires": exp}

    @app.post("/api/auth/mfa/send")
    def mfa_send(body: MfaSendBody, request: Request):
        """Text / e-mail a sign-in code. Needs the correct password, so it cannot be used to spam strangers."""
        ip = request.client.host if request.client else "?"
        limiter.check(ip)
        settings.reload()
        if not password_ok(body.username, body.password):
            limiter.fail(ip)
            raise HTTPException(401, "Invalid credentials")
        try:
            return {"sent": True, "to": mfa.send_login_code(settings, body.method)}
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except SmsError as exc:
            raise HTTPException(502, str(exc))

    @app.get("/static/theme.css")
    def theme_css():
        from .. import theme
        return Response(theme.css_variables(), media_type="text/css")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    # ---- session helpers -------------------------------------------------------
    def root_items(pr: Principal) -> list[dict]:
        out = []
        for rid, (path, writable) in roots_for(pr).items():
            if rid.startswith("u:"):
                label = "My files"
            elif rid.startswith("s:"):
                g = grants.get(rid[2:]) or {}
                label = f"{path.name} (from {g.get('owner', '?')})"
            else:
                label = "Server files" if rid == "main" else rid
            out.append({"id": rid, "label": label, "writable": writable,
                        "kind": "mine" if rid.startswith("u:") else "shared" if rid.startswith("s:") else "server"})
        return out

    @app.get("/api/me")
    def me(pr: Principal = Depends(authenticate)):
        items = root_items(pr)
        return {"role": pr.role, "name": pr.name, "read_only": settings.get("read_only"),
                "domain": settings.get("domain"), "version": __version__, "roots": items,
                "default_root": items[0]["id"] if items else "main"}

    @app.get("/api/ticket")
    def ticket(request: Request, pr: Principal = Depends(authenticate)):
        tid = sid = ""
        hdr = request.headers.get("authorization", "")[7:].strip()
        if hdr.startswith("dst_"):
            parts = hdr.split("_", 2)
            tid = parts[1] if len(parts) == 3 else ""
        elif hdr:
            sid = sid_of(hdr)
        return {"ticket": sign(settings.secret(), {"typ": "ticket", "role": pr.role, "name": pr.name,
                                                   "tid": tid, "sid": sid, "ro": pr.read_only,
                                                   "exp": time.time() + 60})}

    @app.get("/api/usage")
    def usage_info(root: str = "", pr: Principal = Depends(authenticate)):
        return storage_report(pr, root)

    @app.get("/api/roots")
    def roots(pr: Principal = Depends(authenticate)):
        items = root_items(pr)
        return {"roots": [i["id"] for i in items], "items": items}

    # ---- files -------------------------------------------------------------------
    @app.get("/api/files")
    def list_files(root: str = "main", path: str = "", pr: Principal = Depends(authenticate)):
        base, target = safe_path(root, path)
        if not target.is_dir():
            raise HTTPException(404, "Not a folder")
        items = []
        for e in os.scandir(target):
            if ignored(e.name):
                continue
            try:
                st = e.stat()
                is_dir = e.is_dir()
            except OSError:
                continue
            items.append({"name": e.name, "type": "dir" if is_dir else "file",
                          "size": 0 if is_dir else st.st_size, "mtime": st.st_mtime})
        items.sort(key=lambda i: (i["type"] != "dir", i["name"].lower()))
        return {"root": root, "path": relpath(base, target), "items": items}

    @app.put("/api/files")
    async def upload(request: Request, root: str = "main", path: str = "",
                     pr: Principal = Depends(writer)):
        base, target = safe_path(root, path)
        if target == base:
            raise HTTPException(400, "Missing file path")
        if target.is_dir():
            raise HTTPException(409, "A folder with that name exists")
        check_name(target.name)
        existing = target.stat().st_size if target.is_file() else 0
        guard = await run_in_threadpool(space_guard, root, base, existing)
        declared = request.headers.get("content-length", "")
        if declared.isdigit():
            guard(int(declared))
        await run_in_threadpool(target.parent.mkdir, parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".slpart")
        limit = int(settings.get("max_upload_mb")) * 1024 * 1024
        size = 0
        try:
            with open(tmp, "wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    guard(size)
                    if limit and size > limit:
                        raise HTTPException(413, "File exceeds max upload size")
                    await run_in_threadpool(f.write, chunk)
            mt = request.headers.get("x-sl-mtime")
            if mt:
                try:
                    os.utime(tmp, (time.time(), float(mt)))
                except ValueError:
                    pass
            await run_in_threadpool(lib.Versions(base).keep, target, int(settings.get("versions_keep")))
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        usage.invalidate()
        await hub.broadcast({"event": "change", "root": root, "path": relpath(base, target.parent)})
        return {"ok": True, "size": size}

    @app.get("/api/text")
    def read_text(root: str = "main", path: str = "", pr: Principal = Depends(authenticate)):
        """Return a text file for the in-browser / in-app editor."""
        base, target = safe_path(root, path)
        if not target.is_file():
            raise HTTPException(404, "Not a file")
        st = target.stat()
        if st.st_size > MAX_TEXT_BYTES:
            raise HTTPException(413, "File is too large to edit online (limit 2 MB)")
        data = target.read_bytes()
        if b"\0" in data:
            raise HTTPException(415, "This looks like a binary file; download it instead")
        enc = "utf-8"
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            enc, text = "latin-1", data.decode("latin-1")
        if text.startswith("\ufeff"):
            enc, text = "utf-8-sig", text[1:]
        eol = "crlf" if "\r\n" in text else "lf"
        if eol == "crlf":
            text = text.replace("\r\n", "\n")
        return {"content": text, "encoding": enc, "eol": eol, "mtime": st.st_mtime, "size": st.st_size}

    @app.put("/api/text")
    async def write_text(body: TextBody, pr: Principal = Depends(writer)):
        """Save an edited text file (atomic; refuses if it changed on the server meanwhile)."""
        base, target = safe_path(body.root, body.path)
        if target == base or target.is_dir():
            raise HTTPException(400, "Bad file path")
        check_name(target.name)
        if body.encoding not in ("utf-8", "utf-8-sig", "latin-1"):
            raise HTTPException(400, "Unsupported encoding")
        exists = target.is_file()
        if exists and body.mtime is not None and abs(target.stat().st_mtime - body.mtime) > 0.001:
            raise HTTPException(409, "The file changed on the server since you opened it")
        text = body.content.replace("\r\n", "\n")
        if body.eol == "crlf":
            text = text.replace("\n", "\r\n")
        try:
            data = text.encode(body.encoding)
        except UnicodeEncodeError:
            raise HTTPException(400, "Text cannot be saved in the file's original encoding")
        if body.encoding == "utf-8-sig":
            data = b"\xef\xbb\xbf" + data
        if len(data) > MAX_TEXT_BYTES:
            raise HTTPException(413, "File is too large to edit online (limit 2 MB)")
        guard = await run_in_threadpool(space_guard, body.root, base, target.stat().st_size if exists else 0)
        guard(len(data))
        await run_in_threadpool(target.parent.mkdir, parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".slpart")
        try:
            await run_in_threadpool(tmp.write_bytes, data)
            await run_in_threadpool(lib.Versions(base).keep, target, int(settings.get("versions_keep")))
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        usage.invalidate()
        await hub.broadcast({"event": "change", "root": body.root, "path": relpath(base, target.parent)})
        return {"ok": True, "mtime": target.stat().st_mtime, "size": len(data)}

    @app.get("/api/download")
    def download(root: str = "main", path: str = "", pr: Principal = Depends(authenticate)):
        base, target = safe_path(root, path)
        if target.is_file():
            return FileResponse(target, filename=target.name)
        if target.is_dir():
            tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
            tmp.close()
            with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as z:
                for rel, meta in scan_tree(target).items():
                    if meta["type"] == "file":
                        z.write(target / rel, rel)
                    else:
                        z.writestr(rel + "/", "")
            return FileResponse(tmp.name, filename=(target.name or root) + ".zip",
                                background=BackgroundTask(os.unlink, tmp.name))
        raise HTTPException(404, "Not found")

    @app.post("/api/mkdir")
    async def mkdir(body: PathBody, pr: Principal = Depends(writer)):
        base, target = safe_path(body.root, body.path)
        if target.is_file():
            raise HTTPException(409, "A file with that name exists")
        await run_in_threadpool(target.mkdir, parents=True, exist_ok=True)
        await hub.broadcast({"event": "change", "root": body.root, "path": relpath(base, target.parent)})
        return {"ok": True}

    @app.post("/api/move")
    async def move(body: MoveBody, pr: Principal = Depends(writer)):
        base, src = safe_path(body.root, body.src)
        _, dst = safe_path(body.root, body.dst)
        if src == base or dst == base:
            raise HTTPException(400, "Cannot move the root")
        if not src.exists():
            raise HTTPException(404, "Source not found")
        if dst.exists():
            raise HTTPException(409, "Destination exists")
        if src in dst.parents:
            raise HTTPException(400, "Cannot move a folder into itself")
        if src.is_file():
            check_name(dst.name)
        await run_in_threadpool(dst.parent.mkdir, parents=True, exist_ok=True)
        await run_in_threadpool(shutil.move, str(src), str(dst))
        stars_of(pr).moved(body.root, relpath(base, src), relpath(base, dst))
        shares.revoke_path(body.root, relpath(base, src))
        await hub.broadcast({"event": "change", "root": body.root, "path": relpath(base, dst.parent)})
        return {"ok": True}

    @app.delete("/api/files")
    async def delete(root: str = "main", path: str = "", permanent: bool = False,
                     pr: Principal = Depends(writer)):
        base, target = safe_path(root, path)
        if target == base:
            raise HTTPException(400, "Cannot delete the root")
        if not target.exists():
            raise HTTPException(404, "Not found")
        rel = relpath(base, target)
        if permanent or int(settings.get("trash_days")) <= 0:
            if target.is_dir():
                await run_in_threadpool(shutil.rmtree, target)
            else:
                await run_in_threadpool(target.unlink)
                await run_in_threadpool(lib.Versions(base).forget, rel)
        else:
            await run_in_threadpool(lib.Trash(base).add, target, pr.name)
        stars_of(pr).removed(root, rel)
        shares.revoke_path(root, rel)
        usage.invalidate()
        await hub.broadcast({"event": "change", "root": root, "path": relpath(base, target.parent)})
        return {"ok": True}

    @app.get("/api/manifest")
    def manifest(root: str = "main", path: str = "", pr: Principal = Depends(authenticate)):
        _, target = safe_path(root, path)
        return {"entries": scan_tree(target) if target.is_dir() else {}}

    @app.get("/api/hash")
    def file_hash(root: str = "main", path: str = "", pr: Principal = Depends(authenticate)):
        import hashlib
        _, target = safe_path(root, path)
        if not target.is_file():
            raise HTTPException(404, "Not a file")
        h = hashlib.sha256()
        with open(target, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return {"sha256": h.hexdigest()}

    # ---- drive features: trash, history, stars, search, previews, copy, shares, resumable uploads ----------

    @app.post("/api/batch")
    async def batch(body: BatchBody, pr: Principal = Depends(writer)):
        """delete (to trash) / move / copy several items at once. Per-item errors are reported, not fatal."""
        if body.op not in ("delete", "move", "copy") or not body.paths or len(body.paths) > 1000:
            raise HTTPException(400, "Bad batch request")
        base, dest_dir = safe_path(body.root, body.dest)
        done, errors = [], []
        for rel in body.paths:
            try:
                _, src = safe_path(body.root, rel)
                if src == base or not src.exists():
                    raise HTTPException(404, "Not found")
                if body.op == "delete":
                    if int(settings.get("trash_days")) <= 0:
                        await run_in_threadpool(shutil.rmtree if src.is_dir() else os.unlink, src)
                    else:
                        await run_in_threadpool(lib.Trash(base).add, src, pr.name)
                    stars_of(pr).removed(body.root, relpath(base, src))
                    shares.revoke_path(body.root, relpath(base, src))
                else:
                    if not dest_dir.is_dir():
                        raise HTTPException(404, "Destination folder not found")
                    if src.is_dir() and (src == dest_dir or src in dest_dir.parents):
                        raise HTTPException(400, "Cannot put a folder inside itself")
                    if body.op == "move" and src.parent == dest_dir:
                        continue
                    name = lib.unique_name(dest_dir, src.name)
                    if src.is_file():
                        check_name(name)
                    dst = dest_dir / name
                    if body.op == "move":
                        await run_in_threadpool(shutil.move, str(src), str(dst))
                        stars_of(pr).moved(body.root, relpath(base, src), relpath(base, dst))
                        shares.revoke_path(body.root, relpath(base, src))
                    else:
                        guard = space_guard(body.root, base)
                        guard(await run_in_threadpool(lib.size_of, src))
                        if src.is_dir():
                            await run_in_threadpool(shutil.copytree, src, dst, ignore=shutil.ignore_patterns(lib.META))
                        else:
                            await run_in_threadpool(shutil.copy2, src, dst)
                done.append(rel)
            except HTTPException as exc:
                errors.append({"path": rel, "error": exc.detail})
            except OSError as exc:
                errors.append({"path": rel, "error": str(exc)})
        usage.invalidate()
        await hub.broadcast({"event": "change", "root": body.root, "path": body.dest})
        return {"ok": not errors, "done": done, "errors": errors}

    @app.get("/api/trash")
    def trash_list(root: str = "main", pr: Principal = Depends(authenticate)):
        base, _ = safe_path(root, "")
        items = lib.Trash(base).list()
        return {"items": items, "total": sum(i["size"] for i in items), "days": int(settings.get("trash_days"))}

    @app.post("/api/trash/restore")
    async def trash_restore(body: IdBody, pr: Principal = Depends(writer)):
        base, _ = safe_path(body.root, "")
        try:
            rel = await run_in_threadpool(lib.Trash(base).restore, body.id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        await hub.broadcast({"event": "change", "root": body.root, "path": str(Path(rel).parent.as_posix()).replace(".", "")})
        return {"ok": True, "path": rel}

    @app.delete("/api/trash")
    async def trash_purge(root: str = "main", id: str = "", pr: Principal = Depends(writer)):
        base, _ = safe_path(root, "")
        tr = lib.Trash(base)
        try:
            if id:
                await run_in_threadpool(tr.purge, id)
            else:
                await run_in_threadpool(tr.empty)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        usage.invalidate()
        return {"ok": True}

    @app.get("/api/versions")
    def versions_list(root: str = "main", path: str = "", pr: Principal = Depends(authenticate)):
        base, target = safe_path(root, path)
        return {"items": lib.Versions(base).list(relpath(base, target)), "keep": int(settings.get("versions_keep"))}

    @app.post("/api/versions/restore")
    async def versions_restore(body: IdBody, pr: Principal = Depends(writer)):
        base, target = safe_path(body.root, body.path)
        try:
            await run_in_threadpool(lib.Versions(base).restore, target, body.id, int(settings.get("versions_keep")))
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        usage.invalidate()
        await hub.broadcast({"event": "change", "root": body.root, "path": relpath(base, target.parent)})
        return {"ok": True}

    @app.get("/api/versions/download")
    def versions_download(root: str = "main", path: str = "", id: str = "", pr: Principal = Depends(authenticate)):
        base, target = safe_path(root, path)
        try:
            f = lib.Versions(base).file(relpath(base, target), id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        return FileResponse(f, filename=target.name)

    @app.get("/api/stars")
    def stars_list(pr: Principal = Depends(authenticate)):
        out = []
        for s in stars_of(pr).list():
            try:
                _, t = safe_path(s["root"], s["path"])
            except HTTPException:
                continue
            if t.exists():
                st = t.stat()
                out.append({**s, "name": t.name, "type": "dir" if t.is_dir() else "file",
                            "size": 0 if t.is_dir() else st.st_size, "mtime": st.st_mtime})
        return {"items": out}

    @app.put("/api/stars")
    def star_add(body: PathBody, pr: Principal = Depends(authenticate)):
        base, t = safe_path(body.root, body.path)
        if t == base or not t.exists():
            raise HTTPException(404, "Not found")
        stars_of(pr).add(norm(body.root, pr), relpath(base, t))
        return {"ok": True}

    @app.delete("/api/stars")
    def star_remove(root: str = "main", path: str = "", pr: Principal = Depends(authenticate)):
        stars_of(pr).remove(norm(root, pr), path.strip("/"))
        return {"ok": True}

    @app.get("/api/search")
    async def search_files(root: str = "main", q: str = "", kind: str = "", path: str = "",
                           pr: Principal = Depends(authenticate)):
        base, start = safe_path(root, path)
        if len(q.strip()) < 1 and not kind:
            return {"items": []}
        return {"items": await run_in_threadpool(lib.search, base, start, q, 200, kind)}

    @app.get("/api/recent")
    async def recent_files(root: str = "main", limit: int = 60, pr: Principal = Depends(authenticate)):
        base, start = safe_path(root, "")
        return {"items": await run_in_threadpool(lib.recent, base, start, max(1, min(limit, 200)))}

    @app.get("/api/preview")
    def preview(root: str = "main", path: str = "", pr: Principal = Depends(authenticate)):
        """Inline view for images, PDF, audio and video (other types: use /api/download or the text editor)."""
        _, target = safe_path(root, path)
        if not target.is_file():
            raise HTTPException(404, "Not a file")
        ctype = lib.PREVIEW_TYPES.get(target.suffix.lower())
        if not ctype:
            raise HTTPException(415, "No preview for this file type")
        hdr = {"Content-Disposition": "inline", "Cache-Control": "private, max-age=300"}
        if ctype == "image/svg+xml":
            hdr["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
        return FileResponse(target, media_type=ctype, headers=hdr)

    @app.get("/api/thumb")
    def thumb(root: str = "main", path: str = "", size: int = 360, pr: Principal = Depends(authenticate)):
        """Small cached JPEG preview for the grid view (404 / 415 -> the client shows an icon)."""
        base, target = safe_path(root, path)
        if not target.is_file():
            raise HTTPException(404, "Not a file")
        try:
            out = lib.thumbnail(base, target, max(64, min(size, 1024)))
        except RuntimeError as exc:
            raise HTTPException(415, str(exc))
        except Exception:  # noqa: BLE001 - corrupt images etc.
            raise HTTPException(415, "Cannot make a thumbnail")
        return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

    # ---- share links ----
    @app.post("/api/shares")
    def share_create(body: ShareBody, pr: Principal = Depends(authenticate)):
        base, t = safe_path(body.root, body.path)
        if t == base or not t.exists():
            raise HTTPException(404, "Not found")
        if body.days < 0 or body.days > 3650 or body.max_downloads < 0:
            raise HTTPException(400, "Bad expiry or download limit")
        if body.password and len(body.password) < 4:
            raise HTTPException(400, "Share password must be at least 4 characters")
        rec = shares.create(norm(body.root, pr), relpath(base, t), pr.name, body.days,
                            hash_password(body.password) if body.password else "", body.max_downloads)
        return {"token": rec["token"], "url": f"/s/{rec['token']}", "expires": rec["expires"]}

    @app.get("/api/shares")
    def share_list(root: str | None = None, path: str | None = None, pr: Principal = Depends(authenticate)):
        items = shares.list(root, path.strip("/") if path is not None else None)
        if pr.role == "member":
            items = [i for i in items if i["by"] == pr.name]
        return {"items": items}

    @app.delete("/api/shares/{token}")
    def share_revoke(token: str, pr: Principal = Depends(authenticate)):
        rec = next((s for s in shares.list() if s["token"] == token), None)
        if rec and pr.role == "member" and rec["by"] != pr.name:
            raise HTTPException(404, "No such link")
        if not shares.revoke(token):
            raise HTTPException(404, "No such link")
        return {"ok": True}

    def share_target(token: str, pw: str, sub: str = ""):
        rec = shares.get(token)
        if not rec:
            raise HTTPException(404, "This link has expired or does not exist")
        if rec["password"] and not verify_password(pw or "", rec["password"]):
            raise HTTPException(401, "Password required")
        try:
            base, target = safe_path(rec["root"], rec["path"], trusted=True)
        except HTTPException:
            raise HTTPException(404, "This link has expired or does not exist")
        if not target.exists():
            raise HTTPException(404, "The shared item no longer exists")
        if sub:
            if not target.is_dir():
                raise HTTPException(404, "Not found")
            sub_t = (target / sub.replace("\\", "/").strip("/")).resolve()
            if target.resolve() not in sub_t.parents and sub_t != target.resolve():
                raise HTTPException(400, "Path escapes the shared folder")
            target = sub_t
            if not target.exists():
                raise HTTPException(404, "Not found")
        return rec, target

    @app.get("/s/{token}")
    def share_page(token: str):
        return FileResponse(WEB_DIR / "share.html")

    @app.get("/api/public/{token}")
    def share_info(token: str, sub: str = "", pw: str = ""):
        rec, target = share_target(token, pw, sub)
        info = {"name": target.name, "type": "dir" if target.is_dir() else "file", "expires": rec["expires"],
                "protected": bool(rec["password"]), "items": []}
        if target.is_file():
            info["size"] = target.stat().st_size
            info["previewable"] = target.suffix.lower() in lib.PREVIEW_TYPES
        else:
            for e in os.scandir(target):
                if ignored(e.name):
                    continue
                try:
                    st = e.stat()
                    d = e.is_dir()
                except OSError:
                    continue
                info["items"].append({"name": e.name, "type": "dir" if d else "file",
                                      "size": 0 if d else st.st_size, "mtime": st.st_mtime})
            info["items"].sort(key=lambda i: (i["type"] != "dir", i["name"].lower()))
        return info

    @app.get("/api/public/{token}/download")
    def share_download(token: str, sub: str = "", pw: str = "", inline: bool = False):
        rec, target = share_target(token, pw, sub)
        shares.hit(token)
        if target.is_file():
            ctype = lib.PREVIEW_TYPES.get(target.suffix.lower())
            if inline and ctype:
                return FileResponse(target, media_type=ctype, headers={"Content-Disposition": "inline"})
            return FileResponse(target, filename=target.name)
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        tmp.close()
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, meta in scan_tree(target).items():
                if meta["type"] == "file":
                    z.write(target / rel, rel)
                else:
                    z.writestr(rel + "/", "")
        return FileResponse(tmp.name, filename=(target.name or "shared") + ".zip",
                            background=BackgroundTask(os.unlink, tmp.name))

    # ---- resumable uploads ----
    @app.post("/api/uploads")
    async def upload_start(body: UploadStart, pr: Principal = Depends(writer)):
        base, target = safe_path(body.root, body.path)
        if target == base or target.is_dir():
            raise HTTPException(400, "Bad file path")
        check_name(target.name)
        limit = int(settings.get("max_upload_mb")) * 1024 * 1024
        if limit and body.size > limit:
            raise HTTPException(413, "File exceeds max upload size")
        guard = await run_in_threadpool(space_guard, body.root, base, target.stat().st_size if target.is_file() else 0)
        guard(body.size)
        meta = lib.Uploads(base).start(body.root, relpath(base, target), body.size, body.mtime)
        return {"id": meta["id"], "offset": 0}

    @app.get("/api/uploads/{uid}")
    def upload_status(uid: str, root: str = "main", pr: Principal = Depends(writer)):
        base, _ = safe_path(root, "")
        meta = lib.Uploads(base).get(uid)
        if not meta:
            raise HTTPException(404, "Unknown upload")
        return {"id": uid, "offset": meta["offset"], "size": meta["size"]}

    @app.patch("/api/uploads/{uid}")
    async def upload_chunk(uid: str, request: Request, root: str = "main", pr: Principal = Depends(writer)):
        base, _ = safe_path(root, "")
        ups = lib.Uploads(base)
        meta = ups.get(uid)
        if not meta:
            raise HTTPException(404, "Unknown upload")
        try:
            offset = int(request.headers.get("upload-offset", "-1"))
        except ValueError:
            offset = -1
        if offset != meta["offset"]:
            raise HTTPException(409, f"Offset mismatch; the server has {meta['offset']} bytes")
        written = meta["offset"]
        part = ups.part(uid)
        with open(part, "ab") as f:
            async for chunk in request.stream():
                written += len(chunk)
                if written > meta["size"]:
                    raise HTTPException(413, "More data than announced")
                await run_in_threadpool(f.write, chunk)
        if written < meta["size"]:
            return {"offset": written, "done": False}
        _, target = safe_path(meta["root"], meta["path"])
        try:
            await run_in_threadpool(target.parent.mkdir, parents=True, exist_ok=True)
            if meta.get("mtime"):
                os.utime(part, (time.time(), float(meta["mtime"])))
            await run_in_threadpool(lib.Versions(base).keep, target, int(settings.get("versions_keep")))
            os.replace(part, target)
        finally:
            ups.drop(uid)
        usage.invalidate()
        await hub.broadcast({"event": "change", "root": meta["root"], "path": relpath(base, target.parent)})
        return {"offset": written, "done": True}

    @app.delete("/api/uploads/{uid}")
    def upload_cancel(uid: str, root: str = "main", pr: Principal = Depends(writer)):
        base, _ = safe_path(root, "")
        lib.Uploads(base).drop(uid)
        return {"ok": True}

    # ---- accounts: own password, people directory, folder grants ---------------------------------------
    @app.post("/api/account/password")
    def account_password(body: PwChange, pr: Principal = Depends(authenticate)):
        if pr.role != "member":
            raise HTTPException(400, "The admin changes the password under Admin or with `synclayer server passwd`")
        if not users.verify(pr.name, body.current):
            raise HTTPException(403, "Current password is wrong")
        try:
            users.update(pr.name, password=body.new_password)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True}

    @app.get("/api/people")
    def people(pr: Principal = Depends(authenticate)):
        """Other accounts you can share with (names only)."""
        out = [{"name": u["name"], "display": u["display"]} for u in users.list()
               if not u["disabled"] and u["name"].lower() != pr.name.lower()]
        admin = str(settings.get("admin_user"))
        if admin.lower() != pr.name.lower():
            out.insert(0, {"name": admin, "display": "Administrator"})
        return {"items": out}

    @app.post("/api/grants")
    async def grant_create(body: GrantBody, pr: Principal = Depends(authenticate)):
        base, target = safe_path(body.root, body.path)
        if not target.is_dir():
            raise HTTPException(400, "Only folders can be shared with people; use a link for a single file")
        if pr.role == "member" and norm(body.root, pr).startswith("s:"):
            raise HTTPException(403, "You cannot re-share a folder that was shared with you")
        to = body.to.strip()
        rec = users.get(to)
        if not rec:
            raise HTTPException(404, "No such user")
        if pr.role == "member" and rec["name"].lower() == pr.name.lower():
            raise HTTPException(400, "That is you")
        try:
            g = grants.add(pr.name, norm(body.root, pr), relpath(base, target), rec["name"], body.perm)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        await hub.broadcast({"event": "change", "root": body.root, "path": ""})
        return g

    @app.get("/api/grants")
    def grant_list(root: str | None = None, path: str | None = None, pr: Principal = Depends(authenticate)):
        given = grants.given(pr.name if pr.role == "member" else str(settings.get("admin_user")),
                             norm(root, pr) if root else root,
                             path.strip("/") if path is not None else None)
        received = []
        if pr.role == "member":
            for g in grants.received(pr.name):
                d = grant_dir(g)
                if d:
                    received.append({**g, "name": d.name, "writable": g["perm"] == "rw"})
        return {"given": given, "received": received}

    @app.delete("/api/grants/{gid}")
    def grant_remove(gid: str, pr: Principal = Depends(authenticate)):
        if not grants.remove(gid, pr.name if pr.role == "member" else str(settings.get("admin_user")),
                             pr.role == "admin"):
            raise HTTPException(404, "No such share")
        return {"ok": True}

    # ---- admin: people ----
    @app.get("/api/admin/users")
    def admin_users(pr: Principal = Depends(admin_only)):
        out = []
        for u in users.list():
            u["used"] = usage.used(user_base(u["name"]))
            out.append(u)
        return {"items": out, "default_quota_mb": int(settings.get("user_quota_mb"))}

    @app.post("/api/admin/users")
    def admin_user_create(body: NewUser, pr: Principal = Depends(admin_only)):
        if body.name.lower() == str(settings.get("admin_user")).lower():
            raise HTTPException(400, "That name belongs to the administrator")
        try:
            rec = users.create(body.name, body.password, body.quota_mb, body.display)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        user_base(rec["name"])
        return rec

    @app.patch("/api/admin/users/{name}")
    def admin_user_patch(name: str, body: UserPatch, pr: Principal = Depends(admin_only)):
        try:
            return users.update(name, body.password, body.quota_mb, body.disabled, body.display)
        except KeyError:
            raise HTTPException(404, "No such user")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.delete("/api/admin/users/{name}")
    def admin_user_delete(name: str, purge: bool = False, pr: Principal = Depends(admin_only)):
        rec = users.get(name)
        if not rec:
            raise HTTPException(404, "No such user")
        users.delete(name)
        grants.drop_where(lambda g: g["owner"].lower() == name.lower() or g["to"].lower() == name.lower())
        for t in tokens.list():
            if (t.get("owner") or "").lower() == name.lower():
                tokens.revoke(t["id"])
        folder = user_base(rec["name"])
        if purge:
            shutil.rmtree(folder, ignore_errors=True)
        else:
            folder.rename(folder.with_name(f".deleted-{folder.name}-{int(time.time())}"))
        usage.invalidate()
        return {"ok": True, "purged": purge}

    # ---- admin -----------------------------------------------------------------------
    @app.get("/api/admin/settings")
    def admin_get(pr: Principal = Depends(admin_only)):
        root = settings.storage_root()
        try:
            du = shutil.disk_usage(root)
            disk = {"total": du.total, "used": du.used, "free": du.free}
        except OSError:
            disk = {}
        return {"settings": settings.public(), "roots": list(settings.roots().keys()), "disk": disk,
                "usage": storage_report()}

    @app.get("/api/admin/usage")
    def admin_usage(pr: Principal = Depends(admin_only)):
        usage.invalidate()
        return {**storage_report(), "top": breakdown(settings.storage_root())}

    @app.patch("/api/admin/settings")
    def admin_patch(body: SettingsBody, pr: Principal = Depends(admin_only)):
        try:
            settings.update(body.changes)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc))
        usage.invalidate()
        return {"settings": settings.public()}

    @app.post("/api/admin/password")
    def admin_password(body: PasswordBody, pr: Principal = Depends(admin_only)):
        if len(body.new_password) < 10:
            raise HTTPException(400, "Password must be at least 10 characters")
        settings.set_internal("admin_password_hash", hash_password(body.new_password))
        return {"ok": True}

    @app.get("/api/admin/tokens")
    def tokens_list(pr: Principal = Depends(admin_only)):
        return {"tokens": tokens.list()}

    @app.post("/api/admin/tokens")
    def tokens_create(body: TokenBody, pr: Principal = Depends(admin_only)):
        tid, tok = tokens.create(body.name.strip()[:64] or "device", body.read_only)
        return {"id": tid, "token": tok, "read_only": body.read_only}

    @app.delete("/api/admin/tokens/{tid}")
    def tokens_revoke(tid: str, pr: Principal = Depends(admin_only)):
        if not tokens.revoke(tid):
            raise HTTPException(404, "No such token")
        return {"ok": True}

    @app.get("/api/admin/devices")
    def devices_list(request: Request, pr: Principal = Depends(admin_only)):
        live = {m.get("tid") for m in hub.meta.values() if m.get("tid")}
        live_s = {m.get("sid") for m in hub.meta.values() if m.get("sid")}
        hdr = request.headers.get("authorization", "")[7:].strip()
        cur = sid_of(hdr) if hdr and not hdr.startswith("dst_") else ""
        return merge_devices(tokens.devices(live_ids=live), presence.devices(live_s, cur))

    @app.post("/api/admin/rotate-secret")
    def rotate(pr: Principal = Depends(admin_only)):
        try:
            settings.rotate_secret()
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        exp = time.time() + int(settings.get("session_hours")) * 3600
        return {"token": sign(settings.secret(), {"typ": "session", "exp": exp})}

    # ---- two-factor setup (admin session required) ---------------------------------------
    def mfa_guard(fn):
        try:
            return fn()
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except SmsError as exc:
            raise HTTPException(502, str(exc))

    @app.get("/api/admin/mfa")
    def mfa_status(pr: Principal = Depends(admin_only)):
        return mfa.status(settings)

    @app.post("/api/admin/mfa/totp/begin")
    def mfa_totp_begin(pr: Principal = Depends(admin_only)):
        from . import mfa as m
        sec = mfa.begin_totp()
        return {"secret": sec, "grouped": m.group(sec),
                "uri": m.otpauth_uri(sec, settings.get("admin_user"),
                                     "Synclayer" + (" " + settings.get("domain") if settings.get("domain") else ""))}

    def confirmed(codes):
        if codes is None:
            raise HTTPException(400, "That code is wrong or has expired")
        return {"ok": True, "recovery": codes, "status": mfa.status(settings)}

    @app.post("/api/admin/mfa/totp/confirm")
    def mfa_totp_confirm(body: CodeBody, pr: Principal = Depends(admin_only)):
        return confirmed(mfa.confirm_totp(body.code))

    @app.post("/api/admin/mfa/sms/begin")
    def mfa_sms_begin(body: TargetBody, pr: Principal = Depends(admin_only)):
        mfa_guard(lambda: mfa.begin_sms(settings, body.target))
        return {"sent": True}

    @app.post("/api/admin/mfa/sms/confirm")
    def mfa_sms_confirm(body: CodeBody, pr: Principal = Depends(admin_only)):
        return confirmed(mfa.confirm_sms(body.code))

    @app.post("/api/admin/mfa/email/begin")
    def mfa_email_begin(body: TargetBody, pr: Principal = Depends(admin_only)):
        mfa_guard(lambda: mfa.begin_email(settings, body.target))
        return {"sent": True}

    @app.post("/api/admin/mfa/email/confirm")
    def mfa_email_confirm(body: CodeBody, pr: Principal = Depends(admin_only)):
        return confirmed(mfa.confirm_email(body.code))

    @app.delete("/api/admin/mfa/{method}")
    def mfa_remove(method: str, code: str = "", pr: Principal = Depends(admin_only)):
        """Remove one factor (totp | sms | email) or all of them (all). Needs a current code."""
        if mfa.enabled() and not mfa.verify_login(code):
            raise HTTPException(400, "Enter a current code to confirm")
        fn = {"totp": mfa.remove_totp, "sms": mfa.remove_sms, "email": mfa.remove_email, "all": mfa.disable}.get(method)
        if not fn:
            raise HTTPException(404, "Unknown method")
        fn()
        return {"ok": True, "status": mfa.status(settings)}

    @app.post("/api/admin/mfa/recovery")
    def mfa_recovery(body: CodeBody, pr: Principal = Depends(admin_only)):
        if not mfa.enabled():
            raise HTTPException(400, "Turn on a second factor first")
        if not mfa.verify_login(body.code):
            raise HTTPException(400, "Enter a current code to confirm")
        return {"recovery": mfa.new_recovery()}

    # ---- live events -----------------------------------------------------------------
    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        data = unsign(settings.secret(), socket.query_params.get("ticket", ""))
        if not data or data.get("typ") != "ticket":
            await socket.close(code=1008)
            return
        await socket.accept()
        hub.clients.add(socket)
        hub.meta[socket] = {"role": data.get("role", ""), "tid": data.get("tid", ""), "sid": data.get("sid", ""), "name": data.get("name", "")}
        if data.get("sid"):
            presence.touch(data["sid"], socket.client.host if socket.client else "", "websocket", force=True)
        if data.get("tid"):
            tokens.touch(data["tid"], socket.client.host if socket.client else "", "websocket", force=True)
        try:
            while True:
                await socket.receive_text()
                if data.get("tid"):
                    tokens.touch(data["tid"])
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            hub.clients.discard(socket)
            hub.meta.pop(socket, None)
            if data.get("tid"):
                tokens.touch(data["tid"], force=True)

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
    return app


def bootstrap_admin(settings: Settings):
    """Ensure an admin password exists; generate and print one on first start."""
    import secrets

    if settings.get("admin_password_hash") or settings.get("admin_password"):
        return
    pw = secrets.token_urlsafe(14)
    settings.set_internal("admin_password_hash", hash_password(pw))
    print("=" * 60)
    print(f" {APP_NAME} first start - generated admin credentials (shown once)")
    print(f"   user:     {settings.get('admin_user')}")
    print(f"   password: {pw}")
    print(" Change it with: synclayer server passwd")
    print("=" * 60, flush=True)
