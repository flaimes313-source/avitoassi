from app.config import settings

print("✅ Конфигурация загружена успешно")
print(f"   Режим: {settings.bot_mode}")
print(f"   Окружение: {settings.environment}")
print(f"   Модель: {settings.yandex_gpt_model}")
print(f"   Free: {settings.free_monthly_tasks} задач/мес")
print(f"   PRO: {settings.pro_daily_tasks} задач/день за {settings.pro_price_rub}₽")
print(f"   Webhook URL: {settings.webhook_url}")
print(f"   Токен бота: {settings.telegram_bot_token[:15]}...")