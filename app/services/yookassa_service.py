"""
Интеграция с ЮKassa (блок 12 ТЗ).

Возможности:
- Создание платежа
- Проверка статуса через API (server-side check)
- Обработка webhook от ЮKassa
- Активация PRO после подтверждённой оплаты
- Защита от повторной обработки (idempotency_key)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from yookassa import Configuration, Payment
from yookassa.domain.notification import WebhookNotificationFactory
from yookassa.domain.response import PaymentResponse

from app.config import settings
from app.database import db


class YooKassaService:
    """Обёртка над SDK ЮKassa."""

    def __init__(self) -> None:
        # Настраиваем SDK при инициализации
        Configuration.account_id = settings.yookassa_shop_id
        Configuration.secret_key = settings.yookassa_secret_key
        logger.info(
            f"YooKassa SDK настроен: shop_id={settings.yookassa_shop_id[:4]}..., "
            f"test_mode={'test_' in settings.yookassa_secret_key}"
        )

    # --------------------------------------------------------
    # СОЗДАНИЕ ПЛАТЕЖА
    # --------------------------------------------------------
    async def create_pro_payment(
        self,
        user: dict,
        return_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Создаёт платёж PRO на 30 дней.

        Возвращает:
        {
            "payment_id": "...",
            "confirmation_url": "https://yoomoney.ru/checkout/...",
            "amount": 490.00,
            "currency": "RUB",
        }

        Или выбрасывает исключение.
        """
        amount = float(settings.pro_price_rub)
        duration = settings.pro_duration_days

        idempotency_key = str(uuid.uuid4())

        description = f"PRO на {duration} дней"
        return_url = return_url or settings.yookassa_return_url

        try:
            payment: PaymentResponse = Payment.create(
                {
                    "amount": {
                        "value": f"{amount:.2f}",
                        "currency": "RUB",
                    },
                    "confirmation": {
                        "type": "redirect",
                        "return_url": return_url,
                    },
                    "capture": True,
                    "description": description,
                    "metadata": {
                        "user_id": user["id"],
                        "telegram_id": user["telegram_id"],
                        "product": "pro",
                        "days": duration,
                    },
                    "receipt": None,  # без чека
                },
                idempotency_key,
            )

            logger.info(
                f"ЮKassa: платёж создан {payment.id} "
                f"для user={user['telegram_id']} на {amount} ₽"
            )

            # Сохраняем в БД
            await db.execute(
                """
                INSERT INTO payments (
                    user_id, yookassa_payment_id, idempotency_key,
                    amount, currency, status, product, pro_days, raw_response
                )
                VALUES (%s, %s, %s, %s, %s, 'pending', 'pro_30d', %s, %s::jsonb)
                """,
                (
                    user["id"],
                    payment.id,
                    idempotency_key,
                    amount,
                    "RUB",
                    duration,
                    _to_json(payment),
                ),
            )

            return {
                "payment_id": payment.id,
                "confirmation_url": payment.confirmation.confirmation_url,
                "amount": amount,
                "currency": "RUB",
            }

        except Exception as e:
            logger.exception(f"ЮKassa: ошибка создания платежа: {e}")
            raise

    # --------------------------------------------------------
    # ПРОВЕРКА СТАТУСА (SERVER-SIDE)
    # --------------------------------------------------------
    async def check_payment_status(self, payment_id: str) -> dict[str, Any]:
        """
        Проверяет статус платежа через API ЮKassa.
        Это НАДЁЖНЕЕ, чем доверять webhook.
        """
        try:
            payment: PaymentResponse = Payment.find_one(payment_id)
            return {
                "id": payment.id,
                "status": payment.status,
                "paid": payment.paid,
                "amount": float(payment.amount.value),
                "metadata": payment.metadata or {},
            }
        except Exception as e:
            logger.exception(f"ЮKassa: ошибка проверки статуса {payment_id}: {e}")
            raise

    # --------------------------------------------------------
    # ОБРАБОТКА WEBHOOK
    # --------------------------------------------------------
    async def process_webhook(self, event_data: dict) -> None:
        """
        Обрабатывает webhook от ЮKassa.

        ВАЖНО: всегда проверяем статус через API, не доверяем телу webhook.
        """
        try:
            notification = WebhookNotificationFactory().create(event_data)
        except Exception as e:
            logger.error(f"ЮKassa: не удалось распарсить webhook: {e}")
            return

        event = notification.event
        payment_id = notification.object.id

        logger.info(f"ЮKassa webhook: event={event}, payment_id={payment_id}")

        if event not in ("payment.succeeded", "payment.canceled", "payment.waiting_for_capture"):
            logger.debug(f"ЮKassa: неизвестное событие {event}, пропускаем")
            return

        # Всегда проверяем через API
        try:
            status_info = await self.check_payment_status(payment_id)
        except Exception as e:
            logger.error(f"ЮKassa: не удалось проверить платёж {payment_id}: {e}")
            return

        real_status = status_info["status"]
        logger.info(f"ЮKassa: реальный статус платежа {payment_id}: {real_status}")

        # Ищем платёж в БД
        payment_row = await db.fetch_one(
            "SELECT * FROM payments WHERE yookassa_payment_id = %s",
            (payment_id,),
        )
        if not payment_row:
            logger.warning(f"ЮKassa: платёж {payment_id} не найден в БД")
            return

        # Защита от повторной обработки
        if payment_row["status"] in ("succeeded", "canceled", "refunded"):
            logger.info(
                f"ЮKassa: платёж {payment_id} уже обработан "
                f"(status={payment_row['status']}), пропускаем"
            )
            return

        # Обновляем статус в БД
        await db.execute(
            """
            UPDATE payments
            SET status = %s,
                raw_response = %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            """,
            (real_status, _to_json(status_info), payment_row["id"]),
        )

        # Если успешно — активируем PRO
        if real_status == "succeeded":
            await self._activate_pro(payment_row)

        elif real_status == "canceled":
            logger.info(f"ЮKassa: платёж {payment_id} отменён")

    # --------------------------------------------------------
    # АКТИВАЦИЯ PRO
    # --------------------------------------------------------
    async def _activate_pro(self, payment_row: dict) -> None:
        """
        Активирует или продлевает PRO у пользователя.

        Если PRO уже активен — продлевает.
        Если нет — устанавливает новый срок.
        """
        user_id = payment_row["user_id"]
        days = payment_row["pro_days"]

        # Проверяем, не активировали ли уже (защита от двойной активации)
        if payment_row.get("activated_at"):
            logger.warning(
                f"ЮKassa: платёж {payment_row['yookassa_payment_id']} "
                f"уже активирован {payment_row['activated_at']}, пропускаем"
            )
            return

        user = await db.fetch_one(
            "SELECT * FROM users WHERE id = %s",
            (user_id,),
        )
        if not user:
            logger.error(f"ЮKassa: пользователь {user_id} не найден")
            return

        # Определяем новый срок
        now = datetime.now(timezone.utc)
        current_expires = user.get("pro_expires_at")

        if user["tariff"] == "pro" and current_expires and current_expires > now:
            # Продление
            new_expires = current_expires + timedelta(days=days)
            logger.info(
                f"ЮKassa: продление PRO для user={user['telegram_id']} "
                f"до {new_expires.isoformat()}"
            )
        else:
            # Новая активация
            new_expires = now + timedelta(days=days)
            logger.info(
                f"ЮKassa: активация PRO для user={user['telegram_id']} "
                f"до {new_expires.isoformat()}"
            )

        # Обновляем пользователя
        await db.execute(
            """
            UPDATE users
            SET tariff = 'pro',
                pro_expires_at = %s
            WHERE id = %s
            """,
            (new_expires, user_id),
        )

        # Помечаем платёж активированным
        await db.execute(
            """
            UPDATE payments
            SET activated_at = NOW()
            WHERE id = %s
            """,
            (payment_row["id"],),
        )

        # Уведомляем пользователя
        await self._notify_activation(user["telegram_id"], new_expires)

    async def _notify_activation(
        self,
        telegram_id: int,
        expires_at: datetime,
    ) -> None:
        """Отправляет уведомление об активации PRO."""
        from app.main import bot

        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=(
                    f"🎉 <b>PRO активирован!</b>\n\n"
                    f"Теперь у тебя:\n"
                    f"• До {settings.pro_daily_tasks} задач в день\n"
                    f"• Все функции без ограничений\n"
                    f"• Приоритетные рекомендации\n\n"
                    f"Действует до: <b>{expires_at.strftime('%d.%m.%Y')}</b>"
                ),
            )
        except Exception as e:
            logger.warning(f"ЮKassa: не удалось уведомить {telegram_id}: {e}")

    # --------------------------------------------------------
    # ОТПРАВКА УВЕДОМЛЕНИЯ ОБ ОКОНЧАНИИ ПОДПИСКИ
    # --------------------------------------------------------
    async def notify_expiring_subscriptions(self) -> None:
        """
        Отправляет уведомления тем, у кого PRO истекает в течение 3 дней.

        Вызывается из планировщика (например, раз в день).
        """
        from app.main import bot

        soon = datetime.now(timezone.utc) + timedelta(days=3)

        users = await db.fetch_all(
            """
            SELECT telegram_id, pro_expires_at
            FROM users
            WHERE tariff = 'pro'
              AND pro_expires_at IS NOT NULL
              AND pro_expires_at <= %s
              AND pro_expires_at > NOW()
            """,
            (soon,),
        )

        for u in users:
            try:
                days_left = (u["pro_expires_at"] - datetime.now(timezone.utc)).days
                await bot.send_message(
                    chat_id=u["telegram_id"],
                    text=(
                        f"⏰ <b>PRO истекает через {days_left} дн.</b>\n\n"
                        f"Дата окончания: {u['pro_expires_at'].strftime('%d.%m.%Y')}\n\n"
                        f"Продли подписку, чтобы не потерять доступ к безлимиту."
                    ),
                )
                logger.info(
                    f"ЮKassa: отправлено уведомление об окончании PRO "
                    f"user={u['telegram_id']}, осталось {days_left} дн."
                )
            except Exception as e:
                logger.warning(
                    f"ЮKassa: не удалось уведомить {u['telegram_id']}: {e}"
                )


def _to_json(obj: Any) -> str:
    """Безопасная сериализация объекта ЮKassa в JSON."""
    import json
    from datetime import datetime as dt

    def default(o: Any) -> Any:
        if isinstance(o, dt):
            return o.isoformat()
        if hasattr(o, "__dict__"):
            return {k: v for k, v in o.__dict__.items() if not k.startswith("_")}
        return str(o)

    return json.dumps(obj, default=default, ensure_ascii=False)


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================
yookassa_service = YooKassaService()


# ============================================================
# ФУНКЦИИ ДЛЯ MAIN.PY (WEBHOOK)
# ============================================================
async def process_webhook(data: dict) -> None:
    """
    Обрабатывает webhook от ЮKassa.
    Вызывается из main.py при POST /yookassa/webhook.
    """
    await yookassa_service.process_webhook(data)