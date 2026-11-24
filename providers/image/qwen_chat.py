"""Qwen Chat (Qwen2API / chat.qwen.ai) — обёртка services/qwen_chat_service.py."""
import asyncio
import logging
import os

import httpx

from providers.image.base import ImageProvider, download_bytes

logger = logging.getLogger(__name__)

# CDN Qwen отдаёт готовую картинку не всегда сразу: 24.11.2026 ссылка из ответа
# (генерация 2 мин 23 с, 200 OK) дала 404, и пост не вышел. Повтор скачивания
# квоту не тратит, а заново рисовать картинку ради этого незачем.
DOWNLOAD_ATTEMPTS = 6
DOWNLOAD_DELAY = 10


async def _download_with_retries(name, url):
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            return await download_bytes(url)
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            retryable = status is None or status == 404 or status >= 500
            if attempt >= DOWNLOAD_ATTEMPTS or not retryable:
                raise
            # Ни URL, ни текст исключения в журнал не пишем: в ссылке подписанный ключ.
            logger.warning("«%s»: картинка с CDN не скачалась (%s), повтор %d из %d через %d с",
                           name, status or type(exc).__name__, attempt + 1, DOWNLOAD_ATTEMPTS,
                           DOWNLOAD_DELAY)
            await asyncio.sleep(DOWNLOAD_DELAY)


class QwenChatProvider(ImageProvider):
    type = "qwen_chat"
    PARAMS = [
        {"key": "model", "label": "Модель", "kind": "str", "default": "qwen3.7-plus-image"},
        {"key": "aspect_ratio", "label": "Соотношение сторон", "kind": "str", "default": "16:9"},
        {"key": "temperature", "label": "Температура", "kind": "float", "default": 0.7,
         "min": 0, "max": 2},
        {"key": "top_p", "label": "top_p", "kind": "float", "default": 0.95, "min": 0, "max": 1},
    ]

    @property
    def base_url(self):
        return (self.config.get("base_url") or os.getenv("QWEN_CHAT_API_URL",
                "http://192.168.0.58:3001/v1")).rstrip("/")

    async def generate(self, prompt, params):
        from services.qwen_chat_service import QwenChatService
        values = self.apply_defaults(params)
        service = QwenChatService(base_url=self.base_url)
        image_url = await service.generate_image(
            prompt,
            aspect_ratio=values.get("aspect_ratio", "16:9"),
            model=values.get("model", "qwen3.7-plus-image"),
            temperature=values.get("temperature", 0.7),
            top_p=values.get("top_p", 0.95),
        )
        return await _download_with_retries(self.name, image_url)

    async def health(self):
        from config import QWEN_CHAT_API_KEY
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {QWEN_CHAT_API_KEY}"})
            return (True, "API доступен") if response.status_code == 200 \
                else (False, f"HTTP {response.status_code}")
        except Exception as exc:
            return False, str(exc)
