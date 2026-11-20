# -*- coding: utf-8 -*-
"""Создаватор кампаний: кампания + Flow 1 (гео -> Google) + Flow 2 (оффер)."""
import mock_keitaro.main as mock_main
from app.services.creator import create_campaign


def test_create_campaign_full(db, kt):
    result = create_campaign(db, kt, name="test_karin_campaign1", geos=["mx", "au"],
                             offer_id=11111)

    # кампания в mock KT: ротация по позиции, домен/группа/источник подставлены
    camp = mock_main.CAMPAIGNS[result["kt_campaign_id"]]
    assert camp["name"] == "test_karin_campaign1"
    assert camp["type"] == "position"
    assert camp["domain_id"] == 1 and camp["group_id"] == 1 and camp["traffic_source_id"] == 1
    assert len(camp["alias"]) == 6

    streams = [s for s in mock_main.STREAMS.values()
               if s["campaign_id"] == result["kt_campaign_id"]]
    flow1 = next(s for s in streams if s["name"] == "Flow 1")
    flow2 = next(s for s in streams if s["name"] == "Flow 2")

    assert flow1["filters"] == [{"name": "country", "mode": "accept",
                                 "payload": ["MX", "AU"]}]
    assert flow1["schema"] == "redirect"
    assert flow1["action_type"] == "http"
    assert flow1["action_payload"] == "https://google.com"
    assert flow1["position"] == 1
    assert flow2["offers"] == [{"offer_id": 11111, "share": 100, "state": "active"}]
    assert flow2["type"] == "default"
    assert flow2["schema"] == "landings"
    assert flow2["action_type"] == "http"
    assert flow2["position"] == 2

    # состояние в локальной БД обёртки сразу согласовано с KT
    assert result["alias"] == camp["alias"]


def test_create_campaign_registers_in_wrapper_db(db, kt):
    from app.models import Campaign
    result = create_campaign(db, kt, name="test_karin_campaign2", geos=["RO"],
                             offer_id=11112)
    camp = db.get(Campaign, result["kt_campaign_id"])
    assert camp is not None
    assert camp.created_via_wrapper is True
    assert camp.fetched_at is not None
    flow2 = next(s for s in camp.streams if s.name == "Flow 2")
    assert flow2.is_offer_stream
    assert flow2.published_offers == [{"offer_id": 11112, "share": 100}]
    assert not flow2.dirty


def test_create_campaign_validations(db, kt):
    import pytest
    from app.errors import AppError, NotFound
    with pytest.raises(AppError):
        create_campaign(db, kt, name="x", geos=[], offer_id=11111)
    with pytest.raises(AppError):
        create_campaign(db, kt, name="x", geos=["  "], offer_id=11111)
    with pytest.raises(NotFound):
        create_campaign(db, kt, name="x", geos=["AU"], offer_id=999999)


def test_new_demo_campaign_does_not_inherit_archive_after_mock_reset(db, kt):
    from app.services import mutate
    first = create_campaign(db, kt, name="test_karin_before_restart", geos=["AU"],
                            offer_id=3749)
    from app.models import Campaign
    old = db.get(Campaign, first["kt_campaign_id"])
    old_stream = next(s for s in old.streams if s.is_offer_stream)
    mutate.add_offer(db, kt, old_stream.kt_stream_id, 11112)
    mock_main.reset_state()
    second = create_campaign(db, kt, name="test_karin_after_restart", geos=["MX"],
                             offer_id=11111)
    assert second["kt_campaign_id"] != first["kt_campaign_id"]
    new = db.get(Campaign, second["kt_campaign_id"])
    bindings = [b for s in new.streams for b in s.bindings]
    assert [(b.kt_offer_id, b.share) for b in bindings] == [(11111, 100)]
