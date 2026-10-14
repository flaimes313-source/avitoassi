# Контекст проекта «Авито-Помощник»

> Файл-память для возобновления работы в новом чате.
> Обновляется после каждого завершённого блока.

---

## 1. О проекте

**Название**: Авито-Помощник
**Тип**: Telegram-бот для частных продавцов Avito
**Платформа**: BotHost (Pro-тариф), контейнерный деплой
**Стек**: Python 3.11, aiogram 3.15, FastAPI, PostgreSQL, GigaChat SDK, ЮKassa
**Репозиторий**: https://github.com/flaimes313-source/avitoassi.git
**Домен бота**: bot-1791821973-8551-ivan31313131311.bothost.tech

---

## 2. Что умеет бот (по ТЗ)

1. 📝 Создать объявление — по фото и тексту 3 варианта
2. 🛠 Улучшить объявление — разбор проблем
3. 🔍 Анализ конкурентов — сравнение и рекомендации
4. 📸 Помощь с фотографиями
5. 📈 Стратегия продвижения — пошаговый план
6. 💬 Ответы покупателям
7. 📂 Мои объявления — карточки, история, статистика
8. 💳 Тариф и подписка — Free / PRO
9. ⚙️ Настройки и помощь

---

## 3. Архитектура

### Инфраструктура
Telegram → BotHost (контейнер) → FastAPI (webhook) → aiogram Dispatcher
↓
PostgreSQL + GigaChat + ЮKassa
text


- **Порт**: 3000 (BotHost принудительно)
- **Запуск**: `python -m app.main` → `uvicorn.run(app, ...)` с объектом app
- **Webhook**: HTTPS через BotHost-домен, секрет в заголовке
- **FSM**: MemoryStorage (состояние в памяти процесса)

### Структура файлов

avito-assistant/
├── CONTEXT.md
├── bothost.json
├── requirements.txt
├── .env
├── migrations/
│ └── init.sql # 14 таблиц
└── app/
├── main.py # точка входа, uvicorn.run(app)
├── config.py # Pydantic Settings
├── database.py # пул psycopg + ленивая инициализация
├── middlewares/
│ ├── db.py # user + db в контекст
│ ├── subscription.py # автопонижение PRO
│ ├── task_context.py # заглушка
│ └── throttling.py # заглушка
├── handlers/
│ ├── start.py # /start, онбординг, меню — ГОТОВ
│ ├── create_listing.py # блок 3 — ГОТОВ
│ ├── improve_listing.py # блок 4 — заглушка (СЛЕДУЮЩИЙ)
│ ├── competitors.py # блок 5 — заглушка
│ ├── photos.py # блок 6 — заглушка
│ ├── strategy.py # блок 7 — заглушка
│ ├── buyer_replies.py # блок 8 — заглушка
│ ├── items_history.py # блок 9 — заглушка
│ ├── reminders.py # блок 10 — заглушка
│ ├── subscription.py # блоки 11–12 — заглушка
│ ├── settings.py # блок 13 — заглушка
│ ├── support.py # тикеты — заглушка
│ └── admin.py # админка — заглушка
├── services/
│ ├── gigachat_service.py # GigaChat + fallback YandexGPT
│ ├── yandex_gpt.py # fallback
│ ├── task_manager.py # лимиты и задачи
│ ├── scheduler.py # APScheduler (заглушка)
│ └── yookassa_service.py # оплата (заглушка)
├── prompts/
│ ├── system.py # общие промпты
│ └── create_listing.py # промпт генерации
└── utils/
└── keyboards.py # все клавиатуры
text


### Схема БД

- `users` — telegram_id, tariff, pro_expires_at, timezone, onboarded
- `items` — карточки (name, confirmed_specs JSONB, current_price)
- `tasks` — единица лимита (task_type, status, limit_charged)
- `task_messages` — история диалога
- `listings` — версии объявлений (title, body, is_selected)
- `item_photos` — метаданные фото
- `competitors` — сохранённые конкуренты
- `stats_entries` — ручная статистика
- `reminders` — напоминания
- `payments` — платежи ЮKassa (idempotency_key UNIQUE)
- `support_tickets` + `support_messages` — поддержка
- `broadcasts` — рассылки
- `audit_log` — события

---

## 4. Ключевые правила

### Инфраструктура
- Порт 3000 (жёстко, `$PORT` не работает)
- Поле «Главный файл» на BotHost = `app/main.py`
- `uvicorn.run(app, ...)` — с объектом, не строкой (иначе двойной импорт → `Router is already attached`)
- `from __future__ import annotations` — первая строка после докстринга

