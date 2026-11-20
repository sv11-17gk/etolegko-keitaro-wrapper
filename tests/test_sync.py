# -*- coding: utf-8 -*-
"""FETCH STREAMS FROM KT: KT — истина, пропавшие офферы — removed, не удаление."""
import mock_keitaro.main as mock_main
from app.services.sync import fetch_campaign
from app.services.weights import ACTIVE, REMOVED


def _bindings(stream):
    return {b.kt_offer_id: b for b in stream.bindings}


def test_fetch_builds_streams(db, kt, campaign):
    flow1 = next(s for s in campaign.streams if s.kt_stream_id == 564220)
    flow2 = next(s for s in campaign.streams if s.kt_stream_id == 564221)
    # поток без офферов: фиксируем как поток, содержимое не парсим
    assert flow1.is_offer_stream is False
    assert flow1.bindings == []
    assert flow1.kt_meta["filters"][0]["payload"] == ["AU"]
    assert flow2.is_offer_stream is True
    assert flow2.published_offers == [
        {"offer_id": 3749, "share": 33},
        {"offer_id": 3717, "share": 33},
        {"offer_id": 11111, "share": 34},
    ]
    assert flow2.dirty is False
    assert campaign.created_via_wrapper is False


def test_fetch_marks_kt_deleted_offers_as_removed(db, kt, campaign):
    stream = next(s for s in campaign.streams if s.kt_stream_id == 564221)
    mock_main.STREAMS[564221]["offers"] = [
        {"offer_id": 3749, "share": 33, "state": "active"}]
    fetch_campaign(db, kt, 93212)

    bindings = _bindings(stream)
    assert bindings[3749].state == ACTIVE
    assert bindings[3717].state == REMOVED  # серый, не удалён
    assert bindings[11111].state == REMOVED
    assert stream.published_offers == [{"offer_id": 3749, "share": 33}]
    assert not stream.dirty


def test_fetch_restores_offer_returned_to_kt(db, kt, campaign):
    stream = next(s for s in campaign.streams if s.kt_stream_id == 564221)
    mock_main.STREAMS[564221]["offers"] = [
        {"offer_id": 3749, "share": 33, "state": "active"}]
    fetch_campaign(db, kt, 93212)
    mock_main.STREAMS[564221]["offers"] = [
        {"offer_id": 3749, "share": 50, "state": "active"},
        {"offer_id": 11111, "share": 50, "state": "active"},
    ]
    fetch_campaign(db, kt, 93212)
    bindings = _bindings(stream)
    assert bindings[11111].state == ACTIVE
    assert bindings[11111].share == 50


def test_fetch_erases_local_unpushed_additions(db, kt, stream):
    from app.services import mutate
    mutate.add_offer(db, kt, 564221, 11112)
    assert _bindings(stream)[11112].added_unpushed
    fetch_campaign(db, kt, 93212)
    # непушенного добавления больше нет: истина — KT
    assert 11112 not in _bindings(stream)
    assert not stream.dirty
