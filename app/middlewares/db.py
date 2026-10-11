from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable

class DbSessionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        data["db"] = __import__("app.database", fromlist=["db"]).db
        return await handler(event, data)