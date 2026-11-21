"""Управление трекером в демо независимо от рабочей копии обёртки."""
import pytest
import httpx
from starlette.testclient import TestClient

import mock_keitaro.main as mock_main
from app.api.routes import get_kt
from app.config import settings
from app.db import get_db
from app.main import app


@pytest.fixture()
def api(db, kt, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_kt] = lambda: kt
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_catalog_returns_all_pages_without_a_search_term(api):
    first = api.get("/api/offers?limit=2").json()
    second = api.get("/api/offers?limit=2&offset=2").json()
    last = api.get("/api/offers?limit=2&offset=4").json()
    assert first["has_more"] and second["has_more"] and not last["has_more"]
    ids = [o["offer_id"] for page in (first, second, last) for o in page["items"]]
    active_ids = {oid for oid, offer in mock_main.OFFERS.items() if offer["state"] == "active"}
    assert set(ids) == active_ids and len(ids) == len(active_ids)
    assert api.get("/api/offers?limit=1000").status_code == 422


def test_browser_does_not_reuse_stale_reference_or_assets(api):
    assert api.get("/api/reference").headers["cache-control"] == "no-store"
    assert api.get("/js/create.js").headers["cache-control"] == "no-cache"


def test_demo_view_sees_only_published_state_until_push(api):
    original = api.get("/api/campaigns/93212/streams").json()
    stream = next(s for s in original if s["is_offer_stream"])
    draft = api.post(f"/api/streams/{stream['kt_stream_id']}/offers", json={"offer_id": 11112})
    assert draft.status_code == 200
    view = api.get("/api/demo/campaigns/93212").json()
    assert view["campaign"]["domain"] == "in.posdk.xyz"
    assert view["campaign"]["group"] == view["campaign"]["source"] == "FORTESTS"
    published = next(s for s in view["streams"] if s["name"] == "Flow 2")
    assert len(published["offers"]) == 3
    assert api.post(f"/api/streams/{stream['kt_stream_id']}/push").status_code == 200
    view = api.get("/api/demo/campaigns/93212").json()
    published = next(s for s in view["streams"] if s["name"] == "Flow 2")
    assert len(published["offers"]) == 4
    assert {o["share"] for o in published["offers"]} == {25}


def test_external_demo_removal_changes_wrapper_only_after_fetch(api):
    api.get("/api/campaigns/93212/streams")
    assert api.delete("/api/demo/streams/564221/offers/11111").status_code == 200
    streams = api.get("/api/campaigns/93212/streams").json()
    offer = next(o for s in streams for o in s["offers"] if o["offer_id"] == 11111)
    assert offer["state"] == "active"
    api.post("/api/campaigns/93212/fetch")
    streams = api.get("/api/campaigns/93212/streams").json()
    offer = next(o for s in streams for o in s["offers"] if o["offer_id"] == 11111)
    assert offer["state"] == "removed" and offer["share"] == 0
    assert api.post(f"/api/bindings/{offer['binding_id']}/bring-back").status_code == 200
    assert api.post("/api/streams/564221/push").status_code == 200
    assert any(o["offer_id"] == 11111 for o in mock_main.STREAMS[564221]["offers"])


def test_demo_controls_are_inaccessible_in_real_mode(api, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    assert api.get("/api/demo/campaigns/93212").status_code == 404
    assert api.delete("/api/demo/streams/564221/offers/11111").status_code == 404
    assert len(mock_main.STREAMS[564221]["offers"]) == 3


def test_demo_preview_is_explicit_and_escapes_offer_names(api):
    mock_main.OFFERS[3749]["name"] = '<script>alert("x")</script>'
    preview = api.get("/api/offers/3749/preview")
    assert preview.status_code == 200
    assert "Демо-предпросмотр" in preview.text
    assert "<script>" not in preview.text and "&lt;script&gt;" in preview.text
    assert api.get("/api/offers/999999/preview").status_code == 404


def test_real_preview_uses_the_upstream_preview_path(api, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "kt_base_url", "https://keitaro.test")
    mock_main.OFFERS[3749]["preview_path"] = "/admin/preview/3749"
    preview = api.get("/api/offers/3749/preview", follow_redirects=False)
    assert preview.status_code == 307
    assert preview.headers["location"] == "https://keitaro.test/admin/preview/3749"


@pytest.mark.parametrize("field", ["offer_url", "url", None])
def test_preview_fallback(api, monkeypatch, field):
    monkeypatch.setattr(settings, "demo_mode", False)
    if field:
        mock_main.OFFERS[3749][field] = "https://offers.example/preview"
    result = api.get("/api/offers/3749/preview", follow_redirects=False)
    assert result.status_code == (307 if field else 404)
    if field:
        assert result.headers["location"] == "https://offers.example/preview"


def test_catalog_and_search_exclude_inactive_offers(api):
    mock_main.OFFERS[11116] = {"id": 11116, "name": "Deleted demo offer", "status": "deleted"}
    mock_main.OFFERS[11117] = {"id": 11117, "name": "Active demo offer", "status": "active"}
    for offer_id in (11115, 11116):
        assert api.get(f"/api/offers/search?q={offer_id}").json() == []
    result = api.get("/api/offers/search?q=demo+offer").json()
    assert [o["offer_id"] for o in result] == [11117]
    assert {11115, 11116}.isdisjoint(o["offer_id"] for o in api.get("/api/offers").json()["items"])


def test_tracker_unreachable_returns_a_readable_error(api):
    from app.kt_client import KeitaroClient

    def unavailable(request):
        raise httpx.ConnectError("Unreachable", request=request)

    with httpx.Client(base_url="https://keitaro.test/", transport=httpx.MockTransport(unavailable)) as http:
        client = KeitaroClient("https://keitaro.test", "test-key", client=http)
        app.dependency_overrides[get_kt] = lambda: client
        result = api.get("/api/campaigns")
    assert result.status_code == 502
    assert "Keitaro недоступен" in result.json()["detail"]
    assert "test-key" not in result.text


@pytest.mark.parametrize("address", ["javascript:alert(1)", "//unexpected.test/preview"])
def test_real_preview_rejects_unsafe_upstream_urls(api, monkeypatch, address):
    monkeypatch.setattr(settings, "demo_mode", False)
    mock_main.OFFERS[3749]["preview_path"] = address
    assert api.get("/api/offers/3749/preview", follow_redirects=False).status_code in (404, 502)
