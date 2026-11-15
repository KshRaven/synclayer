"""Drive features over the real API: trash, history, copy/move, search, shares, resumable uploads."""
import pytest

from tests.test_core import client  # noqa: F401  (fixture)


@pytest.fixture()
def drive(client, monkeypatch):  # noqa: F811
    client.put("/api/files", params={"path": "docs/a.txt"}, content=b"one")
    return client


def test_delete_goes_to_trash_and_restores(drive):
    assert drive.delete("/api/files", params={"path": "docs/a.txt"}).status_code == 200
    assert drive.get("/api/files", params={"path": "docs"}).json()["items"] == []
    items = drive.get("/api/trash").json()["items"]
    assert [i["path"] for i in items] == ["docs/a.txt"]
    r = drive.post("/api/trash/restore", json={"id": items[0]["id"]})
    assert r.json()["path"] == "docs/a.txt"
    assert drive.get("/api/trash").json()["items"] == []


def test_trash_is_hidden_and_unreachable(drive):
    drive.delete("/api/files", params={"path": "docs/a.txt"})
    assert ".synclayer" not in [i["name"] for i in drive.get("/api/files").json()["items"]]
    assert drive.get("/api/files", params={"path": ".synclayer"}).status_code == 404


def test_permanent_delete_skips_trash(drive):
    drive.delete("/api/files", params={"path": "docs/a.txt", "permanent": "true"})
    assert drive.get("/api/trash").json()["items"] == []


def test_overwrite_keeps_history_and_restores(drive):
    drive.put("/api/files", params={"path": "docs/a.txt"}, content=b"two")
    vers = drive.get("/api/versions", params={"path": "docs/a.txt"}).json()["items"]
    assert len(vers) == 1 and vers[0]["size"] == 3
    drive.post("/api/versions/restore", json={"path": "docs/a.txt", "id": vers[0]["id"]})
    assert drive.get("/api/download", params={"path": "docs/a.txt"}).content == b"one"


def test_batch_copy_move_delete(drive):
    drive.post("/api/mkdir", json={"path": "dest"})
    r = drive.post("/api/batch", json={"op": "copy", "paths": ["docs/a.txt"], "dest": "dest"}).json()
    assert r["ok"] and r["done"] == ["docs/a.txt"]
    drive.post("/api/batch", json={"op": "copy", "paths": ["docs/a.txt"], "dest": "dest"})
    names = sorted(i["name"] for i in drive.get("/api/files", params={"path": "dest"}).json()["items"])
    assert names == ["a (copy).txt", "a.txt"]
    drive.post("/api/batch", json={"op": "move", "paths": ["docs/a.txt"], "dest": "dest"})
    assert drive.get("/api/files", params={"path": "docs"}).json()["items"] == []
    bad = drive.post("/api/batch", json={"op": "delete", "paths": ["nope.txt"]}).json()
    assert not bad["ok"] and bad["errors"][0]["path"] == "nope.txt"


def test_search_recent_and_stars(drive):
    assert [i["path"] for i in drive.get("/api/search", params={"q": "A.TX"}).json()["items"]] == ["docs/a.txt"]
    assert drive.get("/api/recent").json()["items"][0]["path"] == "docs/a.txt"
    drive.put("/api/stars", json={"path": "docs/a.txt"})
    assert drive.get("/api/stars").json()["items"][0]["name"] == "a.txt"
    drive.delete("/api/files", params={"path": "docs/a.txt"})
    assert drive.get("/api/stars").json()["items"] == []


def test_share_link_public_download_with_password(drive):
    r = drive.post("/api/shares", json={"path": "docs/a.txt", "days": 1, "password": "hunter22"}).json()
    token = r["token"]
    anon = drive.__class__(drive.app)
    assert anon.get(f"/api/public/{token}/download").status_code == 401
    ok = anon.get(f"/api/public/{token}/download", params={"pw": "hunter22"})
    assert ok.status_code == 200 and ok.content == b"one"
    assert drive.delete(f"/api/shares/{token}").status_code == 200
    assert anon.get(f"/api/public/{token}").status_code == 404


def test_share_folder_cannot_escape(drive):
    token = drive.post("/api/shares", json={"path": "docs"}).json()["token"]
    anon = drive.__class__(drive.app)
    assert anon.get(f"/api/public/{token}", params={"sub": "../.."}).status_code in (400, 404)
    assert anon.get(f"/api/public/{token}").json()["items"][0]["name"] == "a.txt"


def test_resumable_upload(drive):
    u = drive.post("/api/uploads", json={"path": "big/f.bin", "size": 10}).json()
    r = drive.patch(f"/api/uploads/{u['id']}", content=b"12345", headers={"Upload-Offset": "0"}).json()
    assert r == {"offset": 5, "done": False}
    assert drive.patch(f"/api/uploads/{u['id']}", content=b"x", headers={"Upload-Offset": "0"}).status_code == 409
    r = drive.patch(f"/api/uploads/{u['id']}", content=b"67890", headers={"Upload-Offset": "5"}).json()
    assert r["done"]
    assert drive.get("/api/download", params={"path": "big/f.bin"}).content == b"1234567890"


def test_preview_allows_images_only(drive):
    drive.put("/api/files", params={"path": "p.png"}, content=b"\x89PNG")
    assert drive.get("/api/preview", params={"path": "p.png"}).headers["content-type"] == "image/png"
    assert drive.get("/api/preview", params={"path": "docs/a.txt"}).status_code == 415