### aiogram
- `dp.feed_webhook_update(bot, update)` — для webhook
- Роутеры через `try/except` (защита от повторной привязки)
- Fallback-хендлеры на `dp` НЕ добавлять (перехватывают апдейты)
- `CB.CANCEL` обрабатывается каждым сценарием со своим фильтром состояния

### GigaChat
- Модель: `GigaChat-2-Pro` (старые имена не работают)
- Scope: `GIGACHAT_API_PERS`
- `verify_ssl_certs=False` для dev
- Fallback на YandexGPT, если настроен

### Меню и кнопки
- Тексты кнопок главного меню — короткие, 2 в ряд:
  `📝 Создать`, `🛠 Улучшить`, `🔍 Конкуренты`, `📸 Фото`,
  `📈 Стратегия`, `💬 Ответы`, `📂 Мои`, `💳 Тариф`, `⚙️ Настройки`
- Все тексты кнопок — в классе `MENU` в `keyboards.py`
- Обновлять фильтры хендлеров при смене текстов
- `listing_variants` — без «Редактировать» (вариант ещё не выбран)
- `listing_after_pick` — с «Редактировать»

### Логика лимитов
- Лимит списывается только при `complete_task(status='done')`
- Технический сбой (`technical_failure=True`) — лимит не списывается
- Отмена (`cancelled`) — лимит не списывается
- Уточнения внутри задачи лимит не тратят

---

## 5. Что сделано (✅)

- [x] Инфраструктура: BotHost, порт 3000, webhook, БД
- [x] Схема БД (14 таблиц)
- [x] Конфиг через Pydantic Settings
- [x] Пул PostgreSQL с ленивой инициализацией
- [x] Middlewares: db, subscription, task_context, throttling
- [x] Все клавиатуры
- [x] `/start`, онбординг (приватность + часовой пояс)
- [x] GigaChat сервис с fallback на YandexGPT
- [x] Task Manager (лимиты, задачи)
- [x] **Блок 3 ТЗ: Создание объявления** — сбор, генерация, выбор, редактирование, перегенерация
- [x] Главное меню в 2 столбца, короткие тексты кнопок (класс `MENU`)

## 6. Что в работе (⏳)

- [ ] **Блок 4 ТЗ: Улучшить объявление** ← СЛЕДУЮЩИЙ
- [ ] Блок 5 ТЗ: Анализ конкурентов
- [ ] Блок 6 ТЗ: Помощь с фотографиями
- [ ] Блок 7 ТЗ: Стратегия продвижения
- [ ] Блок 8 ТЗ: Ответы покупателям
- [ ] Блок 9 ТЗ: Карточки и статистика
- [ ] Блок 10 ТЗ: Напоминания (APScheduler)
- [ ] Блоки 11–12 ТЗ: Тарифы и оплата (ЮKassa)
- [ ] Блок 13 ТЗ: Приватность (удаление данных)
- [ ] Поддержка в режиме чата
- [ ] Админка (тикеты, рассылки, статистика)

---

## 7. Журнал проблем и решений

| # | Проблема | Причина | Решение |
|---|---|---|---|
| 1 | `Router is already attached` | Двойной импорт `app.main` | `uvicorn.run(app, ...)` с объектом |
| 2 | `from __future__ imports must occur at the beginning` | `warnings.filterwarnings` до `from __future__` | `from __future__` — первая строка |
| 3 | `scope is empty` | `GIGACHAT_SCOPE` не задан | Переменная на BotHost + защита в коде |
| 4 | `No such model` | Старое имя модели | `GigaChat-2-Pro` |
| 5 | `502 Bad Gateway` | uvicorn слушал 8000 | Жёстко `--port 3000` |
| 6 | Кнопки в столбик | 9 кнопок в 1 колонку | 2 кнопки в ряд, класс `MENU` |
| 7 | «Задача потеряна» после генерации | FSM теряет task_id | `_resolve_task_id` (state → БД) |
| 8 | «Не выбран вариант» при редактировании | `edit_listing` брал вариант из state | `_get_selected_listing` из БД |

---

## 8. Переменные окружения на BotHost

