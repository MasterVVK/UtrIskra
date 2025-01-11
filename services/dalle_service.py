import openai
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config import OPENAI_API_KEY, PROXY_URL  # Используем PROXY_URL из config.py
import logging

logger = logging.getLogger(__name__)

class DalleService:
    def __init__(self):
        """
        Инициализация клиента DALL·E с использованием прокси.
        """
        self.session = requests.Session()
        self.session.proxies = {
            "http": PROXY_URL,
            "https": PROXY_URL,
        }
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

        # Устанавливаем API ключ OpenAI
        openai.api_key = OPENAI_API_KEY
        openai.proxy = PROXY_URL  # Передаем прокси для OpenAI API

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
            logger.info(f"Запрос на генерацию изображения: {prompt}")
            response = openai.Image.create(
                model=model,
                prompt=prompt,
                size=size,
                quality=quality,
                n=n
            )
            if not response["data"] or "url" not in response["data"][0]:
                logger.error(f"Ошибка в ответе DALL·E: {response}")
                raise ValueError("URL изображения отсутствует в ответе DALL·E.")
            return response["data"][0]["url"]
        except openai.OpenAIError as e:
            logger.error(f"Ошибка при обращении к DALL·E API: {e}")
            raise
