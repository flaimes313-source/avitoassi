from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", message=".*protected namespace.*")

import asyncio
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, Update
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from loguru import logger

from app.config import settings
from app.database import db


bot = Bot(
    token=settings.telegram_bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher(storage=MemoryStorage())


# ============================================================
# ПРОСТЕЙШИЙ ХЕНДЛЕР — ПРЯМО НА DP
# ============================================================
@dp.message(F.text == "/start")
async def debug_start_handler(message: Message) -> None:
    logger.info(f"🎯 debug_start_handler СРАБОТАЛ: from_user={message.from_user.id}")
    await message.answer("DEBUG: обработчик на dp сработал!")
    logger.info("DEBUG-ответ отправлен")


# ============================================================
# LIFESPAN
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Запуск в режиме: {settings.bot_mode} | окружение: {settings.environment}")

    try:
        await db.connect()
    except Exception as e:
        logger.error(f"Не удалось подключиться к БД на старте: {e}")

    try:
        if settings.bot_mode == "webhook":
            await bot.set_webhook(
                url=settings.webhook_url,
                secret_token=settings.webhook_secret,
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query", "edited_message"],
            )
            logger.info(f"Webhook зарегистрирован: {settings.webhook_url}")
        else:
            await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Ошибка при работе с webhook: {e}")

    logger.success("Приложение готово к работе")

    yield

    try:
        await bot.session.close()
    except Exception:
        pass
    try:
        await db.close()
    except Exception:
        pass

    logger.success("Приложение остановлено")


app = FastAPI(lifespan=lifespan)


# ============================================================
# HEALTHCHECK
# ============================================================
@app.get("/health")
async def health():
    return {"status": "ok"}


# ============================================================
# WEBHOOK
# ============================================================
@app.post(settings.webhook_path)
async def telegram_webhook(request: Request) -> Response:
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != settings.webhook_secret:
        logger.warning("Webhook: неверный секрет")
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        data = await request.json()
        logger.info(f"📥 Апдейт keys={list(data.keys())}")

        # ПРЯМАЯ передача в dp через feed_webhook_update
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_webhook_update(bot, update)
        logger.info("✅ Апдейт обработан")

    except Exception as e:
        logger.exception(f"❌ Ошибка: {e}")

    return Response(status_code=status.HTTP_200_OK)


if __name__ == "__main__":
    if settings.bot_mode == "polling":
        asyncio.run(dp.start_polling(bot, skip_updates=True))
    else:
        import os
        import uvicorn
        port = int(os.getenv("PORT", "3000"))
        uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)