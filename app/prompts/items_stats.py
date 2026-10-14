"""
Промпт для анализа статистики товара (блок 9 ТЗ).
"""

SYSTEM_PROMPT = """Ты — аналитик продаж на Авито. Помогаешь продавцу понять, что происходит с его товаром, и что попробовать дальше.

Твоя задача — по истории показателей и изменений сделать краткий вывод и предложить ОДИН следующий шаг.

ПРАВИЛА:
1. Сравнивай показатели ТОЛЬКО если есть данные за разные периоды. Не выдумывай.
2. Учитывай изменения: цена, текст, фото, условия.
3. Отделяй наблюдаемые изменения от возможных объяснений:
   • «просмотры выросли с 10 до 45» — это наблюдение
   • «вероятно, из-за смены главного фото» — это предположение, помечай «возможно»
4. Не делай выводов о причинах, если данных для этого нет.
5. Предложи РОВНО ОДИН следующий шаг, который поможет проверить гипотезу.
6. Если данных мало — прямо скажи об этом.

ФОРМАТ ОТВЕТА — строгий JSON без markdown-обёртки:
{
  "summary": "краткий вывод 2-3 предложения",
  "observations": [
    "наблюдение 1 (факт)",
    "наблюдение 2 (факт)"
  ],
  "hypotheses": [
    "возможно, причина в ...",
    "..."
  ],
  "next_step": {
    "action": "что сделать конкретно (1 фраза)",
    "why": "почему это поможет",
    "when_to_check": "когда проверить результат"
  },
  "insufficient_data": false
}

Никаких пояснений до или после JSON. Только JSON.
"""


def build_user_prompt(item: dict, listings: list[dict], stats: list[dict], price_history: list[dict]) -> str:
    """
    Собирает промпт для анализа статистики товара.

    item: {name, current_price, status, created_at}
    listings: [{title, body, approach, is_selected, created_at}]
    stats: [{views, favorites, messages, outcome, price_at_entry, created_at}]
    price_history: [{price, date, reason}]
    """
    lines = ["Товар:"]
    lines.append(f"• Название: {item.get('name', '—')}")
    lines.append(f"• Текущая цена: {item.get('current_price', '—')} ₽")
    lines.append(f"• Статус: {item.get('status', '—')}")

    if item.get("created_at"):
        lines.append(f"• Создан: {item['created_at']}")

    # Версии текста
    if listings:
        lines.append(f"\nВерсий текста: {len(listings)}")
        for i, l in enumerate(listings[:5], 1):
            marker = " ← ВЫБРАН" if l.get("is_selected") else ""
            lines.append(f"  {i}. [{l.get('approach', '?')}] {l.get('title', '')[:60]}{marker}")

    # Цена
    if price_history:
        lines.append(f"\nИстория цены ({len(price_history)}):")
        for p in price_history[-5:]:
            lines.append(f"  • {p.get('date', '?')}: {p.get('price', '?')} ₽ ({p.get('reason', '—')})")
    else:
        lines.append("\nИстория цены: нет изменений")

    # Статистика
    if stats:
        lines.append(f"\nСтатистика ({len(stats)} записей):")
        for s in stats[-10:]:
            parts = []
            if s.get("views") is not None:
                parts.append(f"просмотры={s['views']}")
            if s.get("favorites") is not None:
                parts.append(f"избранное={s['favorites']}")
            if s.get("messages") is not None:
                parts.append(f"сообщения={s['messages']}")
            if s.get("outcome"):
                parts.append(f"итог={s['outcome']}")
            if s.get("price_at_entry"):
                parts.append(f"цена={s['price_at_entry']}₽")
            lines.append(f"  • {s.get('created_at', '?')}: {', '.join(parts)}")
    else:
        lines.append("\nСтатистика: не вводилась")
        lines.append("Это первый ввод статистики — не с чем сравнивать.")

    lines.append(
        "\nПроанализируй и верни JSON. "
        "Если данных мало — укажи insufficient_data=true. "
        "Только JSON."
    )

    return "\n".join(lines)