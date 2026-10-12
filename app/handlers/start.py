"""
Хендлер /start и онбординг.

Сценарий:
1. Новый пользователь → приветствие → согласие на обработку данных →
   выбор часового пояса → главное меню.
2. Существующий, но не завершивший онбординг → продолжаем с того же места.
3. Существующий с завершённым онбордингом → главное меню сразу.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.database import db
from app.utils.keyboards import (
    CB,
    back_to_menu,
    main_menu_reply,
    onboarding_privacy,
    remove_reply_keyboard,
)

router = Router(name="start")


# ============================================================
# СОСТОЯНИЯ ОНБОРДИНГА
# ============================================================
class OnboardingStates(StatesGroup):
    waiting_privacy = State()
    waiting_timezone = State()


# ============================================================
# /start
# ============================================================
@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    user: dict | None,
    db,
) -> None:
    """Точка входа. Развилка по статусу пользователя."""
    tg_user = message.from_user
    if tg_user is None:
        return

    # 1. Новый пользователь — регистрируем
    if user is None:
        user = await db.execute_returning(
            """
            INSERT INTO users (telegram_id, username, first_name, last_name)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (tg_user.id, tg_user.username, tg_user.first_name, tg_user.last_name),
        )
        logger.info(f"Зарегистрирован новый пользователь: {tg_user.id}")

        await message.answer(
            f"👋 Привет, {tg_user.first_name or 'друг'}!\n\n"
            "Я — твой помощник для продаж на Авито.\n\n"
            "Помогу:\n"
            "• 📝 составить объявление, которое заметят\n"
            "• 🛠 улучшить уже опубликованное\n"
            "• 🔍 проанализировать конкурентов\n"
            "• 📸 подобрать лучшие фото\n"
            "• 📈 выстроить стратегию продвижения\n"
            "• 💬 ответить покупателям\n\n"
            "Сначала — короткая настройка. Это займёт минуту."
        )
        await state.set_state(OnboardingStates.waiting_privacy)
        await message.answer(
            "📄 <b>Что я храню и как это использую</b>\n\n"
            "• Твой Telegram ID — чтобы помнить настройки\n"
            "• Тексты и фото объявлений — чтобы давать советы\n"
            "• Данные отправляются в YandexGPT для генерации текста\n"
            "• Я не храню платёжные реквизиты и пароли\n"
            "• В любой момент можно удалить все данные в ⚙️ Настройках\n\n"
            "Продолжая, ты соглашаешься с этим.",
            reply_markup=onboarding_privacy(),
        )
        return

    # 2. Пользователь есть, но онбординг не пройден
    if not user["onboarded"]:
        await state.set_state(OnboardingStates.waiting_privacy)
        await message.answer(
            "Продолжим настройку. Подтверди, пожалуйста, обработку данных:",
            reply_markup=onboarding_privacy(),
        )
        return

    # 3. Всё готово — сразу меню
    await state.clear()
    await _show_main_menu(message)


# ============================================================
# ОНБОРДИНГ — СОГЛАСИЕ
# ============================================================
@router.callback_query(F.data == CB.ONBOARD_ACCEPT_PRIVACY)
async def on_privacy_accepted(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
    db,
) -> None:
    if user is None:
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        return

    await db.execute(
        "UPDATE users SET privacy_accepted_at = NOW() WHERE id = %s",
        (user["id"],),
    )

    await callback.message.edit_text(
        "✅ Принято.\n\n"
        "Теперь выбери свой часовой пояс — он нужен, чтобы напоминания "
        "приходили в правильное время."
    )
    await state.set_state(OnboardingStates.waiting_timezone)
    await callback.message.answer(
        "Напиши город или часовой пояс.\n\n"
        "Примеры:\n"
        "• <code>Москва</code>\n"
        "• <code>Europe/Moscow</code>\n"
        "• <code>Екатеринбург</code>\n"
        "• <code>Asia/Novosibirsk</code>\n\n"
        "Если не знаешь — напиши «Москва», потом изменишь в ⚙️ Настройках.",
        reply_markup=remove_reply_keyboard(),
    )
    await callback.answer()


