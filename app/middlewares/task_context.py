"""
Заглушка middleware контекста задачи.

Полная версия загрузит активную задачу пользователя из БД
и положит её в data["active_task"], чтобы хендлеры могли
продолжать прерванный диалог.
"""

from aiogram import BaseMiddleware


class TaskContextMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # Пока просто пропускаем событие дальше
        return await handler(event, data)