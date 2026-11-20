# -*- coding: utf-8 -*-
"""Сквозной сценарий из видео Миши: add -> push -> удаление в KT -> fetch -> removed ->
bring back -> pin -> пересчёт."""
import mock_keitaro.main as mock_main
from app.services import mutate
from app.services.push import push_stream
from app.services.sync import fetch_campaign
from app.services.weights import REMOVED


def _b(stream, offer_id):
    return next(x for x in stream.bindings if x.kt_offer_id == offer_id)


def _shares(stream):
    return {b.kt_offer_id: b.share for b in stream.bindings}


def _kt(stream_id=564221):
    return {o["offer_id"]: o["share"] for o in mock_main.STREAMS[stream_id]["offers"]}


def test_full_video_scenario(db, kt, stream):
    # 1. добавили 4-й оффер -> жёлтый, по 25%, в KT по-прежнему 3 оффера
    mutate.add_offer(db, kt, 564221, 11112)
    assert stream.dirty
    assert _shares(stream) == {3749: 25, 3717: 25, 11111: 25, 11112: 25}
    assert len(_kt()) == 3

    # 2. CANCEL -> привязка непушенного добавления удалена, поток белый
    mutate.cancel_stream(db, 564221)
    assert not stream.dirty
    assert _shares(stream) == {3749: 33, 3717: 33, 11111: 34}
    assert len(stream.bindings) == 3

    # 3. добавили снова и запушили -> в KT 4 оффера
    mutate.add_offer(db, kt, 564221, 11112)
    push_stream(db, kt, 564221)
    assert not stream.dirty
    assert len(_kt()) == 4 and all(v == 25 for v in _kt().values())

    # 4. удалили оффер прямо в KT -> FETCH -> у нас он removed (серый), не удалён
    mock_main.STREAMS[564221]["offers"] = [
        o for o in mock_main.STREAMS[564221]["offers"] if o["offer_id"] != 11112]
    fetch_campaign(db, kt, 93212)
    assert _b(stream, 11112).state == REMOVED
    assert _b(stream, 11112).share == 0
    assert not stream.dirty
    assert len(_kt()) == 3

    # 5. BRING BACK -> жёлтый -> PUSH -> оффер вернулся в KT
    mutate.bring_back_binding(db, _b(stream, 11112).id)
    assert stream.dirty
    push_stream(db, kt, 564221)
    assert 11112 in _kt()

    # 6. пин 25% -> удаление ещё одного оффера -> пин на месте, остальные делят остаток
    pinned = _b(stream, 3749)
    mutate.set_pin(db, pinned.id, True)
    assert pinned.share == 25
    assert not stream.dirty  # сам пин ничего не меняет
    mutate.remove_binding(db, _b(stream, 3717).id)
    assert _shares(stream) == {3749: 25, 3717: 0, 11111: 37, 11112: 38}
    push_stream(db, kt, 564221)
    assert _kt() == {3749: 25, 11111: 37, 11112: 38}
