# -*- coding: utf-8 -*-
"""REST API обёртки. Ошибки домена и Keitaro переводятся в HTTP-статусы:
404/409 — локальные, 502 — проблемы upstream Keitaro (с телом ошибки)."""
from html import escape
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import AppError
from app.kt_client import KeitaroClient, KtError
from app.models import Campaign, OfferCache, Stream
from app.schemas import CampaignCreateIn, OfferAddIn, PinIn
from app.services import creator, mutate, push
from app.services.sync import fetch_campaign, sync_campaigns_list

router = APIRouter(prefix="/api")


def get_kt() -> KeitaroClient:
    client = KeitaroClient(settings.kt_base_url, settings.kt_api_key, demo_mode=settings.demo_mode)
    try:
        yield client
    finally:
        client.close()


def _kt_admin_base() -> str:
    """База админки KT для кнопки VIEW IN KT (по умолчанию origin из kt_base_url)."""
    if settings.kt_admin_url:
        return settings.kt_admin_url.rstrip("/")
    parts = httpx.URL(settings.kt_base_url)
    origin = f"{parts.scheme}://{parts.host}" + (f":{parts.port}" if parts.port else "")
    return f"{origin}/admin/#!"


@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_kt)):
    camps = sync_campaigns_list(db, kt)
    out = []
    for c in camps:
        dirty_count = sum(1 for s in c.streams if s.dirty)
        out.append({
            "kt_campaign_id": c.kt_campaign_id,
            "name": c.name,
            "alias": c.alias,
            "created_via_wrapper": c.created_via_wrapper,
            "dirty_count": dirty_count,
            "demo_mode": settings.demo_mode,
            "admin_url": (f"/demo-keitaro.html?campaign={c.kt_campaign_id}" if settings.demo_mode else
                          f"{_kt_admin_base()}/campaign/{c.kt_campaign_id}/main"),
        })
    return out


@router.post("/campaigns")
def create_campaign(body: CampaignCreateIn, db: Session = Depends(get_db),
                    kt: KeitaroClient = Depends(get_kt)):
    return creator.create_campaign(db, kt, name=body.name, geos=body.geos,
                                   offer_id=body.offer_id, domain_id=body.domain_id,
                                   group_id=body.group_id, source_id=body.source_id)


@router.post("/campaigns/{campaign_id}/fetch")
def fetch_streams(campaign_id: int, db: Session = Depends(get_db),
                  kt: KeitaroClient = Depends(get_kt)):
    camp = fetch_campaign(db, kt, campaign_id)
    return {"ok": True, "kt_campaign_id": camp.kt_campaign_id,
            "streams": len(camp.streams)}


@router.get("/campaigns/{campaign_id}/streams")
def campaign_streams(campaign_id: int, db: Session = Depends(get_db),
                     kt: KeitaroClient = Depends(get_kt)):
    # первый показ кампании: локально пусто — тянем из KT сразу
    camp = db.get(Campaign, campaign_id)
    if camp is None or not camp.streams:
        fetch_campaign(db, kt, campaign_id)
    clicks = kt.report_clicks_today()
    streams = db.scalars(
        select(Stream).where(Stream.kt_campaign_id == campaign_id)
        .order_by(Stream.position, Stream.kt_stream_id)
    ).all()
    return [stream_dto(db, s, clicks.get(s.kt_stream_id)) for s in streams]


@router.post("/streams/{kt_stream_id}/offers")
def add_offer(kt_stream_id: int, body: OfferAddIn, db: Session = Depends(get_db),
              kt: KeitaroClient = Depends(get_kt)):
    stream = mutate.add_offer(db, kt, kt_stream_id, body.offer_id)
    return stream_dto(db, stream)


@router.post("/streams/{kt_stream_id}/push")
def push_to_kt(kt_stream_id: int, db: Session = Depends(get_db),
               kt: KeitaroClient = Depends(get_kt)):
    stream = push.push_stream(db, kt, kt_stream_id)
    return stream_dto(db, stream)


