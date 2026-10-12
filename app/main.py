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
# LIFESPAN (старт/остановка)
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управляет жизненным циклом приложения.
    Все ошибки на старте логируем, но не роняем контейнер —
    пул досоздастся лениво при первом запросе.
    """
    logger.info(f"Запуск в режиме: {settings.bot_mode} | окружение: {settings.environment}")

    # --- Старт ---
    try:
        await db.connect()
    except Exception as e:
        logger.error(f"Не удалось подключиться к БД на старте: {e}")
        logger.warning("Пул откроется лениво при первом запросе")

    try:
        from app.services.scheduler import scheduler_service
        await scheduler_service.start()
    except Exception as e:
        logger.error(f"Не удалось запустить scheduler: {e}")

    try:
        if settings.bot_mode == "webhook":
            if not settings.webhook_base_url:
                raise RuntimeError("BOT_MODE=webhook, но WEBHOOK_BASE_URL не задан")
            await bot.set_webhook(
                url=settings.webhook_url,
                secret_token=settings.webhook_secret,
                drop_pending_updates=True,
            )
            logger.info(f"Webhook зарегистрирован: {settings.webhook_url}")
        else:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Webhook удалён (режим polling)")
    except Exception as e:
        logger.error(f"Ошибка при работе с webhook: {e}")

    logger.success("Приложение готово к работе")

    yield

    # --- Остановка ---
    logger.info("Остановка приложения...")

    try:
        if settings.bot_mode == "webhook":
            await bot.delete_webhook()
            logger.info("Webhook удалён")
    except Exception as e:
        logger.warning(f"Не удалось удалить webhook: {e}")

    try:
        from app.services.scheduler import scheduler_service
        await scheduler_service.stop()
    except Exception as e:
        logger.warning(f"Ошибка остановки scheduler: {e}")

    try:
        await bot.session.close()
    except Exception as e:
        logger.warning(f"Ошибка закрытия сессии бота: {e}")

    try:
        await db.close()
    except Exception as e:
        logger.warning(f"Ошибка закрытия БД: {e}")

    logger.success("Приложение остановлено")


# ============================================================
# FASTAPI
# ============================================================
app = FastAPI(
    title="Авито-Помощник",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_dev else None,
    redoc_url=None,
)


# ============================================================
# РЕГИСТРАЦИЯ РОУТЕРОВ И MIDDLEWARES
# ============================================================
def _setup_dispatcher() -> None:
    """
    Регистрирует middlewares и роутеры.

    Идемпотентна: если роутер уже привязан к диспетчеру
    (например, при повторном импорте модуля), просто пропускаем.
    """
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

    for router in routers:
        try:
            dp.include_router(router)
        except RuntimeError as e:
            if "already attached" in str(e):
                logger.debug(f"Роутер уже привязан, пропускаю: {e}")
                continue
            raise

    logger.info("Все роутеры и middlewares зарегистрированы")


_setup_dispatcher()


# ============================================================
# HEALTHCHECK
# ============================================================
@app.get("/health", tags=["service"])
async def health() -> JSONResponse:
    """Healthcheck для BotHost."""
    try:
        await db.fetch_val("SELECT 1")
        return JSONResponse(
            {"status": "ok", "db": "ok", "env": settings.environment}
        )
    except Exception as e:
        logger.error(f"Healthcheck не прошёл: {e}")
        return JSONResponse(
            {"status": "degraded", "db": "error", "detail": str(e)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@app.get("/", tags=["service"])
async def root() -> JSONResponse:
    return JSONResponse({"service": "avito-assistant", "status": "running"})


# ============================================================
# WEBHOOK ОТ TELEGRAM
# ============================================================
@app.post(settings.webhook_path, tags=["telegram"])
async def telegram_webhook(request: Request) -> Response:
    """Принимает апдейты от Telegram."""
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != settings.webhook_secret:
        logger.warning("Webhook: неверный секрет")
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        logger.exception(f"Ошибка обработки апдейта: {e}")
        return Response(status_code=status.HTTP_200_OK)

    return Response(status_code=status.HTTP_200_OK)


# ============================================================
# WEBHOOK ОТ YOOKASSA
# ============================================================
@app.post("/yookassa/webhook", tags=["yookassa"])
async def yookassa_webhook(request: Request) -> Response:
    """Принимает коллбэки от ЮKassa."""
    try:
        data = await request.json()
        logger.info(f"ЮKassa webhook: {data.get('event')}")

        from app.services.yookassa_service import process_webhook
        await process_webhook(data)
    except Exception as e:
        logger.exception(f"Ошибка обработки webhook ЮKassa: {e}")

    return Response(status_code=status.HTTP_200_OK)


# ============================================================
# ЛОКАЛЬНЫЙ ЗАПУСК (polling / dev-режим)
# ============================================================
if __name__ == "__main__":
    if settings.bot_mode == "polling":
        logger.info("Запуск long polling...")
        asyncio.run(dp.start_polling(bot, skip_updates=True))
    else:
        import os
        import uvicorn

        # BotHost передаёт порт в переменную PORT (по умолчанию 3000)
        port = int(os.getenv("PORT", "3000"))

        logger.info(f"Запуск webhook на порту {port}")
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=port,
            reload=False,
        )