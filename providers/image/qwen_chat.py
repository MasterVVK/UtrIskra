"""Qwen Chat (Qwen2API / chat.qwen.ai) — обёртка services/qwen_chat_service.py."""
import os

import httpx

from providers.image.base import ImageProvider, download_bytes


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
        return await download_bytes(image_url)

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
