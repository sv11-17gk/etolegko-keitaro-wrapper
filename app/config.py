# -*- coding: utf-8 -*-
"""Конфигурация обёртки. Все значения переопределяются переменными окружения / .env."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # База Keitaro (корень домена трекера, без /admin_api/v1 — клиент добавит сам) и ключ API.
    # Ключ берётся в админке Keitaro: Профиль -> API ключи -> Создать новый ключ.
    kt_base_url: str = "http://localhost:8081"
    kt_api_key: str = ""

    # URL админки для кнопки VIEW IN KT (если пусто — берём origin из kt_base_url).
    kt_admin_url: str = ""

    database_url: str = "sqlite:///./wrapper.db"

    # Схемы и действия потоков. В OpenAPI Keitaro для них нет enum'ов, поэтому значения
    # вынесены в настройки: их нужно сверить с живым инстансом (README, раздел «Допущения»).
    kt_redirect_schema: str = "action"      # Flow 1: редирект на Google
    kt_redirect_action: str = "redirectToUrl"
    kt_offers_schema: str = "offers"        # Flow 2: ротатор офферов
    kt_offers_action: str = "showOffers"

    # URL Google для Flow 1 и длина алиаса кампании (как wVqN1R в их примере).
    flow1_url: str = "https://google.com"
    alias_length: int = 6

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