TELEGRAM_BOT_TOKEN
ADMIN_TELEGRAM_ID
BOT_MODE=webhook
WEBHOOK_BASE_URL=https://bot-1791821973-8551-ivan31313131311.bothost.tech
WEBHOOK_PATH=/webhook
WEBHOOK_SECRET=<случайная строка>
DATABASE_URL=<от BotHost>
GIGACHAT_CREDENTIALS=<base64 client_id:client_secret>
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Pro
GIGACHAT_TEMPERATURE=0.6
GIGACHAT_MAX_TOKENS=2500
GIGACHAT_VERIFY_SSL=false
YOOKASSA_SHOP_ID=<test>
YOOKASSA_SECRET_KEY=<test>
ENVIRONMENT=dev
LOG_LEVEL=INFO
text


---

## 9. Правила работы над проектом

1. Общение только на русском
2. После каждого блока — дополнять этот CONTEXT.md
3. Файлы отдавать полным кодом
4. Не использовать `$PORT` — только 3000
5. Не добавлять fallback-хендлеры на `dp`
6. Тексты кнопок — короткие, 2 в ряд, в классе `MENU`
7. Листинги: `pick_variant` завершает задачу и списывает лимит; перегенерация после завершения — новая задача

---

## 10. Как продолжить в новом чате

1. Прочитать этот файл
2. Открыть раздел «Что в работе» — следующий блок
3. Найти соответствующий раздел ТЗ (блок 4, 5, 6…)
4. Написать хендлер + промпт + клавиатуры
5. Протестировать в Telegram
6. Дополнить CONTEXT.md

**Текущая точка остановки**: закончен блок 3 ТЗ, в работе — **блок 4 «Улучшить объявление»**.

---

*Последнее обновление: 2026-10-12*

- [x] Белый список (whitelist) — безлимитный PRO без оплаты
  - Таблица `whitelist` (telegram_id, added_by, note, expires_at, is_active)
  - Сервис `whitelist_service` (is_whitelisted, add, remove, list_all, get)
  - Проверка whitelist в `TaskManager.check_limit` и `get_limit_status`
  - Автоповышение до PRO в `SubscriptionMiddleware`
  - Админ-панель `/admin` → «🎁 Белый список» (добавить/удалить/список)
  - При удалении из whitelist пользователь понижается до FREE
  - [x] **Блок 4 ТЗ: Улучшить объявление**
  - Сбор материалов: текст, ссылка, скриншоты, статистика
  - Выбор проблемы: 6 вариантов (мало просмотров, мало избранного, нет сообщений, нет продажи, долго не продаётся, нужно быстрее)
  - GigaChat анализирует: сильные стороны, проблемы, приоритетные изменения
  - Предлагает новый заголовок и описание
  - Объясняет, что проверить после изменения
  - Если данных мало — не списывает лимит и просит дополнить
  - [ ] **Блок 5 ТЗ: Анализ конкурентов** ← СЛЕДУЮЩИЙ
  - [x] **Блок 5 ТЗ: Анализ конкурентов**
  - Приём от 1 до 5 конкурентов: ссылки, скриншоты, текст
  - Ссылки не парсятся, но учитываются в промпте
  - Скриншоты группируются с последним «screenshot»-конкурентом
  - GigaChat сравнивает: цена, заголовки, описание, состояние, комплектация
  - Выдаёт: сильные/слабые стороны конкурентов, преимущества пользователя
  - Рекомендует диапазон цены
  - Указывает, где мало данных
  - Лимит списывается один раз за весь анализ
  - [ ] **Блок 6 ТЗ: Помощь с фотографиями** ← СЛЕДУЮЩИЙ
  - [x] **Блок 6 ТЗ: Помощь с фотографиями (Vision)**
  - GigaChat Vision через `upload_file` + `attachments`
  - Скачивание фото из Telegram → загрузка в GigaChat → удаление после анализа
  - Максимум 10 фото за раз (лимит GigaChat)
  - Оценка: лучшее главное фото, разбор каждого, каких ракурсов не хватает
  - Как показать состояние и комплектацию
  - Лимит списывается один раз при «✅ Готово», переанализ бесплатный
  - [ ] **Блок 7 ТЗ: Стратегия продвижения** ← СЛЕДУЮЩИЙ
  - [x] Блок 3: Создание объявления — **Vision подключён** (фото → GigaChat)
