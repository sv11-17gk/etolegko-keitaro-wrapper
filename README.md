# Keitaro Wrapper (Adrobot T3)

Обёртка над рекламным трекером [Keitaro](https://keitaro.io): локальная копия кампаний, потоков и офферов с весами, в которой изменения готовятся локально (жёлтый поток), а в Keitaro публикуются по кнопке **PUSH TO KT**.

Реализованы обе части тестового задания:

1. **Создаватор кампаний** — Name + Geo (коды через запятую) + Offer (автокомплит) → в Keitaro создаётся кампания с доменом/группой/источником и двумя потоками: Flow 1 ловит указанные страны и редиректит на Google, Flow 2 отдаёт трафик выбранному офферу.
2. **Редактор офферов** — воспроизводит логику их обёртки из видео: FETCH STREAMS FROM KT, добавление/удаление офферов с пересчётом весов (сумма всегда 100), пины весов, removed-архив с BRING BACK, синхронизация после удаления офферов прямо в Keitaro, PUSH TO KT и CANCEL.

Стек: **FastAPI + SQLAlchemy 2 + Alembic + httpx**, фронт — статика (vanilla JS) без сборки. 24 теста pytest закрывают инварианты весов и сценарии из видео против mock-Keitaro.

## Быстрый старт

### Вариант 1 — Docker (демо без реального Keitaro)

```bash
docker compose up --build
```

Поднимаются два сервиса:

- **обёртка**: http://localhost:8000 (редактор) и http://localhost:8000/create.html (создаватор);
- **mock-Keitaro**: http://localhost:8081 — фейковый Admin API с фикстурой тестовой кампании `campaign 2` (2 потока, 3 оффера с весами 33/33/34), как на скриншотах ТЗ. В демо режиме состояния mock-Keitaro живут в памяти процесса.

### Вариант 2 — локально с реальным Keitaro

```bash
git clone <repo>
cd keitaro-wrapper
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполните KT_BASE_URL и KT_API_KEY (Профиль -> API ключи -> Создать новый ключ в админке Keitaro)
alembic upgrade head          # миграции (см. ниже)
uvicorn app.main:app --reload
```

Открыть http://localhost:8000.

## Миграции

Схема БД обёртки — [alembic/versions/0001_initial.py](alembic/versions/0001_initial.py): таблицы `kt_offer_cache` (кэш имён офферов), `campaigns`, `streams` (снапшот `published_offers`), `offer_bindings` (рабочая копия привязок).

```bash
alembic upgrade head                    # накатить все миграции
alembic downgrade -1                    # откатить последнюю
alembic revision -m "описание"          # создать новую миграцию
```

Подключение к БД задаётся переменной `DATABASE_URL` (SQLite по умолчанию; под PostgreSQL достаточно сменить URL — вся схема совместима). При старте приложения `uvicorn app.main:app` миграции накатываются автоматически, поэтому ручной шаг не обязателен — он оставлен для прод-практики и CI.

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `KT_BASE_URL` | `http://localhost:8081` | Корень домена Keitaro (без `/admin_api/v1`) |
| `KT_API_KEY` | — | API ключ из админки Keitaro |
| `KT_ADMIN_URL` | origin из `KT_BASE_URL` | База админки для кнопки VIEW IN KT |
| `DATABASE_URL` | `sqlite:///./wrapper.db` | Подключение к БД обёртки |
| `KT_REDIRECT_SCHEMA` / `KT_REDIRECT_ACTION` | `action` / `redirectToUrl` | Схема/действие Flow 1 (редирект на Google) |
| `KT_OFFERS_SCHEMA` / `KT_OFFERS_ACTION` | `offers` / `showOffers` | Схема/действие Flow 2 (ротатор офферов) |
| `FLOW1_URL` | `https://google.com` | Куда редиректит Flow 1 |
| `ALIAS_LENGTH` | `6` | Длина alias кампании (как `wVqN1R` в примере ТЗ) |

## Тесты

```bash
pip install -r requirements-dev.txt
pytest tests/ -q
```

24 теста против mock-Keitaro (in-memory, без сети) покрывают:

- инвариант весов: 3 оффера → 33/33/34 (остаток последнему), 4 → по 25; сумма всегда 100;
- пины: вес закреплён при удалении/возврате, пин сам по себе не желтит поток;
- remove → серый/0%/исключён из распределения; BRING BACK → возврат;
- CANCEL: непушенные добавления удаляются физически, остальное откатывается к снапшоту;
- FETCH после удаления офферов в Keitaro → у нас removed, не удаление;
- PUSH: в payload только активные привязки, блок при сумме весов ≠ 100, после push истина — Keitaro;
- создаватор: кампания с фильтром `country/accept/[MX, AU]`, Flow 2 с share 100, автоподстановка домена/группы/источника;
- полный сценарий из видео: add → yellow → push → удаление в KT → fetch → removed → bring back → pin.

## Как работает модель синхронизации (коротко)

- У потока есть **снапшот `published_offers`** — что реально лежит в Keitaro после последнего fetch/push. Рабочая копия — таблица `offer_bindings`.
- **Жёлтый поток** (`dirty`) = рабочая копия ≠ снапшот. Белый = совпадает.
- **ADD/REMOVE/BRING BACK/PIN** меняют только рабочую копию и пересчитывают веса (непиннутые делят `100 − сумма пинов` поровну, целочисленно, остаток — последнему по порядку).
- **PUSH** шлёт в `PUT /streams/{id}` только активные привязки `{offer_id, share, state:"active"}` и блокируется, если сумма ≠ 100. После push делается контрольный GET: Keitaro — истина.
- **CANCEL** удаляет физически привязки непушенных добавлений и восстанавливает снапшот.
- **FETCH** синхронизирует с KT: пропавшие в KT офферы становятся `removed` (серые, с BRING BACK), вернувшиеся — восстанавливаются; непушенные добавления стираются.
- Потоки без офферов (Flow 1, редирект) отображаются как потоки; их содержимое не парсится — как в оригинальной обёртке.

## Решения и допущения (важно)

1. **`schema`/`action_type` потоков.** В OpenAPI Keitaro для этих полей нет enum'ов. Значения (`action`/`redirectToUrl` для редиректа, `offers`/`showOffers` для ротатора) вынесены в переменные окружения и в тестах совпадают с mock. Перед сдачей на реальном инстансе стоит один раз снять в DevTools Network payload реального потока и при несовпадении поправить четыре переменные — код менять не нужно.
2. **Остаток целочисленного деления весов.** На скриншоте Keitaro (33/33/34) остаток достаётся последнему офферу; на скриншоте их обёртки после правок — первому. Реализован вариант Keitaro (константа `REMAINDER_TO_LAST` в `app/services/weights.py`, меняется одной строкой).
3. **PUT `offers` заменяет привязки целиком** (PUT в Keitaro частичный по остальным полям). Поэтому push шлёт полный набор активных офферов с весами.
4. **`report/build`** — формат `rows` в OpenAPI не зафиксирован; парсер защитный (dict-строки и list-строки с `meta`). Если реальный формат отличается, клики в шапке просто покажутся как «—», остальное не пострадает.
5. **`group_id`** в схеме запроса Keitaro описан как строка, в ответе — число; отправляется числом (проверить на живом инстансе при первом запуске).

## Структура

```
app/
  main.py            FastAPI + автоматический alembic upgrade на старте
  config.py          настройки (pydantic-settings, .env)
  db.py, models.py   SQLAlchemy 2: campaigns, streams, offer_bindings, kt_offer_cache
  kt_client.py       клиент Admin API: Api-Key, ретраи, нормализация ошибок
  schemas.py         Pydantic-схемы входа
  services/          weights (пересчёт), sync (fetch), mutate (add/remove/pin/cancel),
                     push, creator (создаватор кампаний)
  api/routes.py      REST /api/... + раздача ошибок Keitaro как 502 с телом ошибки
frontend/            index.html (редактор), create.html (создаватор), vanilla JS, без сборки
mock_keitaro/        фейковый Admin API для демо и тестов
alembic/             миграции
tests/               pytest + mock Keitaro через starlette TestClient
```

## Что бы я доделал дальше

- интеграционный прогон против живого Keitaro с реальными ответами (сейчас контракт закрыт mock-транспортом);
- optimistic locking на конкурентные fetch/push из двух вкладок;
- audit log изменений потоков и мягкое разрешение конфликтов снапшота;
- авторизация на самой обёртке, если доступ к ней будет у команды продаж.
