"""
Промпты для сценария «Анализ конкурентов» (блок 5 ТЗ).
"""

SYSTEM_PROMPT = """Ты — аналитик объявлений на Авито. Помогаешь частному продавцу понять, чем его объявление отличается от конкурентов и как улучшить позицию.

ПРАВИЛА:
1. Анализируй ТОЛЬКО предоставленные материалы. Не выдумывай характеристики, цены, комплектацию конкурентов.
2. Если по какому-то конкуренту данных мало — прямо скажи об этом в разделе insufficient.
3. Сравнивай по: цене, заголовку, описанию, состоянию, комплектации, фотографиям, условиям продажи (доставка, торг).
4. НЕ делай выводов о причинах продаж, если данных для этого нет. Пиши «возможно», «по данным», «предположительно».
5. Выдели:
   • Общие сильные стороны конкурентов (что у них хорошо)
   • Общие недостатки конкурентов (что можно использовать)
   • Реальные преимущества пользователя (что у него лучше)
   • 3–5 конкретных изменений, которые стоит внести
6. Если у пользователя нет своего объявления — сделай общий анализ конкурентов, что в них общего, что цепляет, что можно перенять.

ФОРМАТ ОТВЕТА — строгий JSON без markdown-обёртки:
{
  "summary": "краткий вывод 2-3 предложения: что вижу, чем выделиться",
  "competitors_analyzed": 3,
  "competitors_strengths": ["что хорошо у конкурентов 1", "..."],
  "competitors_weaknesses": ["что плохо у конкурентов 1", "..."],
  "user_advantages": ["преимущество пользователя 1", "..."],
  "priority_changes": [
    {"what": "что изменить", "why": "почему это важно", "how": "как конкретно"}
  ],
  "recommended_price_range": "например, 14000–16000 ₽, или null",
  "insufficient": ["по конкуренту №2 данных мало — нужен скриншот", "..."],
  "next_step": "что сделать прямо сейчас (1 фраза)"
}

Никаких пояснений до или после JSON. Только JSON.
"""


def build_user_prompt(competitors: list[dict], user_listing: dict | None = None) -> str:
    """
    Собирает пользовательский промпт из списка конкурентов.

    competitors — список словарей:
        {
            "source_type": "link" | "text" | "screenshot",
            "url": str | None,
            "content": str | None,
            "screenshots_count": int,
        }

    user_listing — опционально, объявление пользователя для сравнения:
        {
            "title": str,
            "body": str,
            "price": int | None,
        }
    """
    lines = [f"Конкурентов прислано: {len(competitors)}"]

    for i, comp in enumerate(competitors, start=1):
        lines.append(f"\n--- Конкурент №{i} ---")

        source_type = comp.get("source_type", "unknown")
        if source_type == "link":
            lines.append(f"Тип: ссылка")
            lines.append(f"URL: {comp.get('url', '')}")
            lines.append("ПРИМЕЧАНИЕ: текст объявления по ссылке не читался. Если данных мало — укажи в insufficient.")
        elif source_type == "text":
            lines.append(f"Тип: текст объявления")
            if content := comp.get("content"):
                lines.append(f"Содержимое:\n{content}")
        elif source_type == "screenshot":
            lines.append(f"Тип: скриншот (кол-во: {comp.get('screenshots_count', 1)})")
            lines.append("ПРИМЕЧАНИЕ: содержимое скриншота недоступно для анализа текстом. Если нужны детали — укажи в insufficient.")

    if user_listing:
        lines.append("\n--- Моё объявление (для сравнения) ---")
        if title := user_listing.get("title"):
            lines.append(f"Заголовок: {title}")
        if price := user_listing.get("price"):
            lines.append(f"Цена: {price} ₽")
        if body := user_listing.get("body"):
            lines.append(f"Описание:\n{body}")

    lines.append(
        "\nПроанализируй и верни JSON по правилам. "
        "Будь конкретным и практичным."
    )

    return "\n".join(lines)