"""
Работа с PostgreSQL.

Предоставляет:
- Глобальный пул соединений `db`
- Хелперы `fetch_one`, `fetch_all`, `execute`, `execute_returning`, `fetch_val`
- Ленивую инициализацию пула (важно для uvicorn с несколькими worker'ами)
- Безопасное применение схемы (не падает при повторном запуске)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings


class Database:
    """
    Обёртка над пулом соединений psycopg_pool.

    Использование:
        await db.connect()
        row = await db.fetch_one("SELECT * FROM users WHERE id = %s", (1,))
        await db.close()

    Ленивая инициализация:
        Если пул не открыт — любой из методов автоматически
        вызовет connect() перед выполнением запроса. Это спасает
        при запуске uvicorn с несколькими worker-процессами.
    """

    def __init__(self) -> None:
        self._pool: AsyncConnectionPool | None = None

    # --------------------------------------------------------
    # ЖИЗНЕННЫЙ ЦИКЛ
    # --------------------------------------------------------
    async def connect(self) -> None:
        """
        Открывает пул соединений и применяет схему БД.
        Идемпотентно — повторный вызов ничего не ломает.
        """
        if self._pool is not None:
            logger.debug("Пул уже открыт, повторный вызов connect() проигнорирован")
            return

        logger.info("Подключение к PostgreSQL...")

        self._pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
            open=False,
            kwargs={
                "row_factory": dict_row,
                "autocommit": True,
            },
        )
        await self._pool.open(wait=True, timeout=10)

        # Проверка соединения
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT version();")
                row = await cur.fetchone()
                logger.info(f"PostgreSQL подключён: {row['version'].split(',')[0]}")

        # Применяем схему
        await self._apply_schema()

        logger.success("Пул соединений готов")

    async def close(self) -> None:
        """Закрывает пул при выключении приложения."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Пул соединений закрыт")

    # --------------------------------------------------------
    # ЛЕНИВАЯ ИНИЦИАЛИЗАЦИЯ
    # --------------------------------------------------------
    async def _get_pool(self) -> AsyncConnectionPool:
        """Возвращает пул. Если он ещё не открыт — открывает."""
        if self._pool is None:
            await self.connect()
        assert self._pool is not None
        return self._pool

    # --------------------------------------------------------
    # ПРИМЕНЕНИЕ СХЕМЫ
    # --------------------------------------------------------
    async def _apply_schema(self) -> None:
        """
        Применяет migrations/init.sql.

        Все запросы идемпотентны (IF NOT EXISTS / DROP IF EXISTS),
        поэтому можно вызывать при каждом старте.

        Дополнительно защищаемся от «already exists»: если
        Postgres ругается на дубликат — просто логируем и продолжаем,
        приложение не падает.
        """
        schema_path = Path(__file__).parent.parent / "migrations" / "init.sql"

        if not schema_path.exists():
            logger.error(f"Файл схемы не найден: {schema_path}")
            raise FileNotFoundError(f"Не найден {schema_path}")

        sql = schema_path.read_text(encoding="utf-8")

        logger.info("Применение схемы БД...")
        assert self._pool is not None
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                try:
                    await cur.execute(sql)
                    logger.success("Схема БД применена")
                except Exception as e:
                    if "already exists" in str(e):
                        logger.warning(
                            f"Часть схемы уже применена, пропускаю: {e}"
                        )
                    else:
                        logger.error(f"Ошибка применения схемы: {e}")
                        raise

    # --------------------------------------------------------
    # ХЕЛПЕРЫ ЗАПРОСОВ
    # --------------------------------------------------------
    async def execute(
        self,
        query: str,
        params: tuple | dict | None = None,
    ) -> None:
        """Выполняет запрос без возврата строк (INSERT, UPDATE, DELETE)."""
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)

    async def execute_returning(
        self,
        query: str,
        params: tuple | dict | None = None,
    ) -> dict[str, Any] | None:
        """Выполняет запрос с RETURNING и возвращает одну строку."""
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                return await cur.fetchone()

    async def fetch_one(
        self,
        query: str,
        params: tuple | dict | None = None,
    ) -> dict[str, Any] | None:
        """Возвращает одну строку или None."""
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                return await cur.fetchone()

    async def fetch_all(
        self,
        query: str,
        params: tuple | dict | None = None,
    ) -> list[dict[str, Any]]:
        """Возвращает список строк."""
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                return await cur.fetchall()

    async def fetch_val(
        self,
        query: str,
        params: tuple | dict | None = None,
    ) -> Any:
        """Возвращает одно значение из первой строки."""
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                row = await cur.fetchone()
                if row is None:
                    return None
                return next(iter(row.values()))

    # --------------------------------------------------------
    # ТРАНЗАКЦИИ
    # --------------------------------------------------------
    async def transaction(self):
        """
        Контекстный менеджер для явной транзакции.

        Пример:
            async with await db.transaction() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("UPDATE ...")
                    await cur.execute("INSERT ...")
        """
        pool = await self._get_pool()
        return pool.connection()


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================
db = Database()


# ============================================================
# УТИЛИТЫ ДЛЯ JSONB
# ============================================================
def to_jsonb(value: Any) -> str:
    """
    Сериализует Python-объект в JSON-строку для вставки в JSONB-колонку.

    Пример:
        await db.execute(
            "INSERT INTO items (name, confirmed_specs) VALUES (%s, %s::jsonb)",
            ("Диван", to_jsonb({"ширина": "120 см"})),
        )
    """
    return json.dumps(value, ensure_ascii=False, default=str)


def from_jsonb(value: Any) -> Any:
    """
    psycopg возвращает JSONB уже как dict/list — эта функция
    нужна только для единообразия, если данные пришли строкой.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value