- [x] Блок 5: Анализ конкурентов — **Vision подключён** (скриншоты → GigaChat)
- Vision-методы: `generate_with_photos` (свободный текст), `analyze_with_photos_json` (JSON)
- Всегда fallback на текст, если Vision падает
- Файлы в GigaChat удаляются сразу после анализа
- [x] Логирование расхода токенов GigaChat
  - Таблица `gigachat_usage` (user_id, task_id, call_type, tokens, success)
  - `usage_logger` — центральная точка записи
  - Логирование из текста и Vision после каждого вызова
  - Админ-статистика: расход за день/месяц, топ-3 пользователя
  - `max_tokens`: 5000 (Vision) / 4000 (текст)
- Расход токенов логируется в `gigachat_usage`
- Видим через `/admin` → «Статистика»
- [x] **Блок 3 ТЗ: Создание объявления** (полностью)
  - Приём фото и текста в любом порядке
  - **Двухшаговая генерация**:
    1. Vision (`GigaChat-2-Pro`) описывает фото текстом (300–700 символов)
    2. Текстовый GigaChat генерирует 3 варианта по описанию + текст
  - Обход ограничения Vision-модели (не выдаёт длинный JSON с фото)
  - 3 варианта: фактический, дружелюбный, альтернативный
  - Сохранение в `items` + `listings` при выборе
  - Редактирование заголовка и текста
  - Перегенерация (в рамках задачи — бесплатно, после завершения — новая задача)
  - Логика доставки: СДЭК только для лёгких/средних товаров, для авто/недвижимости/крупногабарита — только самовывоз
  - Fallback на текст, если Vision упал
  - Восстановление обрезанного JSON (`_try_recover_json`)

- [x] **Блок 5 ТЗ: Анализ конкурентов** (полностью)
  - Приём от 1 до 5 конкурентов: ссылки, скриншоты, текст
  - Vision читает текст со скриншотов
  - Сравнение по цене, заголовкам, описанию, состоянию, комплектации
  - Выдаёт сильные/слабые стороны, преимущества пользователя, рекомендованную цену
  - Fallback на текст, если Vision упал

- [x] **Блок 4 ТЗ: Улучшение объявления** (полностью)
  - Приём текста, ссылки, скриншотов, статистики
  - Выбор проблемы из 6 вариантов
  - Анализ: сильные стороны, проблемы, приоритетные изменения
  - Новый заголовок и описание
  - Метрика для проверки результата
  - Если данных мало — не списывает лимит

- [x] **Блок 6 ТЗ: Помощь с фотографиями** (полностью)
  - Vision анализирует фото товара
  - Выбор лучшего главного фото
  - Разбор каждого фото (плюсы/минусы)
  - Рекомендации по ракурсам, состоянию, комплектации
  - Переанализ тех же фото — бесплатно (в рамках задачи)

- [x] **Логирование расхода токенов GigaChat**
  - Таблица `gigachat_usage` (user_id, task_id, call_type, tokens, meta)
  - `usage_logger` — центральная точка записи
  - Логирование из текста (`json`, `text`) и Vision (`vision_json`, `vision_describe`)
  - Админ-статистика: расход за день/месяц, топ-3 пользователя
  - Просмотр через `/admin` → 📊 Статистика

- [x] **Белый список (whitelist)**
  - Таблица `whitelist` (telegram_id, added_by, note, expires_at, is_active)
  - Сервис `whitelist_service`
  - Проверка в `TaskManager.check_limit` и `SubscriptionMiddleware`
  - Автоповышение до PRO без срока
  - Админ-панель `/admin` → 🎁 Белый список

- [x] **Админ-панель** (базовая)
  - `/admin` — только для `ADMIN_TELEGRAM_ID`
  - Белый список: добавить / удалить / список
  - Статистика: пользователи, PRO, whitelist, товары, задачи, расход токенов
  - [ ] **Блок 7 ТЗ: Стратегия продвижения** ← СЛЕДУЮЩИЙ
