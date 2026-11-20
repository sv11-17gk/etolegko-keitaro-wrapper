"""Контракт клиента и безопасные повторы после ошибок транспорта."""
import httpx
import pytest

from app.kt_client import KeitaroClient, KtError


@pytest.mark.parametrize("failure", ["transport", "server"])
def test_create_does_not_retry_an_ambiguous_response(failure):
    requests = []

    def handler(request):
        requests.append(request)
        if failure == "transport":
            raise httpx.ReadTimeout("Response lost", request=request)
        return httpx.Response(503, json={"error": "Unavailable"})

    with httpx.Client(base_url="https://keitaro.test/", transport=httpx.MockTransport(handler)) as http:
        kt = KeitaroClient("https://keitaro.test", "mock-key", client=http)
        with pytest.raises(KtError):
            kt.create_campaign({"name": "test_karin_retry"})
    assert len(requests) == 1


def test_read_retries_a_temporary_server_error():
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, json={"error": "Unavailable"})
        return httpx.Response(200, json={"id": 42})

    with httpx.Client(base_url="https://keitaro.test/", transport=httpx.MockTransport(handler)) as http:
        kt = KeitaroClient("https://keitaro.test", "mock-key", client=http)
        assert kt.campaign(42) == {"id": 42}
    assert len(requests) == 2


def test_default_admin_link_uses_keitaro_hash_route(monkeypatch, db, kt):
    from app.api.routes import _kt_admin_base, list_campaigns
    from app.config import settings

    monkeypatch.setattr(settings, "kt_admin_url", "")
    monkeypatch.setattr(settings, "kt_base_url", "https://keitaro.test")
    assert _kt_admin_base() == "https://keitaro.test/admin/#!"
    assert list_campaigns(db, kt)[0]["admin_url"] == (
        "https://keitaro.test/admin/#!/campaign/93212/main")
    monkeypatch.setattr(settings, "demo_mode", True)
    assert list_campaigns(db, kt)[0]["admin_url"] is None
