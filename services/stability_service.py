import httpx
from config import STABILITY_API_KEY

class StabilityService:
    """Класс для взаимодействия с Stability.ai API."""

#    API_URL = "https://api.stability.ai/v2beta/stable-image/generate/sd3"
    API_URL = "https://api.stability.ai/v2beta/stable-image/generate/ultra"
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {STABILITY_API_KEY}",
            "Accept": "image/*"  # Указываем, что ожидаем изображение
        }
        self.timeout = httpx.Timeout(30.0)  # Таймаут 30 секунд

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

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
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

            except httpx.ReadTimeout:
                print("[ERROR] Таймаут при ожидании ответа от Stability AI.")
                raise
            except httpx.HTTPStatusError as e:
                print(f"[ERROR] HTTP Status Error: {e.response.status_code}")
                print(f"[ERROR] Response Details: {e.response.text}")
                raise
            except Exception as e:
                print(f"[ERROR] General Exception: {e}")
                print(f"[ERROR] Exception Details: {type(e).__name__}, {str(e)}")
                raise
