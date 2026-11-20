# -*- coding: utf-8 -*-
"""Инвариант весов: сумма активных = 100, пины сохраняются, removed не участвуют."""
from app.services.weights import recalc_stream


def _shares(stream):
    return {b.kt_offer_id: b.share for b in stream.bindings}


def test_recalc_three_offers_remainder_to_last(db, stream):
    for b in stream.bindings:
        b.pinned = False
    recalc_stream(db, stream)
    assert _shares(stream) == {3749: 33, 3717: 33, 11111: 34}
    assert sum(_shares(stream).values()) == 100


def test_add_fourth_offer_gives_25_each(db, kt, stream):
    from app.services import mutate
    mutate.add_offer(db, kt, 564221, 11112)
    assert _shares(stream) == {3749: 25, 3717: 25, 11111: 25, 11112: 25}
    assert sum(_shares(stream).values()) == 100
    assert stream.dirty


def test_pinned_weight_survives_removal_and_bring_back(db, kt, stream):
    """Сценарий из видео: пин 25% -> удаление -> возврат оффера; пин неизменен."""
    from app.services import mutate
    mutate.add_offer(db, kt, 564221, 11112)  # 4 оффера по 25

    pinned = next(b for b in stream.bindings if b.kt_offer_id == 3749)
    mutate.set_pin(db, pinned.id, True)

    removed = next(b for b in stream.bindings if b.kt_offer_id == 3717)
    mutate.remove_binding(db, removed.id)
    assert _shares(stream) == {3749: 25, 3717: 0, 11111: 37, 11112: 38}
    assert pinned.share == 25  # пин не тронут

    mutate.bring_back_binding(db, removed.id)
    assert _shares(stream) == {3749: 25, 3717: 25, 11111: 25, 11112: 25}
    assert sum(_shares(stream).values()) == 100


def test_removed_excluded_from_distribution(db, stream):
    """Remove -> перераспределение: двое непиннутых делят 100 пополам (скриншот 5)."""
    from app.services import mutate
    victim = next(b for b in stream.bindings if b.kt_offer_id == 11111)
    mutate.remove_binding(db, victim.id)
    assert _shares(stream) == {3749: 50, 3717: 50, 11111: 0}
    assert sum(_shares(stream).values()) == 100


def test_all_pinned_with_wrong_sum_warns(db, stream):
    for b in stream.bindings:
        b.pinned = True
    shares = {3749: 40, 3717: 40, 11111: 40}
    for b in stream.bindings:
        b.share = shares[b.kt_offer_id]
    recalc_stream(db, stream)
    assert sum(_shares(stream).values()) == 120
    assert stream.warning and "120%" in stream.warning


def test_pin_alone_does_not_make_stream_dirty(db, stream):
    from app.services import mutate
    pinned = next(b for b in stream.bindings if b.kt_offer_id == 3749)
    mutate.set_pin(db, pinned.id, True)
    assert not stream.dirty
