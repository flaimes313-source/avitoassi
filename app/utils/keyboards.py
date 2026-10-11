"""
Все клавиатуры проекта.

Соглашения:
- callback_data: короткие латинские идентификаторы без пробелов
- Reply-клавиатуры используются только для главного меню и запроса телефона
- Inline-клавиатуры — везде остальное
"""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ============================================================
# CALLBACK-КОНСТАНТЫ (реестр всех callback_data)
# ============================================================
class CB:
    """Реестр callback_data — единый источник правды."""

    # ---- Главное меню (блок 2 ТЗ) ----
    MENU_MAIN = "menu:main"

    MENU_CREATE = "menu:create"                # 📝 Создать объявление
    MENU_IMPROVE = "menu:improve"              # 🛠 Улучшить объявление
    MENU_COMPETITORS = "menu:competitors"      # 🔍 Анализ конкурентов
    MENU_PHOTOS = "menu:photos"                # 📸 Помощь с фотографиями
    MENU_STRATEGY = "menu:strategy"            # 📈 Стратегия продвижения
    MENU_BUYER_REPLIES = "menu:buyer_replies"  # 💬 Ответы покупателям
    MENU_ITEMS = "menu:items"                  # 📂 Мои объявления и история
    MENU_SUBSCRIPTION = "menu:subscription"    # 💳 Тариф и подписка
    MENU_SETTINGS = "menu:settings"            # ⚙️ Настройки и помощь

    # ---- Навигация ----
    BACK = "nav:back"
    CANCEL = "nav:cancel"
    CONFIRM_YES = "nav:confirm:yes"
    CONFIRM_NO = "nav:confirm:no"
    SKIP = "nav:skip"
    DONT_KNOW = "nav:dont_know"

    # ---- Онбординг ----
    ONBOARD_START = "onboard:start"
    ONBOARD_ACCEPT_PRIVACY = "onboard:privacy:accept"

    # ---- Работа с задачами ----
    TASK_CONTINUE = "task:continue"
    TASK_NEW = "task:new"
    TASK_ABORT = "task:abort"

    # ---- Создание объявления (блок 3) ----
    CREATE_ADD_PHOTO = "create:add_photo"
    CREATE_DONE_MATERIALS = "create:done_materials"
    CREATE_GENERATE = "create:generate"

    # ---- Улучшение объявления (блок 4) ----
    IMPROVE_MATERIAL_TEXT = "improve:text"
    IMPROVE_MATERIAL_LINK = "improve:link"
    IMPROVE_MATERIAL_SCREEN = "improve:screenshot"
    IMPROVE_MATERIAL_STATS = "improve:stats"

    # Диагностика проблемы (блок 4)
    IMPROVE_PROBLEM_LOW_VIEWS = "improve:problem:low_views"
    IMPROVE_PROBLEM_NO_FAVORITES = "improve:problem:no_favorites"
    IMPROVE_PROBLEM_NO_MESSAGES = "improve:problem:no_messages"
    IMPROVE_PROBLEM_NO_SALE = "improve:problem:no_sale"
    IMPROVE_PROBLEM_LONG = "improve:problem:long"
    IMPROVE_PROBLEM_FASTER = "improve:problem:faster"

    # ---- Анализ конкурентов (блок 5) ----
    COMPETITOR_ADD = "competitor:add"
    COMPETITOR_DONE = "competitor:done"
    COMPETITOR_RUN = "competitor:run"

    # ---- Фото (блок 6) ----
    PHOTOS_UPLOAD = "photos:upload"
    PHOTOS_ANALYZE = "photos:analyze"
    PHOTOS_DONE = "photos:done"

    # ---- Стратегия (блок 7) ----
    STRATEGY_RUN = "strategy:run"
    STRATEGY_CHECK_LATER = "strategy:later"

    # ---- Ответы покупателям (блок 8) ----
    REPLY_PASTE = "reply:paste"
    REPLY_GOAL_CONFIRM = "reply:goal:confirm"
    REPLY_GOAL_HAGGLE = "reply:goal:haggle"
    REPLY_GOAL_STATE = "reply:goal:state"
    REPLY_GOAL_MEET = "reply:goal:meet"
    REPLY_GOAL_REMIND = "reply:goal:remind"
    REPLY_GOAL_REFUSE = "reply:goal:refuse"
    REPLY_GOAL_NONE = "reply:goal:none"

    # ---- Мои объявления (блок 9) ----
    ITEMS_LIST = "items:list"
    ITEMS_STATS = "items:stats"
    ITEMS_HISTORY = "items:history"

    # ---- Тарифы (блоки 11–12) ----
    SUB_SHOW_PRO = "sub:show_pro"
    SUB_PAY = "sub:pay"
    SUB_MY_STATUS = "sub:status"
    SUB_EXTEND = "sub:extend"

    # ---- Настройки ----
    SET_TIMEZONE = "settings:timezone"
    SET_REMINDERS = "settings:reminders"
    SET_LANGUAGE = "settings:language"
    SET_PRIVACY_INFO = "settings:privacy"
    SET_DELETE_DATA = "settings:delete_data"
    SET_SUPPORT = "settings:support"
    SET_HELP = "settings:help"

    # ---- Напоминания (блок 10) ----
    REMIND_1D = "remind:1d"
    REMIND_3D = "remind:3d"
    REMIND_7D = "remind:7d"
    REMIND_OFF = "remind:off"

    # ---- Поддержка (тикеты) ----
    SUPPORT_NEW = "support:new"
    SUPPORT_LIST = "support:list"

    # ---- Админка ----
    ADMIN_PANEL = "admin:panel"
    ADMIN_BROADCAST = "admin:broadcast"
    ADMIN_TICKETS = "admin:tickets"
    ADMIN_STATS = "admin:stats"


