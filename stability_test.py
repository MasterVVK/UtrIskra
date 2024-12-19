import httpx
from config import STABILITY_API_KEY

class StabilityService:
    """Класс для взаимодействия с Stability.ai API."""

    API_URL = "https://api.stability.ai/v2beta/stable-image/generate/sd3"

    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {STABILITY_API_KEY}",
            "Accept": "image/*"  # Указываем, что ожидаем изображение
        }

    async def generate_image(self, prompt: str) -> bytes:
        """
        Генерация изображения по запросу.
        :param prompt: Текстовый промпт для генерации изображения.
        :return: Содержимое изображения в формате байтов.
        """
        payload = {
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "output_format": "png"
        }

        # Преобразуем данные для multipart/form-data
        files = {key: (None, value) for key, value in payload.items()}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                headers=self.headers,
                files=files  # Используем files для формата multipart/form-data
            )

            # Проверка ответа
            if response.status_code == 200:
                print("[INFO] Изображение успешно сгенерировано.")
                return response.content
            else:
                print(f"[ERROR] Статус ответа: {response.status_code}")
                print(f"[ERROR] Текст ответа: {response.text}")
                raise Exception(f"Ошибка API Stability AI: {response.status_code} - {response.text}")
