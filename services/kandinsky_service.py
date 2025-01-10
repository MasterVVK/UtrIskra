import json
import time
import requests
from config import KANDINSKY_API_KEY, KANDINSKY_SECRET_KEY

class KandinskyService:
    """Класс для взаимодействия с Kandinsky 3.1 API."""

    BASE_URL = "https://api-key.fusionbrain.ai/"

    def __init__(self):
        if not KANDINSKY_API_KEY or not KANDINSKY_SECRET_KEY:
            raise ValueError("Необходимо указать KANDINSKY_API_KEY и KANDINSKY_SECRET_KEY в config.py.")
        self.auth_headers = {
            "X-Key": f"Key {KANDINSKY_API_KEY}",
            "X-Secret": f"Secret {KANDINSKY_SECRET_KEY}",
        }

    def get_model_id(self):
        """Получение ID доступной модели."""
        response = requests.get(f"{self.BASE_URL}key/api/v1/models", headers=self.auth_headers)
        response.raise_for_status()
        data = response.json()
        return data[0]["id"]

    def generate_image(self, prompt: str, model_id: str, width: int = 1344, height: int = 768):
        """
        Генерация изображения по текстовому описанию.
        :param prompt: Текстовый запрос.
        :param model_id: ID модели.
        :param width: Ширина изображения.
        :param height: Высота изображения.
        :return: UUID задания.
        """
        params = {
            "type": "GENERATE",
            "numImages": 1,
            "width": width,
            "height": height,
            "generateParams": {"query": prompt},
        }
        files = {
            "model_id": (None, model_id),
            "params": (None, json.dumps(params), "application/json"),
        }
        response = requests.post(f"{self.BASE_URL}key/api/v1/text2image/run", headers=self.auth_headers, files=files)
        response.raise_for_status()
        return response.json()["uuid"]

    def get_image(self, uuid: str, attempts: int = 10, delay: int = 10):
        """
        Получение результата генерации.
        :param uuid: UUID задания.
        :param attempts: Количество попыток.
        :param delay: Задержка между попытками.
        :return: Изображение в формате Base64.
        """
        while attempts > 0:
            response = requests.get(f"{self.BASE_URL}key/api/v1/text2image/status/{uuid}", headers=self.auth_headers)
            response.raise_for_status()
            data = response.json()
            if data["status"] == "DONE":
                return data["images"][0]
            elif data["status"] == "FAIL":
                raise ValueError("Не удалось сгенерировать изображение.")
            attempts -= 1
            time.sleep(delay)
        raise TimeoutError("Превышено количество попыток ожидания результата.")