# ============================================================
# ОБЩИЕ ЭЛЕМЕНТЫ
# ============================================================
def btn(text: str, callback_data: str) -> InlineKeyboardButton:
    """Короткий хелпер для создания кнопки."""
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def btn_url(text: str, url: str) -> InlineKeyboardButton:
    """Кнопка-ссылка."""
    return InlineKeyboardButton(text=text, url=url)


# ============================================================
# ГЛАВНОЕ МЕНЮ (Reply-клавиатура)
# ============================================================
def main_menu_reply() -> ReplyKeyboardMarkup:
    """
    Постоянная Reply-клавиатура с главными действиями.
    Согласно блоку 2 ТЗ — 9 кнопок в сетке 2×5.
    """
    kb = [
        [KeyboardButton(text="📝 Создать объявление")],
        [KeyboardButton(text="🛠 Улучшить объявление")],
        [KeyboardButton(text="🔍 Анализ конкурентов")],
        [KeyboardButton(text="📸 Помощь с фотографиями")],
        [KeyboardButton(text="📈 Стратегия продвижения")],
        [KeyboardButton(text="💬 Ответы покупателям")],
        [KeyboardButton(text="📂 Мои объявления")],
        [KeyboardButton(text="💳 Тариф и подписка")],
        [KeyboardButton(text="⚙️ Настройки и помощь")],
    ]
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите раздел…",
    )


def main_menu_inline() -> InlineKeyboardMarkup:
    """
    Inline-версия главного меню (для сообщений в каналах,
    для возврата назад, для inline-режима).
    """
    builder = InlineKeyboardBuilder()
    builder.row(btn("📝 Создать объявление", CB.MENU_CREATE))
    builder.row(btn("🛠 Улучшить объявление", CB.MENU_IMPROVE))
    builder.row(btn("🔍 Анализ конкурентов", CB.MENU_COMPETITORS))
    builder.row(btn("📸 Помощь с фотографиями", CB.MENU_PHOTOS))
    builder.row(btn("📈 Стратегия продвижения", CB.MENU_STRATEGY))
    builder.row(btn("💬 Ответы покупателям", CB.MENU_BUYER_REPLIES))
    builder.row(btn("📂 Мои объявления и история", CB.MENU_ITEMS))
    builder.row(btn("💳 Тариф и подписка", CB.MENU_SUBSCRIPTION))
    builder.row(btn("⚙️ Настройки и помощь", CB.MENU_SETTINGS))
    return builder.as_markup()


