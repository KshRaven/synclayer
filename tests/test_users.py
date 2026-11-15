"""Multi-user accounts: private drives, folder grants, quotas, admin management."""
import pytest

from tests.test_core import client  # noqa: F401


def login(c, name, pw):
    r = c.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def duo(client):  # noqa: F811
    for n in ("alice", "bob"):
        assert client.post("/api/admin/users", json={"name": n, "password": "password-" + n}).status_code == 200
    admin = dict(client.headers)
    client.headers.clear()
    alice, bob = login(client, "alice", "password-alice"), login(client, "bob", "password-bob")
    yield client, admin, alice, bob


def test_private_drives(duo):
    c, admin, alice, bob = duo
    assert c.put("/api/files", params={"root": "u:alice", "path": "a.txt"}, content=b"hi", headers=alice).status_code == 200
    assert c.get("/api/files", params={"root": "u:alice"}, headers=bob).status_code == 404
    assert c.put("/api/files", params={"root": "main", "path": "secret.txt"}, content=b"x", headers=admin).status_code == 200
    # members asking for "main" (older clients) get their own drive, never the shared server storage
    r = c.get("/api/files", params={"root": "main"}, headers=alice)
    assert r.status_code == 200 and [i["name"] for i in r.json()["items"]] == ["a.txt"]
    me = c.get("/api/me", headers=alice).json()
    assert me["role"] == "member" and me["default_root"] == "u:alice"
    assert [i["name"] for i in c.get("/api/files", params={"root": "u:alice"}, headers=alice).json()["items"]] == ["a.txt"]


def test_grant_read_only_and_read_write(duo):
    c, admin, alice, bob = duo
    c.put("/api/files", params={"root": "u:alice", "path": "pics/x.txt"}, content=b"1", headers=alice)
    g = c.post("/api/grants", json={"root": "u:alice", "path": "pics", "to": "bob", "perm": "ro"}, headers=alice).json()
    root = "s:" + g["id"]
    got = c.get("/api/me", headers=bob).json()["roots"]
    assert [r["id"] for r in got] == ["u:bob", root] and got[1]["writable"] is False
    assert c.get("/api/files", params={"root": root}, headers=bob).json()["items"][0]["name"] == "x.txt"
    assert c.put("/api/files", params={"root": root, "path": "y.txt"}, content=b"2", headers=bob).status_code == 403
    c.post("/api/grants", json={"root": "u:alice", "path": "pics", "to": "bob", "perm": "rw"}, headers=alice)
    assert c.put("/api/files", params={"root": root, "path": "y.txt"}, content=b"2", headers=bob).status_code == 200
    assert c.get("/api/download", params={"root": "u:alice", "path": "pics/y.txt"}, headers=alice).content == b"2"
    assert c.get("/api/files", params={"root": root, "path": "../.."}, headers=bob).status_code == 400
    assert c.delete(f"/api/grants/{g['id']}", headers=alice).status_code == 200
    assert c.get("/api/files", params={"root": root}, headers=bob).status_code == 404


def test_member_cannot_use_admin_api_or_reshare(duo):
    c, admin, alice, bob = duo
    assert c.get("/api/admin/settings", headers=alice).status_code == 403
    assert c.get("/api/admin/users", headers=alice).status_code == 403
    c.post("/api/mkdir", json={"root": "u:alice", "path": "f"}, headers=alice)
    g = c.post("/api/grants", json={"root": "u:alice", "path": "f", "to": "bob"}, headers=alice).json()
    r = c.post("/api/grants", json={"root": "s:" + g["id"], "path": "", "to": "alice"}, headers=bob)
    assert r.status_code == 403


def test_user_quota_and_disable(duo):
    c, admin, alice, bob = duo
    c.patch("/api/admin/users/alice", json={"quota_mb": 1}, headers=admin)
    big = c.put("/api/files", params={"root": "u:alice", "path": "big.bin"}, content=b"x" * (2 << 20), headers=alice)
    assert big.status_code == 507
    c.patch("/api/admin/users/alice", json={"disabled": True}, headers=admin)
    assert c.get("/api/me", headers=alice).status_code == 401
    assert c.post("/api/auth/login", json={"username": "alice", "password": "password-alice"}).status_code == 401


def test_share_links_and_stars_are_per_user(duo):
    c, admin, alice, bob = duo
    c.put("/api/files", params={"root": "u:alice", "path": "doc.txt"}, content=b"d", headers=alice)
    tok = c.post("/api/shares", json={"root": "u:alice", "path": "doc.txt"}, headers=alice).json()["token"]
    assert c.get(f"/api/public/{tok}/download").content == b"d"
    assert c.get("/api/shares", headers=bob).json()["items"] == []
    c.put("/api/stars", json={"root": "u:alice", "path": "doc.txt"}, headers=alice)
    assert len(c.get("/api/stars", headers=alice).json()["items"]) == 1
    assert c.get("/api/stars", headers=bob).json()["items"] == []


def test_delete_user_keeps_or_purges_data(duo):
    c, admin, alice, bob = duo
    assert c.delete("/api/admin/users/bob", headers=admin).json()["ok"]
    assert c.post("/api/auth/login", json={"username": "bob", "password": "password-bob"}).status_code == 401
    assert [u["name"] for u in c.get("/api/admin/users", headers=admin).json()["items"]] == ["alice"]
