from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", message=".*protected namespace.*")

import asyncio
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from loguru import logger

from app.config import settings
from app.database import db


# ============================================================
# BOT И DISPATCHER
# ============================================================
bot = Bot(
    token=settings.telegram_bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher(storage=MemoryStorage())


# ============================================================
# РЕГИСТРАЦИЯ РОУТЕРОВ И MIDDLEWARES
# ============================================================
def _setup_dispatcher() -> None:
    """
    Подключает роутеры и middlewares.
    Вызывается один раз при импорте app.main.
    """
    # --- Роутеры ---
    from app.handlers import (
        admin,
        buyer_replies,
        competitors,
        create_listing,
        improve_listing,
        items_history,
        photos,
        reminders,
        settings as settings_handler,
        start,
        strategy,
        subscription,
        support,
    )

    routers = [
        admin.router,
        start.router,
        settings_handler.router,
        subscription.router,
        create_listing.router,
        improve_listing.router,
        competitors.router,
        photos.router,
        strategy.router,
        buyer_replies.router,
        items_history.router,
        reminders.router,
        support.router,
    ]

    attached = 0
    skipped = 0
    for router in routers:
        try:
            dp.include_router(router)
            attached += 1
        except RuntimeError as e:
            if "already attached" in str(e):
                skipped += 1
                continue
            raise

    # --- Middlewares ---
    from app.middlewares.subscription import SubscriptionMiddleware
    from app.middlewares.task_context import TaskContextMiddleware
    from app.middlewares.throttling import ThrottlingMiddleware
    from app.middlewares.db import DbSessionMiddleware

    try:
        dp.update.outer_middleware(ThrottlingMiddleware())
        dp.update.outer_middleware(DbSessionMiddleware())
        dp.update.outer_middleware(SubscriptionMiddleware())
        dp.update.outer_middleware(TaskContextMiddleware())
    except Exception as e:
        logger.debug(f"Middlewares уже добавлены: {e}")

    logger.info(f"Роутеры подключены: {attached}, пропущено: {skipped}")


_setup_dispatcher()


# ============================================================
# LIFESPAN
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Запуск в режиме: {settings.bot_mode} | окружение: {settings.environment}")

    # --- БД ---
    try:
        await db.connect()
    except Exception as e:
        logger.exception(f"❌ Не удалось подключиться к БД на старте: {e}")

    # --- Scheduler ---
    try:
        from app.services.scheduler import scheduler_service
        logger.info("🔧 Запуск scheduler...")
        await scheduler_service.start()
        logger.success(f"✅ Scheduler запущен: {scheduler_service._scheduler is not None}")
    except Exception as e:
        logger.exception(f"❌ Не удалось запустить scheduler: {e}")

    # --- Webhook ---
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

    # --- Остановка ---
    logger.info("Остановка приложения...")

    try:
        from app.services.scheduler import scheduler_service
        await scheduler_service.stop()
    except Exception as e:
        logger.warning(f"Ошибка остановки scheduler: {e}")

    try:
        await bot.session.close()
    except Exception:
        pass

    try:
        await db.close()
    except Exception:
        pass

    logger.success("Приложение остановлено")


# ============================================================
# FASTAPI
# ============================================================
app = FastAPI(lifespan=lifespan)


@app.get("/health", tags=["service"])
async def health():
    try:
        await db.fetch_val("SELECT 1")
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return JSONResponse(
            {"status": "degraded", "detail": str(e)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@app.get("/", tags=["service"])
async def root():
    return {"service": "avito-assistant", "status": "running"}


# ============================================================
# WEBHOOK ОТ TELEGRAM
# ============================================================
@app.post(settings.webhook_path, tags=["telegram"])
async def telegram_webhook(request: Request) -> Response:
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != settings.webhook_secret:
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        data = await request.json()
        logger.info(f"📥 Апдейт keys={list(data.keys())}")

        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_webhook_update(bot, update)

        logger.info("✅ Апдейт обработан")
    except Exception as e:
        logger.exception(f"❌ Ошибка: {e}")

    return Response(status_code=status.HTTP_200_OK)


# ============================================================
# WEBHOOK ОТ YOOKASSA
# ============================================================
@app.post("/yookassa/webhook", tags=["yookassa"])
async def yookassa_webhook(request: Request) -> Response:
    try:
        data = await request.json()
        from app.services.yookassa_service import process_webhook
        await process_webhook(data)
    except Exception as e:
        logger.exception(f"Ошибка webhook ЮKassa: {e}")
    return Response(status_code=status.HTTP_200_OK)


# ============================================================
# ЗАПУСК НА BOTHOST И ЛОКАЛЬНО
# ============================================================
if __name__ == "__main__":
    # BotHost запускает `python -m app.main`.
    # Здесь мы сами поднимаем uvicorn.
    # Передаём ОБЪЕКТ `app`, а не строку "app.main:app" —
    # это исключает повторный импорт модуля.
    if settings.bot_mode == "polling":
        logger.info("Запуск long polling...")
        asyncio.run(dp.start_polling(bot, skip_updates=True))
    else:
        import os
        import uvicorn
        port = int(os.getenv("PORT", "3000"))
        logger.info(f"Запуск uvicorn на порту {port}")
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=port,
            log_level="info",
        )