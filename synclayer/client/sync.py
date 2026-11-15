"""Two-way file AND folder synchronisation.

Algorithm: three-way compare of local tree, remote tree and the last agreed snapshot
("base"), which is what lets us tell a deletion from a new file, and a one-sided edit
from a real conflict.

  local+remote equal           -> nothing
  one side changed vs base     -> propagate that change
  both changed / no base       -> conflict: newest mtime wins, loser kept as *.conflict-*
  missing on one side + in base-> it was deleted there; delete here if unmodified
  missing on one side, no base -> new file; copy it over

Safety: refuses to run when a previously synced side is suddenly empty (unmounted drive,
swapped server storage) unless force=True.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable

from ..common.scan import scan_tree
from .api import ApiError, Client, set_limits
from .config import ClientConfig, Profile, client_config_dir, safe_name

TOL = 2.0  # seconds; covers FAT/exFAT and network rounding
WORKERS = 4  # parallel transfers per sync run
IGNORE_FILE = ".slignore"  # gitignore-style patterns (one per line, # comments, trailing / = folders only)


def load_ignore(lroot: Path) -> list[str]:
    try:
        lines = (Path(lroot) / IGNORE_FILE).read_text("utf-8").splitlines()
    except OSError:
        return []
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def is_ignored(rel: str, patterns: list[str]) -> bool:
    """True if rel (posix) or any parent folder of it matches a pattern. `*.tmp`, `build/`, `docs/*.bak` ..."""
    if rel == IGNORE_FILE:
        return False
    parts = rel.split("/")
    for pat in patterns:
        dir_only = pat.endswith("/")
        pat = pat.rstrip("/").lstrip("/")
        for i in range(len(parts)):
            if i == len(parts) - 1 and dir_only:
                continue  # the pattern only names folders; this final component is the item itself
            sub = "/".join(parts[:i + 1])
            if fnmatch.fnmatch(parts[i], pat) or fnmatch.fnmatch(sub, pat):
                return True
    return False


def local_signature(p: Profile) -> int:
    """Cheap fingerprint of the local tree (names, sizes, mtimes) used to notice edits between syncs."""
    root = Path(p.local_dir).expanduser()
    pats = load_ignore(root)
    h = 0
    for rel, meta in scan_tree(root).items():
        if _ok_rel(rel) and not is_ignored(rel, pats):
            h ^= hash((rel, meta["type"], meta["size"], int(meta["mtime"])))
    return h


class SyncError(Exception):
    pass


@dataclass
class SyncResult:
    uploaded: int = 0
    downloaded: int = 0
    deleted_local: int = 0
    deleted_remote: int = 0
    conflicts: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)

    @property
    def changed(self) -> int:
        return (self.uploaded + self.downloaded + self.deleted_local + self.deleted_remote)

    def summary(self) -> str:
        s = (f"↑{self.uploaded} ↓{self.downloaded} "
             f"del(local {self.deleted_local}, remote {self.deleted_remote}) conflicts {self.conflicts}")
        return s + (f" errors {len(self.errors)}" if self.errors else "")


def _eq(a: dict, b: dict) -> bool:
    if a["type"] != b["type"]:
        return False
    if a["type"] == "dir":
        return True
    return a["size"] == b["size"] and abs(a["mtime"] - b["mtime"]) <= TOL


def _ok_rel(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return bool(parts) and not PurePosixPath(rel).is_absolute() and ".." not in parts and "\\" not in rel


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _state_path(p: Profile) -> Path:
    d = client_config_dir() / "state"
    d.mkdir(parents=True, exist_ok=True)
    key = f"{p.sid}_{p.name}" if p.sid else p.name
    return d / f"{safe_name(key)}.json"


def load_state(p: Profile) -> dict:
    import json
    try:
        return json.loads(_state_path(p).read_text("utf-8"))
    except (OSError, ValueError):
        pass
    try:   # state written before several servers were supported
        return json.loads((client_config_dir() / "state" / f"{safe_name(p.name)}.json").read_text("utf-8")) if p.sid else {}
    except (OSError, ValueError):
        return {}


def save_state(p: Profile, base: dict):
    import json
    tmp = _state_path(p).with_suffix(".tmp")
    tmp.write_text(json.dumps(base), "utf-8")
    os.replace(tmp, _state_path(p))


def _conflict_name(rel: str) -> str:
    pp = PurePosixPath(rel)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return str(pp.with_name(f"{pp.stem}.conflict-{stamp}{pp.suffix}"))


def sync_once(client: Client, p: Profile, on_event: Callable[[str], None] | None = None,
              should_stop: Callable[[], bool] | None = None, force: bool = False) -> SyncResult:
    emit = on_event or (lambda m: None)
    stop = should_stop or (lambda: False)
    res = SyncResult()
    lroot = Path(p.local_dir).expanduser()
    lroot.mkdir(parents=True, exist_ok=True)
    rbase = p.remote_path.strip("/")

    def lp(rel: str) -> Path:
        return lroot / rel

    def rp(rel: str) -> str:
        return "/".join(x for x in (rbase, rel) if x)

    pats = load_ignore(lroot)
    mode = getattr(p, "mode", "two-way")
    up_ok, down_ok = mode != "download", mode != "upload"
    propagate = bool(getattr(p, "propagate_deletes", False))   # off by default: a delete on this device never reaches the server
    kept: set[str] = set()      # deleted here on purpose-or-not, but kept on the server: remembered so it is not re-downloaded

    def visible(tree: dict) -> dict:
        return {k: v for k, v in tree.items() if _ok_rel(k) and not is_ignored(k, pats)}

    local = visible(scan_tree(lroot))
    remote = visible(client.manifest(p.remote_root, rbase))
    base = load_state(p)

    if base and not force:
        if not local and propagate:
            raise SyncError("Local folder is empty but was synced before; refusing to delete remote "
                            "data. Re-run with force to override.")
        if not remote:
            raise SyncError("Remote folder is empty but was synced before; refusing to delete local "
                            "data. Re-run with force to override.")

    bad: set[str] = set()
    dirs: list[str] = []
    files: list[str] = []
    for rel in sorted(set(local) | set(remote)):
        l, r = local.get(rel), remote.get(rel)
        types = {e["type"] for e in (l, r) if e}
        if len(types) > 1:
            res.errors.append(f"{rel}: file/folder type mismatch")
            bad.add(rel)
            continue
        (dirs if types == {"dir"} else files).append(rel)

    # 1) create missing folders (shallow first); remember deletions for later
    del_local_dirs, del_remote_dirs = [], []
    for rel in sorted(dirs, key=lambda x: x.count("/")):
        l, r, b = local.get(rel), remote.get(rel), base.get(rel)
        if l and r:
            continue
        try:
            if l:
                if b and down_ok:
                    del_local_dirs.append(rel)
                elif up_ok:
                    client.mkdir(p.remote_root, rp(rel))
            else:
                if b and up_ok and propagate:
                    del_remote_dirs.append(rel)
                elif b and up_ok:
                    kept.add(rel)
                elif down_ok:
                    lp(rel).mkdir(parents=True, exist_ok=True)
        except (ApiError, OSError) as exc:
            res.errors.append(f"{rel}: {exc}")
            bad.add(rel)

    # 2) files (independent of each other, so transfers run in parallel)
    remote_deleted: set[str] = set()
    lock = threading.Lock()

    def count(attr: str, n: int = 1):
        with lock:
            setattr(res, attr, getattr(res, attr) + n)

    def upload(rel):
        client.upload(p.remote_root, rp(rel), lp(rel))
        count("uploaded")
        emit(f"↑ {rel}")

    def download(rel):
        client.download(p.remote_root, rp(rel), lp(rel), mtime=remote[rel]["mtime"])
        count("downloaded")
        emit(f"↓ {rel}")

    def handle(rel):
        if stop():
            return
        l, r, b = local.get(rel), remote.get(rel), base.get(rel)
        try:
            if l and r:
                if _eq(l, r):
                    return
                if not b and l["size"] == r["size"]:
                    try:
                        if _sha256(lp(rel)) == client.hash(p.remote_root, rp(rel)):
                            os.utime(lp(rel), (time.time(), r["mtime"]))  # identical: adopt
                            return
                    except (ApiError, OSError):
                        pass
                l_changed = not (b and _eq(l, b))
                r_changed = not (b and _eq(r, b))
                if mode == "upload":          # backup: the local copy always wins
                    upload(rel)
                elif mode == "download":      # mirror: the server copy always wins
                    download(rel)
                elif l_changed and not r_changed:
                    upload(rel)
                elif r_changed and not l_changed:
                    download(rel)
                else:
                    count("conflicts")
                    cname = _conflict_name(rel)
                    if l["mtime"] >= r["mtime"]:
                        client.move(p.remote_root, rp(rel), rp(cname))
                        upload(rel)
                    else:
                        os.replace(lp(rel), lp(cname))
                        download(rel)
                    emit(f"⚠ conflict: {rel} (older copy kept as {cname})")
            elif l:
                if mode == "download":
                    return
                if b and _eq(l, b) and down_ok:
                    lp(rel).unlink()
                    count("deleted_local")
                    emit(f"✕ local {rel}")
                else:
                    upload(rel)
            elif r:
                if mode == "upload":
                    return
                if b and _eq(r, b) and up_ok and not propagate:
                    with lock:
                        kept.add(rel)      # removed from this device only; the server copy stays
                    emit(f"• kept on server: {rel}")
                elif b and _eq(r, b) and up_ok:
                    client.delete(p.remote_root, rp(rel))   # lands in the server trash, so it is recoverable
                    with lock:
                        remote_deleted.add(rel)
                    count("deleted_remote")
                    emit(f"✕ remote {rel}")
                else:
                    download(rel)
        except (ApiError, OSError) as exc:
            with lock:
                res.errors.append(f"{rel}: {exc}")
                bad.add(rel)

    workers = max(1, min(WORKERS, len(files)))
    if workers == 1:
        for rel in files:
            handle(rel)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sl-xfer") as pool:
            list(pool.map(handle, files))

    # 3) folder deletions (deepest first); never remove anything that still has content
    for rel in sorted(del_local_dirs, key=lambda x: -x.count("/")):
        try:
            lp(rel).rmdir()
            res.deleted_local += 1
        except OSError:
            pass
    for rel in sorted(del_remote_dirs, key=lambda x: -x.count("/")):
        prefix = rel + "/"
        if any(k.startswith(prefix) and k not in remote_deleted for k in remote):
            continue
        try:
            client.delete(p.remote_root, rp(rel))
            res.deleted_remote += 1
        except ApiError:
            pass

    # 4) new agreed snapshot
    local2 = visible(scan_tree(lroot))
    remote2 = visible(client.manifest(p.remote_root, rbase))
    newbase = {k: v for k, v in local2.items() if k in remote2 and _eq(v, remote2[k])}
    for k in kept:
        if k in base:
            newbase[k] = base[k]
    for k in bad:  # keep old knowledge for failed items so deletions aren't misread as new files
        if k in base:
            newbase[k] = base[k]
    save_state(p, newbase)
    return res


def pkey(p: Profile) -> str:
    return f"{p.sid}:{p.name}"


class ChangeListener(threading.Thread):
    """Listens to one server's live channel and calls on_change(server_id, root) the moment anything changes there."""

    def __init__(self, sid: str, on_change: Callable[[str, str], None]):
        super().__init__(daemon=True, name=f"sl-live-{sid}")
        self.sid, self.on_change = sid, on_change
        self._halt = threading.Event()
        self.connected = False

    def stop(self):
        self._halt.set()

    def run(self):
        import json
        delay = 2.0
        while not self._halt.is_set():
            srv = next((s for s in ClientConfig.load().servers if s.id == self.sid), None)
            if not (srv and srv.token and srv.profiles):
                self._halt.wait(5)
                continue
            try:
                from websockets.sync.client import connect
                c = Client(srv.url, srv.token)
                try:
                    ticket = c._req("GET", "/api/ticket").json()["ticket"]
                finally:
                    c.close()
                url = srv.url.rstrip("/").replace("https://", "wss://", 1).replace("http://", "ws://", 1)
                with connect(f"{url}/ws?ticket={ticket}", open_timeout=15, ping_interval=None) as ws:
                    self.connected, delay = True, 2.0
                    last_ping = time.time()
                    while not self._halt.is_set():
                        try:
                            msg = ws.recv(timeout=5)
                        except TimeoutError:
                            msg = None
                        if time.time() - last_ping > 25:
                            ws.send("ping")
                            last_ping = time.time()
                        if msg:
                            try:
                                d = json.loads(msg)
                            except ValueError:
                                continue
                            if d.get("event") == "change":
                                self.on_change(self.sid, d.get("root", ""))
            except Exception:  # noqa: BLE001  (offline, server restarting, websockets missing ...)
                pass
            self.connected = False
            self._halt.wait(delay)
            delay = min(60.0, delay * 2)


