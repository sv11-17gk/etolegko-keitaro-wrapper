# -*- coding: utf-8 -*-
"""Мутации рабочей копии: add / remove / bring back / pin / cancel.

Все мутации работают только с локальной БД (поток желтеет) и пересчитывают веса;
Keitaro меняется только по PUSH. CANCEL откатывает к снапшоту published: привязки
непушенных добавлений удаляются физически (по видео), остальное восстанавливается.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, NotFound
from app.kt_client import KeitaroClient
from app.models import OfferBinding, Stream
from app.services.sync import cache_offer
from app.services.weights import ACTIVE, REMOVED, recalc_stream


def _get_stream(db: Session, kt_stream_id: int) -> Stream:
    stream = db.scalars(
        select(Stream).where(Stream.kt_stream_id == kt_stream_id)
    ).first()
    if stream is None:
        raise NotFound(f"Поток {kt_stream_id} не найден локально — сначала FETCH STREAMS FROM KT")
    return stream


def _get_binding(db: Session, binding_id: int) -> OfferBinding:
    b = db.get(OfferBinding, binding_id)
    if b is None:
        raise NotFound(f"Привязка {binding_id} не найдена")
    return b


def add_offer(db: Session, kt: KeitaroClient, kt_stream_id: int, offer_id: int) -> Stream:
    stream = _get_stream(db, kt_stream_id)
    if not stream.is_offer_stream:
        raise Conflict(f"Поток {kt_stream_id} без офферов — добавлять офферы туда нельзя")
    offer = kt.offer(offer_id)
    if offer is None:
        raise NotFound(f"Оффер {offer_id} не найден в Keitaro")
    cache_offer(db, offer)

    b = next((x for x in stream.bindings if x.kt_offer_id == offer_id), None)
    if b is not None and b.state == ACTIVE:
        raise Conflict(f"Оффер {offer_id} уже в потоке")
    if b is None:
        b = OfferBinding(
            stream=stream,
            kt_offer_id=offer_id,
            added_unpushed=True,
            position=(max((x.position for x in stream.bindings), default=-1) + 1),
        )
        db.add(b)
    b.state = ACTIVE
    recalc_stream(db, stream)
    db.commit()
    return stream


def remove_binding(db: Session, binding_id: int) -> OfferBinding:
    b = _get_binding(db, binding_id)
    b.state = REMOVED
    recalc_stream(db, b.stream)
    db.commit()
    return b


def bring_back_binding(db: Session, binding_id: int) -> OfferBinding:
    b = _get_binding(db, binding_id)
    b.state = ACTIVE
    recalc_stream(db, b.stream)
    db.commit()
    return b


def set_pin(db: Session, binding_id: int, pinned: bool) -> OfferBinding:
    b = _get_binding(db, binding_id)
    b.pinned = bool(pinned)
    db.commit()
    return b


def cancel_stream(db: Session, kt_stream_id: int) -> Stream:
    """CANCEL: рабочая копия откатывается к снапшоту published.

    - привязки added_unpushed (добавлены локально, не пушены) удаляются физически;
    - офферы из снапшота восстанавливаются с весами из снапшота;
    - остальные остаются removed (их удаление уже пушено).
    """
    stream = _get_stream(db, kt_stream_id)
    published = {int(x["offer_id"]): int(x["share"])
                 for x in (stream.published_offers or [])}
    for b in list(stream.bindings):
        if b.added_unpushed:
            db.delete(b)
            stream.bindings.remove(b)
        elif b.kt_offer_id in published:
            b.state = ACTIVE
            b.share = published[b.kt_offer_id]
            b.added_unpushed = False
        else:
            b.state = REMOVED
            b.share = 0
    stream.dirty = False
    stream.warning = None
    db.commit()
    return stream
