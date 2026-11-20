# -*- coding: utf-8 -*-
"""PUSH TO KT: перенос рабочей копии потока в Keitaro.

- в PUT уходят только активные привязки {offer_id, share, state:"active"} —
  removed в payload не попадают (в KT они просто исчезают из потока);
- push блокируется, если сумма весов != 100: «цифры должны быть верные»;
- после PUT делаем контрольный GET потока и храним то, что вернул KT:
  Keitaro — истина (он мог нормализовать веса).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, NotFound
from app.kt_client import KeitaroClient
from app.models import Stream
from app.services.weights import ACTIVE, REMOVED


def push_stream(db: Session, kt: KeitaroClient, kt_stream_id: int) -> Stream:
    stream = db.scalars(
        select(Stream).where(Stream.kt_stream_id == kt_stream_id)
    ).first()
    if stream is None:
        raise NotFound(f"Поток {kt_stream_id} не найден локально")

    active = sorted((b for b in stream.bindings if b.state == ACTIVE),
                    key=lambda b: b.position)
    if not active and not stream.is_offer_stream:
        raise Conflict(f"Поток {kt_stream_id} — не офферный, пушить нечего")

    total = sum(b.share for b in active)
    if total != 100:
        raise Conflict(f"Сумма весов {total}% != 100% — push заблокирован")

    payload = [{"offer_id": b.kt_offer_id, "share": b.share, "state": "active"}
               for b in active]
    kt.update_stream(kt_stream_id, {"offers": payload})

    data = kt.stream(kt_stream_id)
    kt_map = {int(o["offer_id"]): int(o.get("share") or 0)
              for o in (data.get("offers") or [])}
    for b in stream.bindings:
        if b.kt_offer_id in kt_map:
            b.state = ACTIVE
            b.share = kt_map[b.kt_offer_id]
            b.added_unpushed = False
        else:
            b.state = REMOVED
            b.share = 0
            b.added_unpushed = False
    stream.published_offers = [{"offer_id": oid, "share": share}
                               for oid, share in kt_map.items()]
    stream.dirty = False
    stream.warning = None
    db.commit()
    return stream
