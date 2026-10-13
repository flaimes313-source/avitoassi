"""
Сервис анализа изображений через GigaChat Vision.

Возможности:
- Скачивание фото из Telegram
- Загрузка в GigaChat через upload_file
- Описание фото (короткий текст для передачи в текстовый чат)
- Анализ изображений с JSON-ответом (для блоков 5, 6)
- Удаление файлов после использования

Модель: GigaChat-2-Pro (поддерживает Vision).
"""

from __future__ import annotations

import asyncio
import io
import json
import re
from typing import Any

from aiogram import Bot
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from loguru import logger

from app.config import settings


# ============================================================
# ВОССТАНОВЛЕНИЕ ОБРЕЗАННОГО JSON
# ============================================================
def _try_recover_json(text: str) -> dict | None:
    """Пытается восстановить обрезанный JSON для массива variants."""
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
            logger.info(f"Recovery: восстановлено {len(variants)} вариантов")
            return {"variants": variants}
    except Exception as e:
        logger.debug(f"Recovery не удался: {e}")
    return None


class GigaChatVisionService:
    """Анализ изображений через GigaChat Vision."""

    def __init__(self) -> None:
        self._client: GigaChat | None = None

    def _get_client(self) -> GigaChat:
        if self._client is None:
            scope = (settings.gigachat_scope or "").strip() or "GIGACHAT_API_PERS"

            client_kwargs: dict[str, Any] = {
                "credentials": settings.gigachat_credentials,
                "scope": scope,
                "model": settings.gigachat_model,
                "timeout": 120.0,
                "max_retries": 2,
            }

            if settings.gigachat_ca_bundle_file:
                client_kwargs["ca_bundle_file"] = settings.gigachat_ca_bundle_file
                client_kwargs["verify_ssl_certs"] = True
            else:
                client_kwargs["verify_ssl_certs"] = settings.gigachat_verify_ssl

            self._client = GigaChat(**client_kwargs)
            logger.info(
                f"GigaChat Vision клиент инициализирован: "
                f"model={settings.gigachat_model}, scope={scope}"
            )
        return self._client

    # --------------------------------------------------------
    # СИНХРОННЫЕ ОПЕРАЦИИ
    # --------------------------------------------------------
    def _sync_upload(self, file_bytes: bytes, filename: str = "photo.jpg") -> str:
        client = self._get_client()
        file_obj = io.BytesIO(file_bytes)
        file_obj.name = filename

        uploaded = client.upload_file(file_obj)
        logger.debug(f"Файл загружен в GigaChat: {uploaded.id_}")
        return uploaded.id_

    def _sync_delete(self, file_id: str) -> None:
        try:
            client = self._get_client()
            client.delete_file(file_id)
            logger.debug(f"Файл {file_id} удалён из GigaChat")
        except Exception as e:
            logger.warning(f"Не удалось удалить файл {file_id}: {e}")

    def _sync_chat_with_attachments(
        self,
        system_prompt: str,
        user_prompt: str,
        file_ids: list[str],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, Any]:
        """Возвращает (текст, usage)."""
        client = self._get_client()

        messages = [
            Messages(role=MessagesRole.SYSTEM, content=system_prompt),
            Messages(
                role=MessagesRole.USER,
                content=user_prompt,
                attachments=file_ids,
            ),
        ]

        chat = Chat(
            model=settings.gigachat_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        response = client.chat(chat)
        text = response.choices[0].message.content
        usage = getattr(response, "usage", None)
        return text, usage

    # --------------------------------------------------------
    # АСИНХРОННЫЕ ОБЁРТКИ
    # --------------------------------------------------------
    async def _download_tg_photo(self, bot: Bot, file_id: str) -> bytes:
        tg_file = await bot.get_file(file_id)
        buf = io.BytesIO()
        await bot.download_file(tg_file.file_path, buf)
        return buf.getvalue()

    async def _upload_photos(
        self, bot: Bot, photos: list[dict], max_photos: int = 10,
    ) -> list[str]:
        photos = photos[:max_photos]
        uploaded_ids: list[str] = []

        for photo in photos:
            tg_file_id = photo.get("file_id")
            if not tg_file_id:
                continue
            try:
                file_bytes = await self._download_tg_photo(bot, tg_file_id)
                giga_id = await asyncio.to_thread(
                    self._sync_upload, file_bytes, "photo.jpg"
                )
                uploaded_ids.append(giga_id)
            except Exception as e:
                logger.warning(f"Не удалось загрузить фото {tg_file_id}: {e}")

        return uploaded_ids

    async def _cleanup(self, file_ids: list[str]) -> None:
        for giga_id in file_ids:
            await asyncio.to_thread(self._sync_delete, giga_id)

    # --------------------------------------------------------
    # ЛОГИРОВАНИЕ USAGE
    # --------------------------------------------------------
    async def _log_usage(
        self,
        usage: Any,
        user_id: int | None,
        task_id: int | None,
        call_type: str,
        temperature: float,
        max_tokens: int,
        prompt_len: int,
        completion_len: int,
        photos_count: int,
        success: bool,
        error: str | None = None,
    ) -> None:
        from app.services.usage_logger import usage_logger

        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        if usage is not None:
            prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            total_tokens = getattr(usage, "total_tokens", 0) or 0

        if total_tokens == 0:
            prompt_tokens = prompt_len // 4
            completion_tokens = completion_len // 4
            total_tokens = prompt_tokens + completion_tokens

        meta = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "prompt_len": prompt_len,
            "completion_len": completion_len,
            "photos_count": photos_count,
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

    # --------------------------------------------------------
    # ГЛАВНЫЙ НОВЫЙ МЕТОД: ОПИСАНИЕ ФОТО (шаг 1)
    # --------------------------------------------------------
    async def describe_photos(
        self,
        bot: Bot,
        photos: list[dict],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1500,
        max_photos: int = 10,
        user_id: int | None = None,
        task_id: int | None = None,
    ) -> str:
        """
        Описывает фото текстом (без JSON).

        Возвращает короткий текст (300–800 символов), который
        потом используется как вход для текстовой генерации.

        Используется в блоке 3 (создание объявления) для обхода
        ограничения длины Vision-модели.
        """
        if not photos:
            raise ValueError("Нет фото для анализа")

        uploaded_ids = await self._upload_photos(bot, photos, max_photos)
        if not uploaded_ids:
            raise RuntimeError("Не удалось загрузить ни одного фото")

        logger.info(f"Vision describe: загружено {len(uploaded_ids)} фото")

        try:
            result, usage = await asyncio.to_thread(
                self._sync_chat_with_attachments,
                system_prompt,
                user_prompt,
                uploaded_ids,
                temperature,
                max_tokens,
            )

            await self._log_usage(
                usage=usage,
                user_id=user_id,
                task_id=task_id,
                call_type="vision_describe",
                temperature=temperature,
                max_tokens=max_tokens,
                prompt_len=len(system_prompt) + len(user_prompt),
                completion_len=len(result),
                photos_count=len(uploaded_ids),
                success=True,
            )

            logger.info(f"Vision describe: получено {len(result)} символов")
            return result

        except Exception as e:
            await self._log_usage(
                usage=None,
                user_id=user_id,
                task_id=task_id,
                call_type="vision_describe",
                temperature=temperature,
                max_tokens=max_tokens,
                prompt_len=len(system_prompt) + len(user_prompt),
                completion_len=0,
                photos_count=len(uploaded_ids),
                success=False,
                error=str(e),
            )
            raise
        finally:
            await self._cleanup(uploaded_ids)

    # --------------------------------------------------------
    # СУЩЕСТВУЮЩИЙ МЕТОД: JSON-АНАЛИЗ (для блоков 5, 6)
    # --------------------------------------------------------
    async def analyze_with_photos_json(
        self,
        bot: Bot,
        photos: list[dict],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        max_tokens: int = 5000,
        max_photos: int = 10,
        user_id: int | None = None,
        task_id: int | None = None,
    ) -> dict:
        """Анализ с фото, возвращает распарсенный JSON."""
        if not photos:
            raise ValueError("Нет фото для анализа")

        uploaded_ids = await self._upload_photos(bot, photos, max_photos)
        if not uploaded_ids:
            raise RuntimeError("Не удалось загрузить ни одного фото")

        logger.info(f"Vision: загружено {len(uploaded_ids)} фото")

        try:
            result, usage = await asyncio.to_thread(
                self._sync_chat_with_attachments,
                system_prompt,
                user_prompt,
                uploaded_ids,
                temperature,
                max_tokens,
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
                parsed = json.loads(cleaned)
            except json.JSONDecodeError as e:
                logger.error(f"Vision: не удалось распарсить JSON: {e}")
                logger.debug(f"Сырой ответ: {result[:500]}")

                recovered = _try_recover_json(cleaned)
                if recovered is None:
                    raise RuntimeError(f"GigaChat вернул невалидный JSON: {e}")
                logger.warning("Vision: JSON восстановлен после обрезки")
                parsed = recovered

            await self._log_usage(
                usage=usage,
                user_id=user_id,
                task_id=task_id,
                call_type="vision_json",
                temperature=temperature,
                max_tokens=max_tokens,
                prompt_len=len(system_prompt) + len(user_prompt),
                completion_len=len(result),
                photos_count=len(uploaded_ids),
                success=True,
            )
            return parsed

        except Exception as e:
            await self._log_usage(
                usage=None,
                user_id=user_id,
                task_id=task_id,
                call_type="vision_json",
                temperature=temperature,
                max_tokens=max_tokens,
                prompt_len=len(system_prompt) + len(user_prompt),
                completion_len=0,
                photos_count=len(uploaded_ids),
                success=False,
                error=str(e),
            )
            raise
        finally:
            await self._cleanup(uploaded_ids)

    async def analyze_photos(
        self,
        bot: Bot,
        photos: list[dict],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        max_tokens: int = 5000,
        max_photos: int = 10,
        user_id: int | None = None,
        task_id: int | None = None,
    ) -> dict:
        """Совместимость со старым API."""
        return await self.analyze_with_photos_json(
            bot=bot,
            photos=photos,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            max_photos=max_photos,
            user_id=user_id,
            task_id=task_id,
        )


gigachat_vision_service = GigaChatVisionService()