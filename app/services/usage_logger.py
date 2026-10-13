"""
Логирование расхода токенов GigaChat в БД.

Вызывается из сервисов GigaChat после каждого чата.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.database import db, to_jsonb


class UsageLogger:
    """Пишет записи о расходе токенов в gigachat_usage."""

    async def log(
        self,
        user_id: int | None,
        task_id: int | None,
        call_type: str,          # 'text' | 'vision' | 'json'
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        success: bool = True,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """Записывает одну запись о расходе."""
        try:
            await db.execute(
                """
                INSERT INTO gigachat_usage (
                    user_id, task_id, call_type, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    success, meta
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    user_id,
                    task_id,
                    call_type,
                    model,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    success,
                    to_jsonb(meta or {}),
                ),
            )
            logger.debug(
                f"Usage logged: {call_type} user={user_id} "
                f"task={task_id} tokens={total_tokens}"
            )
        except Exception as e:
            # Не роняем основной сценарий из-за логирования
            logger.warning(f"Не удалось записать usage: {e}")


usage_logger = UsageLogger()