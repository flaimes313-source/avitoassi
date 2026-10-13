"""
Сценарий «Ответы покупателям» (блок 8 ТЗ).

Пользователь присылает сообщение покупателя и (опционально) цель ответа.
GigaChat генерирует короткий вежливый ответ.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.database import db, to_jsonb
from app.prompts.buyer_replies import (
    GOAL_LABELS,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.services.gigachat_service import gigachat_service
from app.services.task_manager import task_manager
from app.utils.keyboards import (
    CB,
    MENU,
    buyer_reply_goals,
    cancel_and_back,
    main_menu_reply,
)

router = Router(name="buyer_replies")


class ReplyStates(StatesGroup):
    waiting_message = State()   # ждём сообщение покупателя
    choosing_goal = State()     # ждём цель ответа
    done = State()              # ответ готов


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
        WHERE user_id = %s AND task_type = 'buyer_reply' AND status = 'active'
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
@router.callback_query(F.data == CB.MENU_BUYER_REPLIES)
@router.message(F.text == MENU.BUYER_REPLIES)
async def start_buyer_replies(
    event: Message | CallbackQuery,
    state: FSMContext,
    user: dict | None,
    db,
) -> None:
    logger.info(f"start_buyer_replies: событие от {type(event).__name__}")

    if isinstance(event, CallbackQuery):
        message = event.message
        await event.answer()
    else:
        message = event

    if user is None:
        await message.answer("Ошибка: пользователь не найден. Напишите /start.")
        return

    check = await task_manager.check_limit(user, "buyer_reply")
    if not check.allowed:
        await message.answer(
            f"❌ <b>Лимит исчерпан</b>\n\n{check.reason}\n\n"
            f"Оформи PRO, чтобы продолжить: 💳 Тариф и подписка.",
        )
        return

    # Продолжаем активную задачу
    if check.existing_task:
        task = check.existing_task
        collected = task.get("collected_data") or {}
        buyer_msg = collected.get("buyer_message", "")

        await state.set_state(ReplyStates.waiting_message)
        await state.update_data(task_id=task["id"], user_id=user["id"])

        preview = buyer_msg[:200] + ("..." if len(buyer_msg) > 200 else "")
        await message.answer(
            f"📂 <b>У тебя есть незавершённая задача</b>\n\n"
            f"<i>Сообщение покупателя:</i>\n{preview}\n\n"
            f"Продолжаем или пришли новое сообщение?",
            reply_markup=cancel_and_back(),
        )
        return

    # Новая задача
    task = await task_manager.create_task(
        user=user,
        task_type="buyer_reply",
        collected_data={"buyer_message": "", "goal": ""},
    )
    await state.update_data(task_id=task["id"], user_id=user["id"])
    await state.set_state(ReplyStates.waiting_message)

    await message.answer(
        "💬 <b>Ответы покупателям</b>\n\n"
        "Пришли <b>сообщение от покупателя</b>, на которое нужен ответ.\n\n"
        "Например:\n"
        "<i>«Здравствуйте, товар ещё актуален?»</i>\n"
        "<i>«А можно дешевле?»</i>\n"
        "<i>«В каком состоянии?»</i>\n\n"
        "Я подготовлю вежливый ответ, который ты сможешь отправить сам.",
        reply_markup=cancel_and_back(),
    )


# ============================================================
# ПРИЁМ СООБЩЕНИЯ ПОКУПАТЕЛЯ
# ============================================================
@router.message(ReplyStates.waiting_message, F.text, ~F.text.startswith("/"))
async def on_buyer_message(
    message: Message,
    state: FSMContext,
    user: dict,
    db,
) -> None:
    if message.text in MENU.all_texts():
        return

    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await message.answer("Ошибка: задача не найдена.")
        await state.clear()
        return

    collected = {"buyer_message": message.text.strip()}
    await db.execute(
        "UPDATE tasks SET collected_data = collected_data || %s::jsonb WHERE id = %s",
        (to_jsonb(collected), task_id),
    )
    await task_manager.log_message(task_id, "user", message.text)

    await state.set_state(ReplyStates.choosing_goal)

    preview = message.text[:200] + ("..." if len(message.text) > 200 else "")
    await message.answer(
        f"📝 Сообщение сохранено:\n\n<i>{preview}</i>\n\n"
        f"Теперь выбери <b>цель ответа</b> (или «Без цели»):",
        reply_markup=buyer_reply_goals(),
    )


# ============================================================
# ВЫБОР ЦЕЛИ
# ============================================================
@router.callback_query(F.data.startswith("reply:goal:"))
async def on_goal_chosen(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    # Определяем код цели из callback_data
    parts = callback.data.split(":")
    goal_code = parts[2] if len(parts) >= 3 else "none"
    goal_label = GOAL_LABELS.get(goal_code, goal_code)

    logger.info(f"on_goal_chosen: {goal_code}")

    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await callback.answer("Задача потеряна.", show_alert=True)
        await state.clear()
        return

    await db.execute(
        "UPDATE tasks SET collected_data = collected_data || %s::jsonb WHERE id = %s",
        (to_jsonb({"goal": goal_code}), task_id),
    )

    await callback.answer(f"Цель: {goal_label}")
    await callback.message.answer(
        f"🎯 Цель: <b>{goal_label}</b>\n\n"
        f"Готовлю ответ. Это займёт несколько секунд…"
    )
    await _run_reply(callback.message, state, task_id, user)


# ============================================================
# ГЕНЕРАЦИЯ ОТВЕТА
# ============================================================
async def _run_reply(
    message: Message,
    state: FSMContext,
    task_id: int,
    user: dict,
) -> None:
    logger.info(f"_run_reply: task_id={task_id}")

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
            temperature=0.6,
            max_tokens=1500,
            user_id=user_id,
            task_id=task_id,
        )
        logger.info("_run_reply: GigaChat ответил")
    except Exception as e:
        logger.exception(f"Ошибка генерации ответа: {e}")
        await task_manager.complete_task(task_id, status="failed", technical_failure=True)
        await message.answer(
            "❌ Не удалось сгенерировать ответ. Попробуй позже.\nЛимит не списан.",
            reply_markup=cancel_and_back(),
        )
        return

    reply = result.get("reply", "").strip()
    explanation = result.get("explanation", "").strip()

    if not reply:
        await task_manager.complete_task(task_id, status="failed", technical_failure=True)
        await message.answer(
            "❌ GigaChat вернул пустой ответ. Попробуй ещё раз.",
            reply_markup=cancel_and_back(),
        )
        return

    await task_manager.set_result(task_id, {"reply": reply, "explanation": explanation})
    await task_manager.complete_task(task_id, status="done", result=result)

    # Показываем ответ
    text = (
        f"💬 <b>Готовый ответ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{reply}\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )

    if explanation:
        text += f"\n\n<i>{explanation}</i>"

    await message.answer(text)

    await state.set_state(ReplyStates.done)

    await message.answer(
        "Что дальше?\n\n"
        "• Скопируй текст и отправь покупателю в чате Авито\n"
        "• Или пришли новое сообщение — отвечу ещё раз",
        reply_markup=main_menu_reply(),
    )


# ============================================================
# НОВОЕ СООБЩЕНИЕ (после ответа)
# ============================================================
@router.message(ReplyStates.done, F.text, ~F.text.startswith("/"))
async def on_new_message(
    message: Message,
    state: FSMContext,
    user: dict,
    db,
) -> None:
    if message.text in MENU.all_texts():
        return

    # Создаём новую задачу для нового ответа
    task = await task_manager.create_task(
        user=user,
        task_type="buyer_reply",
        collected_data={"buyer_message": message.text.strip(), "goal": ""},
    )
    await state.update_data(task_id=task["id"], user_id=user["id"])
    await state.set_state(ReplyStates.choosing_goal)

    preview = message.text[:200] + ("..." if len(message.text) > 200 else "")
    await message.answer(
        f"📝 Новое сообщение:\n\n<i>{preview}</i>\n\n"
        f"Выбери цель ответа:",
        reply_markup=buyer_reply_goals(),
    )


# ============================================================
# ОТМЕНА
# ============================================================
@router.callback_query(F.data == CB.CANCEL, ReplyStates.waiting_message)
@router.callback_query(F.data == CB.CANCEL, ReplyStates.choosing_goal)
@router.callback_query(F.data == CB.CANCEL, ReplyStates.done)
async def cancel_reply(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    logger.info(f"cancel_reply: user={callback.from_user.id}")

    task_id = await _resolve_task_id(state, user["id"])
    if task_id:
        await task_manager.complete_task(task_id, status="cancelled")

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