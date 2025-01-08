import httpx
import random
from config import STABILITY_API_KEY

class StabilityService:
    """Класс для взаимодействия с Stability.ai API."""

    # Можете использовать нужный эндпоинт — здесь 'ultra':
    API_URL = "https://api.stability.ai/v2beta/stable-image/generate/ultra"

    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {STABILITY_API_KEY}",
            # НЕ указываем Content-Type руками, httpx сам поставит multipart/form-data
            "Accept": "image/*"  # хотим получить изображение
        }
        self.timeout = httpx.Timeout(30.0)  # Таймаут 30 секунд

    async def generate_image(self, prompt: str) -> bytes:
        """
        Генерация изображения по запросу.
        :param prompt: Текстовый промпт для генерации изображения.
        :return: Содержимое изображения в формате байтов.
        """
        random_seed = random.randint(0, 4294967294)
#        print(f"[DEBUG] Случайный сид: {random_seed}")

        # Формируем поля для multipart/form-data
        # Обратите внимание: seed переводим в строку (str), иначе возникнет ошибка 'int' object has no attribute 'read'
        files = {
            "prompt": (None, prompt),
            "negative_prompt": (None, "(embedding:unaestheticXLv31:0.8), low quality, watermark"),
            "aspect_ratio": (None, "9:16"),
            "output_format": (None, "png"),
            "seed": (None, str(random_seed))
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    self.API_URL,
                    headers=self.headers,
                    files=files  # именно files, т.к. нужен multipart/form-data
                )

                # Проверка ответа
                if response.status_code == 200:
                    print("[INFO] Изображение успешно сгенерировано.")
                    return response.content
                else:
                    print(f"[ERROR] Статус ответа: {response.status_code}")
                    print(f"[ERROR] Текст ответа: {response.text}")
                    raise Exception(
                        f"Ошибка API Stability AI: {response.status_code} - {response.text}"
                    )

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
