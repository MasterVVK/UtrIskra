"""Публикация медиафайлов в Telegram с ретраями.

В debug-режиме (тумблер на дашборде) все публикации идут через отладочного
бота в отладочный чат — переопределение chat_id задачи тоже игнорируется,
чтобы в боевой канал гарантированно ничего не ушло.
"""
import asyncio
import contextlib
import logging
import os
import tempfile

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import FSInputFile
from aiohttp import ClientTimeout

from config import (TELEGRAM_TOKEN, TARGET_CHAT_ID,
                    DEBUG_TELEGRAM_TOKEN, DEBUG_TARGET_CHAT_ID)
from core import app_settings

logger = logging.getLogger(__name__)

RETRY_DELAY = 10

# Bot API принимает в sendPhoto файл не больше 10 МБ. PNG на 4 Мп с живописной
# фактурой (Qwen-Image 2.1, 2752×1536) весит 9–10 МБ и в лимит не проходит.
# Порог с запасом: водяной знак пересохраняет PNG, и размер гуляет на сотни КБ.
PHOTO_MAX_BYTES = 9_500_000
# Telegram всё равно пережимает фото в JPEG, так что копия высокого качества
# на глаз от PNG не отличается. Качество снижаем только если и она не влезла.
_JPEG_QUALITIES = (95, 90, 85, 75)
# Больше 2560 по длинной стороне Telegram фото не хранит — уменьшает сам. Копию
# уменьшаем заранее (LANCZOS), чтобы 16-мегапиксельный кадр влез в лимит при q95.
PHOTO_MAX_SIDE = 2560
# sendDocument у Bot API — до 50 МБ.
DOCUMENT_MAX_BYTES = 49_000_000


def _photo_within_limit(path: str):
    """Путь к файлу, который sendPhoto примет, и признак «это временная копия».

    Исходный файл не трогаем: в архиве и галерее остаётся оригинал без потерь.
    """
    if os.path.getsize(path) <= PHOTO_MAX_BYTES:
        return path, False

    from PIL import Image

    handle, copy_path = tempfile.mkstemp(prefix="tg_photo_", suffix=".jpg")
    os.close(handle)
    try:
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            if max(rgb.size) > PHOTO_MAX_SIDE:
                rgb.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE), Image.LANCZOS)
            for quality in _JPEG_QUALITIES:
                rgb.save(copy_path, "JPEG", quality=quality)
                if os.path.getsize(copy_path) <= PHOTO_MAX_BYTES:
                    break
    except Exception:
        os.unlink(copy_path)
        raise
    logger.info("Фото %s весит %.1f МБ — больше лимита Telegram, отправляется JPEG-копия "
                "(%dx%d, %.1f МБ, качество %d)", path, os.path.getsize(path) / 1e6,
                rgb.size[0], rgb.size[1], os.path.getsize(copy_path) / 1e6, quality)
    return copy_path, True


def _document_within_limit(path: str):
    """Оригинал для sendDocument: как есть, а если тяжелее 50 МБ — JPEG q95 в полном размере."""
    if os.path.getsize(path) <= DOCUMENT_MAX_BYTES:
        return path, False

    from PIL import Image

    handle, copy_path = tempfile.mkstemp(prefix="tg_original_", suffix=".jpg")
    os.close(handle)
    try:
        with Image.open(path) as image:
            image.convert("RGB").save(copy_path, "JPEG", quality=95)
    except Exception:
        os.unlink(copy_path)
        raise
    return copy_path, True


async def _send_original(bot, target, path: str, reply_to: int, attempts: int):
    """Оригинал файлом в ответ на пост с фото — чтобы картинку можно было рассмотреть
    в полном разрешении. Фото уже опубликовано, поэтому сбой здесь задачу не роняет."""
    from PIL import Image

    from aiogram.types import ReplyParameters

    with Image.open(path) as image:
        width, height = image.size
    upload_path, is_copy = _document_within_limit(path)
    try:
        for attempt in range(1, attempts + 1):
            try:
                await bot.send_document(
                    chat_id=target, document=FSInputFile(upload_path),
                    caption=f"Оригинал {width}×{height} — откройте файл, чтобы рассмотреть детали",
                    reply_parameters=ReplyParameters(message_id=reply_to),
                    disable_content_type_detection=True)
                logger.info("Оригинал отправлен файлом (%s, %.1f МБ)", target,
                            os.path.getsize(upload_path) / 1e6)
                return
            except Exception as exc:
                if attempt < attempts:
                    await asyncio.sleep(RETRY_DELAY)
                else:
                    logger.warning("Оригинал файлом не отправлен: %s", exc)
    finally:
        if is_copy:
            with contextlib.suppress(OSError):
                os.unlink(upload_path)


def debug_configured() -> bool:
    return bool(DEBUG_TELEGRAM_TOKEN and DEBUG_TARGET_CHAT_ID)


def _resolve_destination(chat_id, job_debug):
    """(token, target_chat, is_debug): debug действует глобально или на задаче."""
    if app_settings.debug_publish_enabled() or job_debug:
        if not debug_configured():
            raise RuntimeError("Debug-режим включён, но DEBUG_TELEGRAM_TOKEN / "
                               "DEBUG_TARGET_CHAT_ID не заданы в .env")
        return DEBUG_TELEGRAM_TOKEN, DEBUG_TARGET_CHAT_ID, True
    return TELEGRAM_TOKEN, chat_id or TARGET_CHAT_ID, False


async def publish_media(path: str, *, media: str = "image",
                        chat_id=None, retries: int = 0, debug: bool = False,
                        caption: str = None, original_as_document: bool = False):
    """Отправляет фото/видео; retries — число повторов после первой попытки.

    original_as_document — следом за фото отправить исходный файл документом
    (ответом на пост): Telegram показывает фото не больше 2560 px по стороне.
    """
    token, target, is_debug = _resolve_destination(chat_id, debug)
    if is_debug:
        logger.warning("DEBUG-режим: публикация уходит в отладочный чат %s", target)
    session = AiohttpSession(timeout=ClientTimeout(total=300, sock_connect=30, sock_read=300))
    bot = Bot(token=token, session=session)
    attempts = max(1, int(retries) + 1)
    upload_path, is_copy = (path, False) if media == "video" else _photo_within_limit(path)
    try:
        for attempt in range(1, attempts + 1):
            try:
                if media == "video":
                    await bot.send_video(chat_id=target, video=FSInputFile(path),
                                         caption=caption)
                else:
                    message = await bot.send_photo(chat_id=target, photo=FSInputFile(upload_path),
                                                   caption=caption)
                logger.info("Опубликовано в Telegram (%s%s): %s",
                            target, " · DEBUG" if is_debug else "", path)
                if media != "video" and original_as_document:
                    await _send_original(bot, target, path, message.message_id, attempts)
                return
            except Exception as exc:
                if attempt < attempts:
                    logger.warning("Отправка в Telegram не удалась (попытка %d/%d): %s. "
                                   "Повтор через %d с", attempt, attempts, exc, RETRY_DELAY)
                    await asyncio.sleep(RETRY_DELAY)
                else:
                    raise
    finally:
        await bot.session.close()
        if is_copy:
            with contextlib.suppress(OSError):
                os.unlink(upload_path)
