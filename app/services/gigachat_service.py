"""
Обёртка над GigaChat API.

Основной провайдер нейросети для проекта.
Если GigaChat недоступен — пробуем YandexGPT (fallback).
"""

from __future__ import annotations

import asyncio
from typing import Any

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from loguru import logger

from app.config import settings


class GigaChatService:
    """
    Асинхронная обёртка над синхронным SDK GigaChat.
    """

    def __init__(self) -> None:
        self._client: GigaChat | None = None

    def _get_client(self) -> GigaChat:
        """Ленивая инициализация клиента."""
        if self._client is None:
            # Защита от пустого scope: если переменная пустая
            # или None — используем GIGACHAT_API_PERS
            scope = (settings.gigachat_scope or "").strip() or "GIGACHAT_API_PERS"

            logger.info(
                f"🔧 GigaChat init: scope={scope!r}, "
                f"model={settings.gigachat_model!r}, "
                f"credentials_length={len(settings.gigachat_credentials)}"
            )

            client_kwargs: dict[str, Any] = {
                "credentials": settings.gigachat_credentials,
                "scope": scope,
                "model": settings.gigachat_model,
                "timeout": 60.0,
                "max_retries": 2,
            }

            if settings.gigachat_ca_bundle_file:
                client_kwargs["ca_bundle_file"] = settings.gigachat_ca_bundle_file
                client_kwargs["verify_ssl_certs"] = True
            else:
                client_kwargs["verify_ssl_certs"] = settings.gigachat_verify_ssl

            self._client = GigaChat(**client_kwargs)
            logger.info(
                f"GigaChat клиент инициализирован: "
                f"model={settings.gigachat_model}, "
                f"scope={scope}"
            )

        return self._client

    def _sync_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        client = self._get_client()

        messages = [
            Messages(role=MessagesRole.SYSTEM, content=system_prompt),
            Messages(role=MessagesRole.USER, content=user_prompt),
        ]

        chat = Chat(
            model=settings.gigachat_model,
            messages=messages,
            temperature=temperature if temperature is not None else settings.gigachat_temperature,
            max_tokens=max_tokens if max_tokens is not None else settings.gigachat_max_tokens,
        )

        response = client.chat(chat)
        return response.choices[0].message.content

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        try:
            result = await asyncio.to_thread(
                self._sync_chat,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
            )
            logger.debug(f"GigaChat ответил, длина: {len(result)} символов")
            return result

        except Exception as e:
            logger.error(f"Ошибка GigaChat: {e}")

            if settings.has_yandex_fallback:
                logger.warning("Пробую fallback на YandexGPT...")
                try:
                    from app.services.yandex_gpt import yandex_gpt_service
                    return await yandex_gpt_service.generate(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except Exception as fallback_error:
                    logger.error(f"Fallback тоже упал: {fallback_error}")

            raise RuntimeError(f"GigaChat недоступен: {e}")

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        import json

        result = await self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature if temperature is not None else 0.3,
            max_tokens=max_tokens,
        )

        cleaned = result.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Не удалось распарсить JSON от GigaChat: {e}")
            logger.debug(f"Сырой ответ: {result[:500]}")
            raise RuntimeError(f"GigaChat вернул невалидный JSON: {e}")


gigachat_service = GigaChatService()