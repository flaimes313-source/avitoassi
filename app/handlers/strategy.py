"""
Сценарий «Стратегия продвижения» (блок 7 ТЗ).

Пользователь присылает данные объявления и статистику →
GigaChat выдаёт пошаговый план действий.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.database import db, to_jsonb
from app.prompts.strategy import SYSTEM_PROMPT, build_user_prompt
from app.services.gigachat_service import gigachat_service
from app.services.task_manager import task_manager
from app.utils.keyboards import (
    CB,
    MENU,
    cancel_and_back,
    main_menu_reply,
    strategy_actions,
)

router = Router(name="strategy")


class StrategyStates(StatesGroup):
    collecting = State()   # сбор данных


# ============================================================
# УТИЛИТЫ
# ============================================================
async def _resolve_task_id(state: FSMContext, user_id: int) -> int | None:
    data = await state.get_data()
    task_id = data.get("task_id")

    if task_id:
        task = await db.fetch_one(
            "SELECT id FROM tasks WHERE id = %s AND status = 'active'",
            (task_id,),
        )
        if task:
            return task_id

    task = await db.fetch_one(
        """
        SELECT id FROM tasks
        WHERE user_id = %s AND task_type = 'strategy' AND status = 'active'
        ORDER BY created_at DESC LIMIT 1
        """,
        (user_id,),
    )
    if task:
        await state.update_data(task_id=task["id"])
        return task["id"]
    return None


# ============================================================
# ВХОД В СЦЕНАРИЙ
# ============================================================
@router.callback_query(F.data == CB.MENU_STRATEGY)
@router.message(F.text == MENU.STRATEGY)
async def start_strategy(
    event: Message | CallbackQuery,
    state: FSMContext,
    user: dict | None,
    db,
) -> None:
    logger.info(f"start_strategy: событие от {type(event).__name__}")

    if isinstance(event, CallbackQuery):
        message = event.message
        await event.answer()
    else:
        message = event

    if user is None:
        await message.answer("Ошибка: пользователь не найден. Напишите /start.")
        return

    check = await task_manager.check_limit(user, "strategy")
    if not check.allowed:
        await message.answer(
            f"❌ <b>Лимит исчерпан</b>\n\n{check.reason}\n\n"
            f"Оформи PRO, чтобы продолжить: 💳 Тариф и подписка.",
        )
        return

    if check.existing_task:
        task = check.existing_task
        await state.set_state(StrategyStates.collecting)
        await state.update_data(task_id=task["id"], user_id=user["id"])
        await message.answer(
            "📂 У тебя уже есть незавершённая стратегия. Продолжаем.",
            reply_markup=strategy_actions(),
        )
        return

    task = await task_manager.create_task(
        user=user,
        task_type="strategy",
        collected_data={
            "listing_title": "",
            "listing_body": "",
            "price": "",
            "days_on_avito": "",
            "views": "",
            "favorites": "",
            "messages": "",
            "extra": "",
        },
    )
    await state.update_data(task_id=task["id"], user_id=user["id"])
    await state.set_state(StrategyStates.collecting)

    await message.answer(
        "📈 <b>Стратегия продвижения</b>\n\n"
        "Пришли данные о своём объявлении одним или несколькими сообщениями:\n\n"
        "• 📝 Заголовок и текст объявления\n"
        "• 💰 Цена\n"
        "• 📊 Сколько дней на Авито, сколько просмотров, избранного, сообщений\n"
        "• ⚠️ Что уже пробовал (если пробовал)\n\n"
        "Чем больше данных — тем точнее план. Когда закончишь — нажми "
        "«▶️ Получить план».",
        reply_markup=strategy_actions(),
    )


# ============================================================
# ПРИЁМ ДАННЫХ
# ============================================================
@router.message(StrategyStates.collecting, F.text, ~F.text.startswith("/"))
async def on_data_received(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    if message.text in MENU.all_texts():
        return

    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await message.answer("Ошибка: задача не найдена.")
        await state.clear()
        return

    task = await db.fetch_one("SELECT collected_data FROM tasks WHERE id = %s", (task_id,))
    if not task:
        return
    collected = task["collected_data"] or {}
    existing = collected.get("extra", "")

    new_text = (existing + "\n\n" + message.text).strip() if existing else message.text
    collected["extra"] = new_text

    await db.execute(
        "UPDATE tasks SET collected_data = %s::jsonb WHERE id = %s",
        (to_jsonb(collected), task_id),
    )
    await task_manager.log_message(task_id, "user", message.text)

    await message.answer(
        "✅ Данные сохранены.\n\n"
        "Можешь прислать ещё или нажать «▶️ Получить план».",
        reply_markup=strategy_actions(),
    )


# ============================================================
# КНОПКИ
# ============================================================
@router.callback_query(F.data == CB.STRATEGY_RUN)
async def run_strategy(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    logger.info(f"run_strategy: user={callback.from_user.id}")

    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await callback.answer("Задача не найдена. Начните заново.", show_alert=True)
        await state.clear()
        return

    task = await db.fetch_one("SELECT collected_data FROM tasks WHERE id = %s", (task_id,))
    if not task:
        return
    collected = task["collected_data"] or {}

    if not collected.get("extra"):
        await callback.answer(
            "Сначала пришли данные о объявлении.",
            show_alert=True,
        )
        return

    await callback.answer("Готовлю план…")
    await callback.message.answer(
        "✅ Данные приняты.\n\n"
        "Составляю план действий. Это займёт до 30 секунд…"
    )
    await _run_strategy(callback.message, state, task_id, user)


@router.callback_query(F.data == CB.STRATEGY_CHECK_LATER)
async def check_later(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    task_id = await _resolve_task_id(state, user["id"])
    if task_id:
        await task_manager.complete_task(task_id, status="cancelled")
    await state.clear()

    try:
        await callback.message.edit_text("⏰ Отложено. Напомню позже.")
    except Exception:
        pass

    await callback.message.answer(
        "Возвращаю в главное меню.",
        reply_markup=main_menu_reply(),
    )
    await callback.answer("Отложено")


# ============================================================
# ГЕНЕРАЦИЯ СТРАТЕГИИ
# ============================================================
async def _run_strategy(
    message: Message,
    state: FSMContext,
    task_id: int,
    user: dict,
) -> None:
    logger.info(f"_run_strategy: task_id={task_id}")

    data = await state.get_data()
    user_id = data.get("user_id")

    task = await db.fetch_one("SELECT * FROM tasks WHERE id = %s", (task_id,))
    if not task:
        await message.answer("Ошибка: задача не найдена.")
        return

    collected = task["collected_data"] or {}
    user_prompt = build_user_prompt(collected)

    try:
        result = await gigachat_service.generate_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.4,
            max_tokens=4000,
            user_id=user_id,
            task_id=task_id,
        )
        logger.info("_run_strategy: GigaChat ответил")
    except Exception as e:
        logger.exception(f"Ошибка стратегии: {e}")
        await task_manager.complete_task(task_id, status="failed", technical_failure=True)
        await message.answer(
            "❌ Не удалось составить план. Попробуй позже.\nЛимит не списан.",
            reply_markup=cancel_and_back(),
        )
        return

    # Сохраняем и завершаем
    await task_manager.set_result(task_id, result)
    await task_manager.complete_task(task_id, status="done", result=result)

    # Формируем ответ
    text_lines = ["📈 <b>Стратегия продвижения</b>\n"]

    if summary := result.get("summary"):
        text_lines.append(f"<i>{summary}</i>\n")

    if current := result.get("current_state"):
        text_lines.append(f"<b>Текущее состояние:</b> {current}\n")

    steps = result.get("steps", [])
    for step in steps:
        when = step.get("when", "")
        actions = step.get("actions", [])
        if not actions:
            continue

        text_lines.append(f"<b>🕐 {when}</b>")
        for i, action in enumerate(actions, 1):
            what = action.get("what", "")
            why = action.get("why", "")
            how = action.get("how", "")
            text_lines.append(f"{i}. <b>{what}</b>")
            if why:
                text_lines.append(f"   <i>Почему:</i> {why}")
            if how:
                text_lines.append(f"   <i>Как:</i> {how}")
        text_lines.append("")

    paid = result.get("paid_promotion") or {}
    if paid.get("recommended"):
        text_lines.append(
            f"<b>💰 Платное продвижение:</b> рекомендую\n"
            f"{paid.get('reason', '')}\n"
        )
    else:
        text_lines.append(
            f"<b>💰 Платное продвижение:</b> пока не нужно\n"
            f"{paid.get('reason', '')}\n"
        )

    if track := result.get("what_to_track"):
        text_lines.append("<b>📊 Что отслеживать:</b>")
        for t in track:
            text_lines.append(f"• {t}")
        text_lines.append("")

    if next_step := result.get("next_step"):
        text_lines.append(f"<b>➡️ Следующий шаг:</b> {next_step}")

    text = "\n".join(text_lines)

    if len(text) > 4000:
        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            await message.answer(chunk)
    else:
        await message.answer(text)

    await message.answer("Что дальше?", reply_markup=main_menu_reply())
    await state.clear()


# ============================================================
# ОТМЕНА
# ============================================================
@router.callback_query(F.data == CB.CANCEL, StrategyStates.collecting)
async def cancel_strategy(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    logger.info(f"cancel_strategy: user={callback.from_user.id}")

    task_id = await _resolve_task_id(state, user["id"])
    if task_id:
        await task_manager.complete_task(task_id, status="cancelled")

    await state.clear()

    try:
        await callback.message.edit_text("❌ Стратегия отменена.")
    except Exception:
        pass

    await callback.message.answer(
        "Возвращаю в главное меню.",
        reply_markup=main_menu_reply(),
    )
    await callback.answer("Отменено")