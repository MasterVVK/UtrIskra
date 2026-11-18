"""Yandex Art (aliceai-image-art-3.0) — обёртка services/yandex_service.py.

Параметры size/aspect API фактически игнорирует (модель отдаёт максимум
1344×768), поэтому в схеме их нет.
"""
import base64
import os

import httpx

from providers.image.base import ImageProvider, PromptRejected

# Ответ модерации: 400 invalid_request_error с этой фразой. Модерация смотрит на
# отдельные слова без смысла — «голые тополя» отклоняются (проверено 18.11.2026).
MODERATION_MARKER = "не могу сгенерировать"


class YandexProvider(ImageProvider):
    type = "yandex"
    PARAMS = []

    def describe(self):
        return "aliceai-image-art-3.0"

    async def generate(self, prompt, params):
        from services.yandex_service import YandexArtService
        try:
            image_base64 = YandexArtService().generate_image(prompt)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400 and MODERATION_MARKER in exc.response.text.lower():
                raise PromptRejected("Yandex Art отклонил запрос модерацией: "
                                     + exc.response.text[:200]) from exc
            raise
        return base64.b64decode(image_base64)

    async def health(self):
        if not os.getenv("YANDEX_API_KEY"):
            return False, "нет YANDEX_API_KEY"
        if not os.getenv("FOLDER_ID"):
            return False, "нет FOLDER_ID"
        return True, "ключ и folder_id заданы (без запроса к API)"
