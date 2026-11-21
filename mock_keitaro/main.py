# -*- coding: utf-8 -*-
"""Mock-Keitaro: локальный фейк Admin API для демо, docker-compose и pytest.

Данные держатся в памяти процесса; reset_state() восстанавливает сид —
используется тестами, рестарт контейнера тоже сбрасывает состояние.

Эндпоинты повторяют официальный Admin API (admin_api/v1). Авторизация:
любой непустой заголовок Api-Key.
"""
import random
import string
import time
from datetime import date, timedelta

from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI(title="Mock Keitaro")

_ALPHABET = string.ascii_letters + string.digits


# ---------------------------------------------------------------------------
# Сид — снимок их тестовой кампании из ТЗ/скриншотов
# ---------------------------------------------------------------------------

def _seed_offers():
    return {
        3749: {"id": 3749, "name": "Miaflow [BEAUTY-RO-BE_0009] [pl -- spin ro -] 2. Основной",
               "affiliate_network_id": 7, "state": "active"},
        3717: {"id": 3717, "name": "Miaflow [BEAUTY-RO-BE_0008] [pl -- prize ro -] 1. Основной",
               "affiliate_network_id": 7, "state": "active"},
        11111: {"id": 11111, "name": "11111 FitoMishki [Weight Loss-CO-DT_0309] [pl es -]",
                "affiliate_network_id": 8, "state": "active"},
        11112: {"id": 11112, "name": "11112 Oxys [BEAUTY-CL-BE_0155] [pl es -]",
                "affiliate_network_id": 8, "state": "active"},
        11113: {"id": 11113, "name": "11113 Zdorov [BEAUTY-RO-IM_0201] [pl es -]",
                "affiliate_network_id": 9, "state": "active"},
        11114: {"id": 11114, "name": "11114 TestoGen [Weight Loss-CO-DT_0311] [pl es -]",
                "affiliate_network_id": 9, "state": "active"},
    }


def _seed_streams():
    return {
        564220: {
            "id": 564220, "campaign_id": 93212, "type": "regular", "name": "Flow 1",
            "position": 1, "state": "active", "schema": "redirect",
            "action_type": "http", "action_payload": "https://google.com",
            "filters": [{"id": 41, "name": "country", "mode": "accept", "payload": ["AU"]}],
            "offers": [],
        },
        564221: {
            "id": 564221, "campaign_id": 93212, "type": "default", "name": "Flow 2",
            "position": 2, "state": "active", "schema": "landings",
            "action_type": "http", "action_payload": None,
            "filters": [],
            "offers": [
                {"offer_id": 3749, "share": 33, "state": "active"},
                {"offer_id": 3717, "share": 33, "state": "active"},
                {"offer_id": 11111, "share": 34, "state": "active"},
            ],
        },
    }


def _seed_campaigns():
    return {
        93212: {"id": 93212, "name": "campaign 2", "alias": "wVqN1R", "type": "position",
                "state": "active", "domain_id": 1, "group_id": 1, "traffic_source_id": 1},
    }


