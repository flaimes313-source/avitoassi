"""
Настройки пользователя (блок 13 ТЗ).

Меню настроек: часовой пояс, напоминания, приватность, удаление данных.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.database import db
from app.utils.keyboards import (
    CB,
    MENU,
    back_to_menu,
    delete_data_confirm,
    main_menu_reply,
    settings_menu,
)

router = Router(name="settings")


class SettingsStates(StatesGroup):
    waiting_timezone = State()
    waiting_delete_confirm = State()


# ============================================================
# ГЛАВНЫЙ ЭКРАН НАСТРОЕК
# ============================================================
@router.callback_query(F.data == CB.MENU_SETTINGS)
@router.message(F.text == MENU.SETTINGS)
async def show_settings(
    event: Message | CallbackQuery,
    user: dict | None,
) -> None:
    logger.info(f"show_settings: событие от {type(event).__name__}")

    if isinstance(event, CallbackQuery):
        message = event.message
        await event.answer()
    else:
        message = event

    if user is None:
        await message.answer("Ошибка: пользователь не найден. Напишите /start.")
        return

    tz = user.get("timezone") or "Europe/Moscow"
    reminder_days = user.get("reminder_interval_days")
    reminder_text = f"каждые {reminder_days} дн." if reminder_days else "отключены"

    text = (
        "⚙️ <b>Настройки и помощь</b>\n\n"
        f"🕐 Часовой пояс: <b>{tz}</b>\n"
        f"⏰ Напоминания: <b>{reminder_text}</b>\n\n"
        "Выбери раздел:"
    )

    await message.answer(text, reply_markup=settings_menu())


# ============================================================
# ЧАСОВОЙ ПОЯС
# ============================================================
@router.callback_query(F.data == CB.SET_TIMEZONE)
async def ask_timezone(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    if user is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    current = user.get("timezone") or "Europe/Moscow"

    await state.set_state(SettingsStates.waiting_timezone)
    await callback.message.answer(
        f"🕐 <b>Часовой пояс</b>\n\n"
        f"Сейчас: <b>{current}</b>\n\n"
        f"Пришли новый город или часовой пояс:\n"
        f"• <code>Москва</code>\n"
        f"• <code>Europe/Moscow</code>\n"
        f"• <code>Екатеринбург</code>\n"
        f"• <code>Asia/Novosibirsk</code>",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


# Карта городов → таймзон
CITY_TO_TZ = {
    "москва": "Europe/Moscow",
    "питер": "Europe/Moscow",
    "санкт-петербург": "Europe/Moscow",
    "спб": "Europe/Moscow",
    "казань": "Europe/Moscow",
    "екатеринбург": "Asia/Yekaterinburg",
    "новосибирск": "Asia/Novosibirsk",
    "красноярск": "Asia/Krasnoyarsk",
    "иркутск": "Asia/Irkutsk",
    "владивосток": "Asia/Vladivostok",
    "калининград": "Europe/Kaliningrad",
    "самара": "Europe/Samara",
    "омск": "Asia/Omsk",
    "хабаровск": "Asia/Vladivostok",
    "сочи": "Europe/Moscow",
}


@router.message(SettingsStates.waiting_timezone, F.text)
async def on_timezone_entered(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Пустое сообщение.")
        return

    # Резолвим
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    key = raw.lower().strip()
    tz_name = None

    if key in CITY_TO_TZ:
        tz_name = CITY_TO_TZ[key]
    else:
        try:
            ZoneInfo(raw)
            tz_name = raw
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            tz_name = None

    if not tz_name:
        await message.answer(
            "Не получилось распознать. Попробуй в формате "
            "«Europe/Moscow» или напиши «Москва»."
        )
        return

    await db.execute(
        "UPDATE users SET timezone = %s WHERE id = %s",
        (tz_name, user["id"]),
    )

    await state.clear()

    await message.answer(
        f"✅ Часовой пояс обновлён: <b>{tz_name}</b>",
        reply_markup=main_menu_reply(),
    )
    logger.info(f"Пользователь {user['telegram_id']}: timezone={tz_name}")


# ============================================================
# ЧТО ХРАНИТСЯ
# ============================================================
@router.callback_query(F.data == CB.SET_PRIVACY_INFO)
async def show_privacy_info(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "📄 <b>Что я храню и куда передаю</b>\n\n"
        "<b>Храню:</b>\n"
        "• Твой Telegram ID, имя, username\n"
        "• Часовой пояс\n"
        "• Тексты и фото объявлений\n"
        "• Статистику и историю работы с товарами\n"
        "• Идентификаторы платежей (без реквизитов карты)\n\n"
        "<b>Передаю внешним сервисам:</b>\n"
        "• <b>GigaChat</b> — тексты и фото для генерации\n"
        "• <b>ЮKassa</b> — сумму и ID платежа\n"
        "• <b>Telegram</b> — сами сообщения\n\n"
        "<b>НЕ храню:</b>\n"
        "• Пароли, номера карт, CVV\n"
        "• Оригиналы фото дольше 24 часов\n\n"
        "<b>Удаление данных:</b>\n"
        "В ⚙️ Настройках → «🗑 Удалить мои данные».",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


# ============================================================
# УДАЛЕНИЕ ДАННЫХ
# ============================================================
@router.callback_query(F.data == CB.SET_DELETE_DATA)
async def ask_delete_data(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.set_state(SettingsStates.waiting_delete_confirm)
    await callback.message.answer(
        "🗑 <b>Удаление данных</b>\n\n"
        "⚠️ Это действие <b>нельзя отменить</b>.\n\n"
        "Будут удалены:\n"
        "• Все твои товары\n"
        "• История объявлений\n"
        "• Статистика\n"
        "• Напоминания\n"
        "• История задач\n\n"
        "Аккаунт останется — но данные исчезнут.\n\n"
        "Подтвердить?",
        reply_markup=delete_data_confirm(),
    )
    await callback.answer()


@router.callback_query(F.data == CB.SET_DELETE_DATA_CONFIRM)
async def confirm_delete_data(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    if user is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    logger.warning(f"Пользователь {user['telegram_id']}: удаление данных")

    # Удаляем всё связанное (CASCADE сделает за нас)
    # items → listings, stats_entries, item_photos (CASCADE)
    # tasks → task_messages (CASCADE)
    # reminders (CASCADE)

    await db.execute("DELETE FROM items WHERE user_id = %s", (user["id"],))
    await db.execute("DELETE FROM tasks WHERE user_id = %s", (user["id"],))
    await db.execute("DELETE FROM reminders WHERE user_id = %s", (user["id"],))
    await db.execute("DELETE FROM competitors WHERE item_id IN (SELECT id FROM items WHERE user_id = %s)", (user["id"],))

    # Оставляем запись в users, но сбрасываем статистику
    await db.execute(
        """
        UPDATE users
        SET tariff = 'free',
            pro_expires_at = NULL,
            reminder_interval_days = NULL
        WHERE id = %s
        """,
        (user["id"],),
    )

    await state.clear()

    await callback.message.answer(
        "✅ <b>Все данные удалены</b>\n\n"
        "История товаров, статистика и напоминания стёрты.\n"
        "Тариф сброшен на Free.\n\n"
        "Можешь начать заново.",
        reply_markup=main_menu_reply(),
    )
    await callback.answer("Данные удалены")


# ============================================================
# ПОМОЩЬ
# ============================================================
@router.callback_query(F.data == CB.SET_HELP)
async def show_help(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "❓ <b>Помощь</b>\n\n"
        "Что я умею:\n"
        "• 📝 Создать объявление — 3 варианта по фото и тексту\n"
        "• 🛠 Улучшить объявление — разбор проблем\n"
        "• 🔍 Анализ конкурентов — сравнение и рекомендации\n"
        "• 📸 Помощь с фотографиями — Vision-анализ\n"
        "• 📈 Стратегия продвижения — пошаговый план\n"
        "• 💬 Ответы покупателям — вежливые ответы\n"
        "• 📂 Мои объявления — история и статистика\n"
        "• 💳 Тариф и подписка — лимиты и PRO\n"
        "• ⚙️ Настройки — часовой пояс, напоминания, удаление данных\n\n"
        "Если что-то не работает — 💬 Поддержка.",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


# ============================================================
# ОТМЕНА
# ============================================================
@router.callback_query(F.data == CB.CANCEL, SettingsStates.waiting_timezone)
@router.callback_query(F.data == CB.CANCEL, SettingsStates.waiting_delete_confirm)
async def cancel_settings(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.clear()
    try:
        await callback.message.edit_text("❌ Отменено.")
    except Exception:
        pass
    await callback.message.answer(
        "Возвращаю в главное меню.",
        reply_markup=main_menu_reply(),
    )
    await callback.answer("Отменено")