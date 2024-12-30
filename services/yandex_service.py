import os
import base64
import requests
import logging
import time
import random
from datetime import datetime
from config import FOLDER_ID, OAUTH_TOKEN, IMAGES_PATH

logger = logging.getLogger(__name__)

class YandexArtService:
    """Класс для взаимодействия с Yandex-Art API."""
    def __init__(self):
        self.iam_token = None
        self.max_prompt_length = 500  # Максимальная длина текста для API

    def update_iam_token(self):
        """
        Обновляет IAM-токен для Yandex Cloud.
        """
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

    def create_image_path(self):
        """
        Создает путь для сохранения изображения в формате: storage/images/{year}/{month}/{file_name}.
        """
        current_date = datetime.now()
        year = current_date.strftime("%Y")
        month = current_date.strftime("%m")
        file_name = f"yandex_story_{current_date.strftime('%Y%m%d_%H%M%S')}.jpeg"

        directory = os.path.join(IMAGES_PATH, year, month)
        os.makedirs(directory, exist_ok=True)

        return os.path.join(directory, file_name)

    def generate_image(self, prompt: str) -> str:
        """
        Генерирует изображение через Yandex-Art API и сохраняет его на диск.
        :param prompt: Текстовый запрос для генерации изображения.
        :return: Путь к сохраненному изображению.
        """
        if not self.iam_token:
            self.update_iam_token()

        # Ограничение длины текста
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

            image_path = self.create_image_path()
            with open(image_path, "wb") as file:
                file.write(base64.b64decode(image_base64))

            logger.info(f"Изображение сохранено в {image_path}")
            return image_path
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при запросе к Yandex API: {e}")
            if e.response:
                logger.error(f"Ответ сервера: {e.response.text}")
            raise