class Runner(threading.Thread):
    """Background loop for every connected server: syncs each enabled folder on its interval, immediately when the
    server announces a change, and right after local files change (watchdog, with cheap polling as a fallback)."""

    LOCAL_POLL = 6.0

    def __init__(self, on_status: Callable[[str], None] | None = None,
                 on_result: Callable[[str, SyncResult | None, str], None] | None = None):
        super().__init__(daemon=True, name="sl-sync")
        self.on_status = on_status or (lambda m: None)
        self.on_result = on_result or (lambda name, res, err: None)
        self._wake = threading.Event()
        self._halt = threading.Event()
        self.paused = False
        self.last_run: dict[str, float] = {}
        self.sigs: dict[str, int] = {}
        self.sig_checked: dict[str, float] = {}
        self.dirty: set[str] = set()
        self.busy = False
        self.active = ""                                  # key of the folder being synced right now
        self.state: dict[str, dict] = {}                  # per folder key: state, last (epoch), summary, error
        self._observers: dict[str, tuple] = {}            # key -> (local_dir, observer)
        self.listeners: dict[str, ChangeListener] = {}

    @property
    def live(self):
        """Compatibility: True when any server's live channel is connected."""
        return type("L", (), {"connected": any(l.connected for l in self.listeners.values())})()

    def status(self) -> dict:
        """Snapshot for the UIs, for the active server: {name: {state: idle|syncing|error|paused|off, last, summary, error}}."""
        out = {}
        for p in ClientConfig.load().profiles:
            st = dict(self.state.get(pkey(p), {"state": "idle", "last": 0, "summary": "", "error": ""}))
            if not p.enabled:
                st["state"] = "off"
            elif self.paused:
                st["state"] = "paused"
            out[p.name] = st
        return out

    def _watch(self, cfg):
        """Instant local change detection through watchdog (when installed); polling remains the fallback."""
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            return
        want = {pkey(p): str(Path(p.local_dir).expanduser()) for _, p in cfg.all_profiles() if p.enabled}
        for key in list(self._observers):
            if want.get(key) != self._observers[key][0]:
                try:
                    self._observers.pop(key)[1].stop()
                except Exception:  # noqa: BLE001
                    pass
        for key, d in want.items():
            if key in self._observers or not Path(d).is_dir():
                continue
            runner = self

            class H(FileSystemEventHandler):
                def on_any_event(self, event, _k=key):
                    if runner.active != _k and not Path(event.src_path).name.startswith(".sl-"):
                        runner.dirty.add(_k)
                        runner._wake.set()
            try:
                ob = Observer()
                ob.schedule(H(), d, recursive=True)
                ob.daemon = True
                ob.start()
                self._observers[key] = (d, ob)
            except Exception:  # noqa: BLE001  (inotify limit etc.): polling still covers it
                pass

    def _remote_changed(self, sid: str, root: str):
        for s, p in ClientConfig.load().all_profiles():
            if s.id == sid and (not root or p.remote_root == root):
                self.dirty.add(pkey(p))
        self._wake.set()

    def sync_now(self):
        self.last_run.clear()
        self._wake.set()

    def stop(self):
        self._halt.set()
        for _, ob in self._observers.values():
            try:
                ob.stop()
            except Exception:  # noqa: BLE001
                pass
        for l in self.listeners.values():
            l.stop()
        self._wake.set()

    def _due(self, p: Profile) -> bool:
        now, key = time.time(), pkey(p)
        since = now - self.last_run.get(key, 0)
        if key in self.dirty and since >= 2:
            return True
        if since >= max(5, p.interval):
            return True
        if since >= 3 and now - self.sig_checked.get(key, 0) >= self.LOCAL_POLL:
            self.sig_checked[key] = now
            try:
                sig = local_signature(p)
            except OSError:
                return False
            if key in self.sigs and sig != self.sigs[key]:
                return True
            self.sigs.setdefault(key, sig)
        return False

    def _listen(self, cfg):
        for s in cfg.servers:
            if s.token and s.profiles and s.id not in self.listeners:
                self.listeners[s.id] = ChangeListener(s.id, self._remote_changed)
                self.listeners[s.id].start()
        for sid in [i for i in self.listeners if not any(s.id == i for s in cfg.servers)]:
            self.listeners.pop(sid).stop()

    def run(self):
        while not self._halt.is_set():
            cfg = ClientConfig.load()
            self._watch(cfg)
            self._listen(cfg)
            set_limits(int(cfg.pref("limit_up_kb", 0) or 0), int(cfg.pref("limit_down_kb", 0) or 0))
            if not self.paused:
                for srv in cfg.servers:
                    if not (srv.token and srv.profiles) or self._halt.is_set() or self.paused:
                        continue
                    client = Client(srv.url, srv.token)
                    try:
                        for p in srv.profiles:
                            if self._halt.is_set() or self.paused:
                                break
                            if p.enabled and self._due(p):
                                self._one(client, p)
                    finally:
                        client.close()
            self._wake.wait(timeout=2)
            self._wake.clear()

    def _one(self, client: Client, p: Profile):
        key = pkey(p)
        self.last_run[key] = time.time()
        self.busy = True
        self.active = key
        self.state[key] = {**self.state.get(key, {}), "state": "syncing", "error": ""}
        self.on_status(f"Syncing {p.name}…")
        try:
            res = sync_once(client, p, on_event=self.on_status, should_stop=self._halt.is_set)
            self.state[key] = {"state": "error" if res.errors else "idle", "last": time.time(), "summary": res.summary(),
                               "error": res.errors[0] if res.errors else ""}
            self.on_status(f"{p.name}: {res.summary()}")
            self.on_result(p.name, res, "")
            try:
                self.sigs[key] = local_signature(p)
            except OSError:
                pass
        except (SyncError, ApiError, OSError) as exc:
            self.state[key] = {**self.state.get(key, {}), "state": "error", "last": time.time(), "error": str(exc)}
            self.on_status(f"{p.name}: {exc}")
            self.on_result(p.name, None, str(exc))
        finally:
            self.busy = False
            self.active = ""
            self.dirty.discard(key)
