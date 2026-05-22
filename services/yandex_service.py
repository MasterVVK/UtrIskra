import logging

import httpx

from config import FOLDER_ID, YANDEX_API_KEY

logger = logging.getLogger(__name__)


class YandexArtService:
    """Класс для взаимодействия с Yandex AI Studio Images API (модель aliceai-image-art-3.0)."""

    API_URL = "https://ai.api.cloud.yandex.net/v1/images/generations"
    MODEL = "aliceai-image-art-3.0/latest"
    MAX_PROMPT_LENGTH = 500

    def __init__(self, timeout: int = 120):
        if not YANDEX_API_KEY:
            raise ValueError("YANDEX_API_KEY отсутствует. Проверьте файл .env.")
        if not FOLDER_ID:
            raise ValueError("FOLDER_ID отсутствует. Проверьте файл .env.")

        self.client = httpx.Client(timeout=httpx.Timeout(timeout))

    @staticmethod
    def _truncate_to_sentence(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        prefix = text[:limit]
        boundary = max(prefix.rfind("."), prefix.rfind("!"),
                       prefix.rfind("?"), prefix.rfind("…"))
        if boundary > limit // 2:
            return prefix[: boundary + 1].rstrip()
        return prefix.rstrip()

    def generate_image(self, prompt: str) -> str:
        """
        Генерирует изображение через Yandex Images API (OpenAI-совместимый endpoint).
        :param prompt: Текстовый запрос для генерации изображения.
        :return: Base64 строка изображения.
        """
        if len(prompt) > self.MAX_PROMPT_LENGTH:
            original_len = len(prompt)
            prompt = self._truncate_to_sentence(prompt, self.MAX_PROMPT_LENGTH)
            logger.warning(
                f"Текст запроса слишком длинный ({original_len} символов). "
                f"Обрезан по последнему предложению до {len(prompt)} символов."
            )

        headers = {
            "Authorization": f"Api-Key {YANDEX_API_KEY}",
            "Content-Type": "application/json",
            "x-folder-id": FOLDER_ID,
        }
        payload = {
            "model": f"art://{FOLDER_ID}/{self.MODEL}",
            "prompt": prompt,
            "size": "1792x1024",
            "n": 1,
            "response_format": "b64_json",
        }

        try:
            response = self.client.post(self.API_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

            items = data.get("data") or []
            if not items or "b64_json" not in items[0]:
                raise ValueError(f"Yandex API не вернул изображение: {data}")

            return items[0]["b64_json"]
        except httpx.HTTPStatusError as e:
            logger.error(f"Ошибка статуса Yandex API: {e.response.status_code} - {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Ошибка при запросе к Yandex API: {e}")
            raise
