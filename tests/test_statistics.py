"""ТЗ v2: фильтры любых потоков и статистика офферов за семь дней."""
import json
from datetime import date, timedelta

import httpx
import pytest
from starlette.testclient import TestClient

from app.api.routes import get_kt
from app.config import settings
from app.db import get_db
from app.kt_client import KeitaroClient, KtError
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


def test_created_campaign_exposes_country_filter_and_null_for_no_filter(api):
    response = api.post("/api/campaigns", json={
        "name": "test_karin_filter_stats", "geos": ["MX", "AU"], "offer_id": 11113})
    assert response.status_code == 200
    cid = response.json()["kt_campaign_id"]
    streams = api.get(f"/api/campaigns/{cid}/streams").json()
    flow1 = next(s for s in streams if s["name"] == "Flow 1")
    flow2 = next(s for s in streams if s["name"] == "Flow 2")
    assert not flow1["is_offer_stream"]
    assert flow1["filter_summary"] == "country accept [MX,AU]"
    assert flow2["filter_summary"] is None


def test_seed_statistics_and_stream_total_are_consistent(api, kt):
    streams = api.get("/api/campaigns/93212/streams").json()
    assert next(s for s in streams if s["name"] == "Flow 2")["filter_summary"] is None
    response = api.get("/api/streams/564221/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["stream_id"] == 564221
    by_id = {o["offer_id"]: o for o in data["offers"]}
    assert set(by_id) == {3749, 3717, 11111}
    assert by_id[3749] == {"offer_id": 3749, "clicks_today": 12,
                          "week": [6, 9, 7, 11, 10, 14, 12]}
    assert by_id[3717]["clicks_today"] == 8
    assert by_id[11111]["clicks_today"] == 10
    assert kt.report_clicks_today()[564221] == sum(o["clicks_today"] for o in by_id.values()) == 30


def test_new_stream_has_zero_statistics_even_for_seed_offer(api):
    created = api.post("/api/campaigns", json={
        "name": "test_karin_zero_stats", "geos": ["MX"], "offer_id": 3749}).json()
    streams = api.get(f"/api/campaigns/{created['kt_campaign_id']}/streams").json()
    stream = next(s for s in streams if s["is_offer_stream"])
    assert api.get(f"/api/streams/{stream['kt_stream_id']}/stats").json()["offers"] == [
        {"offer_id": 3749, "clicks_today": 0, "week": [0] * 7}]


def test_removed_offer_remains_in_statistics_response(api):
    streams = api.get("/api/campaigns/93212/streams").json()
    offer = next(o for s in streams for o in s["offers"] if o["offer_id"] == 11111)
    api.delete(f"/api/bindings/{offer['binding_id']}")
    data = api.get("/api/streams/564221/stats").json()
    assert next(o for o in data["offers"] if o["offer_id"] == 11111)["clicks_today"] == 10


def test_unknown_stream_returns_404_without_requesting_report(api, kt, monkeypatch):
    def unexpected_report(_):
        pytest.fail("Для неизвестного потока не нужен отчёт Keitaro")
    monkeypatch.setattr(kt, "report_offer_clicks", unexpected_report)
    assert api.get("/api/streams/999999/stats").status_code == 404


def test_stats_failure_is_explicit_and_does_not_modify_the_stream(api, kt, monkeypatch):
    before = api.get("/api/campaigns/93212/streams").json()
    def unavailable(_):
        raise KtError(503, "Report unavailable")
    monkeypatch.setattr(kt, "report_offer_clicks", unavailable)
    assert api.get("/api/streams/564221/stats").status_code == 502
    assert api.get("/api/campaigns/93212/streams").json() == before


def test_mock_also_accepts_the_real_keitaro_report_contract(kt):
    from mock_keitaro.main import app as mock_app
    with TestClient(mock_app, base_url="http://mock.local/admin_api/v1/") as http:
        real_contract = KeitaroClient("http://mock.local", "mock-key", client=http)
        assert real_contract.report_offer_clicks(564221)[3749] == {
            "clicks_today": 12, "week": [6, 9, 7, 11, 10, 14, 12]}


@pytest.mark.parametrize("array_rows", [False, True])
@pytest.mark.parametrize("demo_mode", [False, True])
def test_report_uses_one_request_and_fills_missing_dates(array_rows, demo_mode):
    today = date.today()
    first = today - timedelta(days=6)
    requests = []
    rows = [
        {"offer_id": "3749", "date": first.isoformat(), "clicks": "6"},
        {"offer_id": 3749, "date": today.isoformat(), "clicks": 12},
        {"offer_id": 3749, "date": (today + timedelta(days=1)).isoformat(), "clicks": 99},
        {"offer_id": 3749, "date": "bad date", "clicks": 99},
    ]
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "rows": [list(r.values()) for r in rows] if array_rows else rows,
            "meta": ["offer_id", "date", "clicks"],
        })
    with httpx.Client(base_url="https://keitaro.test/", transport=httpx.MockTransport(handler)) as http:
        kt = KeitaroClient("https://keitaro.test", "key", client=http, demo_mode=demo_mode)
        assert kt.report_offer_clicks(564221) == {
            3749: {"clicks_today": 12, "week": [6, 0, 0, 0, 0, 0, 12]}}
    assert len(requests) == 1
    if demo_mode:
        assert requests[0]["stream_id"] == 564221
        assert requests[0]["group_by"] == ["offer_id"]
    else:
        assert "stream_id" not in requests[0] and "group_by" not in requests[0]
    assert requests[0]["dimensions"] == ["offer_id", "day"]
    assert requests[0]["measures"] == ["clicks"]
    assert requests[0]["range"] == {"from": first.isoformat(), "to": today.isoformat()}
    assert requests[0]["filters"] == [
        {"name": "stream_id", "operator": "EQUALS", "expression": 564221}]
