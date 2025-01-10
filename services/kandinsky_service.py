import json
import time
import requests
import logging
from config import KANDINSKY_API_KEY, KANDINSKY_SECRET_KEY

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
class KandinskyService:
    """Класс для взаимодействия с Kandinsky 3.1 API."""

    BASE_URL = "https://api-key.fusionbrain.ai/"
    TIMEOUT = 30  # Тайм-аут в секундах

    def __init__(self):
        if not KANDINSKY_API_KEY or not KANDINSKY_SECRET_KEY:
            raise ValueError("Необходимо указать KANDINSKY_API_KEY и KANDINSKY_SECRET_KEY в config.py.")
        self.auth_headers = {
            "X-Key": f"Key {KANDINSKY_API_KEY}",
            "X-Secret": f"Secret {KANDINSKY_SECRET_KEY}",
        }

    def check_availability_with_timeout(self, attempts: int = 6, delay: int = 300):
        """
        Проверяет доступность API каждые `delay` секунд в течение `attempts` попыток.
        """
        for attempt in range(attempts):
            try:
                logger.debug(f"Отправляем запрос с заголовками: {self.auth_headers}")
                response = requests.get(
                    f"{self.BASE_URL}key/api/v1/text2image/availability",
                    headers=self.auth_headers,  # Заголовки с авторизацией
                    timeout=self.TIMEOUT
                )
                response.raise_for_status()  # Проверяем успешность запроса

                # Логируем полный текст ответа
                logger.debug(f"Ответ сервера: {response.text}")

                # Пытаемся извлечь JSON из ответа
                try:
                    response_data = response.json()
                    logger.debug(f"JSON ответа: {response_data}")
                except ValueError:
                    logger.warning("Не удалось распарсить JSON из ответа сервера.")
                    response_data = {}

                # Проверяем статус доступности
                status = response_data.get("model_status", None)
                if status == "AVAILABLE":
                    logger.info("API доступен для обработки запросов.")
                    return
                logger.warning(f"API недоступен: {status}. Попытка {attempt + 1} из {attempts}.")
            except requests.exceptions.RequestException as e:
                logger.error(f"Ошибка при проверке доступности API: {e}")
            if attempt < attempts - 1:
                time.sleep(delay)  # Ждем перед следующей проверкой
        raise Exception("Сервис остается недоступным более 30 минут.")

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

    def get_image(self, uuid: str, attempts: int = 120, delay: int = 10):
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