- [ ] Блок 8 ТЗ: Ответы покупателям
- [ ] Блок 9 ТЗ: Карточки и статистика
- [ ] Блок 10 ТЗ: Напоминания (APScheduler)
- [ ] Блоки 11–12 ТЗ: Тарифы и оплата (ЮKassa)
- [ ] Блок 13 ТЗ: Приватность (удаление данных)
- [ ] Поддержка в режиме чата
- [ ] Рассылки
- **Модель**: `GigaChat-2-Pro` (Vision + текст)
- **Scope**: `GIGACHAT_API_PERS`
- **`max_tokens`**: Vision describe 1500, Text/JSON 6000, Vision JSON 5000
- **Двухшаговая генерация** для create_listing: Vision describe → Text gen
- **Fallback на текст** везде, если Vision падает
- **Восстановление обрезанного JSON** в обоих сервисах
- **Логика доставки** — классификатор в промпте: легкие товары → СДЭК, тяжелые/авто/недвижимость → самовывоз
- **Расход** логируется в `gigachat_usage`
- **Файлы в GigaChat** удаляются сразу после анализа (минимизация хранения)
- **Главное меню**: 2 кнопки в ряд, тексты в классе `MENU` в `keyboards.py`
- **Короткие тексты**: `📝 Создать`, `🛠 Улучшить`, `🔍 Конкуренты`, `📸 Фото`, `📈 Стратегия`, `💬 Ответы`, `📂 Мои`, `💳 Тариф`, `⚙️ Настройки`
- **`listing_variants`** — без «Редактировать» (вариант ещё не выбран)
- **`listing_after_pick`** — с «Редактировать»
- **`listing_after_edit`** — после правки текста
- **`improve_materials`** — включает «✅ Материалов достаточно» с callback `improve:ready`
- [x] **Блок 7 ТЗ: Стратегия продвижения** (полностью)
  - Приём данных: заголовок, текст, цена, статистика (просмотры, избранное, сообщения), дни на Авито
  - GigaChat выдаёт пошаговый план:
    • Шаг 1 (сегодня): что сделать сейчас
    • Шаг 2 (через 2-3 дня): что проверить
    • Шаг 3 (если не помогло): что делать дальше
  - Логика: сначала бесплатные методы, платное — только если обосновано
  - Учитывает правила Авито: не обещает топ, не советует обход ограничений
  - Логика доставки: для авто/недвижимости/крупногабарита — только самовывоз
  - Отслеживание показателей и следующий шаг
  - «⏰ Напомнить позже» — отложенная стратегия
  - [ ] **Блок 8 ТЗ: Ответы покупателям** ← СЛЕДУЮЩИЙ
- [ ] Блок 9 ТЗ: Карточки и статистика
- [ ] Блок 10 ТЗ: Напоминания (APScheduler)
- [ ] Блоки 11–12 ТЗ: Тарифы и оплата (ЮKassa)
- [ ] Блок 13 ТЗ: Приватность (удаление данных)
- [ ] Поддержка в режиме чата
- [ ] Рассылки
- [x] **Блок 7 ТЗ: Стратегия продвижения** (полностью)
  - Приём данных: заголовок, текст, цена, статистика (просмотры, избранное, сообщения), дни на Авито
  - GigaChat выдаёт пошаговый план:
    • Шаг 1 (сегодня): что сделать сейчас
    • Шаг 2 (через 2-3 дня): что проверить
    • Шаг 3 (если не помогло): что делать дальше
  - Логика: сначала бесплатные методы, платное — только если обосновано
  - Учитывает правила Авито: не обещает топ, не советует обход ограничений
  - Логика доставки: для авто/недвижимости/крупногабарита — только самовывоз
  - Отслеживание показателей и следующий шаг
  - «⏰ Напомнить позже» — отложенная стратегия
  - Проверено: 2587 символов, 1297 токенов, ~10 сек
  - [ ] **Блок 8 ТЗ: Ответы покупателям** ← СЛЕДУЮЩИЙ
- [ ] Блок 9 ТЗ: Карточки и статистика
- [ ] Блок 10 ТЗ: Напоминания (APScheduler)
- [ ] Блоки 11–12 ТЗ: Тарифы и оплата (ЮKassa)
- [ ] Блок 13 ТЗ: Приватность (удаление данных)
- [ ] Поддержка в режиме чата
- [ ] Рассылки
text

