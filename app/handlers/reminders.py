"""
Настройки напоминаний (блок 10 ТЗ).

Пользователь выбирает интервал: 1 / 3 / 7 дней или отключить.
Из этого экрана возврат — в НАСТРОЙКИ, а не в главное меню.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from loguru import logger

from app.database import db
from app.services.scheduler import scheduler_service
from app.utils.keyboards import (
    CB,
    back_to_settings,
    reminders_menu,
)

router = Router(name="reminders")


# ============================================================
# ЭКРАН НАПОМИНАНИЙ
# ============================================================
@router.callback_query(F.data == CB.SET_REMINDERS)
async def show_reminders_settings(
    callback: CallbackQuery,
    user: dict,
) -> None:
    """Показывает текущие настройки напоминаний."""
    if user is None:
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        return

    interval = user.get("reminder_interval_days")
    enabled = interval is not None

    text_lines = ["⏰ <b>Напоминания</b>\n"]

    if enabled:
        text_lines.append(
            f"Сейчас: <b>каждые {interval} дн.</b> после завершения задачи.\n\n"
            f"Я буду напоминать проверить, как идут дела, и предложу внести статистику.\n\n"
            f"<i>Напоминания приходят в 12:00 по твоему часовому поясу.</i>"
        )
    else:
        text_lines.append(
            "Сейчас: <b>отключено</b>.\n\n"
            "Включи напоминания — я буду мягко напоминать о товарах."
        )

    text_lines.append("\nВыбери интервал:")

    await callback.message.edit_text(
        "\n".join(text_lines),
        reply_markup=reminders_menu(current_enabled=enabled, current_interval=interval),
    )
    await callback.answer()


# ============================================================
# УСТАНОВКА ИНТЕРВАЛА
# ============================================================
@router.callback_query(F.data == CB.REMIND_1D)
async def set_1d(callback: CallbackQuery, user: dict) -> None:
    await _set_interval(callback, user, 1)


@router.callback_query(F.data == CB.REMIND_3D)
async def set_3d(callback: CallbackQuery, user: dict) -> None:
    await _set_interval(callback, user, 3)


@router.callback_query(F.data == CB.REMIND_7D)
async def set_7d(callback: CallbackQuery, user: dict) -> None:
    await _set_interval(callback, user, 7)


@router.callback_query(F.data == CB.REMIND_OFF)
async def disable_reminders(callback: CallbackQuery, user: dict) -> None:
    """Отключает напоминания и отменяет все запланированные."""
    if user is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    # Отменяем все запланированные напоминания пользователя
    pending = await db.fetch_all(
        """
        SELECT id FROM reminders
        WHERE user_id = %s AND enabled = TRUE AND sent_at IS NULL
        """,
        (user["id"],),
    )
    for r in pending:
        scheduler_service.cancel_reminder(r["id"])

    # Отключаем в БД
    await db.execute(
        "UPDATE reminders SET enabled = FALSE WHERE user_id = %s AND sent_at IS NULL",
        (user["id"],),
    )
    await db.execute(
        "UPDATE users SET reminder_interval_days = NULL WHERE id = %s",
        (user["id"],),
    )

    await callback.message.edit_text(
        "🔕 <b>Напоминания отключены</b>\n\n"
        "Ты больше не будешь получать напоминания о товарах.",
        reply_markup=back_to_settings(),
    )
    await callback.answer("Отключено")
    logger.info(f"Пользователь {user['telegram_id']}: напоминания отключены")


async def _set_interval(
    callback: CallbackQuery,
    user: dict,
    days: int,
) -> None:
    """Устанавливает интервал напоминаний."""
    if user is None:
        await callback.answer("Ошибка", show_alert=True)
        return

    # Сохраняем в users
    await db.execute(
        "UPDATE users SET reminder_interval_days = %s WHERE id = %s",
        (days, user["id"]),
    )

    # Показываем обновлённый экран напоминаний с галочкой на выбранном интервале
    interval = days
    enabled = True

    text_lines = [
        "⏰ <b>Напоминания</b>\n",
        f"Сейчас: <b>каждые {days} дн.</b> после завершения задачи.\n\n"
        f"Я буду напоминать проверить, как идут дела, и предложу внести статистику.\n\n"
        f"<i>Напоминания приходят в 12:00 по твоему часовому поясу.</i>\n",
        "Выбери интервал:",
    ]

    await callback.message.edit_text(
        "\n".join(text_lines),
        reply_markup=reminders_menu(current_enabled=enabled, current_interval=interval),
    )
    await callback.answer(f"Установлено: {days} дн.")
    logger.info(f"Пользователь {user['telegram_id']}: напоминание через {days} дн.")