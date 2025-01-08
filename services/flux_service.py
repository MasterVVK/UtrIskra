from config import BFL_API_KEY
import time
import requests

class FluxService:
    """Класс для взаимодействия с FLUX API."""

    BASE_URL = "https://api.bfl.ml/v1"
    FLUX_ENDPOINT = "/flux-pro-1.1-ultra"  # Можно заменить на другой эндпоинт, если требуется.

    def __init__(self, api_key: str = BFL_API_KEY):
        """
        Инициализация FluxService.
        :param api_key: API-ключ для взаимодействия с FLUX API.
        """
        if not api_key:
            raise ValueError("Не указан API-ключ FLUX. Убедитесь, что 'BFL_API_KEY' задан в config.py.")
        self.api_key = api_key
        self.headers = {
            "accept": "application/json",
            "x-key": self.api_key,
            "Content-Type": "application/json",
        }

    def create_request(self, prompt: str, width: int = 768, height: int = 1344) -> str:
        """
        Создает запрос на генерацию изображения.
        :param prompt: Описание изображения.
        :param width: Ширина изображения (по умолчанию 1024).
        :param height: Высота изображения (по умолчанию 768).
        :return: ID задачи для последующего получения результата.
        """
        response = requests.post(
            f"{self.BASE_URL}{self.FLUX_ENDPOINT}",
            headers=self.headers,
            json={"prompt": prompt,
                  "width": width,
                  "height": height,
                  "aspect_ratio": "9:16",
                  "steps": 50},
        )

        if response.status_code != 200:
            raise Exception(f"Ошибка при создании запроса: {response.status_code} - {response.text}")

        request_data = response.json()
        return request_data["id"]

    def poll_for_result(self, request_id: str) -> str:
        """
        Ожидает завершения задачи и возвращает URL результата.
        :param request_id: ID задачи.
        :return: Ссылка на результат (URL изображения).
        """
        while True:
            time.sleep(5)
            response = requests.get(
                f"{self.BASE_URL}/get_result",
                headers=self.headers,
                params={"id": request_id},
            )

            if response.status_code != 200:
                raise Exception(f"Ошибка при получении результата: {response.status_code} - {response.text}")

            result_data = response.json()
            if result_data["status"] == "Ready":
                return result_data["result"]["sample"]
            elif result_data["status"] not in {"Pending", "Processing"}:
                raise Exception(f"Ошибка статуса задачи: {result_data['status']}")