avito-assistant/
│
├── 📄 CONTEXT.md                     # файл-память, обновляется после каждого блока
├── 📄 bothost.json                   # конфиг BotHost (start_command, порт 3000)
├── 📄 requirements.txt               # зависимости
├── 📄 .env                           # секреты (не в git)
├── 📄 .env.example                   # шаблон секретов
├── 📄 .gitignore                     # игнор: .env, venv, __pycache__
│
├── 📁 migrations/
│   └── 📄 init.sql                   # 15 таблиц + триггеры + индексы
│
└── 📁 app/
    │
    ├── 📄 __init__.py
    ├── 📄 main.py                    # точка входа: FastAPI + aiogram + uvicorn.run(app)
    ├── 📄 config.py                  # Pydantic Settings — все env-переменные
    ├── 📄 database.py                # пул psycopg + ленивая инициализация + apply_schema
    │
    ├── 📁 middlewares/
    │   ├── 📄 __init__.py
    │   ├── 📄 db.py                  # DbSessionMiddleware: db + user в контекст
    │   ├── 📄 subscription.py        # SubscriptionMiddleware: PRO + whitelist автоповышение
    │   ├── 📄 task_context.py        # TaskContextMiddleware: заглушка
    │   └── 📄 throttling.py          # ThrottlingMiddleware: заглушка
    │
    ├── 📁 handlers/                  # 13 роутеров
    │   ├── 📄 __init__.py
    │   ├── 📄 start.py               # ✅ /start, онбординг, меню, /help
    │   ├── 📄 admin.py               # ✅ /admin, whitelist, статистика
    │   ├── 📄 create_listing.py      # ✅ блок 3 — создание объявления (Vision + текст)
    │   ├── 📄 improve_listing.py     # ✅ блок 4 — улучшение
    │   ├── 📄 competitors.py         # ✅ блок 5 — анализ конкурентов
    │   ├── 📄 photos.py              # ✅ блок 6 — помощь с фото (Vision)
    │   ├── 📄 strategy.py            # ✅ блок 7 — стратегия продвижения
    │   ├── 📄 buyer_replies.py       # ⏳ блок 8 — СЛЕДУЮЩИЙ
    │   ├── 📄 items_history.py       # ⏳ блок 9
    │   ├── 📄 reminders.py           # ⏳ блок 10
    │   ├── 📄 subscription.py        # ⏳ блоки 11–12
    │   ├── 📄 settings.py            # ⏳ блок 13
    │   └── 📄 support.py             # ⏳ тикеты
    │
    ├── 📁 services/
    │   ├── 📄 __init__.py
    │   ├── 📄 gigachat_service.py    # текстовый GigaChat + JSON + recovery
    │   ├── 📄 gigachat_vision.py     # Vision: describe_photos + analyze_with_photos_json
    │   ├── 📄 yandex_gpt.py          # fallback YandexGPT
    │   ├── 📄 task_manager.py        # лимиты, задачи, списание
    │   ├── 📄 whitelist.py           # whitelist_service
    │   ├── 📄 usage_logger.py        # запись расхода токенов в БД
    │   ├── 📄 scheduler.py           # APScheduler (заглушка)
    │   └── 📄 yookassa_service.py    # оплата (заглушка)
    │
    ├── 📁 prompts/                   # системные промпты
    │   ├── 📄 __init__.py
    │   ├── 📄 system.py              # общие промпты (авитолог, конкуренты, ответы, стратегия)
    │   ├── 📄 create_listing.py      # ✅ блок 3 (SYSTEM_PROMPT + SYSTEM_PROMPT_DESCRIBE_PHOTO)
    │   ├── 📄 improve_listing.py     # ✅ блок 4
    │   ├── 📄 competitors.py         # ✅ блок 5
    │   ├── 📄 photos.py              # ✅ блок 6
    │   ├── 📄 strategy.py            # ✅ блок 7
    │   └── 📄 buyer_replies.py       # ⏳ блок 8 — создать
    │
    └── 📁 utils/
        ├── 📄 __init__.py
        ├── 📄 keyboards.py           # все клавиатуры + CB + MENU
        └── 📄 formatters.py          # (опционально, пока пусто)

