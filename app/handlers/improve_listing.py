"""
Сценарий «Улучшить объявление» (блок 4 ТЗ).

Пользователь присылает текст, ссылку, скриншоты или статистику.
Бот уточняет проблему, GigaChat анализирует и выдаёт рекомендации.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.database import db, to_jsonb
from app.prompts.improve_listing import (
    PROBLEM_LABELS,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.services.gigachat_service import gigachat_service
from app.services.task_manager import task_manager
from app.utils.keyboards import (
    CB,
    MENU,
    cancel_and_back,
    improve_materials,
    improve_problems,
    main_menu_reply,
)

router = Router(name="improve_listing")


class ImproveStates(StatesGroup):
    collecting = State()   # сбор материалов
    choosing_problem = State()  # выбор проблемы
    analyzing = State()    # анализ идёт


# ============================================================
# УТИЛИТЫ
# ============================================================
async def _resolve_task_id(state: FSMContext, user_id: int) -> int | None:
    """task_id из state или из БД (последняя активная задача)."""
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
        WHERE user_id = %s AND task_type = 'improve_listing' AND status = 'active'
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
@router.callback_query(F.data == CB.MENU_IMPROVE)
@router.message(F.text == MENU.IMPROVE)
async def start_improve(
    event: Message | CallbackQuery,
    state: FSMContext,
    user: dict | None,
    db,
) -> None:
    logger.info(f"start_improve: событие от {type(event).__name__}")

    if isinstance(event, CallbackQuery):
        message = event.message
        await event.answer()
    else:
        message = event

    if user is None:
        await message.answer("Ошибка: пользователь не найден. Напишите /start.")
        return

    check = await task_manager.check_limit(user, "improve_listing")
    if not check.allowed:
        await message.answer(
            f"❌ <b>Лимит исчерпан</b>\n\n{check.reason}\n\n"
            f"Оформи PRO, чтобы продолжить: 💳 Тариф и подписка.",
        )
        return

    # Активная задача — продолжаем
    if check.existing_task:
        task = check.existing_task
        await state.set_state(ImproveStates.collecting)
        await state.update_data(task_id=task["id"])
        await message.answer(
            "📂 У тебя уже есть незавершённая задача «Улучшить». Продолжаем.",
            reply_markup=improve_materials(),
        )
        return

    # Новая задача
    task = await task_manager.create_task(
        user=user,
        task_type="improve_listing",
        collected_data={
            "text": "",
            "link": "",
            "stats_text": "",
            "screenshots": [],
            "extra": "",
        },
    )
    await state.update_data(task_id=task["id"])
    await state.set_state(ImproveStates.collecting)

    await message.answer(
        "🛠 <b>Улучшаем объявление</b>\n\n"
        "Пришли материалы — что есть:\n\n"
        "• 📝 <b>Текст</b> объявления (можно скопировать из Авито)\n"
        "• 🔗 <b>Ссылку</b> на объявление (если оно уже опубликовано)\n"
        "• 📸 <b>Скриншоты</b> объявления или статистики\n"
        "• 📊 <b>Статистику</b>: просмотры, избранное, сообщения, срок размещения\n\n"
        "Можно присылать всё в любом порядке. Когда закончишь — выбери, "
        "что именно не получается.",
        reply_markup=improve_materials(),
    )


# ============================================================
# СБОР МАТЕРИАЛОВ
# ============================================================
@router.message(ImproveStates.collecting, F.text, ~F.text.startswith("/"))
async def on_text_received(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    # Игнорируем кнопки главного меню
    if message.text in MENU.all_texts():
        return

    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await message.answer("Ошибка: задача не найдена. Начните заново.")
        await state.clear()
        return

    text = message.text.strip()
    task = await db.fetch_one("SELECT collected_data FROM tasks WHERE id = %s", (task_id,))
    if not task:
        return

    collected = task["collected_data"] or {}

    # Определяем, что прислал пользователь
    if text.startswith("http://") or text.startswith("https://"):
        collected["link"] = text
        await message.answer("🔗 Ссылку сохранил.")
    else:
        # Всё остальное — текст объявления
        existing = collected.get("text", "")
        collected["text"] = (existing + "\n\n" + text).strip() if existing else text
        preview = collected["text"][:300] + ("..." if len(collected["text"]) > 300 else "")
        await message.answer(f"📝 Текст сохранён:\n\n<i>{preview}</i>")

    await db.execute(
        "UPDATE tasks SET collected_data = %s::jsonb WHERE id = %s",
        (to_jsonb(collected), task_id),
    )
    await task_manager.log_message(task_id, "user", text)

    await message.answer(
        "Можно прислать ещё материалы или выбрать проблему.",
        reply_markup=improve_materials(),
    )


@router.message(ImproveStates.collecting, F.photo)
async def on_photo_received(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await message.answer("Ошибка: задача не найдена.")
        return

    photo = message.photo[-1]
    task = await db.fetch_one("SELECT collected_data FROM tasks WHERE id = %s", (task_id,))
    if not task:
        return

    collected = task["collected_data"] or {}
    screenshots = collected.get("screenshots", [])

    if any(s.get("file_unique_id") == photo.file_unique_id for s in screenshots):
        await message.answer("Этот скриншот уже добавлен.")
        return

    screenshots.append({
        "file_id": photo.file_id,
        "file_unique_id": photo.file_unique_id,
    })
    collected["screenshots"] = screenshots

    await db.execute(
        "UPDATE tasks SET collected_data = %s::jsonb WHERE id = %s",
        (to_jsonb(collected), task_id),
    )

    await message.answer(
        f"📸 Скриншот добавлен (всего: {len(screenshots)}).",
        reply_markup=improve_materials(),
    )


# ============================================================
# КНОПКИ СБОРА
# ============================================================
@router.callback_query(F.data == CB.IMPROVE_MATERIAL_TEXT)
async def prompt_text(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "📝 Пришли текст объявления одним сообщением.\n\n"
        "Скопируй из Авито и вставь сюда."
    )
    await callback.answer()


@router.callback_query(F.data == CB.IMPROVE_MATERIAL_LINK)
async def prompt_link(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "🔗 Пришли ссылку на объявление.\n\n"
        "Например: <code>https://www.avito.ru/moskva/...</code>\n\n"
        "Я не буду её парсить — просто учту в анализе."
    )
    await callback.answer()


@router.callback_query(F.data == CB.IMPROVE_MATERIAL_SCREEN)
async def prompt_screen(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "📸 Пришли скриншоты объявления или статистики.\n"
        "Можно несколько подряд."
    )
    await callback.answer()


@router.callback_query(F.data == CB.IMPROVE_MATERIAL_STATS)
async def prompt_stats(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "📊 Напиши статистику в свободной форме.\n\n"
        "Например:\n"
        "<code>Просмотров: 45, в избранном: 2, сообщений: 0, опубликовано 10 дней назад</code>"
    )
    await callback.answer()


# ============================================================
# ПЕРЕХОД К ВЫБОРУ ПРОБЛЕМЫ
# ============================================================
@router.callback_query(F.data == "improve:ready")
async def ready_to_analyze(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await callback.answer("Задача не найдена.", show_alert=True)
        return

    task = await db.fetch_one("SELECT collected_data FROM tasks WHERE id = %s", (task_id,))
    collected = task["collected_data"] if task else {}

    has_material = bool(
        collected.get("text")
        or collected.get("link")
        or collected.get("stats_text")
        or collected.get("screenshots")
    )
    if not has_material:
        await callback.answer(
            "Сначала пришли хотя бы текст, ссылку или скриншот.",
            show_alert=True,
        )
        return

    await state.set_state(ImproveStates.choosing_problem)
    await callback.message.answer(
        "🎯 <b>Что именно не получается?</b>\n\n"
        "Это поможет дать точные рекомендации.",
        reply_markup=improve_problems(),
    )
    await callback.answer()


# ============================================================
# ВЫБОР ПРОБЛЕМЫ
# ============================================================
@router.callback_query(F.data.startswith("improve:problem:"))
async def on_problem_chosen(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    problem_code = callback.data.split(":", 2)[2]  # low_views, no_favorites и т.д.
    problem_label = PROBLEM_LABELS.get(problem_code, problem_code)

    logger.info(f"on_problem_chosen: {problem_code}")

    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await callback.answer("Задача потеряна. Начните заново.", show_alert=True)
        await state.clear()
        return

    task = await db.fetch_one("SELECT collected_data FROM tasks WHERE id = %s", (task_id,))
    if not task:
        return

    collected = task["collected_data"] or {}
    collected["problem"] = problem_code

    await db.execute(
        "UPDATE tasks SET collected_data = %s::jsonb WHERE id = %s",
        (to_jsonb(collected), task_id),
    )

    await state.set_state(ImproveStates.analyzing)
    await callback.answer(f"Анализирую: {problem_label}")
    await callback.message.answer(
        f"🎯 Проблема: <b>{problem_label}</b>\n\n"
        f"Анализирую материалы. Это займёт до 30 секунд…"
    )
    await _run_analysis(callback.message, state, task_id, user)


# ============================================================
# АНАЛИЗ ЧЕРЕЗ GIGACHAT
# ============================================================
async def _run_analysis(
    message: Message,
    state: FSMContext,
    task_id: int,
    user: dict,
) -> None:
    logger.info(f"_run_analysis: task_id={task_id}")

    task = await db.fetch_one("SELECT * FROM tasks WHERE id = %s", (task_id,))
    if not task:
        await message.answer("Ошибка: задача не найдена.")
        return

    collected = task["collected_data"] or {}
    user_prompt = build_user_prompt(collected)

    try:
        logger.info("_run_analysis: вызов GigaChat…")
        result = await gigachat_service.generate_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.4,
            max_tokens=2500,
        )
        logger.info(f"_run_analysis: GigaChat ответил")
    except Exception as e:
        logger.exception(f"Ошибка анализа: {e}")
        await task_manager.complete_task(task_id, status="failed", technical_failure=True)
        await message.answer(
            "❌ Не удалось проанализировать объявление. Попробуй позже.\n"
            "Лимит не списан.",
            reply_markup=cancel_and_back(),
        )
        return

    # Если GigaChat сказал, что данных мало
    if result.get("need_more"):
        await task_manager.complete_task(task_id, status="failed", technical_failure=True)
        await message.answer(
            f"🤔 <b>Данных мало для точного анализа</b>\n\n"
            f"{result['need_more']}\n\n"
            f"Лимит не списан — попробуй ещё раз с материалами.",
            reply_markup=main_menu_reply(),
        )
        await state.clear()
        return

    # Сохраняем результат
    await task_manager.set_result(task_id, result)

    # Задача завершена
    await task_manager.complete_task(
        task_id, status="done", result=result,
    )

    # Собираем ответ
    text_lines = ["🔍 <b>Анализ объявления</b>\n"]

    if summary := result.get("summary"):
        text_lines.append(f"<i>{summary}</i>\n")

    if strengths := result.get("strengths"):
        text_lines.append("<b>✅ Сильные стороны:</b>")
        for s in strengths:
            text_lines.append(f"• {s}")
        text_lines.append("")

    if problems := result.get("problems"):
        text_lines.append("<b>⚠️ Вероятные проблемы:</b>")
        for p in problems:
            text_lines.append(f"• {p}")
        text_lines.append("")

    if changes := result.get("priority_changes"):
        text_lines.append("<b>🎯 Что менять в первую очередь:</b>")
        for i, c in enumerate(changes, 1):
            text_lines.append(
                f"{i}. <b>{c.get('what', '')}</b>\n"
                f"   <i>Почему:</i> {c.get('why', '')}\n"
                f"   <i>Как:</i> {c.get('how', '')}"
            )
        text_lines.append("")

    if new_title := result.get("new_title"):
        text_lines.append(f"<b>💡 Новый заголовок:</b>\n<code>{new_title}</code>\n")

    if new_desc := result.get("new_description"):
        text_lines.append(f"<b>💡 Новое описание:</b>\n{new_desc}\n")

    if check_after := result.get("check_after"):
        metric = check_after.get("metric", "")
        timeframe = check_after.get("timeframe", "")
        what_to_compare = check_after.get("what_to_compare", "")
        text_lines.append(
            f"<b>📊 Что проверить:</b>\n"
            f"• Показатель: {metric}\n"
            f"• Когда: {timeframe}\n"
            f"• С чем сравнить: {what_to_compare}"
        )

    text = "\n".join(text_lines)

    # Разбиваем, если длинно
    if len(text) > 4000:
        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            await message.answer(chunk)
    else:
        await message.answer(text)

    await message.answer(
        "Что дальше?",
        reply_markup=main_menu_reply(),
    )
    await state.clear()


# ============================================================
# ОТМЕНА
# ============================================================
@router.callback_query(F.data == CB.CANCEL, ImproveStates.collecting)
@router.callback_query(F.data == CB.CANCEL, ImproveStates.choosing_problem)
async def cancel_improve(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    logger.info(f"cancel_improve: user={callback.from_user.id}")

    task_id = await _resolve_task_id(state, user["id"])
    if task_id:
        await task_manager.complete_task(task_id, status="cancelled")

    await state.clear()

    try:
        await callback.message.edit_text("❌ Улучшение объявления отменено.")
    except Exception as e:
        logger.debug(f"edit_text не сработал: {e}")

    await callback.message.answer(
        "Возвращаю в главное меню.",
        reply_markup=main_menu_reply(),
    )
    await callback.answer("Отменено")