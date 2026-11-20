# -*- coding: utf-8 -*-
"""Синхронизация с Keitaro: FETCH STREAMS FROM KT.

- потоки кампании тянутся из GET /campaigns/{id}/streams;
- потоки с offers[] — офферные: привязки синхронизируются, снапшот published
  заменяется ответом KT;
- офферы, исчезнувшие в KT, не удаляются, а переводятся в removed (серый,
  share 0, BRING BACK) — так ведёт себя их обёртка по видео;
- потоки без offers[] фиксируются как потоки, содержимое не парсим;
- локальные непушенные добавления (added_unpushed) при fetch стираются:
  истина — KT.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFound
from app.kt_client import KeitaroClient
from app.models import Campaign, OfferCache, Stream, OfferBinding, utcnow
from app.services.weights import ACTIVE, REMOVED


def cache_offer(db: Session, offer: dict) -> None:
    row = db.get(OfferCache, offer["id"])
    if row is None:
        row = OfferCache(kt_offer_id=offer["id"])
        db.add(row)
    row.name = offer.get("name") or ""
    row.affiliate_network_id = offer.get("affiliate_network_id")
    db.flush()


def cache_offers(db: Session, kt: KeitaroClient, offer_ids: set[int]) -> None:
    missing = [oid for oid in offer_ids if db.get(OfferCache, oid) is None]
    for oid in missing:
        data = kt.offer(oid)
        if data:
            cache_offer(db, data)


def sync_campaigns_list(db: Session, kt: KeitaroClient) -> list[Campaign]:
    """Список кампаний KT: upsert в локальную таблицу, сохраняя created_via_wrapper."""
    for c in kt.campaigns():
        row = db.get(Campaign, c["id"])
        if row is None:
            row = Campaign(kt_campaign_id=c["id"])
            db.add(row)
        row.name = c.get("name") or ""
        row.alias = c.get("alias") or ""
    db.commit()
    return list(db.scalars(select(Campaign).order_by(Campaign.kt_campaign_id)))


def fetch_campaign(db: Session, kt: KeitaroClient, kt_campaign_id: int) -> Campaign:
    streams = kt.campaign_streams(kt_campaign_id)
    campaign_info = kt.campaign(kt_campaign_id)

    camp = db.get(Campaign, kt_campaign_id)
    if camp is None:
        camp = Campaign(kt_campaign_id=kt_campaign_id)
        db.add(camp)
    camp.name = campaign_info.get("name") or ""
    camp.alias = campaign_info.get("alias") or ""

    seen_streams: set[int] = set()
    seen_offers: set[int] = set()

    for s in streams:
        kt_stream_id = int(s["id"])
        seen_streams.add(kt_stream_id)
        stream = db.scalars(
            select(Stream).where(Stream.kt_stream_id == kt_stream_id)
        ).first()
        if stream is None:
            stream = Stream(kt_stream_id=kt_stream_id)
            db.add(stream)
        stream.campaign = camp
        stream.name = s.get("name") or ""
        stream.position = int(s.get("position") or 0)
        kt_offers = s.get("offers") or []
        # После удаления последнего оффера поток остаётся ротатором:
        # архив и BRING BACK должны быть доступны и при пустом offers[].
        stream.is_offer_stream = bool(kt_offers) or s.get("schema") in ("landings", "offers")
        stream.kt_meta = {
            "type": s.get("type"),
            "schema": s.get("schema"),
            "action_type": s.get("action_type"),
            "filters": [
                {"name": f.get("name"), "mode": f.get("mode"),
                 "payload": f.get("payload")}
                for f in (s.get("filters") or [])
            ],
        }

        if stream.is_offer_stream:
            kt_map: dict[int, int] = {}
            for idx, o in enumerate(kt_offers):
                kt_map[int(o["offer_id"])] = int(o.get("share") or 0)
                seen_offers.add(int(o["offer_id"]))

            # локальные непушенные добавления стираются: их нет в KT
            for b in list(stream.bindings):
                if b.added_unpushed and b.kt_offer_id not in kt_map:
                    db.delete(b)
                    stream.bindings.remove(b)

            for idx, (offer_id, share) in enumerate(kt_map.items()):
                b = next((x for x in stream.bindings if x.kt_offer_id == offer_id), None)
                if b is None:
                    b = OfferBinding(stream=stream, kt_offer_id=offer_id)
                    db.add(b)
                b.state = ACTIVE
                b.share = share
                b.added_unpushed = False
                b.position = idx

            # пропавшие в KT офферы становятся removed — как будто удалили руками
            for b in stream.bindings:
                if b.kt_offer_id not in kt_map:
                    b.state = REMOVED
                    b.share = 0
                    b.added_unpushed = False

            stream.published_offers = [
                {"offer_id": oid, "share": share} for oid, share in kt_map.items()
            ]

        stream.dirty = False
        stream.warning = None

    # потоки, исчезнувшие из KT целиком, удаляем: KT — истина
    for stream in list(camp.streams):
        if stream.kt_stream_id not in seen_streams:
            db.delete(stream)

    camp.fetched_at = utcnow()
    db.flush()
    cache_offers(db, kt, seen_offers)
    db.commit()
    db.refresh(camp)
    return camp