Назначение каждого файла
Инфраструктура (корень)
Файл	Что делает
CONTEXT.md	Память проекта. Обновляется после каждого блока. Содержит всё: что сделано, что в работе, проблемы, решения, правила
bothost.json	Конфиг BotHost. start_command, main: app.main:app, python_version: 3.11
requirements.txt	Все зависимости (aiogram, psycopg, gigachat, yookassa и т.д.)
.env	Секреты — TG_TOKEN, DATABASE_URL, GIGACHAT_CREDENTIALS, YOOKASSA_*
Миграции
Файл	Что делает
migrations/init.sql	Создаёт 15 таблиц: users, items, tasks, task_messages, listings, item_photos, competitors, stats_entries, reminders, payments, support_tickets, support_messages, broadcasts, audit_log, gigachat_usage, whitelist. Плюс индексы и триггеры updated_at
Ядро (app/)
Файл	Что делает
main.py	FastAPI + aiogram. Регистрирует 13 роутеров и 4 middleware. /webhook для Telegram, /yookassa/webhook для оплаты, /health для BotHost. Запуск uvicorn с объектом app (не строкой!)
config.py	Pydantic Settings. Читает .env. Валидирует обязательные переменные. Один глобальный settings
database.py	Пул psycopg_pool с ленивой инициализацией. Хелперы: fetch_one, fetch_all, fetch_val, execute, execute_returning. Применяет init.sql при первом запросе
Middlewares
Файл	Что делает
db.py	Кладёт db и user в data для всех хендлеров
subscription.py	Автопонижение PRO при истечении. Автоповышение для whitelist. Флаги is_pro, is_admin, is_whitelisted
task_context.py	Заглушка (в будущем — активная задача)
throttling.py	Заглушка (в будущем — антиспам)
Handlers (роутеры)
Файл	Статус	Что делает
start.py	✅	/start, онбординг (приватность + таймзона), главное меню, /help, возврат в меню
admin.py	✅	/admin, whitelist (добавить/удалить/список), статистика (пользователи, задачи, расход токенов)
create_listing.py	✅	Блок 3. Двухшаговая генерация: Vision описывает фото → текст генерирует 3 варианта. Редактирование, перегенерация, отмена
improve_listing.py	✅	Блок 4. Сбор материалов (текст, ссылка, скриншоты, статистика), выбор проблемы, анализ
competitors.py	✅	Блок 5. От 1 до 5 конкурентов, Vision читает скриншоты, сравнение
photos.py	✅	Блок 6. Vision анализирует фото, выбор главного, советы по ракурсам
strategy.py	✅	Блок 7. Сбор данных, GigaChat выдаёт пошаговый план
buyer_replies.py	⏳	Блок 8. Ответы на сообщения покупателей
items_history.py	⏳	Блок 9. Карточки товаров, статистика, история
reminders.py	⏳	Блок 10. Напоминания 1/3/7 дней
subscription.py	⏳	Блоки 11–12. Тарифы и оплата ЮKassa
settings.py	⏳	Блок 13. Часовой пояс, удаление данных, поддержка
support.py	⏳	Тикеты поддержки (админ отвечает в режиме чата)
Services
Файл	Что делает
gigachat_service.py	Текстовый GigaChat. generate и generate_json. Fallback на YandexGPT. Восстановление обрезанного JSON (_try_recover_variants, _try_recover_any_json). Логирует usage
gigachat_vision.py	Vision-режим. describe_photos (описание фото текстом), analyze_with_photos_json (JSON-ответ). Загрузка фото в GigaChat, удаление после анализа. Логирует usage
yandex_gpt.py	Fallback на YandexGPT, если GigaChat недоступен
task_manager.py	Лимиты Free/PRO/whitelist. check_limit, create_task, complete_task, log_message, get_limit_status
whitelist.py	is_whitelisted, add, remove, list_all. При удалении — понижение до FREE
usage_logger.py	Запись в gigachat_usage: user_id, task_id, call_type, токены, success, meta
scheduler.py	APScheduler (заглушка, будет в блоке 10)
yookassa_service.py	ЮKassa (заглушка, будет в блоках 11–12)
Prompts
Файл	Что делает
system.py	Общие промпты (не используется, оставлен на будущее)
create_listing.py	SYSTEM_PROMPT (текст), SYSTEM_PROMPT_DESCRIBE_PHOTO (Vision describe), build_user_prompt, DESCRIBE_USER_PROMPT
improve_listing.py	SYSTEM_PROMPT, PROBLEM_LABELS, build_user_prompt
competitors.py	SYSTEM_PROMPT, build_user_prompt
photos.py	SYSTEM_PROMPT, build_user_prompt
strategy.py	SYSTEM_PROMPT, build_user_prompt
buyer_replies.py	⏳ блок 8
Utils
Файл	Что делает
keyboards.py	Все клавиатуры. Класс CB — реестр callback_data. Класс MENU — тексты кнопок главного меню (короткие). Inline и Reply клавиатуры
Поток данных
text

Telegram → BotHost (порт 3000)
    ↓
FastAPI /webhook (secret check)
    ↓
Update.model_validate
    ↓
dp.feed_webhook_update
    ↓
┌─────────────────────────────────┐
│ Middlewares (outer):            │
│ 1. Throttling                   │
│ 2. DbSession (user + db)        │
│ 3. Subscription (PRO/whitelist) │
│ 4. TaskContext                  │
└─────────────────────────────────┘
    ↓
Router (13 штук по порядку)
    ↓
Handler → GigaChat/Vision → БД → ответ пользователю
    ↓
