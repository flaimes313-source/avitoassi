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