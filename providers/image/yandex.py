"""Yandex Art (aliceai-image-art-3.0) — обёртка services/yandex_service.py.

Параметры size/aspect API фактически игнорирует (модель отдаёт максимум
1344×768), поэтому в схеме их нет.
"""
import base64
import os

from providers.image.base import ImageProvider


class YandexProvider(ImageProvider):
    type = "yandex"
    PARAMS = []

    def describe(self):
        return "aliceai-image-art-3.0"

    async def generate(self, prompt, params):
        from services.yandex_service import YandexArtService
        image_base64 = YandexArtService().generate_image(prompt)
        return base64.b64decode(image_base64)

    async def health(self):
        if not os.getenv("YANDEX_API_KEY"):
            return False, "нет YANDEX_API_KEY"
        if not os.getenv("FOLDER_ID"):
            return False, "нет FOLDER_ID"
        return True, "ключ и folder_id заданы (без запроса к API)"