# ============================================================
# ИНФОРМАЦИЯ О ПРИВАТНОСТИ (кнопка «Что хранится?»)
# ============================================================
@router.callback_query(F.data == CB.SET_PRIVACY_INFO)
async def show_privacy_info(callback: CallbackQuery) -> None:
    """Показывает, какие данные хранятся и куда передаются."""
    await callback.message.answer(
        "📄 <b>Что я храню и куда передаю</b>\n\n"
        "<b>Храню:</b>\n"
        "• Твой Telegram ID, имя, username\n"
        "• Часовой пояс\n"
        "• Тексты и фото объявлений, которые ты присылаешь\n"
        "• Статистику и историю работы с товарами\n"
        "• Идентификаторы платежей (без реквизитов карты)\n\n"
        "<b>Передаю внешним сервисам:</b>\n"
        "• <b>YandexGPT</b> — тексты и фото объявлений для генерации\n"
        "• <b>ЮKassa</b> — сумму и ID платежа для оплаты\n"
        "• <b>Telegram</b> — сами сообщения (это мессенджер)\n\n"
        "<b>НЕ храню:</b>\n"
        "• Пароли, номера карт, CVV\n"
        "• Оригиналы фото дольше 24 часов\n\n"
        "<b>Удаление данных:</b>\n"
        "В ⚙️ Настройках → «🗑 Удалить мои данные» — удалю всё безвозвратно."
    )
    await callback.answer()


# ============================================================
# ОНБОРДИНГ — ЧАСОВОЙ ПОЯС
# ============================================================
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


@router.message(OnboardingStates.waiting_timezone, F.text)
async def on_timezone_entered(
    message: Message,
    state: FSMContext,
    user: dict,
    db,
) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Пустое сообщение. Напиши город или часовой пояс.")
        return

    tz_name = _resolve_timezone(raw)
    if tz_name is None:
        await message.answer(
            "Не получилось распознать. Попробуй в формате "
            "«Europe/Moscow» или напиши просто «Москва»."
        )
        return

    await db.execute(
        "UPDATE users SET timezone = %s, onboarded = TRUE WHERE id = %s",
        (tz_name, user["id"]),
    )
    await state.clear()

    await message.answer(
        f"✅ Часовой пояс: <b>{tz_name}</b>\n\n"
        "Настройка завершена. Открываю меню — выбирай, с чего начнём.",
    )
    await _show_main_menu(message)


def _resolve_timezone(raw: str) -> str | None:
    """Пытается превратить ввод пользователя в валидную IANA-зону."""
    key = raw.lower().strip()

    if key in CITY_TO_TZ:
        return CITY_TO_TZ[key]

    try:
        ZoneInfo(raw)
        return raw
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


# ============================================================
# ПОКАЗ ГЛАВНОГО МЕНЮ
# ============================================================
async def _show_main_menu(message: Message) -> None:
    await message.answer(
        "🏠 <b>Главное меню</b>\n\n"
        "Выбери раздел внизу экрана. В любой момент можно вернуться сюда "
        "командой /start.",
        reply_markup=main_menu_reply(),
    )


# ============================================================
# ВОЗВРАТ В МЕНЮ ПО КНОПКЕ
# ============================================================
@router.callback_query(F.data == CB.MENU_MAIN)
async def back_to_main_menu(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.message.answer(
        "🏠 <b>Главное меню</b>",
        reply_markup=main_menu_reply(),
    )
    await callback.answer()


# ============================================================
# /help
# ============================================================
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "❓ <b>Помощь</b>\n\n"
        "Что я умею:\n"
        "• 📝 Создать объявление — по фото и тексту составлю 3 варианта\n"
        "• 🛠 Улучшить объявление — разберу, что мешает продажам\n"
        "• 🔍 Анализ конкурентов — сравню и подскажу, чем выделиться\n"
        "• 📸 Помощь с фотографиями — выберу главное, подскажу ракурсы\n"
        "• 📈 Стратегия продвижения — что делать по шагам\n"
        "• 💬 Ответы покупателям — сформулирую вежливый ответ\n"
        "• 📂 Мои объявления — история и статистика\n"
        "• 💳 Тариф и подписка — лимиты и PRO\n"
        "• ⚙️ Настройки — часовой пояс, напоминания, удаление данных\n\n"
        "Если что-то не работает — пиши в ⚙️ Настройки → 💬 Поддержка.",
        reply_markup=back_to_menu(),
    )


# ============================================================
# ОТМЕНА ТЕКУЩЕЙ ЗАДАЧИ
# ============================================================
@router.callback_query(F.data == CB.CANCEL)
async def cancel_current(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.message.edit_text(
        "❌ Отменено.\n\n"
        "Если нужно начать заново — выбери раздел в меню."
    )
    await callback.answer("Отменено")