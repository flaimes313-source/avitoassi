-- ============================================================
-- СХЕМА БАЗЫ ДАННЫХ «Авито-Помощник»
-- PostgreSQL 14+
-- Все ID — BIGSERIAL, время — TIMESTAMPTZ (с часовым поясом)
-- ============================================================

-- Расширение для генерации UUID (нужно для некоторых сущностей)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- ПОЛЬЗОВАТЕЛИ
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id                  BIGSERIAL PRIMARY KEY,
    telegram_id         BIGINT UNIQUE NOT NULL,
    username            TEXT,
    first_name          TEXT,
    last_name           TEXT,

    -- Тариф: 'free' или 'pro'
    tariff              TEXT NOT NULL DEFAULT 'free'
                        CHECK (tariff IN ('free', 'pro')),

    -- Срок действия PRO (NULL для free)
    pro_expires_at      TIMESTAMPTZ,

    -- Часовой пояс пользователя (запрашивается при /start)
    timezone            TEXT NOT NULL DEFAULT 'Europe/Moscow',

    -- Флаг: прошёл ли пользователь первичную настройку
    onboarded           BOOLEAN NOT NULL DEFAULT FALSE,

    -- Флаг: заблокирован ли бот пользователем (обновляется при ошибке отправки)
    bot_blocked         BOOLEAN NOT NULL DEFAULT FALSE,

    -- Согласие на обработку данных (блок 13 ТЗ)
    privacy_accepted_at TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_users_tariff ON users(tariff) WHERE tariff = 'pro';
CREATE INDEX IF NOT EXISTS idx_users_pro_expires ON users(pro_expires_at)
    WHERE pro_expires_at IS NOT NULL;

-- ============================================================
-- КАРТОЧКИ ТОВАРОВ
-- ============================================================
CREATE TABLE IF NOT EXISTS items (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Название, как его понимает пользователь
    name                TEXT NOT NULL,

    -- Подтверждённые характеристики (JSONB — гибко, под разные товары)
    -- Пример: {"состояние": "б/у", "ширина": "120 см", "гарантия": false}
    confirmed_specs     JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Текущая цена (может меняться)
    current_price       INTEGER,

    -- История изменения цены: [{"date": "...", "price": 21000, "reason": "..."}]
    price_history       JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Статус: active (в продаже), sold (продано), archived (в архиве)
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'sold', 'archived')),

    -- Причина продажи (если пользователь указал)
    sale_reason         TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_items_user ON items(user_id);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_items_specs ON items USING GIN(confirmed_specs);

-- ============================================================
-- ЗАДАЧИ (единица списания лимита)
-- ============================================================
CREATE TABLE IF NOT EXISTS tasks (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Товар, к которому относится задача (может быть NULL на этапе создания)
    item_id             BIGINT REFERENCES items(id) ON DELETE SET NULL,

    -- Тип задачи (соответствует блокам ТЗ)
    task_type           TEXT NOT NULL
                        CHECK (task_type IN (
                            'create_listing',      -- блок 3
                            'improve_listing',     -- блок 4
                            'competitors',         -- блок 5
                            'photos',              -- блок 6
                            'strategy',            -- блок 7
                            'buyer_reply'          -- блок 8
                        )),

    -- Статус: active (в процессе), done (успешно), failed (сбой), cancelled
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'done', 'failed', 'cancelled')),

    -- Задача списала лимит? (списываем при первом успешном запуске)
    limit_charged       BOOLEAN NOT NULL DEFAULT FALSE,

    -- Задача завершилась техническим сбоем? (не списываем лимит, блок 11 ТЗ)
    technical_failure   BOOLEAN NOT NULL DEFAULT FALSE,

    -- Собранные материалы (тексты, ссылки, описания)
    collected_data      JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Результат задачи (сгенерированные варианты, рекомендации)
    result              JSONB,

    -- Метаданные (для аналитики и отладки)
    meta                JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,

    -- Ограничение: одна активная задача каждого типа на пользователя
    -- (реализуется в коде, но полезно для консистентности)
    CONSTRAINT chk_completed_at CHECK (
        (status = 'active' AND completed_at IS NULL) OR
        (status <> 'active')
    )
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_active ON tasks(user_id, task_type)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);

