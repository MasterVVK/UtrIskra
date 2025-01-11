import os
import base64
import requests
import logging
import time
import random
from config import FOLDER_ID, OAUTH_TOKEN

logger = logging.getLogger(__name__)

class YandexArtService:
    """Класс для взаимодействия с Yandex-Art API."""
    def __init__(self):
        self.iam_token = None
        self.max_prompt_length = 500  # Максимальная длина текста для API

    def update_iam_token(self):
        """Обновляет IAM-токен для Yandex Cloud."""
        try:
            url = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
            headers = {"Content-Type": "application/json"}
            data = {"yandexPassportOauthToken": OAUTH_TOKEN}

            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            self.iam_token = response.json().get("iamToken")
            logger.info("IAM-токен успешно обновлен")
        except Exception as e:
            logger.error(f"Ошибка при обновлении IAM-токена: {e}")
            raise

    def generate_image(self, prompt: str) -> str:
        """
        Генерирует изображение через Yandex-Art API и возвращает Base64-данные.
        :param prompt: Текстовый запрос для генерации изображения.
        :return: Base64 строка изображения.
        """
        if not self.iam_token:
            self.update_iam_token()

        if len(prompt) > self.max_prompt_length:
            logger.warning(f"Текст запроса слишком длинный ({len(prompt)} символов). Обрезаем до {self.max_prompt_length} символов.")
            prompt = prompt[:self.max_prompt_length]

        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/imageGenerationAsync"
        headers = {
            "Authorization": f"Bearer {self.iam_token}",
            "X-Folder-Id": FOLDER_ID
        }
        random_seed = random.randint(1, 9223372036854775807)
        data = {
            "modelUri": f"art://{FOLDER_ID}/yandex-art/latest",
            "generationOptions": {
                "seed": random_seed,
                "aspectRatio": {"widthRatio": 9, "heightRatio": 16}
            },
            "messages": [{"weight": 1, "text": prompt}]
        }

        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            request_id = response.json().get("id")

            logger.info("Ожидание завершения генерации изображения...")
            time.sleep(20)

            result_url = f"https://llm.api.cloud.yandex.net:443/operations/{request_id}"
            result_response = requests.get(result_url, headers=headers)
            result_response.raise_for_status()
            image_base64 = result_response.json().get("response", {}).get("image")

            if not image_base64:
                raise ValueError("Yandex API не вернул изображение")

            return image_base64
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при запросе к Yandex API: {e}")
            if e.response:
                logger.error(f"Ответ сервера: {e.response.text}")
            raise
