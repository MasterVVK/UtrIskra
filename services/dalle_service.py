import openai
import httpx
from httpx_socks import SyncProxyTransport
from config import OPENAI_API_KEY, PROXY_URL
import logging

logger = logging.getLogger(__name__)


class DalleService:
    """Класс для взаимодействия с DALL·E через SOCKS5-прокси."""

    def __init__(self, timeout: int = 120):
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY отсутствует. Проверьте файл config.py.")
        if not PROXY_URL:
            raise ValueError("PROXY_URL отсутствует. Проверьте файл config.py.")

        # Настройка прокси
        self.transport = SyncProxyTransport.from_url(PROXY_URL)
        self.client = httpx.Client(transport=self.transport, timeout=httpx.Timeout(timeout))

        # Устанавливаем API ключ для OpenAI
        openai.api_key = OPENAI_API_KEY

    def generate_image(self, prompt, model="dall-e-3", size="1024x1024", quality="standard", n=1):
        """
        Генерация изображения через DALL·E API.
        :param prompt: Промпт для генерации изображения.
        :param model: Модель для генерации (по умолчанию 'dall-e-3').
        :param size: Размер изображения (например, '1024x1024').
        :param quality: Качество изображения ('standard' или 'hd').
        :param n: Количество изображений.
        :return: URL сгенерированного изображения.
        """
        try:
#            logger.info(f"Запрос на генерацию изображения: {prompt}")
            response = self.client.post(
                "https://api.openai.com/v1/images/generations",
                json={
                    "model": model,
                    "prompt": prompt,
                    "size": size,
                    "quality": quality,
                    "n": n,
                },
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            )
            response.raise_for_status()
            data = response.json()
            if "data" in data and len(data["data"]) > 0:
                item = data["data"][0]
                if "url" in item:
                    return item["url"], "url"
                elif "b64_json" in item:
                    return item["b64_json"], "b64_json"
            raise ValueError("Изображение отсутствует в ответе DALL·E.")
        except httpx.RequestError as e:
            logger.error(f"Ошибка при подключении к DALL·E API: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"Ошибка статуса HTTP: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Неизвестная ошибка: {e}")
            raise
