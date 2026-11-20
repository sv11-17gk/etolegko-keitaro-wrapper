# -*- coding: utf-8 -*-
"""HTTP-клиент Keitaro Admin API.

Базовый путь — {kt_base_url}/admin_api/v1, авторизация — заголовок Api-Key
(по документации docs.keitaro.io, раздел Admin API). PUT в Keitaro частичный:
обновляет только переданные поля.
"""
import logging
from datetime import date

import httpx

log = logging.getLogger(__name__)


class KtError(Exception):
    """Ошибка уровня HTTP при обращении к Keitaro."""

    def __init__(self, status: int, message: str, body: str = ""):
        super().__init__(message)
        self.status = status
        self.message = message
        self.body = body


class KeitaroClient:
    def __init__(self, base_url: str, api_key: str, client: httpx.Client | None = None):
        # client подставляется в тестах (starlette TestClient поверх mock-приложения);
        # в бою строим обычный синхронный httpx.Client с базой {root}/admin_api/v1/
        if client is not None:
            self._client = client
            self._client.headers.update({"Api-Key": api_key})
        else:
            root = base_url.rstrip("/")
            self._client = httpx.Client(
                base_url=f"{root}/admin_api/v1/",
                headers={"Api-Key": api_key, "Accept": "application/json"},
                timeout=15.0,
            )

    def close(self) -> None:
        self._client.close()

    # -- низкий уровень ------------------------------------------------------------

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 json: dict | None = None) -> dict | list:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = self._client.request(method, path, params=params, json=json)
            except httpx.TransportError as exc:
                last_exc = exc
                log.warning("Keitaro %s %s: транспортная ошибка (%s), попытка %d",
                            method, path, exc, attempt + 1)
                continue
            if resp.status_code >= 500:
                last_exc = KtError(resp.status_code, f"Keitaro вернул {resp.status_code}",
                                   resp.text[:500])
                log.warning("Keitaro %s %s: %s, попытка %d", method, path,
                            resp.status_code, attempt + 1)
                continue
            if resp.status_code >= 400:
                raise KtError(resp.status_code, f"Keitaro вернул {resp.status_code} на {path}",
                              resp.text[:500])
            if not resp.content:
                return {}
            return resp.json()
        raise KtError(503, f"Keitaro недоступен после ретраев: {path}", str(last_exc))

    # -- чтение --------------------------------------------------------------------

    def campaigns(self) -> list[dict]:
        data = self._request("GET", "campaigns", params={"limit": 100})
        return data if isinstance(data, list) else data.get("items", [])

    def campaign(self, campaign_id: int) -> dict:
        return self._request("GET", f"campaigns/{campaign_id}")

    def campaign_streams(self, campaign_id: int) -> list[dict]:
        data = self._request("GET", f"campaigns/{campaign_id}/streams")
        return data if isinstance(data, list) else []

    def stream(self, stream_id: int) -> dict:
        return self._request("GET", f"streams/{stream_id}")

    def offers(self, offset: int = 0, limit: int = 500) -> list[dict]:
        data = self._request("GET", "offers", params={"offset": offset, "limit": limit})
        return data if isinstance(data, list) else data.get("items", [])

    def offer(self, offer_id: int) -> dict | None:
        try:
            return self._request("GET", f"offers/{offer_id}")
        except KtError as exc:
            if exc.status == 404:
                return None
            raise

    def domains(self) -> list[dict]:
        return self._list("domains")

    def groups(self) -> list[dict]:
        return self._list("groups")

    def traffic_sources(self) -> list[dict]:
        return self._list("traffic_sources")

    def _list(self, path: str) -> list[dict]:
        data = self._request("GET", path)
        return data if isinstance(data, list) else data.get("items", [])

    # -- запись --------------------------------------------------------------------

    def create_campaign(self, payload: dict) -> dict:
        return self._request("POST", "campaigns", json=payload)

    def create_stream(self, payload: dict) -> dict:
        return self._request("POST", "streams", json=payload)

    def update_stream(self, stream_id: int, payload: dict) -> dict:
        return self._request("PUT", f"streams/{stream_id}", json=payload)

    # -- отчёты --------------------------------------------------------------------

    def report_clicks_today(self) -> dict[int, int]:
        """Клики за сегодня в разрезе stream_id. Формат rows в Keitaro не зафиксирован
        в OpenAPI, поэтому парсим защитно: и dict-строки, и list-строки с meta."""
        payload = {
            "range": {"from": date.today().isoformat(), "to": date.today().isoformat()},
            "dimensions": ["stream_id"],
            "measures": ["clicks"],
        }
        try:
            data = self._request("POST", "report/build", json=payload)
        except KtError as exc:
            log.warning("report/build недоступен: %s", exc.message)
            return {}
        rows = data.get("rows", []) if isinstance(data, dict) else (data or [])
        meta = data.get("meta", []) if isinstance(data, dict) else []
        names: list[str] = []
        for m in meta or []:
            if isinstance(m, dict):
                names.append(str(m.get("name") or m.get("key") or ""))
            elif isinstance(m, str):
                names.append(m)
        out: dict[int, int] = {}
        for r in rows or []:
            if isinstance(r, dict):
                sid, clicks = r.get("stream_id"), r.get("clicks")
            elif isinstance(r, list) and names:
                d = dict(zip(names, r))
                sid, clicks = d.get("stream_id"), d.get("clicks")
            else:
                continue
            if sid is None:
                continue
            try:
                out[int(sid)] = int(clicks or 0)
            except (TypeError, ValueError):
                continue
        return out