def reset_state() -> None:
    global OFFERS, STREAMS, CAMPAIGNS, CLICKS, OFFER_STATS, DOMAINS, GROUPS, SOURCES, _next_id
    OFFERS = _seed_offers()
    # Insert before active offers so catalog checks cover pagination around it.
    OFFERS = {11115: {"id": 11115, "name": "Paused demo offer", "state": "paused"}, **OFFERS}
    STREAMS = _seed_streams()
    CAMPAIGNS = _seed_campaigns()
    OFFER_STATS = {564221: {
        3749: {"today": 12, "week": [6, 9, 7, 11, 10, 14, 12]},
        3717: {"today": 8, "week": [5, 6, 8, 7, 9, 6, 8]},
        11111: {"today": 10, "week": [7, 8, 6, 9, 8, 11, 10]},
    }}
    CLICKS = {564220: 0, 564221: 30}
    DOMAINS = [{"id": 1, "name": "in.posdk.xyz", "state": "active"}]
    GROUPS = [{"id": 1, "name": "FORTESTS", "type": "campaigns"}]
    SOURCES = [{"id": 1, "name": "FORTESTS", "state": "active"}]
    # Локальная БД обёртки переживает перезапуск mock. Не выдаём заново
    # старые идентификаторы: иначе новая кампания наследует чужой архив.
    _next_id = max(globals().get("_next_id", 94000), time.time_ns() // 1_000_000)


reset_state()


# ---------------------------------------------------------------------------
# Endpoints: /admin_api/v1/...
# ---------------------------------------------------------------------------

def _auth(api_key: str | None) -> None:
    if not api_key:
        raise HTTPException(status_code=401, detail="Api-Key header required")


def _stream_payload(s: dict) -> dict:
    out = dict(s)
    out["offers"] = [{"offer_id": o["offer_id"], "share": o["share"],
                      "state": o.get("state", "active")} for o in s["offers"]]
    return out


@app.get("/admin_api/v1/campaigns")
def campaigns(api_key: str | None = Header(default=None)):
    _auth(api_key)
    return list(CAMPAIGNS.values())


@app.get("/admin_api/v1/campaigns/{campaign_id}")
def campaign(campaign_id: int, api_key: str | None = Header(default=None)):
    _auth(api_key)
    c = CAMPAIGNS.get(campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return c


@app.get("/admin_api/v1/campaigns/{campaign_id}/streams")
def campaign_streams(campaign_id: int, api_key: str | None = Header(default=None)):
    _auth(api_key)
    streams = [s for s in STREAMS.values() if s["campaign_id"] == campaign_id]
    return [_stream_payload(s) for s in sorted(streams, key=lambda x: x["position"])]


@app.get("/admin_api/v1/streams/{stream_id}")
def get_stream(stream_id: int, api_key: str | None = Header(default=None)):
    _auth(api_key)
    s = STREAMS.get(stream_id)
    if s is None:
        raise HTTPException(status_code=404, detail="stream not found")
    return _stream_payload(s)


@app.put("/admin_api/v1/streams/{stream_id}")
async def update_stream(stream_id: int, request: Request,
                        api_key: str | None = Header(default=None)):
    _auth(api_key)
    s = STREAMS.get(stream_id)
    if s is None:
        raise HTTPException(status_code=404, detail="stream not found")
    body = await request.json()
    for field in ("name", "type", "weight", "schema", "action_type", "action_payload", "filters"):
        if field in body:
            s[field] = body[field]
    if "offers" in body:
        # PUT частичный, но offers заменяются целиком
        s["offers"] = [{"offer_id": int(o["offer_id"]), "share": int(o["share"]),
                        "state": o.get("state", "active")} for o in body["offers"]]
    return _stream_payload(s)


@app.post("/admin_api/v1/streams")
async def create_stream(request: Request, api_key: str | None = Header(default=None)):
    global _next_id
    _auth(api_key)
    body = await request.json()
    _next_id += 1
    s = {
        "id": _next_id,
        "campaign_id": int(body["campaign_id"]),
        "type": body.get("type", "regular"),
        "name": body.get("name", ""),
        "position": int(body.get("position") or 0),
        "state": "active",
        "schema": body.get("schema", "action"),
        "action_type": body.get("action_type", "http"),
        "action_payload": body.get("action_payload"),
        "filters": body.get("filters", []),
        "offers": [{"offer_id": int(o["offer_id"]), "share": int(o["share"]),
                    "state": o.get("state", "active")} for o in body.get("offers", [])],
    }
    STREAMS[s["id"]] = s
    return _stream_payload(s)


@app.post("/admin_api/v1/campaigns")
async def create_campaign(request: Request, api_key: str | None = Header(default=None)):
    global _next_id
    _auth(api_key)
    body = await request.json()
    if not body.get("name"):
        raise HTTPException(status_code=400, detail="name is required")
    alias = body.get("alias") or "".join(random.choices(_ALPHABET, k=6))
    if any(c["alias"] == alias for c in CAMPAIGNS.values()):
        raise HTTPException(status_code=409, detail="alias already exists")
    _next_id += 1
    campaign = {
        "id": _next_id,
        "name": body["name"],
        "alias": alias,
        "type": body.get("type", "position"),
        "state": "active",
        "domain_id": body.get("domain_id"),
        "group_id": body.get("group_id"),
        "traffic_source_id": body.get("traffic_source_id"),
    }
    CAMPAIGNS[campaign["id"]] = campaign
    return campaign


@app.get("/admin_api/v1/offers")
def offers(offset: int = 0, limit: int = 100, api_key: str | None = Header(default=None)):
    _auth(api_key)
    items = list(OFFERS.values())
    return items[offset:offset + limit]


@app.get("/admin_api/v1/offers/{offer_id}")
def offer(offer_id: int, api_key: str | None = Header(default=None)):
    _auth(api_key)
    o = OFFERS.get(offer_id)
    if o is None:
        raise HTTPException(status_code=404, detail="offer not found")
    return o


@app.get("/admin_api/v1/domains")
def domains(api_key: str | None = Header(default=None)):
    _auth(api_key)
    return DOMAINS


@app.get("/admin_api/v1/groups")
def groups(type: str, api_key: str | None = Header(default=None)):
    _auth(api_key)
    return [g for g in GROUPS if g["type"] == type]


@app.get("/admin_api/v1/traffic_sources")
def traffic_sources(api_key: str | None = Header(default=None)):
    _auth(api_key)
    return SOURCES


@app.post("/admin_api/v1/report/build")
async def report_build(request: Request, api_key: str | None = Header(default=None)):
    _auth(api_key)
    body = await request.json()
    if "offer_id" in (body.get("group_by") or []) or "offer_id" in (body.get("dimensions") or []):
        today = date.today()
        first = today - timedelta(days=6)
        time_range = body.get("range") or {}
        start = date.fromisoformat(time_range.get("from", first.isoformat())[:10])
        end = date.fromisoformat(time_range.get("to", today.isoformat())[:10])
        selected = body.get("stream_id")
        if selected is None:
            selected = next((f.get("expression") for f in body.get("filters", [])
                             if f.get("name") == "stream_id" and f.get("operator") == "EQUALS"), None)
        rows = []
        for sid, stream in STREAMS.items():
            if selected is not None and sid != int(selected):
                continue
            stats = OFFER_STATS.get(sid, {})
            offer_ids = set(stats) | {o["offer_id"] for o in stream.get("offers", [])}
            for oid in sorted(offer_ids):
                week = stats.get(oid, {}).get("week", [0] * 7)
                for index, clicks in enumerate(week):
                    day = first + timedelta(days=index)
                    if start <= day <= end:
                        rows.append({"offer_id": oid, "date": day.isoformat(), "clicks": clicks})
        return {"rows": rows, "total": sum(r["clicks"] for r in rows),
                "meta": [{"name": k} for k in ("offer_id", "date", "clicks")]}
    rows = [{"stream_id": sid, "clicks": clicks}
            for sid, clicks in CLICKS.items() if clicks]
    return {"rows": rows, "total": sum(CLICKS.values()),
            "meta": [{"name": "stream_id"}, {"name": "clicks"}]}
