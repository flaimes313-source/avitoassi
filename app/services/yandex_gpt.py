"""
Обёртка над YandexGPT.

Используется как fallback, если GigaChat недоступен.
Основной провайдер — GigaChat (см. gigachat_service.py).
"""

from __future__ import annotations

import asyncio
from typing import Any

import yandexcloud
from loguru import logger
from yandex.cloud.ai.foundation_models.v1.text_common_pb2 import (
    CompletionOptions,
    Message,
)
from yandex.cloud.ai.foundation_models.v1.text_generation.text_generation_service_pb2_grpc import (
    TextGenerationServiceStub,
)
from yandex.cloud.ai.foundation_models.v1.text_generation.text_generation_service_pb2 import (
    CompletionRequest,
)

from app.config import settings


class YandexGPTService:
    """Асинхронная обёртка над YandexGPT."""

    def __init__(self) -> None:
        self._sdk: yandexcloud.SDK | None = None
        self._stub: Any | None = None

    def _get_stub(self) -> Any:
        """Ленивая инициализация gRPC-клиента."""
        if self._stub is None:
            self._sdk = yandexcloud.SDK(
                token=settings.yandex_api_key,
                endpoint="llm.api.cloud.yandex.net:443",
            )
            self._stub = self._sdk.client(
                TextGenerationServiceStub,
                endpoint="llm.api.cloud.yandex.net:443",
            )
            logger.info(f"YandexGPT клиент инициализирован: model={settings.yandex_gpt_model}")

        return self._stub

    def _sync_generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Синхронный вызов YandexGPT."""
        stub = self._get_stub()

        model_uri = f"gpt://{settings.yandex_folder_id}/{settings.yandex_gpt_model}"

        messages = [
            Message(role="system", text=system_prompt),
            Message(role="user", text=user_prompt),
        ]

        request = CompletionRequest(
            model_uri=model_uri,
            completion_options=CompletionOptions(
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            messages=messages,
        )

        response = stub.Completion(request)
        return response.alternatives[0].message.text

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Асинхронная генерация через YandexGPT."""
        try:
            result = await asyncio.to_thread(
                self._sync_generate,
                system_prompt,
                user_prompt,
                temperature if temperature is not None else settings.yandex_gpt_temperature,
                max_tokens if max_tokens is not None else settings.yandex_gpt_max_tokens,
            )
            logger.debug(f"YandexGPT ответил, длина: {len(result)} символов")
            return result
        except Exception as e:
            logger.error(f"Ошибка YandexGPT: {e}")
            raise RuntimeError(f"YandexGPT недоступен: {e}")


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================
yandex_gpt_service = YandexGPTService()