# ============================================================
# НАВИГАЦИЯ
# ============================================================
def back_to_menu() -> InlineKeyboardMarkup:
    """Кнопка «Назад в меню»."""
    builder = InlineKeyboardBuilder()
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


def cancel_and_back() -> InlineKeyboardMarkup:
    """Кнопки «Отменить» и «В меню»."""
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("❌ Отменить", CB.CANCEL),
        btn("🏠 В меню", CB.MENU_MAIN),
    )
    return builder.as_markup()


def confirm_keyboard(yes_text: str = "✅ Да", no_text: str = "❌ Нет") -> InlineKeyboardMarkup:
    """Универсальная клавиатура подтверждения."""
    builder = InlineKeyboardBuilder()
    builder.row(
        btn(yes_text, CB.CONFIRM_YES),
        btn(no_text, CB.CONFIRM_NO),
    )
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


def skip_or_answer() -> InlineKeyboardMarkup:
    """
    Кнопки «Не знаю» и «Пропустить» для вопросов интервью
    (блок 3 ТЗ).
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("🤷 Не знаю", CB.DONT_KNOW),
        btn("⏭ Пропустить", CB.SKIP),
    )
    builder.row(btn("❌ Отменить", CB.CANCEL))
    return builder.as_markup()


def remove_reply_keyboard() -> ReplyKeyboardRemove:
    """Убирает Reply-клавиатуру."""
    return ReplyKeyboardRemove()


# ============================================================
# ОНБОРДИНГ
# ============================================================
def onboarding_start() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("🚀 Начать", CB.ONBOARD_START))
    return builder.as_markup()


def onboarding_privacy() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("✅ Принимаю", CB.ONBOARD_ACCEPT_PRIVACY))
    builder.row(btn("📄 Что хранится?", CB.SET_PRIVACY_INFO))
    return builder.as_markup()


# ============================================================
# СОЗДАНИЕ ОБЪЯВЛЕНИЯ (блок 3)
# ============================================================
def create_listing_actions() -> InlineKeyboardMarkup:
    """Действия во время сбора материалов."""
    builder = InlineKeyboardBuilder()
    builder.row(btn("📸 Добавить фото", CB.CREATE_ADD_PHOTO))
    builder.row(btn("✅ Материалов достаточно", CB.CREATE_DONE_MATERIALS))
    builder.row(btn("❌ Отменить", CB.CANCEL))
    return builder.as_markup()


def create_listing_generate() -> InlineKeyboardMarkup:
    """Кнопка запуска генерации."""
    builder = InlineKeyboardBuilder()
    builder.row(btn("⚡ Сгенерировать объявления", CB.CREATE_GENERATE))
    builder.row(
        btn("📸 Ещё фото", CB.CREATE_ADD_PHOTO),
        btn("❌ Отменить", CB.CANCEL),
    )
    return builder.as_markup()


def listing_variants() -> InlineKeyboardMarkup:
    """
    Выбор одного из 3 сгенерированных вариантов.
    Варианты: фактический, дружелюбный, альтернативный.
    """
    builder = InlineKeyboardBuilder()
    builder.row(btn("1️⃣ Фактический", "listing:pick:1"))
    builder.row(btn("2️⃣ Дружелюбный", "listing:pick:2"))
    builder.row(btn("3️⃣ Альтернативный", "listing:pick:3"))
    builder.row(
        btn("🔄 Перегенерировать", "listing:regen"),
        btn("✏️ Редактировать", "listing:edit"),
    )
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


def listing_after_pick() -> InlineKeyboardMarkup:
    """Действия после выбора варианта."""
    builder = InlineKeyboardBuilder()
    builder.row(btn("📋 Скопировать ещё раз", "listing:copy"))
    builder.row(btn("💾 Сохранить в карточку", "listing:save"))
    builder.row(btn("📈 Стратегия продвижения", CB.MENU_STRATEGY))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


# ============================================================
# УЛУЧШЕНИЕ ОБЪЯВЛЕНИЯ (блок 4)
# ============================================================
def improve_materials() -> InlineKeyboardMarkup:
    """Что прислать для анализа."""
    builder = InlineKeyboardBuilder()
    builder.row(btn("📝 Текст объявления", CB.IMPROVE_MATERIAL_TEXT))
    builder.row(btn("🔗 Ссылку на объявление", CB.IMPROVE_MATERIAL_LINK))
    builder.row(btn("📸 Скриншоты", CB.IMPROVE_MATERIAL_SCREEN))
    builder.row(btn("📊 Статистику", CB.IMPROVE_MATERIAL_STATS))
    builder.row(btn("❌ Отменить", CB.CANCEL))
    return builder.as_markup()


def improve_problems() -> InlineKeyboardMarkup:
    """Диагностика: что именно не получается (блок 4 ТЗ)."""
    builder = InlineKeyboardBuilder()
    builder.row(btn("👁 Мало просмотров", CB.IMPROVE_PROBLEM_LOW_VIEWS))
    builder.row(btn("⭐ Просмотры есть, мало избранного", CB.IMPROVE_PROBLEM_NO_FAVORITES))
    builder.row(btn("💬 Избранное есть, нет сообщений", CB.IMPROVE_PROBLEM_NO_MESSAGES))
    builder.row(btn("🤝 Сообщения есть, продажи нет", CB.IMPROVE_PROBLEM_NO_SALE))
    builder.row(btn("⏳ Объявление долго не продаётся", CB.IMPROVE_PROBLEM_LONG))
    builder.row(btn("⚡ Нужно продать быстрее", CB.IMPROVE_PROBLEM_FASTER))
    builder.row(btn("❌ Отменить", CB.CANCEL))
    return builder.as_markup()


# ============================================================
# АНАЛИЗ КОНКУРЕНТОВ (блок 5)
# ============================================================
def competitors_collect() -> InlineKeyboardMarkup:
    """Сбор конкурентов — от 1 до 5."""
    builder = InlineKeyboardBuilder()
    builder.row(btn("➕ Добавить ещё", CB.COMPETITOR_ADD))
    builder.row(btn("▶️ Запустить анализ", CB.COMPETITOR_RUN))
    builder.row(btn("❌ Отменить", CB.CANCEL))
    return builder.as_markup()


# ============================================================
# ФОТО (блок 6)
# ============================================================
def photos_actions() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("📸 Загрузить фото", CB.PHOTOS_UPLOAD))
    builder.row(btn("🔍 Анализировать", CB.PHOTOS_ANALYZE))
    builder.row(btn("✅ Готово", CB.PHOTOS_DONE))
    builder.row(btn("❌ Отменить", CB.CANCEL))
    return builder.as_markup()


# ============================================================
# СТРАТЕГИЯ (блок 7)
# ============================================================
def strategy_actions() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("▶️ Получить план", CB.STRATEGY_RUN))
    builder.row(btn("⏰ Напомнить позже", CB.STRATEGY_CHECK_LATER))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


# ============================================================
# ОТВЕТЫ ПОКУПАТЕЛЯМ (блок 8)
# ============================================================
def buyer_reply_goals() -> InlineKeyboardMarkup:
    """Необязательная цель ответа (блок 8 ТЗ)."""
    builder = InlineKeyboardBuilder()
    builder.row(btn("✅ Подтвердить актуальность", CB.REPLY_GOAL_CONFIRM))
    builder.row(btn("💰 Обсудить торг", CB.REPLY_GOAL_HAGGLE))
    builder.row(btn("📦 Объяснить состояние", CB.REPLY_GOAL_STATE))
    builder.row(btn("📍 Договориться о встрече", CB.REPLY_GOAL_MEET))
    builder.row(btn("🔔 Напомнить о себе", CB.REPLY_GOAL_REMIND))
    builder.row(btn("🚫 Вежливо отказать", CB.REPLY_GOAL_REFUSE))
    builder.row(btn("⏭ Без цели", CB.REPLY_GOAL_NONE))
    return builder.as_markup()


# ============================================================
# ТАРИФЫ (блоки 11–12)
# ============================================================
def subscription_menu(is_pro: bool) -> InlineKeyboardMarkup:
    """Меню тарифа — меняется в зависимости от статуса."""
    builder = InlineKeyboardBuilder()
    if is_pro:
        builder.row(btn("📊 Мой статус", CB.SUB_MY_STATUS))
        builder.row(btn("🔄 Продлить PRO", CB.SUB_EXTEND))
    else:
        builder.row(btn("⭐ Перейти на PRO", CB.SUB_SHOW_PRO))
        builder.row(btn("📊 Мой лимит", CB.SUB_MY_STATUS))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


def subscription_pro_offer() -> InlineKeyboardMarkup:
    """Оффер PRO."""
    builder = InlineKeyboardBuilder()
    builder.row(btn("💳 Оплатить 490 ₽", CB.SUB_PAY))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


# ============================================================
# НАСТРОЙКИ (блок 13 + настройки)
# ============================================================
def settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("🕐 Часовой пояс", CB.SET_TIMEZONE))
    builder.row(btn("⏰ Напоминания", CB.SET_REMINDERS))
    builder.row(btn("📄 Что хранится обо мне", CB.SET_PRIVACY_INFO))
    builder.row(btn("🗑 Удалить мои данные", CB.SET_DELETE_DATA))
    builder.row(btn("💬 Поддержка", CB.SET_SUPPORT))
    builder.row(btn("❓ Помощь", CB.SET_HELP))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


def delete_data_confirm() -> InlineKeyboardMarkup:
    """Двойное подтверждение удаления (блок 13 ТЗ)."""
    builder = InlineKeyboardBuilder()
    builder.row(btn("🗑 Да, удалить всё", "settings:delete_data:confirm"))
    builder.row(btn("❌ Отмена", CB.MENU_SETTINGS))
    return builder.as_markup()


# ============================================================
# НАПОМИНАНИЯ (блок 10)
# ============================================================
def reminders_menu(current_enabled: bool, current_interval: int | None) -> InlineKeyboardMarkup:
    """Выбор интервала напоминаний."""
    def mark(text: str, val: int) -> str:
        return f"✅ {text}" if current_interval == val and current_enabled else text

    builder = InlineKeyboardBuilder()
    builder.row(btn(mark("Через 1 день", 1), CB.REMIND_1D))
    builder.row(btn(mark("Через 3 дня", 3), CB.REMIND_3D))
    builder.row(btn(mark("Через 7 дней", 7), CB.REMIND_7D))
    builder.row(btn(
        "🔕 Отключить напоминания" if current_enabled else "🔔 Включить (через 3 дня)",
        CB.REMIND_OFF if current_enabled else CB.REMIND_3D,
    ))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


# ============================================================
# ПОДДЕРЖКА
# ============================================================
def support_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("✉️ Написать в поддержку", CB.SUPPORT_NEW))
    builder.row(btn("📬 Мои обращения", CB.SUPPORT_LIST))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


# ============================================================
# АДМИНКА
# ============================================================
def admin_panel() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("🎫 Тикеты поддержки", CB.ADMIN_TICKETS))
    builder.row(btn("📢 Рассылка", CB.ADMIN_BROADCAST))
    builder.row(btn("📊 Статистика", CB.ADMIN_STATS))
    return builder.as_markup()