# -*- coding: utf-8 -*-
"""PUSH TO KT: payload только из активных, блок при сумме != 100, KT — истина после push."""
from copy import deepcopy

import pytest

import mock_keitaro.main as mock_main
from app.errors import Conflict
from app.services import mutate
from app.services.push import push_stream


def _kt_offers(stream_id=564221):
    return {o["offer_id"]: o["share"] for o in mock_main.STREAMS[stream_id]["offers"]}


def test_push_sends_only_active_bindings(db, kt, stream):
    mutate.add_offer(db, kt, 564221, 11112)
    victim = next(b for b in stream.bindings if b.kt_offer_id == 3717)
    mutate.remove_binding(db, victim.id)

    push_stream(db, kt, 564221)

    # В KT три активных оффера, остаток у первого: 34/33/33.
    kt_offers = _kt_offers()
    assert set(kt_offers) == {3749, 11111, 11112}
    assert sum(kt_offers.values()) == 100
    assert not stream.dirty
    assert stream.published_offers == [
        {"offer_id": offer_id, "share": share} for offer_id, share in kt_offers.items()
    ]


def test_push_blocked_when_shares_do_not_sum_to_100(db, kt, stream):
    for b in stream.bindings:
        b.pinned = True
        b.share = 80 if b.kt_offer_id == 3749 else b.share
    from app.services.weights import recalc_stream
    recalc_stream(db, stream)
    total = sum(b.share for b in stream.bindings if b.state == "active")
    assert total != 100
    with pytest.raises(Conflict):
        push_stream(db, kt, 564221)
    # KT не изменился
    assert len(mock_main.STREAMS[564221]["offers"]) == 3


def test_push_snapshot_matches_kt(db, kt, stream):
    mutate.add_offer(db, kt, 564221, 11112)
    push_stream(db, kt, 564221)
    # истина теперь KT: снапшот = то, что вернул GET /streams/{id}
    kt_offers = _kt_offers()
    assert stream.published_offers == [
        {"offer_id": oid, "share": share} for oid, share in kt_offers.items()
    ]
    for b in stream.bindings:
        assert b.added_unpushed is False
        assert b.share == kt_offers[b.kt_offer_id]


def test_push_preserves_redirect_flow_and_offer_flow_settings(db, kt, stream):
    redirect = deepcopy(kt.stream(564220))
    before = kt.stream(564221)
    mutate.add_offer(db, kt, 564221, 11112)
    push_stream(db, kt, 564221)
    assert kt.stream(564220) == redirect
    after = kt.stream(564221)
    assert after.pop("offers") != before.pop("offers")
    assert before.pop("action_payload") is None
    assert after.pop("action_payload") == ""
    assert after == before