@router.get("/streams/{kt_stream_id}/stats")
def offer_stats(kt_stream_id: int, db: Session = Depends(get_db),
                kt: KeitaroClient = Depends(get_kt)):
    stream = db.scalar(select(Stream).where(Stream.kt_stream_id == kt_stream_id))
    if stream is None:
        raise HTTPException(404, "Поток не найден")
    report = kt.report_offer_clicks(kt_stream_id)
    return {"stream_id": kt_stream_id, "offers": [
        {"offer_id": b.kt_offer_id,
         **report.get(b.kt_offer_id, {"clicks_today": 0, "week": [0] * 7})}
        for b in sorted(stream.bindings, key=lambda b: b.position)
    ]}


@router.post("/streams/{kt_stream_id}/cancel")
def cancel(kt_stream_id: int, db: Session = Depends(get_db)):
    stream = mutate.cancel_stream(db, kt_stream_id)
    return stream_dto(db, stream)


@router.delete("/bindings/{binding_id}")
def remove_offer(binding_id: int, db: Session = Depends(get_db)):
    b = mutate.remove_binding(db, binding_id)
    return stream_dto(db, b.stream)


@router.post("/bindings/{binding_id}/bring-back")
def bring_back(binding_id: int, db: Session = Depends(get_db)):
    b = mutate.bring_back_binding(db, binding_id)
    return stream_dto(db, b.stream)


@router.post("/bindings/{binding_id}/pin")
def pin(binding_id: int, body: PinIn, db: Session = Depends(get_db)):
    b = mutate.set_pin(db, binding_id, body.pinned)
    return stream_dto(db, b.stream)


@router.get("/offers/search")
def search_offers(q: str = "", db: Session = Depends(get_db),
                  kt: KeitaroClient = Depends(get_kt)):
    """Автокомплит оффера: точный id — GET /offers/{id}, иначе фильтр списка по подстроке."""
    q = (q or "").strip()
    if not q:
        return []
    if q.isdigit():
        offer = kt.offer(int(q))
        if offer:
            from app.services.sync import cache_offer
            cache_offer(db, offer)
            db.commit()
            return [_offer_dto(offer)]
    out = []
    for offer in kt.offers(offset=0, limit=500):
        text = f"{offer.get('id')} {offer.get('name') or ''}".lower()
        if q.lower() in text:
            out.append(_offer_dto(offer))
        if len(out) >= 20:
            break
    return out


@router.get("/offers")
def list_offers(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                kt: KeitaroClient = Depends(get_kt)):
    items = kt.offers(offset=offset, limit=limit + 1)
    return {"items": [_offer_dto(o) for o in items[:limit]],
            "offset": offset, "limit": limit, "has_more": len(items) > limit}


