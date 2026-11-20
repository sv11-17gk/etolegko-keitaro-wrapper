# -*- coding: utf-8 -*-
"""Мутации: add/remove/bring back/cancel — только локально, до PUSH."""
import pytest

import mock_keitaro.main as mock_main
from app.errors import Conflict, NotFound
from app.services import mutate


def _bindings(stream):
    return {b.kt_offer_id: b for b in stream.bindings}


def _shares(stream):
    return {b.kt_offer_id: b.share for b in stream.bindings}


def test_add_offer_makes_stream_dirty_locally(db, kt, stream):
    mutate.add_offer(db, kt, 564221, 11112)
    assert stream.dirty
    # Keitaro при этом не менялся: в KT по-прежнему 3 оффера
    assert len(mock_main.STREAMS[564221]["offers"]) == 3
    b = _bindings(stream)[11112]
    assert b.added_unpushed is True


def test_add_duplicate_conflict(db, kt, stream):
    with pytest.raises(Conflict):
        mutate.add_offer(db, kt, 564221, 3749)


def test_add_unknown_offer_not_found(db, kt, stream):
    with pytest.raises(NotFound):
        mutate.add_offer(db, kt, 564221, 999999)


def test_remove_then_cancel_restores_snapshot(db, kt, stream):
    mutate.add_offer(db, kt, 564221, 11112)
    mutate.cancel_stream(db, stream.kt_stream_id)
    # привязка непушенного добавления удалена физически (как в их обёртке)
    assert 11112 not in _bindings(stream)
    assert not stream.dirty
    assert _shares(stream) == {3749: 33, 3717: 33, 11111: 34}


def test_cancel_restores_locally_removed_offer(db, kt, stream):
    victim = _bindings(stream)[3749]
    mutate.remove_binding(db, victim.id)
    assert stream.dirty
    mutate.cancel_stream(db, stream.kt_stream_id)
    assert _shares(stream) == {3749: 33, 3717: 33, 11111: 34}
    assert not stream.dirty


def test_cancel_keeps_published_removals(db, kt, stream):
    """Оффер, удалённый и запушенный ранее, после CANCEL остаётся removed;
    непушенное добавление удаляется физически."""
    mutate.remove_binding(db, _bindings(stream)[3749].id)
    from app.services import push
    push.push_stream(db, kt, 564221)
    mutate.add_offer(db, kt, 564221, 11112)
    mutate.cancel_stream(db, stream.kt_stream_id)
    assert _bindings(stream)[3749].state == "removed"
    assert 11112 not in _bindings(stream)  # привязка удалена, а не removed
    assert not stream.dirty


def test_remove_makes_dirty_and_zero_share(db, stream):
    victim = _bindings(stream)[11111]
    mutate.remove_binding(db, victim.id)
    assert victim.state == "removed"
    assert victim.share == 0
    assert stream.dirty


@pytest.mark.parametrize("restore", ["bring_back", "add"])
def test_cancel_restored_archive_keeps_its_binding(db, kt, stream, restore):
    from app.services.push import push_stream

    victim = _bindings(stream)[3749]
    original_id = victim.id
    mutate.remove_binding(db, original_id)
    push_stream(db, kt, stream.kt_stream_id)
    if restore == "bring_back":
        mutate.bring_back_binding(db, original_id)
    else:
        mutate.add_offer(db, kt, stream.kt_stream_id, victim.kt_offer_id)
    assert stream.dirty
    mutate.cancel_stream(db, stream.kt_stream_id)
    assert _bindings(stream)[3749].id == original_id
    assert _bindings(stream)[3749].state == "removed"
    assert _bindings(stream)[3749].share == 0
    assert not stream.dirty
