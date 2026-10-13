"""
Сценарий «Помощь с фотографиями» (блок 6 ТЗ).

Пользователь присылает фото → Vision анализирует → рекомендации.
Повторный анализ тех же фото в рамках задачи не списывает лимит.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.database import db, to_jsonb
from app.prompts.photos import SYSTEM_PROMPT, build_user_prompt
from app.services.gigachat_vision import gigachat_vision_service
from app.services.task_manager import task_manager
from app.utils.keyboards import (
    CB,
    MENU,
    cancel_and_back,
    main_menu_reply,
    photos_actions,
)

router = Router(name="photos")

MAX_PHOTOS = 10


class PhotosStates(StatesGroup):
    collecting = State()   # сбор фото
    analyzing = State()    # анализ идёт
    done = State()         # анализ готов, ждём действий


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
        WHERE user_id = %s AND task_type = 'photos' AND status = 'active'
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
@router.callback_query(F.data == CB.MENU_PHOTOS)
@router.message(F.text == MENU.PHOTOS)
async def start_photos(
    event: Message | CallbackQuery,
    state: FSMContext,
    user: dict | None,
    db,
) -> None:
    logger.info(f"start_photos: событие от {type(event).__name__}")

    if isinstance(event, CallbackQuery):
        message = event.message
        await event.answer()
    else:
        message = event

    if user is None:
        await message.answer("Ошибка: пользователь не найден. Напишите /start.")
        return

    check = await task_manager.check_limit(user, "photos")
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
        photos = collected.get("photos", [])
        await state.set_state(PhotosStates.collecting)
        await state.update_data(task_id=task["id"])
        await message.answer(
            f"📂 У тебя есть незавершённая задача (фото: {len(photos)}).\n\n"
            f"Пришли ещё или нажми «🔍 Анализировать».",
            reply_markup=photos_actions(),
        )
        return

    # Новая задача
    task = await task_manager.create_task(
        user=user,
        task_type="photos",
        collected_data={"photos": []},
    )
    await state.update_data(task_id=task["id"])
    await state.set_state(PhotosStates.collecting)

    await message.answer(
        "📸 <b>Помощь с фотографиями</b>\n\n"
        "Пришли фото товара — от 1 до 10 штук.\n\n"
        "Я оценю каждое, скажу, какое лучше поставить главным, "
        "каких ракурсов не хватает и как лучше показать состояние.\n\n"
        "Фото можно присылать в любом порядке.",
        reply_markup=photos_actions(),
    )


# ============================================================
# ПРИЁМ ФОТО
# ============================================================
@router.message(PhotosStates.collecting, F.photo)
async def on_photo(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await message.answer("Ошибка: задача не найдена. Начните заново.")
        await state.clear()
        return

    task = await db.fetch_one("SELECT collected_data FROM tasks WHERE id = %s", (task_id,))
    if not task:
        return
    collected = task["collected_data"] or {}
    photos = collected.get("photos", [])

    if len(photos) >= MAX_PHOTOS:
        await message.answer(
            f"⚠️ Максимум {MAX_PHOTOS} фото. Нажми «🔍 Анализировать».",
            reply_markup=photos_actions(),
        )
        return

    photo = message.photo[-1]

    if any(p.get("file_unique_id") == photo.file_unique_id for p in photos):
        await message.answer("Это фото уже добавлено.")
        return

    photos.append({
        "file_id": photo.file_id,
        "file_unique_id": photo.file_unique_id,
    })
    collected["photos"] = photos

    await db.execute(
        "UPDATE tasks SET collected_data = %s::jsonb WHERE id = %s",
        (to_jsonb(collected), task_id),
    )

    await message.answer(
        f"📸 Фото добавлено (всего: {len(photos)}/{MAX_PHOTOS}).\n\n"
        f"Пришли ещё или нажми «🔍 Анализировать».",
        reply_markup=photos_actions(),
    )


# ============================================================
# КНОПКИ
# ============================================================
@router.callback_query(F.data == CB.PHOTOS_UPLOAD)
async def prompt_upload(callback: CallbackQuery) -> None:
    await callback.message.answer("📸 Пришли фото (можно несколько подряд).")
    await callback.answer()


@router.callback_query(F.data == CB.PHOTOS_ANALYZE)
async def run_analysis(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
    bot,
) -> None:
    logger.info(f"run_analysis (photos): user={callback.from_user.id}")

    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await callback.answer("Задача не найдена. Начните заново.", show_alert=True)
        await state.clear()
        return

    task = await db.fetch_one("SELECT collected_data FROM tasks WHERE id = %s", (task_id,))
    if not task:
        return
    collected = task["collected_data"] or {}
    photos = collected.get("photos", [])

    if not photos:
        await callback.answer(
            "Сначала пришли хотя бы одно фото.",
            show_alert=True,
        )
        return

    await callback.answer("Анализирую…")
    await callback.message.answer(
        f"✅ Принято {len(photos)} фото.\n\n"
        f"Анализирую через Vision. Это займёт до 60 секунд…"
    )
    await _run_analysis(callback.message, state, task_id, user, bot)


@router.callback_query(F.data == CB.PHOTOS_DONE)
async def done_photos(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    logger.info(f"done_photos: user={callback.from_user.id}")

    task_id = await _resolve_task_id(state, user["id"])
    if task_id:
        await task_manager.complete_task(task_id, status="done")

    await state.clear()

    try:
        await callback.message.edit_text("✅ Работа с фото завершена.")
    except Exception:
        pass

    await callback.message.answer(
        "Возвращаю в главное меню.",
        reply_markup=main_menu_reply(),
    )
    await callback.answer()


# ============================================================
# АНАЛИЗ ЧЕРЕЗ VISION
# ============================================================
async def _run_analysis(
    message: Message,
    state: FSMContext,
    task_id: int,
    user: dict,
    bot,
) -> None:
    logger.info(f"_run_analysis (photos): task_id={task_id}")

    task = await db.fetch_one("SELECT * FROM tasks WHERE id = %s", (task_id,))
    if not task:
        await message.answer("Ошибка: задача не найдена.")
        return

    collected = task["collected_data"] or {}
    photos = collected.get("photos", [])

    await state.set_state(PhotosStates.analyzing)

    try:
        result = await gigachat_vision_service.analyze_photos(
            bot=bot,
            photos=photos,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_user_prompt(len(photos)),
            temperature=0.4,
            max_tokens=2500,
        )
        logger.info("Vision: анализ завершён")
    except Exception as e:
        logger.exception(f"Ошибка Vision: {e}")
        await message.answer(
            "❌ Не удалось проанализировать фото. Попробуй позже.\n"
            "Лимит не списан.",
            reply_markup=cancel_and_back(),
        )
        await state.set_state(PhotosStates.collecting)
        return

    # Сохраняем результат
    await task_manager.set_result(task_id, result)

    # Формируем ответ
    text_lines = ["📸 <b>Анализ фотографий</b>\n"]

    if summary := result.get("summary"):
        text_lines.append(f"<i>{summary}</i>\n")

    best_idx = result.get("best_main_photo_index")
    best_reason = result.get("best_main_photo_reason")
    if best_idx and best_reason:
        text_lines.append(
            f"⭐ <b>Лучшее главное фото:</b> №{best_idx}\n"
            f"<i>{best_reason}</i>\n"
        )

    reviews = result.get("photo_reviews", [])
    if reviews:
        text_lines.append("<b>Разбор каждого фото:</b>")
        for r in reviews:
            idx = r.get("index", "?")
            visible = r.get("what_visible", "")
            text_lines.append(f"\n<b>Фото №{idx}</b>: {visible}")
            for p in r.get("pros", []):
                text_lines.append(f"  ✅ {p}")
            for c in r.get("cons", []):
                text_lines.append(f"  ⚠️ {c}")
        text_lines.append("")

    if missing := result.get("missing_shots"):
        text_lines.append("<b>📷 Каких ракурсов не хватает:</b>")
        for m in missing:
            text_lines.append(f"• {m}")
        text_lines.append("")

    if state_advice := result.get("state_advice"):
        text_lines.append("<b>🔍 Как показать состояние:</b>")
        for s in state_advice:
            text_lines.append(f"• {s}")
        text_lines.append("")

    if kit_advice := result.get("kit_advice"):
        text_lines.append("<b>📦 Как показать комплектацию:</b>")
        for k in kit_advice:
            text_lines.append(f"• {k}")
        text_lines.append("")

    if tips := result.get("general_tips"):
        text_lines.append("<b>💡 Общие советы:</b>")
        for t in tips:
            text_lines.append(f"• {t}")
        text_lines.append("")

    if first := result.get("what_to_fix_first"):
        text_lines.append(f"<b>🎯 Что исправить первым:</b> {first}")

    text = "\n".join(text_lines)

    if len(text) > 4000:
        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            await message.answer(chunk)
    else:
        await message.answer(text)

    await state.set_state(PhotosStates.done)

    # Предлагаем: ещё фото / анализировать снова / готово
    await message.answer(
        "Что дальше?\n\n"
        "• Пришли ещё фото — добавлю к анализу\n"
        "• «🔍 Анализировать» — перегенерирую с новыми фото (лимит не спишется)\n"
        "• «✅ Готово» — завершить",
        reply_markup=photos_actions(),
    )


# ============================================================
# ОТМЕНА
# ============================================================
@router.callback_query(F.data == CB.CANCEL, PhotosStates.collecting)
@router.callback_query(F.data == CB.CANCEL, PhotosStates.done)
async def cancel_photos(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    logger.info(f"cancel_photos: user={callback.from_user.id}")

    task_id = await _resolve_task_id(state, user["id"])
    if task_id:
        await task_manager.complete_task(task_id, status="cancelled")

    await state.clear()

    try:
        await callback.message.edit_text("❌ Работа с фото отменена.")
    except Exception:
        pass

    await callback.message.answer(
        "Возвращаю в главное меню.",
        reply_markup=main_menu_reply(),
    )
    await callback.answer("Отменено")