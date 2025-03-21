import httpx
import random
import logging
from config import STABILITY_API_KEY

logger = logging.getLogger(__name__)

class StabilityService:
    """Класс для взаимодействия с Stability.ai API."""

    API_URL = "https://api.stability.ai/v2beta/stable-image/generate/ultra"

    def __init__(self, timeout: int = 30):
        if not STABILITY_API_KEY:
            raise ValueError("STABILITY_API_KEY отсутствует. Проверьте файл config.py.")
        self.headers = {
            "Authorization": f"Bearer {STABILITY_API_KEY}",
            "Accept": "image/*"
        }
        self.timeout = timeout

    async def generate_image(self, prompt: str) -> bytes:
        """
        Генерация изображения по запросу.
        :param prompt: Текстовый промпт для генерации изображения.
        :return: Содержимое изображения в формате байтов.
        """
        random_seed = random.randint(0, 4294967294)
        files = {
            "prompt": (None, prompt),
            "negative_prompt": (None, "low quality, watermark"),
            "aspect_ratio": (None, "16:9"),
            "output_format": (None, "png"),
            "seed": (None, str(random_seed))
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    self.API_URL,
                    headers=self.headers,
                    files=files
                )

                if response.status_code == 200:
                    logger.info("Изображение успешно сгенерировано.")
                    return response.content
                else:
                    logger.error(f"Ошибка API Stability AI: {response.status_code} - {response.text}")
                    response.raise_for_status()
            except httpx.RequestError as e:
                logger.error(f"Ошибка подключения к Stability AI: {e}")
                raise
            except httpx.HTTPStatusError as e:
                logger.error(f"Ошибка статуса HTTP: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Неизвестная ошибка: {e}")
                raise
