# -*- coding: utf-8 -*-
"""Mock-Keitaro: локальный фейк Admin API для демо, docker-compose и pytest.

Данные держатся в памяти процесса; reset_state() восстанавливает сид —
используется тестами, рестарт контейнера тоже сбрасывает состояние.

Эндпоинты повторяют официальный Admin API (admin_api/v1). Авторизация:
любой непустой заголовок Api-Key.
"""
import random
import string

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
            "position": 1, "state": "active", "schema": "action",
            "action_type": "redirectToUrl", "action_payload": {"url": "https://google.com"},
            "filters": [{"id": 41, "name": "country", "mode": "accept", "payload": ["AU"]}],
            "offers": [],
        },
        564221: {
            "id": 564221, "campaign_id": 93212, "type": "default", "name": "Flow 2",
            "position": 2, "state": "active", "schema": "offers",
            "action_type": "showOffers", "action_payload": None,
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
    global OFFERS, STREAMS, CAMPAIGNS, CLICKS, DOMAINS, GROUPS, SOURCES, _next_id
    OFFERS = _seed_offers()
    STREAMS = _seed_streams()
    CAMPAIGNS = _seed_campaigns()
    CLICKS = {564220: 0, 564221: 1}
    DOMAINS = [{"id": 1, "name": "in.posdk.xyz", "state": "active"}]
    GROUPS = [{"id": 1, "name": "FORTESTS", "type": "campaigns"}]
    SOURCES = [{"id": 1, "name": "FORTESTS", "state": "active"}]
    _next_id = 94000


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
        "action_type": body.get("action_type", "showOffers"),
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
def groups(api_key: str | None = Header(default=None)):
    _auth(api_key)
    return GROUPS


@app.get("/admin_api/v1/traffic_sources")
def traffic_sources(api_key: str | None = Header(default=None)):
    _auth(api_key)
    return SOURCES


@app.post("/admin_api/v1/report/build")
async def report_build(request: Request, api_key: str | None = Header(default=None)):
    _auth(api_key)
    rows = [{"stream_id": sid, "clicks": clicks}
            for sid, clicks in CLICKS.items() if clicks]
    return {"rows": rows, "total": sum(CLICKS.values()),
            "meta": [{"name": "stream_id"}, {"name": "clicks"}]}