@router.get("/offers/{offer_id}/preview", include_in_schema=False)
def preview_offer(offer_id: int, kt: KeitaroClient = Depends(get_kt)):
    offer = kt.offer(offer_id)
    if offer is None:
        raise HTTPException(404, "Оффер не найден")
    if settings.demo_mode:
        name = escape(offer.get("name") or str(offer_id))
        return HTMLResponse(f'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Предпросмотр оффера {offer_id}</title><link rel="stylesheet" href="/css/style.css">
<main class="page"><section class="card form-card"><h1>{name}</h1>
<p>Демо-предпросмотр оффера {offer_id}. Это тестовый оффер без рекламного сайта.</p>
<a href="/">Вернуться к кампаниям</a></section></main></html>''')
    preview = offer.get("preview_path") or ""
    if not isinstance(preview, str) or not preview or preview.startswith("//"):
        raise HTTPException(404, "Keitaro не предоставил адрес предпросмотра")
    destination = urljoin(settings.kt_base_url.rstrip("/") + "/", preview)
    if urlsplit(destination).scheme not in ("https", "http"):
        raise HTTPException(502, "Keitaro вернул некорректный адрес предпросмотра")
    return RedirectResponse(destination)


def _require_demo() -> None:
    if not settings.demo_mode:
        raise HTTPException(404, "Демо-режим отключён")


@router.get("/demo/campaigns/{campaign_id}", dependencies=[Depends(_require_demo)])
def demo_campaign(campaign_id: int, kt: KeitaroClient = Depends(get_kt)):
    """Читаем сам тестовый трекер, не рабочую копию обёртки."""
    campaign = kt.campaign(campaign_id)
    def name_for(items, item_id):
        return next((x.get("name") for x in items if x["id"] == item_id), None)
    streams = []
    for stream in kt.campaign_streams(campaign_id):
        offers = []
        for binding in stream.get("offers") or []:
            offer = kt.offer(binding["offer_id"])
            offers.append({"offer_id": binding["offer_id"], "share": binding.get("share", 0),
                           "name": (offer or {}).get("name") or str(binding["offer_id"])})
        streams.append({key: stream.get(key) for key in (
            "id", "name", "position", "schema", "type", "action_type", "action_payload", "filters")}
                       | {"offers": offers})
    return {"campaign": {key: campaign.get(key) for key in ("id", "name", "alias", "type")}
            | {"domain": name_for(kt.domains(), campaign.get("domain_id")),
               "group": name_for(kt.groups(), campaign.get("group_id")),
               "source": name_for(kt.traffic_sources(), campaign.get("traffic_source_id"))},
            "streams": streams}


@router.delete("/demo/streams/{stream_id}/offers/{offer_id}",
               dependencies=[Depends(_require_demo)])
def demo_remove_offer(stream_id: int, offer_id: int, kt: KeitaroClient = Depends(get_kt)):
    """Внешнее удаление в mock: локальная копия узнаёт о нём только по FETCH."""
    stream = kt.stream(stream_id)
    offers = stream.get("offers") or []
    if not any(o["offer_id"] == offer_id for o in offers):
        raise HTTPException(404, "Оффер отсутствует в потоке")
    kt.update_stream(stream_id, {"offers": [o for o in offers if o["offer_id"] != offer_id]})
    return {"ok": True}


@router.get("/reference")
def reference(db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_kt)):
    return {
        "demo_mode": settings.demo_mode,
        "domains": [{"id": d["id"], "name": d.get("name")}
                    for d in kt.domains()],
        "groups": [{"id": g["id"], "name": g.get("name")}
                   for g in kt.groups()],
        "sources": [{"id": s["id"], "name": s.get("name")}
                    for s in kt.traffic_sources()],
    }


def _offer_dto(offer: dict) -> dict:
    return {"offer_id": offer["id"], "name": offer.get("name") or "",
            "affiliate_network_id": offer.get("affiliate_network_id")}


def _filter_summary(stream: Stream) -> str | None:
    filters = (stream.kt_meta or {}).get("filters") or []
    if not filters:
        return None
    parts = []
    for f in filters:
        # Неизвестные/неструктурированные фильтры не ломают шапку потока.
        if not isinstance(f, dict) or not f.get("name") or not f.get("mode"):
            continue
        values = f.get("payload") or []
        if not isinstance(values, list):
            continue
        payload = ",".join(str(value) for value in values)
        parts.append(f"{f.get('name')} {f.get('mode')} [{payload}]")
    return "; ".join(parts) or None


def stream_dto(db: Session, stream: Stream, clicks_today: int | None = None) -> dict:
    offers = []
    if stream.is_offer_stream:
        for b in sorted(stream.bindings, key=lambda x: x.position):
            cache = db.get(OfferCache, b.kt_offer_id)
            offers.append({
                "binding_id": b.id,
                "offer_id": b.kt_offer_id,
                "name": cache.name if cache else str(b.kt_offer_id),
                "share": b.share,
                "state": b.state,
                "pinned": b.pinned,
                "preview_url": f"/api/offers/{b.kt_offer_id}/preview",
            })
    meta = stream.kt_meta or {}
    return {
        "kt_stream_id": stream.kt_stream_id,
        "kt_campaign_id": stream.kt_campaign_id,
        "name": stream.name,
        "position": stream.position,
        "type": meta.get("type"),
        "action_type": meta.get("action_type"),
        "filter_summary": _filter_summary(stream),
        "is_offer_stream": stream.is_offer_stream,
        "dirty": stream.dirty,
        "warning": stream.warning,
        "clicks_today": clicks_today,
        "offers": offers,
    }


# общий обработчик доменных и upstream-ошибок
def install_error_handlers(app) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request, exc: AppError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.exception_handler(KtError)
    async def kt_error_handler(request, exc: KtError):
        return JSONResponse(status_code=502,
                            content={"detail": f"Keitaro API: {exc.message}",
                                     "kt_status": exc.status, "kt_body": exc.body})
