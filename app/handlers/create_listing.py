"""
Сценарий «Создать объявление» (блок 3 ТЗ).
Vision: если есть фото — GigaChat их видит.
Fallback: если Vision падает — работает только текст.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.database import db, to_jsonb
from app.prompts.create_listing import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_VISION,
    build_user_prompt,
    build_user_prompt_with_photos,
)
from app.services.gigachat_service import gigachat_service
from app.services.gigachat_vision import gigachat_vision_service
from app.services.task_manager import task_manager
from app.utils.keyboards import (
    CB,
    MENU,
    cancel_and_back,
    create_listing_after_photo,
    create_listing_ready,
    create_listing_start,
    listing_after_edit,
    listing_after_pick,
    listing_variants,
    main_menu_reply,
)

router = Router(name="create_listing")


class CreateStates(StatesGroup):
    collecting = State()
    choosing = State()
    editing = State()


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
        logger.warning(f"task_id={task_id} из state не активен, ищу в БД")

    task = await db.fetch_one(
        """
        SELECT id FROM tasks
        WHERE user_id = %s AND task_type = 'create_listing' AND status = 'active'
        ORDER BY created_at DESC LIMIT 1
        """,
        (user_id,),
    )
    if task:
        await state.update_data(task_id=task["id"])
        return task["id"]
    return None


async def _get_selected_listing(user_id: int) -> dict | None:
    return await db.fetch_one(
        """
        SELECT l.id, l.title, l.body, l.item_id, l.approach
        FROM listings l
        JOIN items i ON i.id = l.item_id
        WHERE i.user_id = %s AND l.is_selected = TRUE
        ORDER BY l.created_at DESC LIMIT 1
        """,
        (user_id,),
    )


# ============================================================
# ВХОД В СЦЕНАРИЙ
# ============================================================
@router.callback_query(F.data == CB.MENU_CREATE)
@router.message(F.text == MENU.CREATE)
async def start_create(
    event: Message | CallbackQuery,
    state: FSMContext,
    user: dict | None,
    db,
) -> None:
    logger.info(f"start_create: событие от {type(event).__name__}")

    if isinstance(event, CallbackQuery):
        message = event.message
        await event.answer()
    else:
        message = event

    if user is None:
        await message.answer("Ошибка: пользователь не найден. Напишите /start.")
        return

    check = await task_manager.check_limit(user, "create_listing")
    if not check.allowed:
        await message.answer(
            f"❌ <b>Лимит исчерпан</b>\n\n{check.reason}\n\n"
            f"Оформи PRO, чтобы продолжить: 💳 Тариф и подписка.",
        )
        return

    if check.existing_task:
        task = check.existing_task
        collected = task.get("collected_data") or {}
        photos = collected.get("photos", [])
        text = collected.get("extra", "")

        summary_lines = ["📂 <b>У тебя есть незавершённая задача</b>\n"]
        if photos:
            summary_lines.append(f"• Фото: {len(photos)} шт.")
        if text:
            preview = text[:100] + ("..." if len(text) > 100 else "")
            summary_lines.append(f"• Текст: {preview}")

        await state.set_state(CreateStates.collecting)
        await state.update_data(task_id=task["id"])
        await message.answer(
            "\n".join(summary_lines) + "\n\nПродолжаем или начнём заново?",
            reply_markup=create_listing_ready(),
        )
        return

    task = await task_manager.create_task(
        user=user,
        task_type="create_listing",
        collected_data={"photos": [], "extra": ""},
    )
    await state.update_data(task_id=task["id"])
    await state.set_state(CreateStates.collecting)

    await message.answer(
        "📝 <b>Создаём объявление</b>\n\n"
        "Пришли материалы о товаре в любом порядке:\n"
        "• 📸 Фото (можно несколько) — я их увижу\n"
        "• ✏️ Текст: что это, состояние, характеристики, цена\n\n"
        "Когда закончишь — нажми «✅ Материалов достаточно».",
        reply_markup=create_listing_start(),
    )


# ============================================================
# ФОТО
# ============================================================
@router.message(CreateStates.collecting, F.photo)
async def on_photo_received(
    message: Message,
    state: FSMContext,
    user: dict,
    db,
) -> None:
    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await message.answer("Ошибка: задача не найдена. Начните заново.")
        await state.clear()
        return

    photo = message.photo[-1]
    file_id = photo.file_id
    file_unique_id = photo.file_unique_id
    file_size = photo.file_size or 0

    task = await db.fetch_one("SELECT collected_data FROM tasks WHERE id = %s", (task_id,))
    if not task:
        return
    collected = task["collected_data"] or {}
    photos = collected.get("photos", [])

    if any(p.get("file_unique_id") == file_unique_id for p in photos):
        await message.answer("Это фото уже добавлено.")
        return

    photos.append({
        "file_id": file_id,
        "file_unique_id": file_unique_id,
        "file_size": file_size,
    })

    await db.execute(
        "UPDATE tasks SET collected_data = collected_data || %s::jsonb WHERE id = %s",
        (to_jsonb({"photos": photos}), task_id),
    )

    await task_manager.log_message(
        task_id, "user", f"[фото] размер {file_size // 1024} КБ",
        attachments=[{"type": "photo", "file_id": file_id}],
    )

    await message.answer(
        f"📸 Фото добавлено (всего: {len(photos)}).\n\n"
        "Добавь текст о товаре или пришли ещё фото.",
        reply_markup=create_listing_after_photo(),
    )


# ============================================================
# ТЕКСТ
# ============================================================
@router.message(CreateStates.collecting, F.text, ~F.text.startswith("/"))
async def on_text_received(
    message: Message,
    state: FSMContext,
    user: dict,
    db,
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
    existing = collected.get("extra", "")

    new_text = (existing + "\n\n" + message.text).strip() if existing else message.text

    await db.execute(
        "UPDATE tasks SET collected_data = collected_data || %s::jsonb WHERE id = %s",
        (to_jsonb({"extra": new_text}), task_id),
    )

    await task_manager.log_message(task_id, "user", message.text)

    preview = new_text[:300] + ("..." if len(new_text) > 300 else "")
    await message.answer(
        f"✏️ Текст сохранён.\n\n"
        f"<i>Текущий текст:</i>\n{preview}\n\n"
        f"Можно добавить ещё или запустить генерацию.",
        reply_markup=create_listing_ready(),
    )


# ============================================================
# КНОПКИ СБОРА
# ============================================================
@router.callback_query(F.data == CB.CREATE_ADD_PHOTO)
async def prompt_add_photo(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("📸 Пришли фото товара (можно несколько подряд).")
    await callback.answer()


@router.callback_query(F.data == CB.CREATE_ADD_TEXT)
async def prompt_add_text(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer(
        "✏️ Напиши, что за товар, состояние, характеристики, цену. Одним сообщением."
    )
    await callback.answer()


# ============================================================
# ГЕНЕРАЦИЯ
# ============================================================
@router.callback_query(F.data == CB.CREATE_DONE_MATERIALS)
@router.callback_query(F.data == CB.CREATE_GENERATE)
async def materials_done(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
    bot,
) -> None:
    logger.info(f"materials_done: user={callback.from_user.id}")

    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        await callback.answer("Задача не найдена. Начните заново.", show_alert=True)
        await state.clear()
        return

    await state.update_data(task_id=task_id)
    await state.set_state(CreateStates.choosing)

    await callback.answer("Запускаю генерацию…")
    await callback.message.answer(
        "✅ Материалы собраны.\n\n"
        "Запускаю генерацию трёх вариантов. Это займёт до 30 секунд…"
    )
    await _run_generation(callback.message, state, task_id, bot=bot)


async def _run_generation(
    message: Message,
    state: FSMContext,
    task_id: int,
    bot=None,
) -> None:
    logger.info(f"_run_generation: task_id={task_id}, bot={'есть' if bot else 'нет'}")

    task = await db.fetch_one("SELECT * FROM tasks WHERE id = %s", (task_id,))
    if not task:
        await message.answer("Ошибка: задача не найдена.")
        return

    collected = task["collected_data"] or {}
    photos = collected.get("photos", [])
    text = collected.get("extra", "").strip()

    if not text and not photos:
        await message.answer(
            "Недостаточно данных для генерации. "
            "Пришли хотя бы текст о товаре или фото.",
            reply_markup=create_listing_start(),
        )
        return

    result = None

    # --- Vision ---
    if photos and bot is not None:
        try:
            logger.info(f"_run_generation: пробую Vision ({len(photos)} фото)")
            user_prompt = build_user_prompt_with_photos(collected)
            result = await gigachat_vision_service.analyze_with_photos_json(
                bot=bot,
                photos=photos,
                system_prompt=SYSTEM_PROMPT_VISION,
                user_prompt=user_prompt,
                temperature=0.6,
                max_tokens=3500,
            )
            logger.info("_run_generation: Vision успешен")
        except Exception as e:
            logger.warning(f"_run_generation: Vision упал, fallback на текст: {e}")
            result = None

    # --- Fallback: текст ---
    if result is None:
        try:
            logger.info("_run_generation: текстовый режим")
            user_prompt = build_user_prompt({
                "extra": text,
                "photos_count": len(photos),
            })
            result = await gigachat_service.generate_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.6,
                max_tokens=3000,
            )
        except Exception as e:
            logger.exception(f"Ошибка генерации: {e}")
            await task_manager.complete_task(task_id, status="failed", technical_failure=True)
            await message.answer(
                "❌ Не удалось сгенерировать объявление. Попробуй позже.\nЛимит не списан.",
                reply_markup=cancel_and_back(),
            )
            return

    variants = result.get("variants", [])
    if not variants:
        await task_manager.complete_task(task_id, status="failed", technical_failure=True)
        await message.answer(
            "❌ GigaChat вернул пустой ответ. Попробуй ещё раз.",
            reply_markup=cancel_and_back(),
        )
        return

    await task_manager.set_result(task_id, {"variants": variants})
    await state.update_data(task_id=task_id, variants=variants)

    approach_names = {
        "factual": "1️⃣ Фактический",
        "friendly": "2️⃣ Дружелюбный",
        "alternative": "3️⃣ Альтернативный",
    }

    for i, variant in enumerate(variants[:3], start=1):
        approach = variant.get("approach", "")
        header = approach_names.get(approach, f"Вариант {i}")
        title = variant.get("title", "")
        body = variant.get("body", "")

        await message.answer(f"<b>{header}</b>\n\n<b>{title}</b>\n\n{body}")

    await message.answer(
        "Выбери вариант, который нравится больше:",
        reply_markup=listing_variants(),
    )


# ============================================================
# ВЫБОР ВАРИАНТА
# ============================================================
@router.callback_query(F.data.in_({CB.LISTING_PICK_1, CB.LISTING_PICK_2, CB.LISTING_PICK_3}))
async def pick_variant(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    logger.info(f"pick_variant: {callback.data}")

    task_id = await _resolve_task_id(state, user["id"])
    if not task_id:
        task = await db.fetch_one(
            """
            SELECT * FROM tasks
            WHERE user_id = %s AND task_type = 'create_listing'
              AND result IS NOT NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            (user["id"],),
        )
        if not task:
            await callback.answer("Задача потеряна. Начните заново.", show_alert=True)
            await state.clear()
            return
        task_id = task["id"]

    idx = {CB.LISTING_PICK_1: 0, CB.LISTING_PICK_2: 1, CB.LISTING_PICK_3: 2}[callback.data]

    task = await db.fetch_one("SELECT * FROM tasks WHERE id = %s", (task_id,))
    if not task or not task["result"]:
        await callback.answer("Результат потерян.", show_alert=True)
        return

    variants = task["result"].get("variants", [])
    if idx >= len(variants):
        await callback.answer("Вариант не найден.", show_alert=True)
        return

    variant = variants[idx]

    item = await db.execute_returning(
        "INSERT INTO items (user_id, name) VALUES (%s, %s) RETURNING *",
        (user["id"], variant.get("title", "Без названия")[:100]),
    )

    await db.execute(
        """
        INSERT INTO listings (item_id, task_id, version, approach, title, body, is_selected)
        VALUES (%s, %s, 1, %s, %s, %s, TRUE)
        """,
        (
            item["id"],
            task_id,
            variant.get("approach", "factual"),
            variant.get("title", ""),
            variant.get("body", ""),
        ),
    )

    await task_manager.complete_task(
        task_id, status="done",
        result={"variants": variants, "selected_index": idx},
    )

    await state.update_data(
        item_id=item["id"],
        selected_variant=variant,
        selected_variant_index=idx,
        task_id=task_id,
    )
    await state.set_state(CreateStates.editing)

    approach_label = {
        "factual": "Фактический",
        "friendly": "Дружелюбный",
        "alternative": "Альтернативный",
    }.get(variant.get("approach", ""), f"Вариант {idx + 1}")

    await callback.message.answer(
        f"✅ <b>Выбран вариант: {approach_label}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{variant.get('title', '')}</b>\n\n"
        f"{variant.get('body', '')}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"Что дальше?",
        reply_markup=listing_after_pick(),
    )
    await callback.answer("Сохранено")


