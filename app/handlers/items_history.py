"""
Сценарий «Мои объявления» (блок 9 ТЗ).

Список товаров, детали карточки, статистика, история, рекомендации.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from app.database import db, to_jsonb
from app.prompts.items_stats import SYSTEM_PROMPT, build_user_prompt
from app.services.gigachat_service import gigachat_service
from app.utils.keyboards import (
    CB,
    MENU,
    cancel_and_back,
    item_after_action,
    main_menu_reply,
)

router = Router(name="items_history")


class ItemsStates(StatesGroup):
    viewing_list = State()
    viewing_item = State()
    entering_stats = State()
    entering_price = State()
    analyzing = State()


def _btn(text: str, callback: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback)


# ============================================================
# УТИЛИТЫ
# ============================================================
async def _get_user_items(user_id: int) -> list[dict]:
    return await db.fetch_all(
        """
        SELECT
            i.id, i.name, i.current_price, i.status, i.created_at,
            (SELECT COUNT(*) FROM listings WHERE item_id = i.id) AS versions_count,
            (SELECT title FROM listings WHERE item_id = i.id AND is_selected = TRUE LIMIT 1) AS selected_title,
            (SELECT created_at FROM stats_entries WHERE item_id = i.id ORDER BY created_at DESC LIMIT 1) AS last_stats_date
        FROM items i
        WHERE i.user_id = %s
        ORDER BY i.created_at DESC
        """,
        (user_id,),
    )


async def _get_item_detail(item_id: int, user_id: int) -> dict | None:
    return await db.fetch_one(
        "SELECT * FROM items WHERE id = %s AND user_id = %s",
        (item_id, user_id),
    )


def _extract_int(text: str, keywords: list[str]) -> int | None:
    """Извлекает целое число после одного из ключевых слов."""
    for kw in keywords:
        pattern = rf"{kw}[а-я]*\D{{0,15}}(\d+)"
        m = re.search(pattern, text)
        if m:
            return int(m.group(1))
    return None


async def _show_item_card(
    message: Message,
    user: dict,
    item_id: int,
    state: FSMContext,
) -> None:
    """Отправляет карточку товара сообщением."""
    item = await _get_item_detail(item_id, user["id"])
    if not item:
        await message.answer("Товар не найден.")
        return

    listings = await db.fetch_all(
        "SELECT * FROM listings WHERE item_id = %s ORDER BY created_at DESC",
        (item_id,),
    )
    stats = await db.fetch_all(
        "SELECT * FROM stats_entries WHERE item_id = %s ORDER BY created_at DESC LIMIT 10",
        (item_id,),
    )
    price_history = item.get("price_history") or []

    lines = [f"📦 <b>{item['name']}</b>\n"]

    status_label = {"active": "🟢 В продаже", "sold": "✅ Продано", "archived": "📦 В архиве"}.get(
        item["status"], item["status"]
    )
    lines.append(f"Статус: {status_label}")

    if item.get("current_price"):
        lines.append(f"Цена: <b>{item['current_price']} ₽</b>")

    if item.get("sale_reason"):
        lines.append(f"Причина продажи: {item['sale_reason']}")

    lines.append(f"Создан: {item['created_at'].strftime('%d.%m.%Y')}")

    if listings:
        lines.append(f"\n<b>Версий текста:</b> {len(listings)}")
        for i, l in enumerate(listings[:3], 1):
            marker = " ←" if l.get("is_selected") else ""
            lines.append(f"{i}. [{l['approach']}] {l['title'][:40]}{marker}")

    if stats:
        last = stats[0]
        lines.append(f"\n<b>Последняя статистика</b> ({last['created_at'].strftime('%d.%m.%Y')}):")
        parts = []
        if last.get("views") is not None:
            parts.append(f"👁 {last['views']}")
        if last.get("favorites") is not None:
            parts.append(f"⭐ {last['favorites']}")
        if last.get("messages") is not None:
            parts.append(f"💬 {last['messages']}")
        lines.append(" · ".join(parts) if parts else "нет данных")
    else:
        lines.append("\n<b>Статистика:</b> пока не вводилась")

    if price_history:
        lines.append(f"\n<b>История цены:</b> {len(price_history)} изменений")

    text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    builder.row(_btn("📊 Ввести статистику", f"item:stats:{item_id}"))
    builder.row(_btn("💰 Изменить цену", f"item:price:{item_id}"))
    builder.row(_btn("📝 Показать текст", f"item:text:{item_id}"))
    builder.row(_btn("🔄 Сменить версию текста", f"item:switch:{item_id}"))

    if item["status"] == "active":
        builder.row(_btn("✅ Пометить как «продано»", f"item:sold:{item_id}"))

    builder.row(_btn("🤖 Получить рекомендацию", f"item:advice:{item_id}"))
    builder.row(_btn("🔙 К списку", CB.MENU_ITEMS))

    await state.set_state(ItemsStates.viewing_item)
    await state.update_data(item_id=item_id)

    await message.answer(text, reply_markup=builder.as_markup())


# ============================================================
# СПИСОК ТОВАРОВ
# ============================================================
@router.callback_query(F.data == CB.MENU_ITEMS)
@router.message(F.text == MENU.ITEMS)
async def show_items(
    event: Message | CallbackQuery,
    state: FSMContext,
    user: dict | None,
) -> None:
    logger.info(f"show_items: событие от {type(event).__name__}")

    if isinstance(event, CallbackQuery):
        message = event.message
        await event.answer()
    else:
        message = event

    if user is None:
        await message.answer("Ошибка: пользователь не найден. Напишите /start.")
        return

    items = await _get_user_items(user["id"])

    if not items:
        await state.clear()
        await message.answer(
            "📂 <b>Мои объявления</b>\n\n"
            "У тебя пока нет сохранённых товаров.\n\n"
            "Создай первое объявление — оно сохранится автоматически "
            "после выбора одного из вариантов.",
            reply_markup=main_menu_reply(),
        )
        return

    builder = InlineKeyboardBuilder()

    lines = [f"📂 <b>Мои объявления</b> ({len(items)})\n"]

    for i, it in enumerate(items, 1):
        status_emoji = {"active": "🟢", "sold": "✅", "archived": "📦"}.get(it["status"], "❓")
        price = f"{it['current_price']} ₽" if it.get("current_price") else "цена не указана"
        title = it.get("selected_title") or it.get("name") or "Без названия"
        title_short = title[:40] + ("…" if len(title) > 40 else "")

        lines.append(f"{status_emoji} <b>{title_short}</b>")
        lines.append(f"    {price} · версий: {it['versions_count']}")

        builder.row(_btn(f"{status_emoji} {title_short}", f"item:view:{it['id']}"))

    builder.row(_btn("🏠 В главное меню", CB.MENU_MAIN))

    await state.set_state(ItemsStates.viewing_list)
    await message.answer("\n".join(lines), reply_markup=builder.as_markup())


# ============================================================
# КАРТОЧКА ТОВАРА
# ============================================================
@router.callback_query(F.data.startswith("item:view:"))
async def view_item(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    item_id = int(callback.data.split(":")[2])
    logger.info(f"view_item: item_id={item_id}")

    await callback.answer()
    await _show_item_card(callback.message, user, item_id, state)


# ============================================================
# ПРОСМОТР ТЕКСТА
# ============================================================
@router.callback_query(F.data.startswith("item:text:"))
async def show_text(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    item_id = int(callback.data.split(":")[2])

    listing = await db.fetch_one(
        """
        SELECT title, body, approach FROM listings
        WHERE item_id = %s AND is_selected = TRUE
        LIMIT 1
        """,
        (item_id,),
    )
    if not listing:
        await callback.answer("Текст не найден.", show_alert=True)
        return

    await callback.message.answer(
        f"📝 <b>{listing['title']}</b>\n\n{listing['body']}",
        reply_markup=item_after_action(item_id),
    )
    await callback.answer()


# ============================================================
# СМЕНА ВЕРСИИ ТЕКСТА
# ============================================================
@router.callback_query(F.data.startswith("item:switch:"))
async def switch_version(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    item_id = int(callback.data.split(":")[2])

    listings = await db.fetch_all(
        "SELECT id, title, approach, is_selected FROM listings WHERE item_id = %s ORDER BY created_at DESC",
        (item_id,),
    )
    if len(listings) < 2:
        await callback.answer("Доступна только одна версия текста.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for l in listings:
        marker = "✅ " if l["is_selected"] else ""
        builder.row(_btn(
            f"{marker}[{l['approach']}] {l['title'][:40]}",
            f"item:setversion:{item_id}:{l['id']}",
        ))
    builder.row(_btn("🔙 Назад", f"item:view:{item_id}"))

    await callback.message.answer(
        "Выбери версию текста, которую хочешь сделать основной:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("item:setversion:"))
async def set_version(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    parts = callback.data.split(":")
    item_id = int(parts[2])
    listing_id = int(parts[3])

    await db.execute(
        "UPDATE listings SET is_selected = FALSE WHERE item_id = %s",
        (item_id,),
    )
    await db.execute(
        "UPDATE listings SET is_selected = TRUE WHERE id = %s",
        (listing_id,),
    )

    await callback.answer("Версия выбрана")
    await callback.message.answer("✅ Версия текста обновлена.")
    await _show_item_card(callback.message, user, item_id, state)


# ============================================================
# ВВОД СТАТИСТИКИ
# ============================================================
@router.callback_query(F.data.startswith("item:stats:"))
async def ask_stats(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    item_id = int(callback.data.split(":")[2])
    await state.update_data(item_id=item_id)
    await state.set_state(ItemsStates.entering_stats)

    await callback.message.answer(
        "📊 <b>Ввод статистики</b>\n\n"
        "Пришли данные в одном сообщении:\n\n"
        "<code>Просмотры: 45, избранное: 2, сообщения: 0</code>\n\n"
        "Можно только часть — например, только просмотры.\n"
        "Можно добавить итог:\n"
        "<code>Просмотры: 45, избранное: 2, сообщения: 1, итог: продано</code>",
        reply_markup=cancel_and_back(),
    )
    await callback.answer()


@router.message(ItemsStates.entering_stats, F.text)
async def on_stats_input(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    text = (message.text or "").strip().lower()

    views = _extract_int(text, ["просмотр"])
    favorites = _extract_int(text, ["избранн"])
    messages_cnt = _extract_int(text, ["сообщени"])

    outcome = None
    if "продано" in text or "продал" in text:
        outcome = "sold"
    elif "нет результата" in text or "не продаётся" in text:
        outcome = "no_result"

    if views is None and favorites is None and messages_cnt is None and outcome is None:
        await message.answer(
            "🤔 Не получилось распознать. Пришли в формате:\n\n"
            "<code>Просмотры: 45, избранное: 2, сообщения: 0</code>"
        )
        return

    data = await state.get_data()
    item_id = data.get("item_id")
    if not item_id:
        await message.answer("Ошибка: товар не найден.")
        await state.clear()
        return

    item = await _get_item_detail(item_id, user["id"])
    if not item:
        await message.answer("Товар не найден.")
        await state.clear()
        return

    await db.execute(
        """
        INSERT INTO stats_entries (
            item_id, user_id, views, favorites, messages,
            outcome, price_at_entry, source
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'manual')
        """,
        (
            item_id, user["id"], views, favorites, messages_cnt,
            outcome, item.get("current_price"),
        ),
    )

    if outcome == "sold":
        await db.execute(
            "UPDATE items SET status = 'sold' WHERE id = %s",
            (item_id,),
        )

    parts = []
    if views is not None:
        parts.append(f"просмотры: {views}")
    if favorites is not None:
        parts.append(f"избранное: {favorites}")
    if messages_cnt is not None:
        parts.append(f"сообщения: {messages_cnt}")
    if outcome:
        parts.append(f"итог: {outcome}")

    await state.set_state(ItemsStates.viewing_item)

    await message.answer(
        f"✅ <b>Статистика сохранена:</b>\n" + "\n".join(f"• {p}" for p in parts),
        reply_markup=item_after_action(item_id),
    )


# ============================================================
# ИЗМЕНЕНИЕ ЦЕНЫ
# ============================================================
@router.callback_query(F.data.startswith("item:price:"))
async def ask_price(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    item_id = int(callback.data.split(":")[2])
    await state.update_data(item_id=item_id)
    await state.set_state(ItemsStates.entering_price)

    await callback.message.answer(
        "💰 <b>Изменение цены</b>\n\n"
        "Пришли новую цену одним числом. Например: <code>55000</code>\n\n"
        "Или с причиной: <code>55000 — снизил для быстрой продажи</code>",
        reply_markup=cancel_and_back(),
    )
    await callback.answer()


@router.message(ItemsStates.entering_price, F.text)
async def on_price_input(
    message: Message,
    state: FSMContext,
    user: dict,
) -> None:
    text = (message.text or "").strip()

    m = re.search(r"\d[\d\s]*", text)
    if not m:
        await message.answer("🤔 Не вижу числа. Пришли цену, например: <code>55000</code>")
        return

    new_price = int(m.group(0).replace(" ", ""))
    reason = text[m.end():].strip(" —-—:") or None

    data = await state.get_data()
    item_id = data.get("item_id")
    if not item_id:
        await message.answer("Ошибка: товар не найден.")
        await state.clear()
        return

    item = await _get_item_detail(item_id, user["id"])
    if not item:
        await message.answer("Товар не найден.")
        await state.clear()
        return

    old_price = item.get("current_price")
    price_history = item.get("price_history") or []

    price_history.append({
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "price": new_price,
        "reason": reason or "без указания причины",
        "old_price": old_price,
    })

    await db.execute(
        """
        UPDATE items
        SET current_price = %s, price_history = %s::jsonb
        WHERE id = %s
        """,
        (new_price, to_jsonb(price_history), item_id),
    )

    await state.set_state(ItemsStates.viewing_item)

    msg = f"✅ Цена обновлена: <b>{new_price} ₽</b>"
    if old_price:
        msg += f"\nБыло: {old_price} ₽"
    if reason:
        msg += f"\n<i>Причина: {reason}</i>"

    await message.answer(msg, reply_markup=item_after_action(item_id))


# ============================================================
# ПОМЕТИТЬ ПРОДАНО
# ============================================================
@router.callback_query(F.data.startswith("item:sold:"))
async def mark_sold(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    item_id = int(callback.data.split(":")[2])
    item = await _get_item_detail(item_id, user["id"])
    if not item:
        await callback.answer("Товар не найден.", show_alert=True)
        return

    await db.execute(
        "UPDATE items SET status = 'sold' WHERE id = %s",
        (item_id,),
    )

    await db.execute(
        """
        INSERT INTO stats_entries (item_id, user_id, outcome, price_at_entry, source)
        VALUES (%s, %s, 'sold', %s, 'manual')
        """,
        (item_id, user["id"], item.get("current_price")),
    )

    await callback.answer("✅ Продано!")
    await callback.message.answer(
        "🎉 <b>Поздравляю с продажей!</b>\n\nТовар помечен как проданный.",
        reply_markup=item_after_action(item_id),
    )


# ============================================================
# РЕКОМЕНДАЦИЯ
# ============================================================
@router.callback_query(F.data.startswith("item:advice:"))
async def get_advice(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
) -> None:
    item_id = int(callback.data.split(":")[2])
    logger.info(f"get_advice: item_id={item_id}")

    item = await _get_item_detail(item_id, user["id"])
    if not item:
        await callback.answer("Товар не найден.", show_alert=True)
        return

    listings = await db.fetch_all(
        "SELECT * FROM listings WHERE item_id = %s ORDER BY created_at DESC",
        (item_id,),
    )
    stats = await db.fetch_all(
        "SELECT * FROM stats_entries WHERE item_id = %s ORDER BY created_at DESC LIMIT 15",
        (item_id,),
    )
    price_history = item.get("price_history") or []

    await callback.answer("Анализирую…")
    await callback.message.answer("🤖 Анализирую статистику. Это займёт 10–20 секунд…")

    user_prompt = build_user_prompt(item, listings, stats, price_history)

    try:
        result = await gigachat_service.generate_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.4,
            max_tokens=1500,
            user_id=user["id"],
        )
    except Exception as e:
        logger.exception(f"Ошибка анализа: {e}")
        await callback.message.answer(
            "❌ Не удалось проанализировать. Попробуй позже.",
            reply_markup=item_after_action(item_id),
        )
        return

    lines = ["🤖 <b>Рекомендация</b>\n"]

    if summary := result.get("summary"):
        lines.append(f"<i>{summary}</i>\n")

    if obs := result.get("observations"):
        lines.append("<b>📊 Наблюдения:</b>")
        for o in obs:
            lines.append(f"• {o}")
        lines.append("")

    if hyp := result.get("hypotheses"):
        lines.append("<b>💭 Возможные объяснения:</b>")
        for h in hyp:
            lines.append(f"• {h}")
        lines.append("")

    if step := result.get("next_step"):
        lines.append("<b>➡️ Следующий шаг:</b>")
        lines.append(f"<b>{step.get('action', '')}</b>")
        if why := step.get("why"):
            lines.append(f"<i>Почему:</i> {why}")
        if when := step.get("when_to_check"):
            lines.append(f"<i>Проверить:</i> {when}")

    if result.get("insufficient_data"):
        lines.append("\n⚠️ <i>Данных мало для точных выводов. Введи ещё статистику через 2-3 дня.</i>")

    await callback.message.answer(
        "\n".join(lines),
        reply_markup=item_after_action(item_id),
    )


# ============================================================
# ОТМЕНА
# ============================================================
@router.callback_query(F.data == CB.CANCEL, ItemsStates.entering_stats)
@router.callback_query(F.data == CB.CANCEL, ItemsStates.entering_price)
async def cancel_items(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    item_id = data.get("item_id")

    await state.clear()

    try:
        await callback.message.edit_text("❌ Отменено.")
    except Exception:
        pass

    if item_id:
        await callback.message.answer(
            "Возвращаю к карточке товара.",
            reply_markup=item_after_action(item_id),
        )
    else:
        await callback.message.answer(
            "Возвращаю в главное меню.",
            reply_markup=main_menu_reply(),
        )
    await callback.answer("Отменено")