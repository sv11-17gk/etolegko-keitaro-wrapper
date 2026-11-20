# -*- coding: utf-8 -*-
"""Общие фикстуры: in-memory БД + mock Keitaro через starlette TestClient (без сети)."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

import mock_keitaro.main as mock_main
from mock_keitaro.main import app as mock_app
from app.db import Base
from app.kt_client import KeitaroClient
from app.models import Stream
from app.services.sync import fetch_campaign


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def kt():
    mock_main.reset_state()
    test_client = TestClient(mock_app, base_url="http://mock-keitaro.local/admin_api/v1/")
    client = KeitaroClient("http://mock-keitaro.local", "mock-key", client=test_client)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture()
def campaign(db, kt):
    """Кампания 93212 после fetch: два потока, Flow 2 с 33/33/34."""
    return fetch_campaign(db, kt, 93212)


@pytest.fixture()
def stream(db, campaign):
    return db.scalars(select(Stream).where(Stream.kt_stream_id == 564221)).first()
