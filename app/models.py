# -*- coding: utf-8 -*-
"""Модели SQLAlchemy: локальная копия состояния Keitaro.

Ключевая идея: у каждого потока есть снапшот `published_offers` — то, что реально
лежит в Keitaro на момент последнего sync/push. Рабочая копия — таблица
offer_binding. dirty = рабочая копия != снапшот (жёлтый поток).
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OfferCache(Base):
    """Кэш имён офферов: внутри Stream.offers Keitaro отдаёт только offer_id."""
    __tablename__ = "kt_offer_cache"

    kt_offer_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    affiliate_network_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Campaign(Base):
    """Кампании, видимые обёрткой; created_via_wrapper помечает созданные создаватором."""
    __tablename__ = "campaigns"

    kt_campaign_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    alias: Mapped[str] = mapped_column(String, default="")
    created_via_wrapper: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    streams: Mapped[list["Stream"]] = relationship(back_populates="campaign",
                                                   cascade="all, delete-orphan")


class Stream(Base):
    """Поток кампании. Для не-офферных потоков (Flow 1, редирект на Google) содержимое
    не редактируем; по уточнению v2 фильтры доступны в шапке."""
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kt_stream_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    kt_campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.kt_campaign_id"), index=True)
    name: Mapped[str] = mapped_column(String, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_offer_stream: Mapped[bool] = mapped_column(Boolean, default=False)
    dirty: Mapped[bool] = mapped_column(Boolean, default=False)
    warning: Mapped[str | None] = mapped_column(String, nullable=True)
    # [{offer_id: int, share: int}] — снапшот последнего состояния, согласованного с KT
    published_offers: Mapped[list] = mapped_column(JSON, default=list)
    # имя/тип/фильтры потока для шапки в UI
    kt_meta: Mapped[dict] = mapped_column(JSON, default=dict)

    campaign: Mapped[Campaign] = relationship(back_populates="streams")
    bindings: Mapped[list["OfferBinding"]] = relationship(back_populates="stream",
                                                         cascade="all, delete-orphan")


class OfferBinding(Base):
    """Рабочая копия привязки «оффер -> поток».

    state: active | removed (removed = серый, share 0, с кнопкой BRING BACK).
    pinned: вес закреплён и не участвует в пересчёте.
    added_unpushed: привязка добавлена локально и ещё не пушена (CANCEL удаляет её
    физически — так ведёт себя их обёртка по видео).
    """
    __tablename__ = "offer_bindings"
    __table_args__ = (UniqueConstraint("stream_id", "kt_offer_id", name="uq_stream_offer"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"), index=True)
    kt_offer_id: Mapped[int] = mapped_column(Integer, index=True)
    share: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String, default="active")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    added_unpushed: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)

    stream: Mapped[Stream] = relationship(back_populates="bindings")
