# -*- coding: utf-8 -*-
"""Создаватор кампаний (часть 1 ТЗ).

Вход: имя кампании, гео-коды (список, в UI через запятую), ID оффера.
Результат в Keitaro:
- кампания: type="position" (ротация «По позиции»), домен, группа, источник
  (заданы явно или автоподстановка первых активных из API);
- Flow 1: ловит указанные страны (фильтр country/accept) -> редирект на Google;
- Flow 2: офферный поток (catch-all) с выбранным оффером, share 100.
"""
import random
import string

from sqlalchemy.orm import Session

from app.config import settings
from app.errors import AppError, NotFound
from app.kt_client import KeitaroClient
from app.services.sync import cache_offer, fetch_campaign

_ALPHABET = string.ascii_letters + string.digits


def _generate_alias(length: int) -> str:
    return "".join(random.SystemRandom().choice(_ALPHABET) for _ in range(length))


def _pick(items: list[dict], what: str) -> dict:
    for item in items:
        if item.get("state", "active") == "active":
            return item
    if items:
        return items[0]
    raise AppError(f"В Keitaro нет ни одного {what} — создайте в админке или выберите вручную")


def _by_id(items: list[dict], item_id: int | None, what: str) -> dict:
    if item_id is None:
        return _pick(items, what)
    for item in items:
        if item.get("id") == item_id:
            return item
    raise NotFound(f"{what} с id={item_id} не найдено в Keitaro")


def create_campaign(db: Session, kt: KeitaroClient, *, name: str, geos: list[str],
                    offer_id: int, domain_id: int | None = None,
                    group_id: int | None = None, source_id: int | None = None) -> dict:
    if not (name or "").strip():
        raise AppError("Название кампании не может быть пустым")
    geo_codes = [g.strip().upper() for g in geos or [] if g.strip()]
    if not geo_codes:
        raise AppError("Укажите хотя бы один гео-код (например MX, AU, RO)")

    offer = kt.offer(offer_id)
    if offer is None:
        raise NotFound(f"Оффер {offer_id} не найден в Keitaro")
    cache_offer(db, offer)

    domain = _by_id(kt.domains(), domain_id, "Домен")
    group = _by_id(kt.groups(), group_id, "Группа")
    source = _by_id(kt.traffic_sources(), source_id, "Источник")

    payload = {
        "name": name.strip(),
        "type": "position",
        "domain_id": domain["id"],
        "group_id": group["id"],
        "traffic_source_id": source["id"],
    }
    # alias в Keitaro уникален; при коллизии генерируем заново
    for _ in range(3):
        payload["alias"] = _generate_alias(settings.alias_length)
        try:
            created = kt.create_campaign(payload)
            break
        except Exception as exc:
            from app.kt_client import KtError
            body = getattr(exc, "body", "") or str(exc)
            if isinstance(exc, KtError) and exc.status in (400, 409) and \
                    "alias" in body.lower():
                continue
            raise
    else:
        raise AppError("Не удалось подобрать уникальный alias кампании")

    campaign_id = int(created["id"])

    flow1 = {
        "campaign_id": campaign_id,
        "schema": settings.kt_redirect_schema,
        "type": "regular",
        "name": "Flow 1",
        "action_type": settings.kt_redirect_action,
        "action_payload": settings.flow1_url,
        "filters": [{"name": "country", "mode": "accept", "payload": geo_codes}],
        "position": 1,
    }
    flow2 = {
        "campaign_id": campaign_id,
        "schema": settings.kt_offers_schema,
        "type": "default",
        "name": "Flow 2",
        "action_type": settings.kt_offers_action,
        "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
        "position": 2,
    }
    kt.create_stream(flow1)
    kt.create_stream(flow2)

    camp = fetch_campaign(db, kt, campaign_id)
    camp.created_via_wrapper = True
    db.commit()
    return {"kt_campaign_id": campaign_id, "alias": camp.alias, "name": camp.name,
            "domain": domain.get("name"), "group": group.get("name"),
            "source": source.get("name"), "geos": geo_codes}
