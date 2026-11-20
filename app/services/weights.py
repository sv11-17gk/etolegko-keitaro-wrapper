# -*- coding: utf-8 -*-
"""Пересчёт весов (shares) — главный инвариант обёртки: сумма активных весов = 100.

Правила (из видео и скриншотов их обёртки):
- активные непиннутые офферы делят остаток (100 - сумма пинов) поровну,
  целочисленно, остаток от деления получает первый непиннутый оффер;
- пиннутые офферы сохраняют свой вес при любых операциях;
- удалённые (removed) офферы имеют share 0 и в распределении не участвуют.
"""
from sqlalchemy.orm import Session

from app.models import Stream

ACTIVE = "active"
REMOVED = "removed"

# В видео ETOLEGKO на 5:46 остаток достаётся первому непиннутому офферу:
# при закреплённых 25% остальные получают 38% и 37%.
REMAINDER_TO_LAST = False


def _working_state(stream: Stream) -> list[dict]:
    return sorted(
        ({"offer_id": b.kt_offer_id, "share": b.share}
         for b in stream.bindings if b.state == ACTIVE),
        key=lambda x: x["offer_id"],
    )


def update_dirty(stream: Stream) -> None:
    """dirty = рабочая копия != снапшот published (жёлтый поток)."""
    published = sorted(stream.published_offers or [], key=lambda x: x["offer_id"])
    stream.dirty = _working_state(stream) != published


def recalc_stream(db: Session, stream: Stream) -> None:
    active = [b for b in stream.bindings if b.state == ACTIVE]
    unpinned = [b for b in active if not b.pinned]
    pinned_sum = sum(b.share for b in active if b.pinned)

    for b in stream.bindings:
        if b.state == REMOVED:
            b.share = 0

    if not active:
        stream.warning = "Нет активных офферов — добавьте оффер или нажмите BRING BACK"
        update_dirty(stream)
        return

    if not unpinned:
        stream.warning = None if pinned_sum == 100 else (
            f"Все активные офферы запинены, сумма весов {pinned_sum}% != 100%")
        update_dirty(stream)
        return

    rest = 100 - pinned_sum
    if rest < 0:
        stream.warning = (f"Сумма пинов {pinned_sum}% > 100%, "
                          f"веса {len(unpinned)} непиннутых офферов обнулены")
        for b in unpinned:
            b.share = 0
        update_dirty(stream)
        return

    stream.warning = None
    ordered = sorted(unpinned, key=lambda b: b.position)
    base, remainder = divmod(rest, len(ordered))
    for i, b in enumerate(ordered):
        share = base
        if REMAINDER_TO_LAST and i == len(ordered) - 1:
            share += remainder
        if not REMAINDER_TO_LAST and i == 0:
            share += remainder
        b.share = share
    update_dirty(stream)