-- ============================================================
-- СООБЩЕНИЯ ДИАЛОГА ВНУТРИ ЗАДАЧИ
-- ============================================================
-- История сообщений: что бот спросил, что пользователь ответил.
-- Нужно для восстановления контекста и для промптов.
CREATE TABLE IF NOT EXISTS task_messages (
    id                  BIGSERIAL PRIMARY KEY,
    task_id             BIGINT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,

    -- Роль: 'user' или 'assistant'
    role                TEXT NOT NULL CHECK (role IN ('user', 'assistant')),

    -- Текст сообщения
    content             TEXT NOT NULL,

    -- Прикреплённые файлы (telegram file_id)
    attachments         JSONB NOT NULL DEFAULT '[]'::jsonb,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_messages_task ON task_messages(task_id, created_at);

-- ============================================================
-- ВЕРСИИ ОБЪЯВЛЕНИЙ
-- ============================================================
CREATE TABLE IF NOT EXISTS listings (
    id                  BIGSERIAL PRIMARY KEY,
    item_id             BIGINT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    task_id             BIGINT REFERENCES tasks(id) ON DELETE SET NULL,

    -- Номер версии (1, 2, 3...)
    version             INTEGER NOT NULL DEFAULT 1,

    -- Подход: 'factual' (фактический), 'friendly' (дружелюбный), 'alternative'
    approach            TEXT NOT NULL DEFAULT 'factual'
                        CHECK (approach IN ('factual', 'friendly', 'alternative')),

    -- Заголовок и текст
    title               TEXT NOT NULL,
    body                TEXT NOT NULL,

    -- Выбрал ли пользователь этот вариант как основной
    is_selected         BOOLEAN NOT NULL DEFAULT FALSE,

    -- Скопировал ли пользователь (аналитика)
    was_copied          BOOLEAN NOT NULL DEFAULT FALSE,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_listings_item ON listings(item_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_listings_selected ON listings(item_id)
    WHERE is_selected = TRUE;

-- ============================================================
-- ФОТОГРАФИИ ТОВАРА
-- ============================================================
-- Храним только метаданные и telegram file_id, оригиналы не храним
-- (блок 13 ТЗ — минимизация хранения).
CREATE TABLE IF NOT EXISTS item_photos (
    id                  BIGSERIAL PRIMARY KEY,
    item_id             BIGINT NOT NULL REFERENCES items(id) ON DELETE CASCADE,

    -- Telegram file_id (позволяет скачать фото при необходимости)
    telegram_file_id    TEXT NOT NULL,

    -- Уникальный ID файла на стороне Telegram (для дедупликации)
    telegram_file_unique_id TEXT,

    -- Размер и метаданные
    file_size           INTEGER,
    width               INTEGER,
    height              INTEGER,

    -- Порядок в карточке (первое = главное)
    sort_order          INTEGER NOT NULL DEFAULT 0,

    -- Анализ от ИИ (если проводился)
    ai_analysis         JSONB,

    -- Когда удалить оригинал (если временно скачивали)
    expires_at          TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_item_photos_item ON item_photos(item_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_item_photos_expires ON item_photos(expires_at)
    WHERE expires_at IS NOT NULL;

-- ============================================================
-- КОНКУРЕНТЫ (сохранённые для анализа)
-- ============================================================
CREATE TABLE IF NOT EXISTS competitors (
    id                  BIGSERIAL PRIMARY KEY,
    item_id             BIGINT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    task_id             BIGINT REFERENCES tasks(id) ON DELETE SET NULL,

    -- Тип источника: 'link', 'screenshot', 'text'
    source_type         TEXT NOT NULL
                        CHECK (source_type IN ('link', 'screenshot', 'text')),

    -- Ссылка (если source_type = 'link')
    url                 TEXT,

    -- Текст или описание (если source_type = 'text')
    content             TEXT,

    -- Скриншоты (telegram file_id)
    screenshots         JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Доступна ли ссылка (проверено ли при парсинге)
    is_accessible       BOOLEAN,

    -- Извлечённые данные (цена, заголовок, описание и т.п.)
    extracted_data      JSONB,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_competitors_item ON competitors(item_id);

-- ============================================================
-- СТАТИСТИКА (ручной ввод)
-- ============================================================
CREATE TABLE IF NOT EXISTS stats_entries (
    id                  BIGSERIAL PRIMARY KEY,
    item_id             BIGINT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Показатели на момент ввода
    views               INTEGER,
    favorites           INTEGER,
    messages            INTEGER,

    -- Результат: 'in_progress', 'sold', 'no_result'
    outcome             TEXT CHECK (outcome IN ('in_progress', 'sold', 'no_result')),

    -- Цена на момент ввода (для сопоставления с изменениями)
    price_at_entry      INTEGER,

    -- Комментарий пользователя
    note                TEXT,

    -- Из какого источника: 'manual' (ручной), 'screenshot' (со скрина)
    source              TEXT NOT NULL DEFAULT 'manual'
                        CHECK (source IN ('manual', 'screenshot')),

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stats_item_date ON stats_entries(item_id, created_at DESC);

-- ============================================================
-- НАПОМИНАНИЯ
-- ============================================================
CREATE TABLE IF NOT EXISTS reminders (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_id             BIGINT REFERENCES items(id) ON DELETE CASCADE,
    task_id             BIGINT REFERENCES tasks(id) ON DELETE CASCADE,

    -- Тип: 'follow_up' (общий), 'stats_check' (запрос статистики),
    -- 'subscription_expiring' (окончание подписки)
    reminder_type       TEXT NOT NULL
                        CHECK (reminder_type IN (
                            'follow_up',
                            'stats_check',
                            'subscription_expiring'
                        )),

    -- Когда отправить
    run_at              TIMESTAMPTZ NOT NULL,

    -- Текст напоминания (если кастомный)
    custom_text         TEXT,

    -- Включено ли
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,

    -- Отправлено ли (чтобы не дублировать)
    sent_at             TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reminders_pending ON reminders(run_at)
    WHERE enabled = TRUE AND sent_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id, enabled);

-- ============================================================
-- ПЛАТЕЖИ
-- ============================================================
CREATE TABLE IF NOT EXISTS payments (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,

    -- ID платежа в ЮKassa
    yookassa_payment_id TEXT UNIQUE NOT NULL,

    -- Idempotency-ключ для защиты от дублей
    idempotency_key     TEXT UNIQUE NOT NULL,

    -- Сумма и валюта
    amount              NUMERIC(10, 2) NOT NULL,
    currency            TEXT NOT NULL DEFAULT 'RUB',

    -- Статус: 'pending', 'succeeded', 'canceled', 'refunded'
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'succeeded', 'canceled', 'refunded')),

    -- Что оплачивали: 'pro_30d'
    product             TEXT NOT NULL DEFAULT 'pro_30d',

    -- Срок подписки, который активируется при успехе
    pro_days            INTEGER NOT NULL DEFAULT 30,

    -- Полный ответ от ЮKassa (для аудита)
    raw_response        JSONB,

    -- Когда активировали PRO
    activated_at        TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)
    WHERE status = 'pending';

-- ============================================================
-- ТИКЕТЫ ПОДДЕРЖКИ (для админки в режиме чата)
-- ============================================================
CREATE TABLE IF NOT EXISTS support_tickets (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Тема / краткое описание
    subject             TEXT NOT NULL,

    -- Статус: 'open', 'in_progress', 'closed'
    status              TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'in_progress', 'closed')),

    -- Кто последний ответил: 'user' или 'admin'
    last_reply_by       TEXT CHECK (last_reply_by IN ('user', 'admin')),

    -- Счётчик непрочитанных сообщений (для обеих сторон)
    unread_by_user      INTEGER NOT NULL DEFAULT 0,
    unread_by_admin     INTEGER NOT NULL DEFAULT 0,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tickets_user ON support_tickets(user_id, status);
CREATE INDEX IF NOT EXISTS idx_tickets_open ON support_tickets(status, updated_at DESC)
    WHERE status <> 'closed';

-- Сообщения внутри тикета
CREATE TABLE IF NOT EXISTS support_messages (
    id                  BIGSERIAL PRIMARY KEY,
    ticket_id           BIGINT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,

    -- Кто отправил: 'user' или 'admin'
    sender              TEXT NOT NULL CHECK (sender IN ('user', 'admin')),

    -- ID админа (если sender = 'admin')
    admin_telegram_id   BIGINT,

    content             TEXT NOT NULL,

    -- Прикреплённые файлы
    attachments         JSONB NOT NULL DEFAULT '[]'::jsonb,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_support_messages_ticket
    ON support_messages(ticket_id, created_at);

-- ============================================================
-- РАССЫЛКИ (заложено на будущее)
-- ============================================================
CREATE TABLE IF NOT EXISTS broadcasts (
    id                  BIGSERIAL PRIMARY KEY,

    -- Заголовок для админки
    title               TEXT NOT NULL,

    -- Текст сообщения (Markdown/HTML)
    message_text        TEXT NOT NULL,

    -- Медиа (если есть)
    media               JSONB,

    -- Статус: 'draft', 'scheduled', 'running', 'done', 'cancelled'
    status              TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'scheduled', 'running', 'done', 'cancelled')),

    -- Фильтр аудитории (JSONB): {"tariff": "pro", "active_days": 30}
    audience_filter     JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Когда запускать (для отложенной)
    scheduled_at        TIMESTAMPTZ,

    -- Прогресс
    total_recipients    INTEGER NOT NULL DEFAULT 0,
    sent_count          INTEGER NOT NULL DEFAULT 0,
    failed_count        INTEGER NOT NULL DEFAULT 0,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_broadcasts_status ON broadcasts(status, scheduled_at);

-- ============================================================
-- АУДИТ (для отладки и разбора инцидентов)
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT REFERENCES users(id) ON DELETE SET NULL,

    -- Тип события: 'task_created', 'task_completed', 'limit_exceeded',
    -- 'payment_created', 'payment_succeeded', 'admin_action' и т.д.
    event_type          TEXT NOT NULL,

    -- Данные события (без секретов)
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- IP / user agent для веб-хуков
    ip_address          TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at DESC);

-- ============================================================
-- ТРИГГЕР: обновление updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_items_updated_at
    BEFORE UPDATE ON items
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_payments_updated_at
    BEFORE UPDATE ON payments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_tickets_updated_at
    BEFORE UPDATE ON support_tickets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- КОНЕЦ СХЕМЫ
-- ============================================================