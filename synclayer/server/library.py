"""Cloud-drive features on top of plain folders: trash, file history, share links, stars, search, uploads.

Everything the server keeps for itself lives in a hidden `.synclayer/` folder inside each root
(trash, old versions, partial uploads) or in the config folder (share links, stars). The
folder is invisible to listings, sync manifests, search and zip downloads.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import threading
import time
from pathlib import Path

META = ".synclayer"
PREVIEW_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".avif": "image/avif", ".bmp": "image/bmp", ".ico": "image/x-icon", ".pdf": "application/pdf",
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav", ".ogg": "audio/ogg", ".flac": "audio/flac",
    ".opus": "audio/ogg", ".aac": "audio/aac", ".mkv": "video/x-matroska", ".svg": "image/svg+xml",
    ".ogv": "video/ogg", ".3gp": "video/3gpp", ".gifv": "video/mp4",
}


def _read(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data), "utf-8")
    os.replace(tmp, path)


def unique_name(folder: Path, name: str, suffix: str = " (copy)") -> str:
    """name, or 'name (copy).ext', 'name (copy 2).ext' ... whichever does not exist in folder."""
    if not (folder / name).exists():
        return name
    p = Path(name)
    for i in range(1, 10_000):
        tag = suffix if i == 1 else suffix[:-1] + f" {i})"
        cand = f"{p.stem}{tag}{p.suffix}"
        if not (folder / cand).exists():
            return cand
    return f"{p.stem}-{secrets.token_hex(3)}{p.suffix}"


def size_of(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for dp, _dn, fn in os.walk(path):
        for f in fn:
            try:
                total += os.stat(os.path.join(dp, f)).st_size
            except OSError:
                pass
    return total


# ---- trash ----------------------------------------------------------------------------------------------
class Trash:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.dir = self.base / META / "trash"

    def add(self, target: Path, who: str = "") -> dict:
        rel = target.relative_to(self.base).as_posix()
        tid = f"{int(time.time())}-{secrets.token_hex(4)}"
        slot = self.dir / tid
        slot.mkdir(parents=True, exist_ok=True)
        info = {"id": tid, "path": rel, "name": target.name, "type": "dir" if target.is_dir() else "file",
                "size": size_of(target), "deleted": time.time(), "by": who}
        shutil.move(str(target), str(slot / "payload"))
        _write(slot / "meta.json", info)
        return info

    def list(self) -> list[dict]:
        out = []
        if self.dir.is_dir():
            for slot in self.dir.iterdir():
                meta = _read(slot / "meta.json", None)
                if meta and (slot / "payload").exists():
                    out.append(meta)
        out.sort(key=lambda m: m.get("deleted", 0), reverse=True)
        return out

    def restore(self, tid: str) -> str:
        slot = self._slot(tid)
        meta = _read(slot / "meta.json", None)
        if not meta or not (slot / "payload").exists():
            raise FileNotFoundError("Not in the trash")
        dest = self.base / meta["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        name = unique_name(dest.parent, dest.name, " (restored)")
        dest = dest.parent / name
        shutil.move(str(slot / "payload"), str(dest))
        shutil.rmtree(slot, ignore_errors=True)
        return dest.relative_to(self.base).as_posix()

    def purge(self, tid: str) -> None:
        shutil.rmtree(self._slot(tid), ignore_errors=True)

    def empty(self) -> int:
        n = len(self.list())
        shutil.rmtree(self.dir, ignore_errors=True)
        return n

    def expire(self, days: int) -> int:
        if days <= 0:
            return 0
        cutoff, n = time.time() - days * 86400, 0
        for m in self.list():
            if m.get("deleted", 0) < cutoff:
                self.purge(m["id"])
                n += 1
        return n

    def _slot(self, tid: str) -> Path:
        if not tid or "/" in tid or "\\" in tid or tid.startswith("."):
            raise FileNotFoundError("Bad id")
        return self.dir / tid


# ---- versions (file history) ---------------------------------------------------------------------------
class Versions:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.root = self.base / META / "versions"

    def _dir(self, rel: str) -> Path:
        return self.root / hashlib.sha1(rel.encode()).hexdigest()[:20]

    def keep(self, target: Path, keep: int) -> None:
        """Move the current file into history just before it is replaced (cheap rename, same disk)."""
        if keep <= 0 or not target.is_file():
            return
        rel = target.relative_to(self.base).as_posix()
        d = self._dir(rel)
        d.mkdir(parents=True, exist_ok=True)
        st = target.stat()
        vid = f"{int(time.time() * 1000)}"
        shutil.move(str(target), str(d / vid))
        _write(d / f"{vid}.json", {"id": vid, "path": rel, "size": st.st_size, "mtime": st.st_mtime,
                                    "saved": time.time()})
        self._prune(d, keep)

    def _prune(self, d: Path, keep: int) -> None:
        metas = sorted(d.glob("*.json"), key=lambda p: p.stem, reverse=True)
        for m in metas[keep:]:
            m.unlink(missing_ok=True)
            (d / m.stem).unlink(missing_ok=True)

    def list(self, rel: str) -> list[dict]:
        d = self._dir(rel)
        out = [_read(m, None) for m in d.glob("*.json")] if d.is_dir() else []
        out = [m for m in out if m and (d / m["id"]).is_file()]
        out.sort(key=lambda m: m["saved"], reverse=True)
        return out

    def file(self, rel: str, vid: str) -> Path:
        if not vid.isdigit():
            raise FileNotFoundError("Bad version")
        p = self._dir(rel) / vid
        if not p.is_file():
            raise FileNotFoundError("Version not found")
        return p

    def restore(self, target: Path, vid: str, keep: int) -> None:
        rel = target.relative_to(self.base).as_posix()
        old = self.file(rel, vid)
        meta = _read(old.with_name(vid + ".json"), {})
        tmp = target.with_name(target.name + ".slpart")
        shutil.copy2(old, tmp)
        if meta.get("mtime"):
            os.utime(tmp, (time.time(), meta["mtime"]))
        self.keep(target, max(keep, 1))
        os.replace(tmp, target)

    def forget(self, rel: str) -> None:
        shutil.rmtree(self._dir(rel), ignore_errors=True)


# ---- resumable uploads ---------------------------------------------------------------------------------
class Uploads:
    """Chunked, resumable uploads: start -> PATCH chunks at the right offset -> finished automatically."""

    def __init__(self, base: Path):
        self.dir = Path(base) / META / "uploads"

    def start(self, root: str, rel: str, size: int, mtime: float | None) -> dict:
        uid = secrets.token_hex(12)
        self.dir.mkdir(parents=True, exist_ok=True)
        meta = {"id": uid, "root": root, "path": rel, "size": size, "mtime": mtime, "created": time.time()}
        _write(self.dir / f"{uid}.json", meta)
        (self.dir / f"{uid}.part").write_bytes(b"")
        return meta

    def get(self, uid: str) -> dict | None:
        if not uid.isalnum():
            return None
        meta = _read(self.dir / f"{uid}.json", None)
        if not meta:
            return None
        part = self.dir / f"{uid}.part"
        meta["offset"] = part.stat().st_size if part.exists() else 0
        return meta

    def part(self, uid: str) -> Path:
        return self.dir / f"{uid}.part"

    def drop(self, uid: str) -> None:
        for suffix in (".json", ".part"):
            (self.dir / f"{uid}{suffix}").unlink(missing_ok=True)

    def expire(self, hours: float = 48) -> int:
        n, cutoff = 0, time.time() - hours * 3600
        if self.dir.is_dir():
            for m in self.dir.glob("*.json"):
                meta = _read(m, {})
                if meta.get("created", 0) < cutoff:
                    self.drop(m.stem)
                    n += 1
        return n


# ---- stars ---------------------------------------------------------------------------------------------
class Stars:
    def __init__(self, path: Path):
        self.path, self._lock = Path(path), threading.Lock()

    def list(self) -> list[dict]:
        return _read(self.path, [])

    def add(self, root: str, rel: str) -> None:
        with self._lock:
            items = self.list()
            if not any(i["root"] == root and i["path"] == rel for i in items):
                items.append({"root": root, "path": rel, "added": time.time()})
                _write(self.path, items)

    def remove(self, root: str, rel: str) -> None:
        with self._lock:
            _write(self.path, [i for i in self.list() if not (i["root"] == root and i["path"] == rel)])

    def moved(self, root: str, src: str, dst: str) -> None:
        with self._lock:
            items, changed = self.list(), False
            for i in items:
                if i["root"] == root and (i["path"] == src or i["path"].startswith(src + "/")):
                    i["path"] = dst + i["path"][len(src):]
                    changed = True
            if changed:
                _write(self.path, items)

    def removed(self, root: str, rel: str) -> None:
        with self._lock:
            items = self.list()
            keep = [i for i in items if not (i["root"] == root and (i["path"] == rel or i["path"].startswith(rel + "/")))]
            if len(keep) != len(items):
                _write(self.path, keep)


# ---- share links ---------------------------------------------------------------------------------------
class Shares:
    def __init__(self, path: Path):
        self.path, self._lock = Path(path), threading.Lock()

    def _all(self) -> dict:
        return _read(self.path, {})

    def create(self, root: str, rel: str, by: str, days: int = 0, password_hash: str = "",
               max_downloads: int = 0) -> dict:
        token = secrets.token_urlsafe(18)
        rec = {"token": token, "root": root, "path": rel, "by": by, "created": time.time(),
               "expires": time.time() + days * 86400 if days > 0 else 0, "password": password_hash,
               "max_downloads": max_downloads, "downloads": 0}
        with self._lock:
            data = self._all()
            data[token] = rec
            _write(self.path, data)
        return rec

    def get(self, token: str) -> dict | None:
        rec = self._all().get(token)
        if not rec:
            return None
        if rec["expires"] and rec["expires"] < time.time():
            return None
        if rec["max_downloads"] and rec["downloads"] >= rec["max_downloads"]:
            return None
        return rec

    def hit(self, token: str) -> None:
        with self._lock:
            data = self._all()
            if token in data:
                data[token]["downloads"] += 1
                _write(self.path, data)

    def list(self, root: str | None = None, rel: str | None = None) -> list[dict]:
        out = []
        for r in self._all().values():
            if root is not None and r["root"] != root:
                continue
            if rel is not None and r["path"] != rel:
                continue
            out.append({k: v for k, v in r.items() if k != "password"} | {"protected": bool(r["password"])})
        out.sort(key=lambda r: r["created"], reverse=True)
        return out

    def revoke(self, token: str) -> bool:
        with self._lock:
            data = self._all()
            if data.pop(token, None) is None:
                return False
            _write(self.path, data)
            return True

    def revoke_path(self, root: str, rel: str) -> None:
        with self._lock:
            data = self._all()
            keep = {t: r for t, r in data.items()
                    if not (r["root"] == root and (r["path"] == rel or r["path"].startswith(rel + "/")))}
            if len(keep) != len(data):
                _write(self.path, keep)


# ---- search / recent -------------------------------------------------------------------------------------
def walk_files(base: Path, start: Path):
    """Yield (relpath, DirEntry-like tuple) for everything under start, skipping hidden server folders."""
    stack = [start]
    while stack:
        d = stack.pop()
        try:
            it = list(os.scandir(d))
        except OSError:
            continue
        for e in it:
            if e.name == META:
                continue
            try:
                if e.is_symlink():
                    continue
                st = e.stat(follow_symlinks=False)
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            yield Path(e.path).relative_to(base).as_posix(), e.name, is_dir, st
            if is_dir:
                stack.append(Path(e.path))


def search(base: Path, start: Path, query: str, limit: int = 200, kind: str = "") -> list[dict]:
    q = query.lower().strip()
    out = []
    exts = {"image": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif", ".heic"),
            "video": (".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"),
            "audio": (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"),
            "doc": (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".txt", ".md", ".csv")}.get(kind)
    for rel, name, is_dir, st in walk_files(base, start):
        if q and q not in name.lower():
            continue
        if exts and (is_dir or not name.lower().endswith(exts)):
            continue
        out.append({"name": name, "path": rel, "type": "dir" if is_dir else "file",
                    "size": 0 if is_dir else st.st_size, "mtime": st.st_mtime})
        if len(out) >= limit:
            break
    out.sort(key=lambda i: (i["type"] != "dir", i["name"].lower()))
    return out


def recent(base: Path, start: Path, limit: int = 60) -> list[dict]:
    import heapq
    best: list[tuple[float, int, dict]] = []
    n = 0
    for rel, name, is_dir, st in walk_files(base, start):
        if is_dir:
            continue
        n += 1
        item = {"name": name, "path": rel, "type": "file", "size": st.st_size, "mtime": st.st_mtime}
        if len(best) < limit:
            heapq.heappush(best, (st.st_mtime, n, item))
        elif st.st_mtime > best[0][0]:
            heapq.heapreplace(best, (st.st_mtime, n, item))
    return [i for _, _, i in sorted(best, reverse=True)]


THUMB_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tif", ".tiff"}


def thumbnail(base: Path, target: Path, size: int = 360) -> Path:
    """Cached JPEG thumbnail of an image (needs Pillow; raises RuntimeError / OSError when impossible)."""
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pillow is not installed") from exc
    if target.suffix.lower() not in THUMB_EXT:
        raise RuntimeError("No thumbnail for this type")
    st = target.stat()
    key = hashlib.sha1(f"{target.relative_to(base).as_posix()}|{st.st_size}|{int(st.st_mtime)}|{size}".encode()).hexdigest()
    out = base / META / "thumbs" / f"{key}.jpg"
    if out.is_file():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(target) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((size, size))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        tmp = out.with_suffix(".tmp")
        im.save(tmp, "JPEG", quality=80, optimize=True)
    os.replace(tmp, out)
    return out
