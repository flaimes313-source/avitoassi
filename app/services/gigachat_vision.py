"""
Сервис анализа изображений через GigaChat Vision.

Возможности:
- Скачивание фото из Telegram
- Загрузка в GigaChat через upload_file
- Анализ изображений с текстовым промптом
- Генерация с фото (свободный текст)
- Восстановление обрезанного JSON
- Удаление файлов из GigaChat после анализа

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
    """
    Пытается восстановить обрезанный JSON.

    GigaChat при превышении max_tokens обрезает ответ посередине.
    Для ответов с массивом variants — ищем все полные объекты
    вариантов и собираем из них валидный JSON.
    """
    try:
        # Ищем все полные объекты вида {"approach": "...", "title": "...", "body": "..."}
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
            logger.info(f"Recovery: удалось восстановить {len(variants)} вариантов")
            return {"variants": variants}

    except Exception as e:
        logger.debug(f"Recovery не удался: {e}")

    return None


class GigaChatVisionService:
    """Анализ изображений через GigaChat Vision."""

    def __init__(self) -> None:
        self._client: GigaChat | None = None

    def _get_client(self) -> GigaChat:
        """Ленивая инициализация клиента."""
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
        """Загружает картинку в GigaChat, возвращает file_id."""
        client = self._get_client()
        file_obj = io.BytesIO(file_bytes)
        file_obj.name = filename

        uploaded = client.upload_file(file_obj)
        logger.debug(f"Файл загружен в GigaChat: {uploaded.id_}")
        return uploaded.id_

    def _sync_delete(self, file_id: str) -> None:
        """Удаляет файл из GigaChat."""
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
    ) -> str:
        """Отправляет чат с прикреплёнными картинками."""
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
        return response.choices[0].message.content

    # --------------------------------------------------------
    # АСИНХРОННЫЕ ОБЁРТКИ
    # --------------------------------------------------------
    async def _download_tg_photo(self, bot: Bot, file_id: str) -> bytes:
        """Скачивает фото из Telegram по file_id."""
        tg_file = await bot.get_file(file_id)
        buf = io.BytesIO()
        await bot.download_file(tg_file.file_path, buf)
        return buf.getvalue()

    async def _upload_photos(
        self,
        bot: Bot,
        photos: list[dict],
        max_photos: int = 10,
    ) -> list[str]:
        """
        Загружает фото из Telegram в GigaChat.
        Возвращает список giga_file_id.
        """
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
        """Удаляет файлы из GigaChat."""
        for giga_id in file_ids:
            await asyncio.to_thread(self._sync_delete, giga_id)

    # --------------------------------------------------------
    # ПУБЛИЧНЫЕ МЕТОДЫ
    # --------------------------------------------------------
    async def generate_with_photos(
        self,
        bot: Bot,
        photos: list[dict],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.6,
        max_tokens: int = 3500,
        max_photos: int = 10,
    ) -> str:
        """Генерация с фото (свободный текст)."""
        if not photos:
            raise ValueError("Нет фото для анализа")

        uploaded_ids = await self._upload_photos(bot, photos, max_photos)
        if not uploaded_ids:
            raise RuntimeError("Не удалось загрузить ни одного фото в GigaChat")

        logger.info(f"Vision: загружено {len(uploaded_ids)} фото")

        try:
            result = await asyncio.to_thread(
                self._sync_chat_with_attachments,
                system_prompt,
                user_prompt,
                uploaded_ids,
                temperature,
                max_tokens,
            )
            return result
        finally:
            await self._cleanup(uploaded_ids)

    async def analyze_with_photos_json(
        self,
        bot: Bot,
        photos: list[dict],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        max_tokens: int = 3500,
        max_photos: int = 10,
    ) -> dict:
        """Анализ с фото, возвращает распарсенный JSON."""
        if not photos:
            raise ValueError("Нет фото для анализа")

        uploaded_ids = await self._upload_photos(bot, photos, max_photos)
        if not uploaded_ids:
            raise RuntimeError("Не удалось загрузить ни одного фото в GigaChat")

        logger.info(f"Vision: загружено {len(uploaded_ids)} фото")

        try:
            result = await asyncio.to_thread(
                self._sync_chat_with_attachments,
                system_prompt,
                user_prompt,
                uploaded_ids,
                temperature,
                max_tokens,
            )

            # Чистим markdown-обёртки
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
                logger.error(f"Vision: не удалось распарсить JSON: {e}")
                logger.debug(f"Сырой ответ: {result[:500]}")

                recovered = _try_recover_json(cleaned)
                if recovered is not None:
                    logger.warning("Vision: JSON восстановлен после обрезки")
                    return recovered

                raise RuntimeError(f"GigaChat вернул невалидный JSON: {e}")
        finally:
            await self._cleanup(uploaded_ids)

    # Алиас для обратной совместимости
    async def analyze_photos(
        self,
        bot: Bot,
        photos: list[dict],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        max_tokens: int = 3500,
        max_photos: int = 10,
    ) -> dict:
        """Совместимость со старым API (блок 6)."""
        return await self.analyze_with_photos_json(
            bot=bot,
            photos=photos,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            max_photos=max_photos,
        )


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================
gigachat_vision_service = GigaChatVisionService()