usage_logger → gigachat_usage

Что в работе (по блокам ТЗ)
Блок	Статус	Файлы
3 — Создать объявление	✅	handlers/create_listing.py, prompts/create_listing.py
4 — Улучшить объявление	✅	handlers/improve_listing.py, prompts/improve_listing.py
5 — Анализ конкурентов	✅	handlers/competitors.py, prompts/competitors.py
6 — Помощь с фото	✅	handlers/photos.py, prompts/photos.py
7 — Стратегия	✅	handlers/strategy.py, prompts/strategy.py
8 — Ответы покупателям	⏳	handlers/buyer_replies.py, prompts/buyer_replies.py — СЛЕДУЮЩИЕ
9 — Карточки и статистика	⏳	handlers/items_history.py
10 — Напоминания	⏳	handlers/reminders.py, services/scheduler.py
11–12 — Тарифы и оплата	⏳	handlers/subscription.py, services/yookassa_service.py
13 — Приватность	⏳	handlers/settings.py
Поддержка	⏳	handlers/support.py
Рассылки	⏳	в handlers/admin.py
Итого

    Роутеров: 13 (7 готовы, 6 заглушки)

    Таблиц в БД: 16 (whitelist + gigachat_usage добавлены)

    Middlewares: 4 (2 работают, 2 заглушки)

    Сервисов: 8 (5 работают, 3 заглушки)

    Промптов: 5 (готовы), 1 в работе (блок 8)

Следующий шаг — блок 8 «Ответы покупателям»: handlers/buyer_replies.py + prompts/buyer_replies.py.
- [x] **Блок 8 ТЗ: Ответы покупателям** (полностью)
  - Приём сообщения покупателя
  - Выбор цели ответа из 7 вариантов:
    • ✅ Подтвердить актуальность
    • 💰 Обсудить торг
    • 📦 Объяснить состояние
    • 📍 Договориться о встрече
    • 🔔 Напомнить о себе
    • 🚫 Вежливо отказать
    • ⏭ Без цели
  - GigaChat генерирует короткий (1-4 предложения) вежливый ответ
  - Не придумывает условий сделки, не создаёт ложную срочность
  - Не снижает цену самостоятельно
  - Можно сразу отправить новое сообщение → новая задача (без потери контекста)
  - [ ] **Блок 9 ТЗ: Карточки и статистика** ← СЛЕДУЮЩИЙ
- [ ] Блок 10 ТЗ: Напоминания (APScheduler)
- [ ] Блоки 11–12 ТЗ: Тарифы и оплата (ЮKassa)
- [ ] Блок 13 ТЗ: Приватность (удаление данных)
- [ ] Поддержка в режиме чата
- [ ] Рассылки
- Цели ответа покупателю — `buyer_reply_goals()` в keyboards.py
- Callback: `reply:goal:confirm`, `reply:goal:haggle`, и т.д.
- [x] **Блок 9 ТЗ: Карточки, история и статистика** (полностью)
  - Список товаров пользователя (с эмодзи статуса, ценой, кол-вом версий)
  - Карточка товара: название, цена, статус, версии текста, статистика, история цены
  - **Ввод статистики вручную**: просмотры, избранное, сообщения, итог
  - Парсер свободного текста: «Просмотры: 45, избранное: 2, сообщения: 0»
  - **Изменение цены** с записью в price_history (JSONB)
  - **Смена версии текста** (переключение is_selected между listings)
  - **Пометка «продано»** — меняет статус товара и создаёт запись в stats_entries
  - **Рекомендация от GigaChat** на основе истории:
    • observations — что наблюдается
    • hypotheses — возможные объяснения (с оговоркой «возможно»)
    • next_step — один следующий шаг с обоснованием
  - Учитывает изменения цены, текста, условий
  - Разделяет факты и предположения
  - [ ] **Блок 10 ТЗ: Напоминания (APScheduler)** ← СЛЕДУЮЩИЙ
- [ ] Блоки 11–12 ТЗ: Тарифы и оплата (ЮKassa)
- [ ] Блок 13 ТЗ: Приватность (удаление данных)
- [ ] Поддержка в режиме чата
- [ ] Рассылки
  - После действий (статистика, цена, продано, текст, рекомендация) — кнопки:
    • 🔙 К карточке товара (вернуться к этому же товару)
    • 📂 К списку товаров
    • 🏠 В главное меню
  - Функция `item_after_action(item_id)` в keyboards.py