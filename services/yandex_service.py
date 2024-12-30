import os
import base64
import requests
import logging
from config import FOLDER_ID, OAUTH_TOKEN, IMAGES_PATH

logger = logging.getLogger(__name__)

class YandexArtService:
    """Класс для взаимодействия с Yandex-Art API."""
    def __init__(self):
        self.iam_token = None

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

    def generate_image(self, prompt: str) -> str:
        """
        Генерирует изображение через Yandex-Art API.
        :param prompt: Текстовый запрос для генерации изображения.
        :return: Путь к сохраненному изображению.
        """
        if not self.iam_token:
            self.update_iam_token()

        # Ограничение длины промпта
        max_prompt_length = 500
        if len(prompt) > max_prompt_length:
            prompt = prompt[:max_prompt_length] + "..."

        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/imageGenerationAsync"
        headers = {
            "Authorization": f"Bearer {self.iam_token}",
            "X-Folder-Id": FOLDER_ID
        }
        data = {
            "modelUri": f"art://{FOLDER_ID}/yandex-art/latest",
            "generationOptions": {
                "seed": 1863,
                "aspectRatio": {"widthRatio": 2, "heightRatio": 1}
            },
            "messages": [{"weight": 1, "text": prompt}]
        }

        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            request_id = response.json().get("id")

            logger.info("Ожидание завершения генерации изображения...")
            result_url = f"https://llm.api.cloud.yandex.net:443/operations/{request_id}"
            result_response = requests.get(result_url, headers=headers)
            result_response.raise_for_status()
            image_base64 = result_response.json().get("response").get("image")

            image_path = os.path.join(IMAGES_PATH, f"yandex_story_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpeg")
            os.makedirs(IMAGES_PATH, exist_ok=True)
            with open(image_path, "wb") as file:
                file.write(base64.b64decode(image_base64))

            logger.info(f"Изображение сохранено в {image_path}")
            return image_path
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при генерации изображения: {e}")
            raise