# -*- coding: utf-8 -*-
"""REST API обёртки. Ошибки домена и Keitaro переводятся в HTTP-статусы:
404/409 — локальные, 502 — проблемы upstream Keitaro (с телом ошибки)."""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
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
    client = KeitaroClient(settings.kt_base_url, settings.kt_api_key)
    try:
        yield client
    finally:
        client.close()


def _kt_admin_base() -> str:
    """База админки KT для кнопки VIEW IN KT (по умолчанию origin из kt_base_url)."""
    if settings.kt_admin_url:
        return settings.kt_admin_url.rstrip("/")
    parts = httpx.URL(settings.kt_base_url)
    return f"{parts.scheme}://{parts.host}" + (f":{parts.port}" if parts.port else "")


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
            "admin_url": f"{_kt_admin_base()}/campaigns/{c.kt_campaign_id}",
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


@router.get("/reference")
def reference(db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_kt)):
    return {
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


def _filter_summary(stream: Stream) -> str:
    filters = (stream.kt_meta or {}).get("filters") or []
    if not filters:
        return "None"
    parts = []
    for f in filters:
        payload = ",".join(f.get("payload") or [])
        parts.append(f"{f.get('name')} {f.get('mode')} [{payload}]")
    return "; ".join(parts)


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
