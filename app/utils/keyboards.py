"""
Все клавиатуры проекта.
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
# CALLBACK-КОНСТАНТЫ
# ============================================================
class CB:
    """Реестр callback_data — единый источник правды."""

    # ---- Главное меню ----
    MENU_MAIN = "menu:main"
    MENU_CREATE = "menu:create"
    MENU_IMPROVE = "menu:improve"
    MENU_COMPETITORS = "menu:competitors"
    MENU_PHOTOS = "menu:photos"
    MENU_STRATEGY = "menu:strategy"
    MENU_BUYER_REPLIES = "menu:buyer_replies"
    MENU_ITEMS = "menu:items"
    MENU_SUBSCRIPTION = "menu:subscription"
    MENU_SETTINGS = "menu:settings"

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

    # ---- Создание объявления ----
    CREATE_ADD_PHOTO = "create:add_photo"
    CREATE_ADD_TEXT = "create:add_text"
    CREATE_DONE_MATERIALS = "create:done_materials"
    CREATE_GENERATE = "create:generate"
    CREATE_PROCEED_AS_IS = "create:proceed_as_is"

    # Выбор варианта
    LISTING_PICK_1 = "listing:pick:1"
    LISTING_PICK_2 = "listing:pick:2"
    LISTING_PICK_3 = "listing:pick:3"
    LISTING_REGEN = "listing:regen"
    LISTING_EDIT = "listing:edit"
    LISTING_COPY = "listing:copy"
    LISTING_SAVE = "listing:save"

    # ---- Улучшение объявления ----
    IMPROVE_MATERIAL_TEXT = "improve:text"
    IMPROVE_MATERIAL_LINK = "improve:link"
    IMPROVE_MATERIAL_SCREEN = "improve:screenshot"
    IMPROVE_MATERIAL_STATS = "improve:stats"
    IMPROVE_READY = "improve:ready"

    IMPROVE_PROBLEM_LOW_VIEWS = "improve:problem:low_views"
    IMPROVE_PROBLEM_NO_FAVORITES = "improve:problem:no_favorites"
    IMPROVE_PROBLEM_NO_MESSAGES = "improve:problem:no_messages"
    IMPROVE_PROBLEM_NO_SALE = "improve:problem:no_sale"
    IMPROVE_PROBLEM_LONG = "improve:problem:long"
    IMPROVE_PROBLEM_FASTER = "improve:problem:faster"

    # ---- Анализ конкурентов ----
    COMPETITOR_ADD = "competitor:add"
    COMPETITOR_DONE = "competitor:done"
    COMPETITOR_RUN = "competitor:run"

    # ---- Фото ----
    PHOTOS_UPLOAD = "photos:upload"
    PHOTOS_ANALYZE = "photos:analyze"
    PHOTOS_DONE = "photos:done"

    # ---- Стратегия ----
    STRATEGY_RUN = "strategy:run"
    STRATEGY_CHECK_LATER = "strategy:later"

    # ---- Ответы покупателям ----
    REPLY_PASTE = "reply:paste"
    REPLY_GOAL_CONFIRM = "reply:goal:confirm"
    REPLY_GOAL_HAGGLE = "reply:goal:haggle"
    REPLY_GOAL_STATE = "reply:goal:state"
    REPLY_GOAL_MEET = "reply:goal:meet"
    REPLY_GOAL_REMIND = "reply:goal:remind"
    REPLY_GOAL_REFUSE = "reply:goal:refuse"
    REPLY_GOAL_NONE = "reply:goal:none"

    # ---- Мои объявления ----
    ITEMS_LIST = "items:list"
    ITEMS_STATS = "items:stats"
    ITEMS_HISTORY = "items:history"

    # ---- Тарифы ----
    SUB_SHOW_PRO = "sub:show_pro"
    SUB_PAY = "sub:pay"
    SUB_MY_STATUS = "sub:status"
    SUB_EXTEND = "sub:extend"

    # ---- Настройки ----
    SET_TIMEZONE = "settings:timezone"
    SET_REMINDERS = "settings:reminders"
    SET_PRIVACY_INFO = "settings:privacy"
    SET_DELETE_DATA = "settings:delete_data"
    SET_DELETE_DATA_CONFIRM = "settings:delete_data:confirm"
    SET_SUPPORT = "settings:support"
    SET_HELP = "settings:help"

    # ---- Напоминания ----
    REMIND_1D = "remind:1d"
    REMIND_3D = "remind:3d"
    REMIND_7D = "remind:7d"
    REMIND_OFF = "remind:off"

    # ---- Поддержка ----
    SUPPORT_NEW = "support:new"
    SUPPORT_LIST = "support:list"

    # ---- Админка ----
    ADMIN_PANEL = "admin:panel"
    ADMIN_BROADCAST = "admin:broadcast"
    ADMIN_TICKETS = "admin:tickets"
    ADMIN_STATS = "admin:stats"
    ADMIN_WHITELIST = "admin:whitelist"


# ============================================================
# ТЕКСТЫ КНОПОК ГЛАВНОГО МЕНЮ
# ============================================================
class MENU:
    CREATE = "📝 Создать"
    IMPROVE = "🛠 Улучшить"
    COMPETITORS = "🔍 Конкуренты"
    PHOTOS = "📸 Фото"
    STRATEGY = "📈 Стратегия"
    BUYER_REPLIES = "💬 Ответы"
    ITEMS = "📂 Мои"
    SUBSCRIPTION = "💳 Тариф"
    SETTINGS = "⚙️ Настройки"

    @classmethod
    def all_texts(cls) -> set[str]:
        """Множество всех текстов меню — для фильтра-исключения."""
        return {
            cls.CREATE, cls.IMPROVE, cls.COMPETITORS,
            cls.PHOTOS, cls.STRATEGY, cls.BUYER_REPLIES,
            cls.ITEMS, cls.SUBSCRIPTION, cls.SETTINGS,
        }


# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def btn(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def btn_url(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


# ============================================================
# ГЛАВНОЕ МЕНЮ (2 кнопки в ряд)
# ============================================================
def main_menu_reply() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text=MENU.CREATE), KeyboardButton(text=MENU.IMPROVE)],
        [KeyboardButton(text=MENU.COMPETITORS), KeyboardButton(text=MENU.PHOTOS)],
        [KeyboardButton(text=MENU.STRATEGY), KeyboardButton(text=MENU.BUYER_REPLIES)],
        [KeyboardButton(text=MENU.ITEMS), KeyboardButton(text=MENU.SUBSCRIPTION)],
        [KeyboardButton(text=MENU.SETTINGS)],
    ]
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите раздел…",
    )


def main_menu_inline() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("📝 Создать", CB.MENU_CREATE), btn("🛠 Улучшить", CB.MENU_IMPROVE))
    builder.row(btn("🔍 Конкуренты", CB.MENU_COMPETITORS), btn("📸 Фото", CB.MENU_PHOTOS))
    builder.row(btn("📈 Стратегия", CB.MENU_STRATEGY), btn("💬 Ответы", CB.MENU_BUYER_REPLIES))
    builder.row(btn("📂 Мои", CB.MENU_ITEMS), btn("💳 Тариф", CB.MENU_SUBSCRIPTION))
    builder.row(btn("⚙️ Настройки", CB.MENU_SETTINGS))
    return builder.as_markup()


# ============================================================
# НАВИГАЦИЯ
# ============================================================
def back_to_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


def back_to_settings() -> InlineKeyboardMarkup:
    """Возврат в настройки (для разделов внутри настроек)."""
    builder = InlineKeyboardBuilder()
    builder.row(btn("🔙 К настройкам", CB.MENU_SETTINGS))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


def cancel_and_back() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("❌ Отменить", CB.CANCEL), btn("🏠 В меню", CB.MENU_MAIN))
    return builder.as_markup()


def confirm_keyboard(yes_text: str = "✅ Да", no_text: str = "❌ Нет") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn(yes_text, CB.CONFIRM_YES), btn(no_text, CB.CONFIRM_NO))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


def remove_reply_keyboard() -> ReplyKeyboardRemove:
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
def create_listing_start() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("📸 Добавить фото", CB.CREATE_ADD_PHOTO))
    builder.row(btn("✏️ Добавить текст", CB.CREATE_ADD_TEXT))
    builder.row(btn("✅ Материалов достаточно", CB.CREATE_DONE_MATERIALS))
    builder.row(btn("❌ Отменить", CB.CANCEL))
    return builder.as_markup()


def create_listing_after_photo() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("✏️ Добавить текст", CB.CREATE_ADD_TEXT))
    builder.row(btn("✅ Материалов достаточно", CB.CREATE_DONE_MATERIALS))
    builder.row(btn("❌ Отменить", CB.CANCEL))
    return builder.as_markup()


def create_listing_ready() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("⚡ Сгенерировать", CB.CREATE_GENERATE))
    builder.row(btn("📸 Ещё фото", CB.CREATE_ADD_PHOTO), btn("✏️ Ещё текст", CB.CREATE_ADD_TEXT))
    builder.row(btn("❌ Отменить", CB.CANCEL))
    return builder.as_markup()


def create_listing_question() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("🤷 Не знаю", CB.DONT_KNOW), btn("⏭ Пропустить", CB.SKIP))
    builder.row(btn("⚡ Хватит вопросов", CB.CREATE_PROCEED_AS_IS))
    builder.row(btn("❌ Отменить", CB.CANCEL))
    return builder.as_markup()


def listing_variants() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("1️⃣ Фактический", CB.LISTING_PICK_1))
    builder.row(btn("2️⃣ Дружелюбный", CB.LISTING_PICK_2))
    builder.row(btn("3️⃣ Альтернативный", CB.LISTING_PICK_3))
    builder.row(btn("🔄 Перегенерировать", CB.LISTING_REGEN))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


def listing_after_pick() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("✏️ Редактировать", CB.LISTING_EDIT))
    builder.row(btn("🔄 Перегенерировать", CB.LISTING_REGEN))
    builder.row(btn("📋 Показать ещё раз", CB.LISTING_COPY))
    builder.row(btn("📈 Стратегия", CB.MENU_STRATEGY))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


def listing_after_edit() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("✏️ Редактировать ещё", CB.LISTING_EDIT))
    builder.row(btn("🔄 Перегенерировать", CB.LISTING_REGEN))
    builder.row(btn("📈 Стратегия", CB.MENU_STRATEGY))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


# ============================================================
# УЛУЧШЕНИЕ ОБЪЯВЛЕНИЯ (блок 4)
# ============================================================
def improve_materials() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("📝 Добавить текст", CB.IMPROVE_MATERIAL_TEXT))
    builder.row(btn("🔗 Добавить ссылку", CB.IMPROVE_MATERIAL_LINK))
    builder.row(btn("📸 Добавить скриншоты", CB.IMPROVE_MATERIAL_SCREEN))
    builder.row(btn("📊 Добавить статистику", CB.IMPROVE_MATERIAL_STATS))
    builder.row(btn("✅ Материалов достаточно", CB.IMPROVE_READY))
    builder.row(btn("❌ Отменить", CB.CANCEL))
    return builder.as_markup()


def improve_problems() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("👁 Мало просмотров", CB.IMPROVE_PROBLEM_LOW_VIEWS))
    builder.row(btn("⭐ Мало избранного", CB.IMPROVE_PROBLEM_NO_FAVORITES))
    builder.row(btn("💬 Нет сообщений", CB.IMPROVE_PROBLEM_NO_MESSAGES))
    builder.row(btn("🤝 Нет продажи", CB.IMPROVE_PROBLEM_NO_SALE))
    builder.row(btn("⏳ Долго не продаётся", CB.IMPROVE_PROBLEM_LONG))
    builder.row(btn("⚡ Продать быстрее", CB.IMPROVE_PROBLEM_FASTER))
    builder.row(btn("❌ Отменить", CB.CANCEL))
    return builder.as_markup()


# ============================================================
# АНАЛИЗ КОНКУРЕНТОВ (блок 5)
# ============================================================
def competitors_collect() -> InlineKeyboardMarkup:
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
# КАРТОЧКА ТОВАРА (блок 9) — возврат к товару после действия
# ============================================================
def item_after_action(item_id: int) -> InlineKeyboardMarkup:
    """Кнопки после действия с товаром — вернуться к карточке."""
    builder = InlineKeyboardBuilder()
    builder.row(btn("🔙 К карточке товара", f"item:view:{item_id}"))
    builder.row(btn("📂 К списку товаров", CB.MENU_ITEMS))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


# ============================================================
# ТАРИФЫ
# ============================================================
def subscription_menu(is_pro: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_pro:
        builder.row(btn("📊 Мой статус", CB.SUB_MY_STATUS))
        builder.row(btn("🔄 Продлить PRO", CB.SUB_EXTEND))
    else:
        builder.row(btn("⭐ Перейти на PRO", CB.SUB_SHOW_PRO))
        builder.row(btn("📊 Мой лимит", CB.SUB_MY_STATUS))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


def subscription_pro_offer(price: int = 490) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn(f"💳 Оплатить {price} ₽", CB.SUB_PAY))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


# ============================================================
# НАСТРОЙКИ
# ============================================================
def settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("🕐 Часовой пояс", CB.SET_TIMEZONE))
    builder.row(btn("⏰ Напоминания", CB.SET_REMINDERS))
    builder.row(btn("📄 Что хранится", CB.SET_PRIVACY_INFO))
    builder.row(btn("🗑 Удалить данные", CB.SET_DELETE_DATA))
    builder.row(btn("💬 Поддержка", CB.SET_SUPPORT))
    builder.row(btn("❓ Помощь", CB.SET_HELP))
    builder.row(btn("🏠 В главное меню", CB.MENU_MAIN))
    return builder.as_markup()


def delete_data_confirm() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("🗑 Да, удалить всё", CB.SET_DELETE_DATA_CONFIRM))
    builder.row(btn("❌ Отмена", CB.MENU_SETTINGS))
    return builder.as_markup()


# ============================================================
# НАПОМИНАНИЯ
# ============================================================
def reminders_menu(current_enabled: bool, current_interval: int | None) -> InlineKeyboardMarkup:
    """
    Клавиатура настроек напоминаний.
    Кнопка «В меню» ведёт в НАСТРОЙКИ, а не в главное меню.
    """
    def mark(text: str, val: int) -> str:
        return f"✅ {text}" if current_interval == val and current_enabled else text

    builder = InlineKeyboardBuilder()
    builder.row(btn(mark("Через 1 день", 1), CB.REMIND_1D))
    builder.row(btn(mark("Через 3 дня", 3), CB.REMIND_3D))
    builder.row(btn(mark("Через 7 дней", 7), CB.REMIND_7D))
    builder.row(btn(
        "🔕 Отключить напоминания" if current_enabled else "🔔 Включить напоминания",
        CB.REMIND_OFF if current_enabled else CB.REMIND_3D,
    ))
    builder.row(btn("🔙 К настройкам", CB.MENU_SETTINGS))
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
    builder.row(btn("🎁 Белый список", CB.ADMIN_WHITELIST))
    builder.row(btn("🎫 Тикеты поддержки", CB.ADMIN_TICKETS))
    builder.row(btn("📢 Рассылка", CB.ADMIN_BROADCAST))
    builder.row(btn("📊 Статистика", CB.ADMIN_STATS))
    return builder.as_markup()


def admin_whitelist_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("➕ Добавить", "admin:wl:add"))
    builder.row(btn("➖ Удалить", "admin:wl:remove"))
    builder.row(btn("🔙 Назад", CB.ADMIN_PANEL))
    return builder.as_markup()