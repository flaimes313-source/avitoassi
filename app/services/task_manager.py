"""
Менеджер задач и лимитов (блоки 9, 11 ТЗ).

Центральная точка для:
- проверки лимитов Free/PRO/whitelist
- создания и завершения задач
- записи истории диалога внутри задачи
- предотвращения двойного списания лимита
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from loguru import logger

from app.config import settings
from app.database import db, to_jsonb

# Типы задач (совпадают с CHECK в init.sql)
TaskType = Literal[
    "create_listing",
    "improve_listing",
    "competitors",
    "photos",
    "strategy",
    "buyer_reply",
]

TaskStatus = Literal["active", "done", "failed", "cancelled"]


# ============================================================
# РЕЗУЛЬТАТ ПРОВЕРКИ ЛИМИТА
# ============================================================
class LimitCheckResult:
    """
    Результат проверки лимита.

    Поля:
        allowed: можно ли запустить задачу
        reason: почему нельзя (если allowed=False)
        used: сколько уже использовано
        limit: сколько всего доступно
        period: 'month' | 'day' | 'whitelist'
        existing_task: активная задача, если есть
    """

    def __init__(
        self,
        allowed: bool,
        used: int = 0,
        limit: int = 0,
        period: str = "month",
        reason: str = "",
        existing_task: dict | None = None,
    ) -> None:
        self.allowed = allowed
        self.used = used
        self.limit = limit
        self.period = period
        self.reason = reason
        self.existing_task = existing_task

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


# ============================================================
# МЕНЕДЖЕР
# ============================================================
class TaskManager:
    """Управление задачами и лимитами."""

    # --------------------------------------------------------
    # ПРОВЕРКА ЛИМИТА
    # --------------------------------------------------------
    async def check_limit(
        self,
        user: dict[str, Any],
        task_type: TaskType,
    ) -> LimitCheckResult:
        """
        Проверяет, может ли пользователь запустить задачу.

        Порядок:
        1. Whitelist — безлимит
        2. Активная задача этого типа — можно продолжить без списания
        3. Лимит по тарифу
        """
        user_id = user["id"]
        tariff = user["tariff"]

        # 0. Whitelist — безлимит
        from app.services.whitelist import whitelist_service
        try:
            if await whitelist_service.is_whitelisted(user["telegram_id"]):
                logger.debug(f"Пользователь {user_id}: в whitelist, безлимит")
                return LimitCheckResult(
                    allowed=True,
                    used=0,
                    limit=999999,
                    period="whitelist",
                )
        except Exception as e:
            logger.warning(f"Ошибка проверки whitelist: {e}")

        # 1. Активная задача этого типа
        active_task = await db.fetch_one(
            """
            SELECT * FROM tasks
            WHERE user_id = %s
              AND task_type = %s
              AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id, task_type),
        )

        if active_task:
            logger.debug(
                f"Пользователь {user_id}: найдена активная задача "
                f"{task_type} (id={active_task['id']})"
            )
            return LimitCheckResult(
                allowed=True,
                existing_task=active_task,
            )

        # 2. Считаем лимит по тарифу
        if tariff == "pro":
            limit = settings.pro_daily_tasks
            period = "day"
            used = await self._count_tasks_today(user_id)
        else:
            limit = settings.free_monthly_tasks
            period = "month"
            used = await self._count_tasks_this_month(user_id)

        # 3. Проверяем
        if used >= limit:
            reason = (
                f"Лимит исчерпан: {used}/{limit} "
                f"{'в день' if period == 'day' else 'в месяц'}"
            )
            logger.info(f"Пользователь {user_id}: лимит исчерпан ({used}/{limit})")
            return LimitCheckResult(
                allowed=False,
                used=used,
                limit=limit,
                period=period,
                reason=reason,
            )

        return LimitCheckResult(
            allowed=True,
            used=used,
            limit=limit,
            period=period,
        )

    async def _count_tasks_today(self, user_id: int) -> int:
        """Считает завершённые задачи за сегодня (UTC)."""
        count = await db.fetch_val(
            """
            SELECT COUNT(*) FROM tasks
            WHERE user_id = %s
              AND status = 'done'
              AND limit_charged = TRUE
              AND completed_at >= CURRENT_DATE
            """,
            (user_id,),
        )
        return int(count or 0)

    async def _count_tasks_this_month(self, user_id: int) -> int:
        """Считает завершённые задачи за текущий календарный месяц."""
        count = await db.fetch_val(
            """
            SELECT COUNT(*) FROM tasks
            WHERE user_id = %s
              AND status = 'done'
              AND limit_charged = TRUE
              AND completed_at >= DATE_TRUNC('month', CURRENT_DATE)
            """,
            (user_id,),
        )
        return int(count or 0)

    # --------------------------------------------------------
    # СОЗДАНИЕ ЗАДАЧИ
    # --------------------------------------------------------
    async def create_task(
        self,
        user: dict[str, Any],
        task_type: TaskType,
        item_id: int | None = None,
        collected_data: dict | None = None,
        meta: dict | None = None,
    ) -> dict[str, Any]:
        """
        Создаёт новую задачу в БД.
        limit_charged остаётся FALSE до успешного завершения.
        """
        user_id = user["id"]

        row = await db.execute_returning(
            """
            INSERT INTO tasks (
                user_id, item_id, task_type, status,
                collected_data, meta
            )
            VALUES (%s, %s, %s, 'active', %s::jsonb, %s::jsonb)
            RETURNING *
            """,
            (
                user_id,
                item_id,
                task_type,
                to_jsonb(collected_data or {}),
                to_jsonb(meta or {}),
            ),
        )
        logger.info(
            f"Создана задача id={row['id']} type={task_type} "
            f"user={user_id} item={item_id}"
        )
        return row

    # --------------------------------------------------------
    # ОБНОВЛЕНИЕ ЧЕРНОВИКА ЗАДАЧИ
    # --------------------------------------------------------
    async def update_collected(
        self,
        task_id: int,
        patch: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Мержит патч в collected_data."""
        return await db.execute_returning(
            """
            UPDATE tasks
            SET collected_data = collected_data || %s::jsonb
            WHERE id = %s
            RETURNING *
            """,
            (to_jsonb(patch), task_id),
        )

    async def set_result(
        self,
        task_id: int,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Сохраняет результат задачи."""
        return await db.execute_returning(
            """
            UPDATE tasks
            SET result = %s::jsonb
            WHERE id = %s
            RETURNING *
            """,
            (to_jsonb(result), task_id),
        )

    # --------------------------------------------------------
    # ЗАПИСЬ СООБЩЕНИЙ ДИАЛОГА
    # --------------------------------------------------------
    async def log_message(
        self,
        task_id: int,
        role: Literal["user", "assistant"],
        content: str,
        attachments: list[dict] | None = None,
    ) -> None:
        """Записывает сообщение в историю задачи."""
        await db.execute(
            """
            INSERT INTO task_messages (task_id, role, content, attachments)
            VALUES (%s, %s, %s, %s::jsonb)
            """,
            (task_id, role, content, to_jsonb(attachments or [])),
        )

    # --------------------------------------------------------
    # ЗАВЕРШЕНИЕ ЗАДАЧИ
    # --------------------------------------------------------
    async def complete_task(
        self,
        task_id: int,
        status: TaskStatus,
        result: dict | None = None,
        technical_failure: bool = False,
    ) -> dict[str, Any] | None:
        """
        Завершает задачу.

        Списание лимита:
        - status='done' и technical_failure=False → списываем
        - status='failed' или technical_failure=True → НЕ списываем
        - status='cancelled' → НЕ списываем
        """
        should_charge = status == "done" and not technical_failure

        row = await db.execute_returning(
            """
            UPDATE tasks
            SET status = %s,
                result = COALESCE(%s::jsonb, result),
                technical_failure = %s,
                limit_charged = %s,
                completed_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                status,
                to_jsonb(result) if result else None,
                technical_failure,
                should_charge,
                task_id,
            ),
        )

        if should_charge:
            logger.info(f"Задача id={task_id} завершена, лимит списан")
        else:
            logger.info(
                f"Задача id={task_id} завершена (status={status}, "
                f"tech_fail={technical_failure}), лимит не списан"
            )

        return row

    # --------------------------------------------------------
    # ОТМЕНА АКТИВНЫХ ЗАДАЧ
    # --------------------------------------------------------
    async def cancel_active_tasks(
        self,
        user_id: int,
        task_type: TaskType | None = None,
    ) -> int:
        """Отменяет все активные задачи пользователя (опц. по типу)."""
        if task_type:
            rows = await db.fetch_all(
                """
                UPDATE tasks
                SET status = 'cancelled', completed_at = NOW()
                WHERE user_id = %s
                  AND status = 'active'
                  AND task_type = %s
                RETURNING id
                """,
                (user_id, task_type),
            )
        else:
            rows = await db.fetch_all(
                """
                UPDATE tasks
                SET status = 'cancelled', completed_at = NOW()
                WHERE user_id = %s
                  AND status = 'active'
                RETURNING id
                """,
                (user_id,),
            )

        count = len(rows) if rows else 0
        if count:
            logger.info(
                f"Пользователь {user_id}: отменено {count} активных "
                f"задач (type={task_type or 'all'})"
            )
        return count

    # --------------------------------------------------------
    # ПОЛУЧЕНИЕ АКТИВНОЙ ЗАДАЧИ
    # --------------------------------------------------------
    async def get_active_task(
        self,
        user_id: int,
        task_type: TaskType | None = None,
    ) -> dict[str, Any] | None:
        """Возвращает активную задачу пользователя."""
        if task_type:
            return await db.fetch_one(
                """
                SELECT * FROM tasks
                WHERE user_id = %s AND status = 'active' AND task_type = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, task_type),
            )
        return await db.fetch_one(
            """
            SELECT * FROM tasks
            WHERE user_id = %s AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
            """,
            (user_id,),
        )

    # --------------------------------------------------------
    # СТАТУС ЛИМИТА ДЛЯ ПОКАЗА
    # --------------------------------------------------------
    async def get_limit_status(
        self,
        user: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Возвращает статус лимита для показа пользователю.
        """
        user_id = user["id"]
        tariff = user["tariff"]

        # Whitelist — безлимит
        from app.services.whitelist import whitelist_service
        try:
            if await whitelist_service.is_whitelisted(user["telegram_id"]):
                return {
                    "tariff": "whitelist",
                    "used": 0,
                    "limit": 999999,
                    "remaining": 999999,
                    "period": "whitelist",
                    "text": "🎁 <b>Безлимит</b> (белый список). Задач не ограничено.",
                }
        except Exception as e:
            logger.warning(f"Ошибка проверки whitelist в get_limit_status: {e}")

        if tariff == "pro":
            limit = settings.pro_daily_tasks
            period = "day"
            used = await self._count_tasks_today(user_id)
            text = (
                f"⭐ <b>PRO</b>: {used} из {limit} задач за сегодня. "
                f"Осталось {max(0, limit - used)}."
            )
        else:
            limit = settings.free_monthly_tasks
            period = "month"
            used = await self._count_tasks_this_month(user_id)
            remaining = max(0, limit - used)
            if remaining == 0:
                text = (
                    f"🆓 <b>Free</b>: лимит исчерпан ({used}/{limit} за месяц).\n"
                    f"Оформи PRO — будет {settings.pro_daily_tasks} задач в день."
                )
            else:
                text = (
                    f"🆓 <b>Free</b>: {used} из {limit} задач за месяц. "
                    f"Осталось {remaining}."
                )

        return {
            "tariff": tariff,
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
            "period": period,
            "text": text,
        }


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================
task_manager = TaskManager()