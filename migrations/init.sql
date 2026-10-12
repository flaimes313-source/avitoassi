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

    tariff              TEXT NOT NULL DEFAULT 'free'
                        CHECK (tariff IN ('free', 'pro')),

    pro_expires_at      TIMESTAMPTZ,

    timezone            TEXT NOT NULL DEFAULT 'Europe/Moscow',

    onboarded           BOOLEAN NOT NULL DEFAULT FALSE,

    bot_blocked         BOOLEAN NOT NULL DEFAULT FALSE,

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

    name                TEXT NOT NULL,

    confirmed_specs     JSONB NOT NULL DEFAULT '{}'::jsonb,

    current_price       INTEGER,

    price_history       JSONB NOT NULL DEFAULT '[]'::jsonb,

    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'sold', 'archived')),

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

    item_id             BIGINT REFERENCES items(id) ON DELETE SET NULL,

    task_type           TEXT NOT NULL
                        CHECK (task_type IN (
                            'create_listing',
                            'improve_listing',
                            'competitors',
                            'photos',
                            'strategy',
                            'buyer_reply'
                        )),

    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'done', 'failed', 'cancelled')),

    limit_charged       BOOLEAN NOT NULL DEFAULT FALSE,

    technical_failure   BOOLEAN NOT NULL DEFAULT FALSE,

    collected_data      JSONB NOT NULL DEFAULT '{}'::jsonb,

    result              JSONB,

    meta                JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_active ON tasks(user_id, task_type)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);

-- ============================================================
-- СООБЩЕНИЯ ДИАЛОГА ВНУТРИ ЗАДАЧИ
-- ============================================================
CREATE TABLE IF NOT EXISTS task_messages (
    id                  BIGSERIAL PRIMARY KEY,
    task_id             BIGINT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,

    role                TEXT NOT NULL CHECK (role IN ('user', 'assistant')),

    content             TEXT NOT NULL,

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

    version             INTEGER NOT NULL DEFAULT 1,

    approach            TEXT NOT NULL DEFAULT 'factual'
                        CHECK (approach IN ('factual', 'friendly', 'alternative')),

    title               TEXT NOT NULL,
    body                TEXT NOT NULL,

    is_selected         BOOLEAN NOT NULL DEFAULT FALSE,

    was_copied          BOOLEAN NOT NULL DEFAULT FALSE,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_listings_item ON listings(item_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_listings_selected ON listings(item_id)
    WHERE is_selected = TRUE;

-- ============================================================
-- ФОТОГРАФИИ ТОВАРА
-- ============================================================
CREATE TABLE IF NOT EXISTS item_photos (
    id                  BIGSERIAL PRIMARY KEY,
    item_id             BIGINT NOT NULL REFERENCES items(id) ON DELETE CASCADE,

    telegram_file_id    TEXT NOT NULL,

    telegram_file_unique_id TEXT,

    file_size           INTEGER,
    width               INTEGER,
    height              INTEGER,

    sort_order          INTEGER NOT NULL DEFAULT 0,

    ai_analysis         JSONB,

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

    source_type         TEXT NOT NULL
                        CHECK (source_type IN ('link', 'screenshot', 'text')),

    url                 TEXT,

    content             TEXT,

    screenshots         JSONB NOT NULL DEFAULT '[]'::jsonb,

    is_accessible       BOOLEAN,

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

    views               INTEGER,
    favorites           INTEGER,
    messages            INTEGER,

    outcome             TEXT CHECK (outcome IN ('in_progress', 'sold', 'no_result')),

    price_at_entry      INTEGER,

    note                TEXT,

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

    reminder_type       TEXT NOT NULL
                        CHECK (reminder_type IN (
                            'follow_up',
                            'stats_check',
                            'subscription_expiring'
                        )),

    run_at              TIMESTAMPTZ NOT NULL,

    custom_text         TEXT,

    enabled             BOOLEAN NOT NULL DEFAULT TRUE,

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

    yookassa_payment_id TEXT UNIQUE NOT NULL,

    idempotency_key     TEXT UNIQUE NOT NULL,

    amount              NUMERIC(10, 2) NOT NULL,
    currency            TEXT NOT NULL DEFAULT 'RUB',

    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'succeeded', 'canceled', 'refunded')),

    product             TEXT NOT NULL DEFAULT 'pro_30d',

    pro_days            INTEGER NOT NULL DEFAULT 30,

    raw_response        JSONB,

    activated_at        TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)
    WHERE status = 'pending';

-- ============================================================
-- ТИКЕТЫ ПОДДЕРЖКИ
-- ============================================================
CREATE TABLE IF NOT EXISTS support_tickets (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    subject             TEXT NOT NULL,

    status              TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'in_progress', 'closed')),

    last_reply_by       TEXT CHECK (last_reply_by IN ('user', 'admin')),

    unread_by_user      INTEGER NOT NULL DEFAULT 0,
    unread_by_admin     INTEGER NOT NULL DEFAULT 0,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tickets_user ON support_tickets(user_id, status);
CREATE INDEX IF NOT EXISTS idx_tickets_open ON support_tickets(status, updated_at DESC)
    WHERE status <> 'closed';

CREATE TABLE IF NOT EXISTS support_messages (
    id                  BIGSERIAL PRIMARY KEY,
    ticket_id           BIGINT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,

    sender              TEXT NOT NULL CHECK (sender IN ('user', 'admin')),

    admin_telegram_id   BIGINT,

    content             TEXT NOT NULL,

    attachments         JSONB NOT NULL DEFAULT '[]'::jsonb,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_support_messages_ticket
    ON support_messages(ticket_id, created_at);

-- ============================================================
-- РАССЫЛКИ
-- ============================================================
CREATE TABLE IF NOT EXISTS broadcasts (
    id                  BIGSERIAL PRIMARY KEY,

    title               TEXT NOT NULL,

    message_text        TEXT NOT NULL,

    media               JSONB,

    status              TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'scheduled', 'running', 'done', 'cancelled')),

    audience_filter     JSONB NOT NULL DEFAULT '{}'::jsonb,

    scheduled_at        TIMESTAMPTZ,

    total_recipients    INTEGER NOT NULL DEFAULT 0,
    sent_count          INTEGER NOT NULL DEFAULT 0,
    failed_count        INTEGER NOT NULL DEFAULT 0,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_broadcasts_status ON broadcasts(status, scheduled_at);

-- ============================================================
-- АУДИТ
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT REFERENCES users(id) ON DELETE SET NULL,

    event_type          TEXT NOT NULL,

    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,

    ip_address          TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at DESC);

-- ============================================================
-- ТРИГГЕР: обновление updated_at
-- ============================================================
-- Postgres не поддерживает CREATE TRIGGER IF NOT EXISTS,
-- поэтому используем DROP TRIGGER IF EXISTS + CREATE.
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_items_updated_at ON items;
CREATE TRIGGER trg_items_updated_at
    BEFORE UPDATE ON items
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_payments_updated_at ON payments;
CREATE TRIGGER trg_payments_updated_at
    BEFORE UPDATE ON payments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_tickets_updated_at ON support_tickets;
CREATE TRIGGER trg_tickets_updated_at
    BEFORE UPDATE ON support_tickets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- КОНЕЦ СХЕМЫ
-- ============================================================