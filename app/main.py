# -*- coding: utf-8 -*-
"""Точка входа: FastAPI + API-роуты + статика фронтенда.

При старте накатывает миграции alembic (alembic upgrade head), поэтому сервис
поднимается одной командой; README описывает ручной вариант для прод-привычки.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import install_error_handlers, router
from app.config import settings

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger(__name__)


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")
    log.info("Миграции применены")


@asynccontextmanager
async def lifespan(_: FastAPI):
    run_migrations()
    yield


app = FastAPI(title="Keitaro Wrapper (Adrobot T3)", lifespan=lifespan)
app.include_router(router)
install_error_handlers(app)


@app.get("/", include_in_schema=False)
def editor():
    """Сразу открывает рабочий редактор кампаний."""
    return FileResponse(ROOT / "frontend" / "index.html")


app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
