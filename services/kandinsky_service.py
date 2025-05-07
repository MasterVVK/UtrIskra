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

    def get_model_id(self):
        """Получение ID доступной модели."""
        # Исправлено с models на pipelines согласно документации
        response = requests.get(f"{self.BASE_URL}key/api/v1/pipelines", headers=self.auth_headers)
        response.raise_for_status()
        data = response.json()
        return data[0]["id"]

    def check_availability_with_timeout(self, model_id, attempts: int = 6, delay: int = 300):
        """
        Проверяет доступность API каждые `delay` секунд в течение `attempts` попыток.
        """
        for attempt in range(attempts):
            try:
                logger.debug(f"Отправляем запрос на проверку доступности с model_id={model_id}.")
                # Исправлено согласно документации
                response = requests.get(
                    f"{self.BASE_URL}key/api/v1/pipeline/{model_id}/availability",
                    headers=self.auth_headers,
                    timeout=self.TIMEOUT
                )
                response.raise_for_status()
                response_data = response.json()
                logger.info(f"Ответ сервера: {response_data}")
                status = response_data.get("pipeline_status")
                if status == "DISABLED_BY_QUEUE":
                    logger.warning(f"API недоступен: {status}. Попытка {attempt + 1} из {attempts}.")
                else:
                    # Любые состояния, кроме DISABLED_BY_QUEUE, считаются доступными
                    logger.info(f"API доступен: статус {status}.")
                    return
            except requests.exceptions.RequestException as e:
                logger.error(f"Ошибка при проверке доступности API: {e}")
            if attempt < attempts - 1:
                time.sleep(delay)  # Ждем перед следующей проверкой
        raise Exception("Сервис остается недоступным более 30 минут.")

    def generate_image(self, prompt: str, model_id: str, width: int = 1344, height: int = 768):
        """
        Генерация изображения по текстовому описанию.
        """
        params = {
            "type": "GENERATE",
            "numImages": 1,
            "width": width,
            "height": height,
            "generateParams": {
                "query": prompt
            }
        }

        # Правильный формат для multipart/form-data запроса согласно документации
        data = {
            'pipeline_id': (None, model_id),
            'params': (None, json.dumps(params), 'application/json')
        }

        response = requests.post(
            f"{self.BASE_URL}key/api/v1/pipeline/run",
            headers=self.auth_headers,
            files=data
        )
        response.raise_for_status()
        return response.json()["uuid"]

    def get_image(self, uuid: str, attempts: int = 120, delay: int = 10):
        """
        Получение результата генерации.
        """
        while attempts > 0:
            # Исправлено с text2image на pipeline согласно документации
            response = requests.get(f"{self.BASE_URL}key/api/v1/pipeline/status/{uuid}", headers=self.auth_headers)
            response.raise_for_status()
            data = response.json()
            if data["status"] == "DONE":
                # Исправлено с images[0] на result.files[0] согласно документации
                return data["result"]["files"][0]
            elif data["status"] == "FAIL":
                raise ValueError("Не удалось сгенерировать изображение.")
            attempts -= 1
            time.sleep(delay)
        raise TimeoutError("Превышено количество попыток ожидания результата.")