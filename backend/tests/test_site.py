"""Serving the built website from the API (single-origin deployment)."""

from fastapi.testclient import TestClient

from app.config import get_settings
from tests.conftest import FRONTEND_ORIGIN


def test_site_and_api_get_their_own_headers(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><title>Duo</title>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(get_settings(), "static_dir", str(tmp_path))

    from app.main import create_app

    client = TestClient(create_app(), base_url="http://localhost", headers={"Origin": FRONTEND_ORIGIN})

    page = client.get("/")
    assert page.status_code == 200
    assert "<title>Duo</title>" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-cache"

    asset = client.get("/assets/app-abc123.js")
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]

    api = client.get("/api/health")
    assert api.headers["content-security-policy"].startswith("default-src 'none'")
    assert api.headers["cache-control"] == "no-store"

    # API routes still win over the site, and unknown API paths are not served the page.
    assert client.get("/api/does-not-exist").status_code == 404
