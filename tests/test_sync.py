# -*- coding: utf-8 -*-
"""FETCH STREAMS FROM KT: KT — истина, пропавшие офферы — removed, не удаление."""
import mock_keitaro.main as mock_main
from app.services.sync import fetch_campaign
from app.services.weights import ACTIVE, REMOVED


def test_campaign_list_excludes_stale_local_cache_without_deleting_it(db, kt):
    from app.models import Campaign
    from app.services.sync import sync_campaigns_list

    stale = Campaign(kt_campaign_id=999999, name="removed in Keitaro", alias="old")
    db.add(stale)
    db.commit()
    assert [c.kt_campaign_id for c in sync_campaigns_list(db, kt)] == [93212]
    assert db.get(Campaign, 999999) is stale


def _bindings(stream):
    return {b.kt_offer_id: b for b in stream.bindings}


def test_fetch_builds_streams(db, kt, campaign):
    flow1 = next(s for s in campaign.streams if s.kt_stream_id == 564220)
    flow2 = next(s for s in campaign.streams if s.kt_stream_id == 564221)
    # поток без офферов: фиксируем как поток, содержимое не парсим
    assert flow1.is_offer_stream is False
    assert flow1.bindings == []
    assert flow1.kt_meta["filters"] == []
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


def test_fetch_empty_offer_stream_preserves_archive_and_bring_back(db, kt, stream):
    from app.services import mutate
    from app.services.push import push_stream

    mutate.add_offer(db, kt, 564221, 11112)
    mock_main.STREAMS[564221]["offers"] = []
    fetch_campaign(db, kt, 93212)

    assert stream.is_offer_stream
    assert stream.published_offers == []
    assert 11112 not in _bindings(stream)
    assert all(b.state == REMOVED and b.share == 0 for b in stream.bindings)
    assert not stream.dirty

    mutate.bring_back_binding(db, _bindings(stream)[3749].id)
    assert _bindings(stream)[3749].share == 100
    push_stream(db, kt, 564221)
    assert mock_main.STREAMS[564221]["offers"] == [
        {"offer_id": 3749, "share": 100, "state": "active"}]


def test_non_offer_stream_does_not_parse_its_filters(db, kt):
    from app.api.routes import stream_dto

    mock_main.STREAMS[564220]["filters"] = [
        {"name": "ignored_filter", "payload": {"opaque": 42}}]
    campaign = fetch_campaign(db, kt, 93212)
    flow = next(s for s in campaign.streams if s.kt_stream_id == 564220)
    dto = stream_dto(db, flow)
    assert not dto["is_offer_stream"]
    assert dto["filter_summary"] is None
    assert dto["offers"] == []
