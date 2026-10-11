import asyncio
from app.database import db


async def main():
    await db.connect()

    # Проверяем, что таблицы создались
    tables = await db.fetch_all(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
        """
    )
    print("📋 Созданные таблицы:")
    for t in tables:
        print(f"   • {t['table_name']}")

    # Проверяем INSERT + RETURNING
    row = await db.execute_returning(
        """
        INSERT INTO users (telegram_id, first_name)
        VALUES (%s, %s)
        ON CONFLICT (telegram_id) DO UPDATE
            SET first_name = EXCLUDED.first_name
        RETURNING id, telegram_id, tariff
        """,
        (999999999, "Тестовый"),
    )
    print(f"\n👤 Тестовый пользователь: {row}")

    # Проверяем SELECT
    user = await db.fetch_one(
        "SELECT * FROM users WHERE telegram_id = %s",
        (999999999,),
    )
    print(f"✅ Найден: id={user['id']}, тариф={user['tariff']}")

    # Чистим
    await db.execute("DELETE FROM users WHERE telegram_id = %s", (999999999,))
    print("🧹 Тестовые данные удалены")

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())