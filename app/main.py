"""
Точка входа приложения.

Собирает вместе:
- FastAPI (для webhook на BotHost)
- aiogram (Dispatcher, Bot)
- PostgreSQL (пул соединений)
- APScheduler (напоминания и рассылки)

Запуск локально (polling):
    uvicorn app.main:app --reload

Запуск на BotHost (webhook):
    uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

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

# FSM-хранилище: в памяти процесса.
# Для MVP ок. Позже, если понадобится переживать рестарты в середине диалога,
# можно переключиться на persistent-хранилище (например, в PostgreSQL).
dp = Dispatcher(storage=MemoryStorage())


# ============================================================
# LIFESPAN (старт/остановка)
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управляет жизненным циклом приложения:
    - на старте: подключаем БД, запускаем scheduler, регистрируем webhook
    - на остановке: останавливаем scheduler, закрываем БД
    """
    logger.info(f"Запуск в режиме: {settings.bot_mode} | окружение: {settings.environment}")

    # --- Старт ---
    await db.connect()

    # Импорты здесь, чтобы избежать циклических зависимостей
    # (handlers импортируют keyboard, keyboard импортирует bot и т.д.)
    from app.services.scheduler import scheduler_service

    await scheduler_service.start()

    # Регистрируем webhook в Telegram (только если режим webhook)
    if settings.bot_mode == "webhook":
        if not settings.webhook_base_url:
            raise RuntimeError(
                "BOT_MODE=webhook, но WEBHOOK_BASE_URL не задан в .env"
            )
        await bot.set_webhook(
            url=settings.webhook_url,
            secret_token=settings.webhook_secret,
            drop_pending_updates=True,
        )
        logger.info(f"Webhook зарегистрирован: {settings.webhook_url}")

    # В режиме polling — удаляем webhook, чтобы Telegram шёл через getUpdates
    if settings.bot_mode == "polling":
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook удалён (режим polling)")

    logger.success("Приложение готово к работе")

    yield

    # --- Остановка ---
    logger.info("Остановка приложения...")

    if settings.bot_mode == "webhook":
        try:
            await bot.delete_webhook()
            logger.info("Webhook удалён")
        except Exception as e:
            logger.warning(f"Не удалось удалить webhook: {e}")

    from app.services.scheduler import scheduler_service
    await scheduler_service.stop()

    await bot.session.close()
    await db.close()
    logger.success("Приложение остановлено")


# ============================================================
# FASTAPI
# ============================================================
app = FastAPI(
    title="Авито-Помощник",
    description="Telegram-бот — помощник частного продавца Avito",
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
    Регистрирует middlewares, роутеры и глобальные обработчики.
    Вызывается один раз при импорте модуля.
    """
    # --- Middlewares ---
    from app.middlewares.subscription import SubscriptionMiddleware
    from app.middlewares.task_context import TaskContextMiddleware
    from app.middlewares.throttling import ThrottlingMiddleware
    from app.middlewares.db import DbSessionMiddleware

    # Порядок важен: сначала throttling (отсекает спам),
    # потом БД (нужна всем дальше), потом подписка (проверяет лимит),
    # потом контекст задачи (загружает активную задачу)
    dp.update.outer_middleware(ThrottlingMiddleware())
    dp.update.outer_middleware(DbSessionMiddleware())
    dp.update.outer_middleware(SubscriptionMiddleware())
    dp.update.outer_middleware(TaskContextMiddleware())

    # --- Роутеры ---
    # Импортируем в порядке приоритета.
    # Команды и админка — первыми.
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

    dp.include_router(admin.router)          # /admin — только для админа
    dp.include_router(start.router)          # /start, /help, главное меню
    dp.include_router(settings_handler.router)  # ⚙️ Настройки
    dp.include_router(subscription.router)   # 💳 Тариф и оплата
    dp.include_router(create_listing.router) # 📝 Создать объявление
    dp.include_router(improve_listing.router) # 🛠 Улучшить
    dp.include_router(competitors.router)    # 🔍 Конкуренты
    dp.include_router(photos.router)         # 📸 Фото
    dp.include_router(strategy.router)       # 📈 Стратегия
    dp.include_router(buyer_replies.router)  # 💬 Ответы покупателям
    dp.include_router(items_history.router)  # 📂 Мои объявления
    dp.include_router(reminders.router)      # ⏰ Напоминания
    dp.include_router(support.router)        # 💬 Поддержка

    logger.info("Все роутеры и middlewares зарегистрированы")


_setup_dispatcher()


# ============================================================
# HEALTHCHECK
# ============================================================
@app.get("/health", tags=["service"])
async def health() -> JSONResponse:
    """
    Healthcheck для BotHost.
    BotHost пингует этот URL раз в 30 секунд.
    Если 3 раза подряд не ответит — перезапустит контейнер.
    """
    try:
        # Проверяем, что БД жива
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
    """Корневой роут — простая проверка, что сервис отвечает."""
    return JSONResponse({"service": "avito-assistant", "status": "running"})


# ============================================================
# WEBHOOK ОТ TELEGRAM
# ============================================================
@app.post(settings.webhook_path, tags=["telegram"])
async def telegram_webhook(request: Request) -> Response:
    """
    Принимает апдейты от Telegram.
    Проверяет секрет, чтобы отсечь левые запросы.
    """
    # Проверка секрета (Telegram шлёт его в заголовке)
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != settings.webhook_secret:
        logger.warning("Webhook: неверный секрет")
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        # Не роняем webhook при ошибке обработки — Telegram будет ретраить
        logger.exception(f"Ошибка обработки апдейта: {e}")
        return Response(status_code=status.HTTP_200_OK)

    return Response(status_code=status.HTTP_200_OK)


# ============================================================
# WEBHOOK ОТ YOOKASSA
# ============================================================
@app.post("/yookassa/webhook", tags=["yookassa"])
async def yookassa_webhook(request: Request) -> Response:
    """
    Принимает коллбэки от ЮKassa.

    Безопасность: ЮKassa не подписывает коллбэки секретом,
    поэтому защищаемся двумя способами:
    1. ВСЕГДА проверяем статус платежа через API ЮKassa (server-side check)
    2. Только после подтверждения активируем PRO
    """
    try:
        data = await request.json()
        logger.info(f"ЮKassa webhook: {data.get('event')}")

        from app.services.yookassa_service import process_webhook
        await process_webhook(data)

    except Exception as e:
        logger.exception(f"Ошибка обработки webhook ЮKassa: {e}")

    # ЮKassa ждёт 200 OK в любом случае, иначе будет ретраить
    return Response(status_code=status.HTTP_200_OK)


# ============================================================
# ЛОКАЛЬНЫЙ ЗАПУСК (polling)
# ============================================================
if __name__ == "__main__":
    if settings.bot_mode == "polling":
        logger.info("Запуск long polling...")
        asyncio.run(dp.start_polling(bot, skip_updates=True))
    else:
        import uvicorn
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=settings.is_dev,
        )