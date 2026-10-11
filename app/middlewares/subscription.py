from aiogram import BaseMiddleware

class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        return await handler(event, data)