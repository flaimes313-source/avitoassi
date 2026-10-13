"""
Обёртка над GigaChat API (текстовый режим).

Логирует расход токенов в gigachat_usage.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from loguru import logger

from app.config import settings


# ============================================================
# ВОССТАНОВЛЕНИЕ ОБРЕЗАННОГО JSON
# ============================================================
def _try_recover_variants(text: str) -> dict | None:
    try:
        pattern = re.compile(
            r'\{\s*"approach"\s*:\s*"[^"]*"\s*,\s*'
            r'"title"\s*:\s*"(?:[^"\\]|\\.)*"\s*,\s*'
            r'"body"\s*:\s*"(?:[^"\\]|\\.)*"\s*\}',
            re.DOTALL,
        )
        matches = pattern.findall(text)
        if not matches:
            return None
        variants = []
        for m in matches:
            try:
                variants.append(json.loads(m))
            except json.JSONDecodeError:
                continue
        if variants:
            logger.info(f"Recovery (text): восстановлено {len(variants)} вариантов")
            return {"variants": variants}
    except Exception as e:
        logger.debug(f"Recovery (text) не удался: {e}")
    return None


def _try_recover_any_json(text: str) -> dict | None:
    variants = _try_recover_variants(text)
    if variants:
        return variants

    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = text[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = -1
    return None


class GigaChatService:
    """Асинхронная обёртка над синхронным SDK GigaChat (текст)."""

    def __init__(self) -> None:
        self._client: GigaChat | None = None

    def _get_client(self) -> GigaChat:
        if self._client is None:
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
                f"model={settings.gigachat_model}, scope={scope}"
            )
        return self._client

    def _sync_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, Any]:
        """Синхронный вызов GigaChat. Возвращает (текст, usage)."""
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
        text = response.choices[0].message.content
        usage = getattr(response, "usage", None)
        return text, usage

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        user_id: int | None = None,
        task_id: int | None = None,
        call_type: str = "text",
    ) -> str:
        """Генерирует текст через GigaChat (с fallback и логированием)."""
        try:
            result, usage = await asyncio.to_thread(
                self._sync_chat,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
            )
            logger.debug(f"GigaChat ответил, длина: {len(result)} символов")

            # Логируем расход
            await self._log_usage(
                usage=usage,
                user_id=user_id,
                task_id=task_id,
                call_type=call_type,
                temperature=temperature,
                max_tokens=max_tokens,
                prompt_len=len(system_prompt) + len(user_prompt),
                completion_len=len(result),
                success=True,
            )

            return result

        except Exception as e:
            logger.error(f"Ошибка GigaChat: {e}")

            await self._log_usage(
                usage=None,
                user_id=user_id,
                task_id=task_id,
                call_type=call_type,
                temperature=temperature,
                max_tokens=max_tokens,
                prompt_len=len(system_prompt) + len(user_prompt),
                completion_len=0,
                success=False,
                error=str(e),
            )

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

    async def _log_usage(
        self,
        usage: Any,
        user_id: int | None,
        task_id: int | None,
        call_type: str,
        temperature: float | None,
        max_tokens: int | None,
        prompt_len: int,
        completion_len: int,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Пишет расход в БД."""
        from app.services.usage_logger import usage_logger

        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        if usage is not None:
            prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            total_tokens = getattr(usage, "total_tokens", 0) or 0

        # Fallback-оценка, если usage не пришёл
        if total_tokens == 0:
            prompt_tokens = prompt_len // 4
            completion_tokens = completion_len // 4
            total_tokens = prompt_tokens + completion_tokens

        meta = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "prompt_len": prompt_len,
            "completion_len": completion_len,
        }
        if error:
            meta["error"] = error[:300]

        await usage_logger.log(
            user_id=user_id,
            task_id=task_id,
            call_type=call_type,
            model=settings.gigachat_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            success=success,
            meta=meta,
        )

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        user_id: int | None = None,
        task_id: int | None = None,
    ) -> dict:
        """Генерирует JSON. Логирует как 'json'."""
        result = await self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature if temperature is not None else 0.3,
            max_tokens=max_tokens,
            user_id=user_id,
            task_id=task_id,
            call_type="json",
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
            logger.error(f"Не удалось распарсить JSON: {e}")
            logger.debug(f"Сырой ответ: {result[:500]}")

            recovered = _try_recover_any_json(cleaned)
            if recovered is not None:
                logger.warning("JSON восстановлен после обрезки")
                return recovered

            raise RuntimeError(f"GigaChat вернул невалидный JSON: {e}")


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================
gigachat_service = GigaChatService()