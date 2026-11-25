from __future__ import annotations

import pytest

from app.connections import ConnectionError_, ConnectionStore, display_url, normalize_url
from app.database import DatabaseRegistry


def test_normalize_picks_driver():
    assert normalize_url("postgresql://u:p@h:5432/db").drivername == "postgresql+psycopg"
    assert normalize_url("postgres://u:p@h/db").drivername == "postgresql+psycopg"
    assert normalize_url("mysql://u:p@h/db").drivername == "mysql+pymysql"
    assert normalize_url("mariadb://u:p@h/db").drivername == "mysql+pymysql"


@pytest.mark.parametrize("bad", ["", "not a url", "sqlite:///etc/passwd", "sqlite:////tmp/x.db", "oracle://u:p@h/db",
                                 "postgresql://u:p@/db", "postgresql://u:p@h"])
def test_normalize_rejects(bad):
    with pytest.raises(ConnectionError_):
        normalize_url(bad)


def test_display_url_hides_password():
    assert "secret" not in display_url(normalize_url("postgresql://u:secret@h/db"))


def test_store_encrypts_and_roundtrips(tmp_path):
    store = ConnectionStore(tmp_path)
    store.add("Prod", "postgresql://u:hunter2@h/db")
    assert "hunter2" not in (tmp_path / "connections.json").read_text()
    assert [(c.name, c.url) for c in store.list()] == [("Prod", "postgresql://u:hunter2@h/db")]
    assert (tmp_path / ".connection_key").stat().st_mode & 0o077 == 0
    store.remove("Prod")
    assert store.list() == []


def test_store_skips_entries_it_cannot_decrypt(tmp_path):
    store = ConnectionStore(tmp_path)
    store.add("A", "postgresql://u:p@h/db")
    (tmp_path / ".connection_key").unlink()  # key lost
    assert ConnectionStore(tmp_path).list() == []


def test_registry_connect_and_delete(registry: DatabaseRegistry, monkeypatch):
    monkeypatch.setattr(DatabaseRegistry, "_probe", staticmethod(lambda url: None))
    info = registry.add_connection("Warehouse", "postgresql://u:pw@db.example.com/sales")
    assert info.kind == "external" and info.dialect == "postgresql" and info.saved
    out = info.to_out()
    assert out.deletable and "pw" not in out.description
    registry.delete_connection(info.id)
    assert all(d.name != "Warehouse" for d in registry.list())


def test_registry_rejects_duplicate_and_bad_probe(registry: DatabaseRegistry, monkeypatch):
    def boom(url):
        raise ConnectionError_("Could not connect: refused")

    monkeypatch.setattr(DatabaseRegistry, "_probe", staticmethod(boom))
    with pytest.raises(ConnectionError_, match="refused"):
        registry.add_connection("X", "postgresql://u:p@h/db")
    assert all(d.name != "X" for d in registry.list())
    with pytest.raises(ConnectionError_, match="already exists"):
        registry.add_connection(registry.list()[0].name, "postgresql://u:p@h/db")


def test_connect_endpoint(client, monkeypatch):
    monkeypatch.setattr(DatabaseRegistry, "_probe", staticmethod(lambda url: None))
    r = client.post("/api/databases/connect", json={"name": "Live", "url": "mysql://u:p@h/db"})
    assert r.status_code == 201 and r.json()["deletable"] and r.json()["dialect"] == "mysql"
    assert client.post("/api/databases/connect", json={"name": "Bad", "url": "sqlite:///x.db"}).status_code == 400
    assert client.delete(f"/api/databases/{r.json()['id']}").status_code == 204
    assert all(d["name"] != "Live" for d in client.get("/api/databases").json())


def test_real_connection_failure_is_a_clean_error(registry: DatabaseRegistry):
    with pytest.raises(ConnectionError_, match="Could not connect"):
        registry.add_connection("Nope", "postgresql://u:p@127.0.0.1:1/db")
