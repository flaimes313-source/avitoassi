"""
Сценарий «Анализ конкурентов» (блок 5 ТЗ).

Vision: если есть скриншоты — GigaChat их читает.
Fallback: если Vision падает — работает только текст.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.database import db, to_jsonb
from app.prompts.competitors import SYSTEM_PROMPT, build_user_prompt
from app.services.gigachat_service import gigachat_service
from app.services.gigachat_vision import gigachat_vision_service
from app.services.task_manager import task_manager
from app.utils.keyboards import (
    CB,
    MENU,
    cancel_and_back,
    competitors_collect,
    main_menu_reply,
)

router = Router(name="competitors")

MAX_COMPETITORS = 5


class CompetitorsStates(StatesGroup):
    collecting = State()


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
        WHERE user_id = %s AND task_type = 'competitors' AND status = 'active'
        ORDER BY created_at DESC LIMIT 1
        """,
        (user_id,),
    )
    if task:
        await state.update_data(task_id=task["id"])
        return task["id"]
    return None


def _detect_source_type(text: str) -> str:
    t = text.strip()
    if t.startswith("http://") or t.startswith("https://"):
        return "link"
    return "text"


# ============================================================
# ВХОД В СЦЕНАРИЙ
# ============================================================
@router.callback_query(F.data == CB.MENU_COMPETITORS)
@router.message(F.text == MENU.COMPETITORS)
async def start_competitors(
    event: Message | CallbackQuery,
    state: FSMContext,
    user: dict | None,
    db,
) -> None:
    logger.info(f"start_competitors: событие от {type(event).__name__}")

    if isinstance(event, CallbackQuery):
        message = event.message
        await event.answer()
    else:
        message = event

    if user is None:
        await message.answer("Ошибка: пользователь не найден. Напишите /start.")
        return

    check = await task_manager.check_limit(user, "competitors")
    if not check.allowed:
        await message.answer(
            f"❌ <b>Лимит исчерпан</b>\n\n{check.reason}\n\n"
            f"Оформи PRO, чтобы продолжить: 💳 Тариф и подписка.",
        )
        return

    if check.existing_task:
        task = check.existing_task
        collected = task.get("collected_data") or {}
        competitors = collected.get("competitors", [])
        await state.set_state(CompetitorsStates.collecting)
        await state.update_data(task_id=task["id"])
        await message.answer(
            f"📂 У тебя есть незавершённый анализ (конкурентов: {len(competitors)}).\n\n"
            f"Пришли ещё или нажми «▶️ Запустить анализ».",
            reply_markup=competitors_collect(),
        )
        return

    task = await task_manager.create_task(
        user=user,
        task_type="competitors",
        collected_data={"competitors": []},
    )
    await state.update_data(task_id=task["id"])
    await state.set_state(CompetitorsStates.collecting)

    await message.answer(
        "🔍 <b>Анализ конкурентов</b>\n\n"
        "Пришли от 1 до 5 конкурентов:\n\n"
        "• 📝 <b>Текстом</b> — самый точный вариант, скопируй объявление\n"
        "• 📸 <b>Скриншотом</b> — я прочитаю текст с картинки\n"
        "• 🔗 <b>Ссылкой</b> — просто учту как факт (не парсю)\n\n"
        "Когда добавишь всех — нажми «▶️ Запустить анализ».",
        reply_markup=competitors_collect(),
    )


