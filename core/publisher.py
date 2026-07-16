"""Публикация медиафайлов в Telegram с ретраями.

В debug-режиме (тумблер на дашборде) все публикации идут через отладочного
бота в отладочный чат — переопределение chat_id задачи тоже игнорируется,
чтобы в боевой канал гарантированно ничего не ушло.
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import FSInputFile
from aiohttp import ClientTimeout

from config import (TELEGRAM_TOKEN, TARGET_CHAT_ID,
                    DEBUG_TELEGRAM_TOKEN, DEBUG_TARGET_CHAT_ID)
from core import app_settings

logger = logging.getLogger(__name__)

RETRY_DELAY = 10


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
                        chat_id=None, retries: int = 0, debug: bool = False):
    """Отправляет фото/видео; retries — число повторов после первой попытки."""
    token, target, is_debug = _resolve_destination(chat_id, debug)
    if is_debug:
        logger.warning("DEBUG-режим: публикация уходит в отладочный чат %s", target)
    session = AiohttpSession(timeout=ClientTimeout(total=300, sock_connect=30, sock_read=300))
    bot = Bot(token=token, session=session)
    attempts = max(1, int(retries) + 1)
    try:
        for attempt in range(1, attempts + 1):
            try:
                if media == "video":
                    await bot.send_video(chat_id=target, video=FSInputFile(path))
                else:
                    await bot.send_photo(chat_id=target, photo=FSInputFile(path))
                logger.info("Опубликовано в Telegram (%s%s): %s",
                            target, " · DEBUG" if is_debug else "", path)
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