@router.callback_query(F.data == CB.LISTING_COPY)
async def show_again(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    listing = await _get_selected_listing(user["id"])
    if not listing:
        await callback.answer("Нечего показывать", show_alert=True)
        return

    await callback.message.answer(
        f"<b>{listing['title']}</b>\n\n{listing['body']}"
    )
    await callback.answer()


# ============================================================
# ПЕРЕГЕНЕРАЦИЯ
# ============================================================
@router.callback_query(F.data == CB.LISTING_REGEN)
async def regenerate(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
    bot,
) -> None:
    logger.info(f"regenerate: user={callback.from_user.id}")

    task = await db.fetch_one(
        """
        SELECT id, status FROM tasks
        WHERE user_id = %s AND task_type = 'create_listing'
        ORDER BY created_at DESC LIMIT 1
        """,
        (user["id"],),
    )

    if not task:
        await callback.answer("Нечего перегенерировать. Начните заново.", show_alert=True)
        return

    if task["status"] != "active":
        old_task = await db.fetch_one(
            "SELECT collected_data FROM tasks WHERE id = %s", (task["id"],),
        )
        collected = old_task["collected_data"] if old_task else {}

        new_task = await task_manager.create_task(
            user=user,
            task_type="create_listing",
            collected_data=collected,
        )
        task_id = new_task["id"]
        logger.info(f"Создана новая задача для перегенерации: id={task_id}")
    else:
        task_id = task["id"]

    await state.update_data(task_id=task_id)
    await state.set_state(CreateStates.choosing)

    await callback.answer("Генерирую заново…")

    message = callback.message
    await message.answer("🔄 Генерирую заново…")
    await _run_generation(message, state, task_id, bot=bot)


# ============================================================
# РЕДАКТИРОВАНИЕ
# ============================================================
@router.callback_query(F.data == CB.LISTING_EDIT)
async def edit_listing(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    logger.info(f"edit_listing: user={callback.from_user.id}")

    listing = await _get_selected_listing(user["id"])
    if not listing:
        await callback.answer(
            "Сначала выбери вариант (1/2/3), потом редактируй.",
            show_alert=True,
        )
        return

    await state.update_data(item_id=listing["item_id"])
    await state.set_state(CreateStates.editing)

    await callback.message.answer(
        f"✏️ <b>Редактирование</b>\n\n"
        f"<b>Текущий текст:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{listing['title']}</b>\n\n"
        f"{listing['body']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"Пришли <b>новый текст</b> объявления одним сообщением.\n\n"
        f"Или <b>новый заголовок</b>, начиная со слова «Заголовок:».\n\n"
        f"Пример: <code>Заголовок: Диван 180 см б/у</code>"
    )
    await callback.answer()


@router.message(CreateStates.editing, F.text)
async def on_edit_text(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    data = await state.get_data()
    item_id = data.get("item_id")

    if not item_id:
        await message.answer("Ошибка: карточка не найдена.")
        await state.clear()
        return

    if text.lower().startswith("заголовок:"):
        new_title = text.split(":", 1)[1].strip()
        await db.execute(
            "UPDATE listings SET title = %s WHERE item_id = %s AND is_selected = TRUE",
            (new_title, item_id),
        )
        action = "Заголовок обновлён"
    else:
        await db.execute(
            "UPDATE listings SET body = %s WHERE item_id = %s AND is_selected = TRUE",
            (text, item_id),
        )
        action = "Текст обновлён"

    updated = await db.fetch_one(
        "SELECT title, body FROM listings WHERE item_id = %s AND is_selected = TRUE",
        (item_id,),
    )

    if not updated:
        await message.answer("Ошибка: не удалось загрузить обновлённый текст.")
        return

    await message.answer(
        f"✅ <b>{action}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{updated['title']}</b>\n\n"
        f"{updated['body']}\n"
        f"━━━━━━━━━━━━━━━━━━━",
        reply_markup=listing_after_edit(),
    )


# ============================================================
# ОТМЕНА
# ============================================================
@router.callback_query(F.data == CB.CANCEL, CreateStates.collecting)
@router.callback_query(F.data == CB.CANCEL, CreateStates.choosing)
async def cancel_create(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    logger.info(f"cancel_create: user={callback.from_user.id}")

    task_id = await _resolve_task_id(state, user["id"])
    if task_id:
        await task_manager.complete_task(task_id, status="cancelled")

    await state.clear()

    try:
        await callback.message.edit_text("❌ Создание объявления отменено.")
    except Exception as e:
        logger.debug(f"edit_text не сработал: {e}")

    await callback.message.answer(
        "Возвращаю в главное меню.",
        reply_markup=main_menu_reply(),
    )
    await callback.answer("Отменено")