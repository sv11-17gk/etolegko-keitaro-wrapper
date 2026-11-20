# -*- coding: utf-8 -*-
"""Pydantic-схемы входных тел API."""
from pydantic import BaseModel, Field


class CampaignCreateIn(BaseModel):
    name: str = Field(min_length=1)
    geos: list[str] = Field(min_length=1)
    offer_id: int
    domain_id: int | None = None
    group_id: int | None = None
    source_id: int | None = None


class OfferAddIn(BaseModel):
    offer_id: int


class PinIn(BaseModel):
    pinned: bool