# ============================================================
# ПРИЁМ КОНКУРЕНТОВ
# ============================================================
@router.message(CompetitorsStates.collecting, F.text, ~F.text.startswith("/"))
async def on_text_competitor(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    if message.text in MENU.all_texts():
        return

    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await message.answer("Ошибка: задача не найдена. Начните заново.")
        await state.clear()
        return

    task = await db.fetch_one("SELECT collected_data FROM tasks WHERE id = %s", (task_id,))
    if not task:
        return
    collected = task["collected_data"] or {}
    competitors = collected.get("competitors", [])

    if len(competitors) >= MAX_COMPETITORS:
        await message.answer(
            f"⚠️ Уже {MAX_COMPETITORS} конкурентов — максимум.\n\n"
            f"Нажми «▶️ Запустить анализ».",
        )
        return

    source_type = _detect_source_type(message.text)

    if source_type == "link":
        competitors.append({
            "source_type": "link",
            "url": message.text.strip(),
            "content": None,
            "screenshots_count": 0,
            "screenshots": [],
        })
        preview = message.text.strip()[:80]
        await message.answer(
            f"🔗 Ссылка добавлена ({len(competitors)}/{MAX_COMPETITORS}).\n"
            f"<i>{preview}</i>\n\n"
            f"Можешь добавить ещё или запустить анализ.",
            reply_markup=competitors_collect(),
        )
    else:
        competitors.append({
            "source_type": "text",
            "url": None,
            "content": message.text.strip(),
            "screenshots_count": 0,
            "screenshots": [],
        })
        preview = message.text.strip()[:150] + (
            "..." if len(message.text) > 150 else ""
        )
        await message.answer(
            f"📝 Текст добавлен ({len(competitors)}/{MAX_COMPETITORS}).\n\n"
            f"<i>{preview}</i>",
            reply_markup=competitors_collect(),
        )

    collected["competitors"] = competitors
    await db.execute(
        "UPDATE tasks SET collected_data = %s::jsonb WHERE id = %s",
        (to_jsonb(collected), task_id),
    )
    await task_manager.log_message(task_id, "user", message.text)


@router.message(CompetitorsStates.collecting, F.photo)
async def on_photo_competitor(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await message.answer("Ошибка: задача не найдена.")
        return

    task = await db.fetch_one("SELECT collected_data FROM tasks WHERE id = %s", (task_id,))
    if not task:
        return
    collected = task["collected_data"] or {}
    competitors = collected.get("competitors", [])

    if len(competitors) >= MAX_COMPETITORS:
        await message.answer(
            f"⚠️ Уже {MAX_COMPETITORS} конкурентов — максимум.",
        )
        return

    photo = message.photo[-1]

    # Ищем последнего конкурента типа "screenshot" — если есть, добавляем к нему
    last_screenshot = None
    for c in reversed(competitors):
        if c.get("source_type") == "screenshot":
            last_screenshot = c
            break

    if last_screenshot is not None:
        last_screenshot["screenshots_count"] = last_screenshot.get("screenshots_count", 0) + 1
        last_screenshot.setdefault("screenshots", []).append({
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
        })
        await message.answer(
            f"📸 Скриншот добавлен к конкуренту №{len(competitors)} "
            f"(всего: {last_screenshot['screenshots_count']}).",
            reply_markup=competitors_collect(),
        )
    else:
        competitors.append({
            "source_type": "screenshot",
            "url": None,
            "content": None,
            "screenshots_count": 1,
            "screenshots": [{
                "file_id": photo.file_id,
                "file_unique_id": photo.file_unique_id,
            }],
        })
        await message.answer(
            f"📸 Скриншот добавлен как конкурент №{len(competitors)}/{MAX_COMPETITORS}.",
            reply_markup=competitors_collect(),
        )

    collected["competitors"] = competitors
    await db.execute(
        "UPDATE tasks SET collected_data = %s::jsonb WHERE id = %s",
        (to_jsonb(collected), task_id),
    )


# ============================================================
# КНОПКИ
# ============================================================
@router.callback_query(F.data == CB.COMPETITOR_ADD)
async def prompt_add(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "Пришли ещё конкурента: ссылкой, скриншотом или текстом."
    )
    await callback.answer()


@router.callback_query(F.data == CB.COMPETITOR_RUN)
async def run_analysis(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
    bot,
) -> None:
    logger.info(f"run_analysis: user={callback.from_user.id}")

    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await callback.answer("Задача не найдена. Начните заново.", show_alert=True)
        await state.clear()
        return

    task = await db.fetch_one("SELECT collected_data FROM tasks WHERE id = %s", (task_id,))
    if not task:
        return
    collected = task["collected_data"] or {}
    competitors = collected.get("competitors", [])

    if not competitors:
        await callback.answer(
            "Сначала пришли хотя бы одного конкурента.",
            show_alert=True,
        )
        return

    await callback.answer("Анализирую…")
    await callback.message.answer(
        f"✅ Принято {len(competitors)} конкурентов.\n\n"
        f"Запускаю анализ. Это займёт до 40 секунд…"
    )
    await _run_analysis(callback.message, state, task_id, user, bot=bot)


# ============================================================
# АНАЛИЗ
# ============================================================
async def _run_analysis(
    message: Message,
    state: FSMContext,
    task_id: int,
    user: dict,
    bot=None,
) -> None:
    logger.info(f"_run_analysis (competitors): task_id={task_id}, bot={'есть' if bot else 'нет'}")

    task = await db.fetch_one("SELECT * FROM tasks WHERE id = %s", (task_id,))
    if not task:
        await message.answer("Ошибка: задача не найдена.")
        return

    collected = task["collected_data"] or {}
    competitors = collected.get("competitors", [])

    # Собираем все скриншоты
    all_screenshots = []
    for comp in competitors:
        if comp.get("source_type") == "screenshot":
            for s in comp.get("screenshots", []):
                all_screenshots.append({"file_id": s["file_id"]})

    user_prompt = build_user_prompt(competitors)

    result = None

    # --- Vision, если есть скриншоты ---
    if all_screenshots and bot is not None:
        try:
            logger.info(f"_run_analysis: пробую Vision ({len(all_screenshots)} скриншотов)")
            result = await gigachat_vision_service.analyze_with_photos_json(
                bot=bot,
                photos=all_screenshots,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.4,
                max_tokens=3000,
            )
            logger.info("_run_analysis: Vision успешен")
        except Exception as e:
            logger.warning(f"_run_analysis: Vision упал, fallback на текст: {e}")
            result = None

    # --- Fallback: только текст ---
    if result is None:
        try:
            logger.info("_run_analysis: текстовый режим")
            result = await gigachat_service.generate_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.4,
                max_tokens=3000,
            )
        except Exception as e:
            logger.exception(f"Ошибка анализа: {e}")
            await task_manager.complete_task(task_id, status="failed", technical_failure=True)
            await message.answer(
                "❌ Не удалось проанализировать конкурентов. Попробуй позже.\n"
                "Лимит не списан.",
                reply_markup=cancel_and_back(),
            )
            return

    # Сохраняем и завершаем
    await task_manager.set_result(task_id, result)
    await task_manager.complete_task(task_id, status="done", result=result)

    # Формируем ответ
    text_lines = ["🔍 <b>Анализ конкурентов</b>\n"]

    if summary := result.get("summary"):
        text_lines.append(f"<i>{summary}</i>\n")

    analyzed = result.get("competitors_analyzed")
    if analyzed:
        text_lines.append(f"Проанализировано: <b>{analyzed}</b>\n")

    if strengths := result.get("competitors_strengths"):
        text_lines.append("<b>✅ Что хорошо у конкурентов:</b>")
        for s in strengths:
            text_lines.append(f"• {s}")
        text_lines.append("")

    if weaknesses := result.get("competitors_weaknesses"):
        text_lines.append("<b>⚠️ Слабые места конкурентов:</b>")
        for w in weaknesses:
            text_lines.append(f"• {w}")
        text_lines.append("")

    if advantages := result.get("user_advantages"):
        text_lines.append("<b>💪 Твои преимущества:</b>")
        for a in advantages:
            text_lines.append(f"• {a}")
        text_lines.append("")

    if changes := result.get("priority_changes"):
        text_lines.append("<b>🎯 Что изменить в первую очередь:</b>")
        for i, c in enumerate(changes, 1):
            text_lines.append(
                f"{i}. <b>{c.get('what', '')}</b>\n"
                f"   <i>Почему:</i> {c.get('why', '')}\n"
                f"   <i>Как:</i> {c.get('how', '')}"
            )
        text_lines.append("")

    if price_range := result.get("recommended_price_range"):
        text_lines.append(f"<b>💰 Рекомендуемый диапазон цены:</b> {price_range}\n")

    if insufficient := result.get("insufficient"):
        text_lines.append("<b>⚠️ Недостаточно данных:</b>")
        for inc in insufficient:
            text_lines.append(f"• {inc}")
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
@router.callback_query(F.data == CB.CANCEL, CompetitorsStates.collecting)
async def cancel_competitors(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    logger.info(f"cancel_competitors: user={callback.from_user.id}")

    task_id = await _resolve_task_id(state, user["id"])
    if task_id:
        await task_manager.complete_task(task_id, status="cancelled")

    await state.clear()

    try:
        await callback.message.edit_text("❌ Анализ конкурентов отменён.")
    except Exception as e:
        logger.debug(f"edit_text не сработал: {e}")

    await callback.message.answer(
        "Возвращаю в главное меню.",
        reply_markup=main_menu_reply(),
    )
    await callback.answer("Отменено")